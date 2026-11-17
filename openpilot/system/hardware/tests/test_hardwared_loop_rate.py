"""hardwared end to end: the real hardware_thread with fake messaging and fake device reads.

These tests don't need the background-read module, so they also run against
builds that still read inline (where the 12 s cases fail by design).
"""
import ast
import importlib
import inspect
import queue
import textwrap
import threading
import time

import pytest

import openpilot.cereal.messaging as messaging
from openpilot.cereal import log
from openpilot.common.hardware.base import ThermalConfig
from openpilot.common.params import Params
from openpilot.common.version import terms_version, training_version
import openpilot.system.hardware.hardwared as hwd

ThermalStatus = log.DeviceState.ThermalStatus
PANDA_TYPE = next(v for k, v in log.PandaState.PandaType.schema.enumerants.items() if k != "unknown")

try:
  bg = importlib.import_module("openpilot.system.hardware.bg_reads")
except ImportError:
  bg = None


class Zone:
  def __init__(self, name, temp, block=None):
    self.name = name
    self.temp = temp
    self.block = block  # callable run inside read(), may sleep

  def read(self):
    if self.block is not None:
      self.block()
    return self.temp


class FakePM:
  def __init__(self, services):
    self.sent = []

  def send(self, service, msg):
    ds = msg.deviceState
    self.sent.append({"t": time.monotonic(), "started": ds.started, "thermalStatus": ds.thermalStatus,
                      "fan": ds.fanSpeedPercentDesired, "maxTempC": ds.maxTempC, "somPowerDrawW": ds.somPowerDrawW,
                      "cpuTempC": list(ds.cpuTempC), "freeSpacePercent": ds.freeSpacePercent,
                      "memoryUsagePercent": ds.memoryUsagePercent})


class FakeSM:
  """pandaStates at a steady 10 Hz from an absolute schedule, like pandad; ignition on, panda connected."""

  def __init__(self, services, poll=None):
    ps = messaging.new_message('pandaStates', 1)
    ps.pandaStates[0].ignitionLine = True
    ps.pandaStates[0].pandaType = PANDA_TYPE
    ps.pandaStates[0].harnessStatus = log.PandaState.HarnessStatus.normal
    self.data = {s: getattr(messaging.new_message(s), s) for s in services if s != 'pandaStates'}
    self.data['pandaStates'] = ps.pandaStates
    self.updated = dict.fromkeys(services, False)
    self.alive = dict.fromkeys(services, False)
    self.valid = dict.fromkeys(services, False)
    self.recv_time = dict.fromkeys(services, time.monotonic())
    self.frame = 0
    self.slow_once_s = 0.0
    self._next = time.monotonic()

  def __getitem__(self, s):
    return self.data[s]

  def update(self, timeout=None):
    if self.slow_once_s > 0:
      time.sleep(self.slow_once_s)
      self.slow_once_s = 0.0
      self._next = time.monotonic()
    self._next += 0.1
    time.sleep(max(0.0, self._next - time.monotonic()))
    self.frame += 1
    self.updated['pandaStates'] = True
    self.recv_time['pandaStates'] = time.monotonic()


class Harness:
  def __init__(self, monkeypatch, zones, som_power_draw=lambda: 3.3):
    self.events = []
    self.alerts = []
    self.pm = None
    self.sm = None
    params = Params()
    params.put("HasAcceptedTerms", terms_version)
    params.put("CompletedTrainingVersion", training_version)
    for k in ("IsDriverViewEnabled", "DoUninstall", "OnroadCycleRequested"):
      params.remove(k)

    def make_pm(services):
      self.pm = FakePM(services)
      return self.pm

    def make_sm(services, poll=None):
      self.sm = FakeSM(services, poll)
      return self.sm

    cfg = ThermalConfig(cpu=zones["cpu"], gpu=zones["gpu"], memory=zones["memory"], pmic=zones["pmic"])
    monkeypatch.setattr(hwd.messaging, "PubMaster", make_pm)
    monkeypatch.setattr(hwd.messaging, "SubMaster", make_sm)
    H = hwd.HARDWARE
    monkeypatch.setattr(H, "initialize_hardware", lambda: None)
    monkeypatch.setattr(H, "get_thermal_config", lambda: cfg)
    monkeypatch.setattr(H, "get_som_power_draw", som_power_draw)
    monkeypatch.setattr(H, "get_current_power_draw", lambda: 1.1)
    monkeypatch.setattr(H, "get_gpu_usage_percent", lambda: 10.0)
    monkeypatch.setattr(H, "get_screen_brightness", lambda: 50)
    monkeypatch.setattr(H, "booted", lambda: True)
    monkeypatch.setattr(H, "set_power_save", lambda on: None)
    monkeypatch.setattr(hwd, "get_usb_state", list)
    monkeypatch.setattr(hwd, "get_short_branch", lambda: "test")
    monkeypatch.setattr(hwd, "set_offroad_alert_if_changed", lambda name, show, extra_text=None: self.alerts.append((name, show, extra_text)))
    real_event = hwd.cloudlog.event

    def event(name, *a, **kw):
      self.events.append((time.monotonic(), name, kw))
      return real_event(name, *a, **kw)
    monkeypatch.setattr(hwd.cloudlog, "event", event)
    self.end = threading.Event()
    self.thread = threading.Thread(target=hwd.hardware_thread, args=(self.end, queue.Queue(maxsize=1)), daemon=True)

  def run(self, seconds, during=None):
    self.t0 = time.monotonic()
    self.thread.start()
    while time.monotonic() - self.t0 < seconds:
      if during is not None:
        during(self, time.monotonic() - self.t0)
      time.sleep(0.02)
    self.end.set()

  def onroad_msgs(self):
    sent = self.pm.sent if self.pm is not None else []
    return [m for m in sent if m["started"]]


def zones(temp, block_cpu0=None):
  return {"cpu": [Zone("cpu0", temp, block_cpu0), Zone("cpu1", temp)], "gpu": [Zone("gpu0", temp)],
          "memory": Zone("ddr", temp), "pmic": [Zone("pm", temp)]}


def rate_and_gap(msgs):
  t = [m["t"] for m in msgs]
  gaps = [b - a for a, b in zip(t, t[1:], strict=False)]
  return (len(t) - 1) / (t[-1] - t[0]), max(gaps)


class OneHang:
  """A read that blocks 12 s once, the first time it's called after arm()."""

  def __init__(self, hang_s=12.0):
    self.hang_s = hang_s
    self.armed = False
    self.release = threading.Event()
    self.started_at = None
    self.ended_at = None

  def arm(self):
    self.armed = True

  def __call__(self):
    if self.armed:
      self.armed = False
      self.started_at = time.monotonic()
      self.release.wait(self.hang_s)
      self.ended_at = time.monotonic()


def check_2hz_through_hang(h, hang):
  msgs = h.onroad_msgs()
  assert len(msgs) >= 2, "deviceState never got onroad"
  assert hang.started_at is not None and hang.ended_at is not None, "the fake 12 s read never ran to the end"
  assert hang.ended_at - hang.started_at >= 11.9
  rate, gap = rate_and_gap(msgs)
  print(f"RATE_GATE n={len(msgs)} rate_hz={rate:.3f} max_gap_s={gap:.3f} hang_s={hang.ended_at - hang.started_at:.2f}")
  in_hang = [m for m in msgs if hang.started_at + 0.5 < m["t"] < hang.ended_at - 0.5]
  assert len(in_hang) >= 20, f"only {len(in_hang)} deviceState during the 12 s read"
  assert rate >= 1.9 and gap < 0.6
  return msgs, in_hang


def test_12s_som_power_draw_read_keeps_device_state_at_2hz(monkeypatch):
  hang = OneHang()
  calls = {"n": 0}

  def som():
    calls["n"] += 1
    hang()
    return 3.3
  h = Harness(monkeypatch, zones(45.0), som_power_draw=som)
  h.run(16.0, during=lambda h, t: hang.arm() if 2.0 < t < 2.1 and hang.started_at is None else None)
  hang.release.set()
  msgs, in_hang = check_2hz_through_hang(h, hang)
  # the cached value is held, never zeroed, while the read hangs
  assert all(m["somPowerDrawW"] == pytest.approx(3.3) for m in in_hang)


def test_12s_thermal_zone_read_keeps_device_state_at_2hz_and_holds_temps(monkeypatch):
  _policy(monkeypatch, "nap")  # the held cool reading stays ok under NAP's rule; strict is tested below
  hang = OneHang()
  h = Harness(monkeypatch, zones(45.0, block_cpu0=hang))
  h.run(16.0, during=lambda h, t: hang.arm() if 2.0 < t < 2.1 and hang.started_at is None else None)
  hang.release.set()
  msgs, in_hang = check_2hz_through_hang(h, hang)
  # held temperatures, not zeros; cool, so no fail-hot within 12 s
  assert all(m["cpuTempC"] == [45.0, 45.0] for m in in_hang)
  assert all(m["thermalStatus"] == ThermalStatus.ok for m in msgs)
  # stale after 10 s without a reading: fan full until fresh readings return
  stale = [m for m in in_hang if m["t"] > hang.started_at + 10.6]
  assert stale and all(m["fan"] == 100 for m in stale)
  names = [e[1] for e in h.events]
  assert "hardwared thermal stale" in names and "hardwared slow thermal zone" in names


def _short_thresholds(monkeypatch):
  if bg is not None:
    monkeypatch.setattr(bg, "THERMAL_STALE_S", 1.0)
    monkeypatch.setattr(bg, "THERMAL_FAIL_HOT_S", 2.0)


def _policy(monkeypatch, policy):
  if bg is not None and hasattr(bg, "STALE_THERMAL_POLICY"):
    monkeypatch.setattr(bg, "STALE_THERMAL_POLICY", policy)


def _stuck_after_onroad(gate):
  def during(h, t):
    if h.onroad_msgs() and not gate.armed and gate.started_at is None:
      gate.arm()
  return during


def test_thermal_stale_and_warm_goes_overheated_with_full_fan(monkeypatch):
  _short_thresholds(monkeypatch)
  stuck = OneHang(hang_s=40.0)
  z = zones(45.0, block_cpu0=stuck)
  every_zone = z["cpu"] + z["gpu"] + z["pmic"] + [z["memory"]]
  h = Harness(monkeypatch, z)

  def during(h, t):
    msgs = h.onroad_msgs()
    if not msgs:
      return  # start cool: a hot device never goes onroad (offroad danger rule)
    for zone in every_zone:
      zone.temp = 92.0  # warm: above the overheated entry (88 C), below the ok band's top (96 C)
    if msgs[-1]["maxTempC"] >= 88.5 and stuck.started_at is None and not stuck.armed:
      stuck.arm()
  h.run(22.0, during=during)
  stuck.release.set()
  msgs = h.onroad_msgs()
  assert stuck.started_at is not None, "the filtered temperature never got warm"
  before = [m for m in msgs if stuck.started_at - 1.0 < m["t"] < stuck.started_at]
  after = [m for m in msgs if m["t"] > stuck.started_at + 1.6]
  assert before and after, "no deviceState once the thermal read got stuck"
  # warm but fresh: still ok; warm and stale: overheated with a full fan, temperatures held
  assert all(m["thermalStatus"] == ThermalStatus.ok for m in before)
  assert all(m["thermalStatus"] >= ThermalStatus.overheated and m["fan"] == 100 for m in after)
  assert all(88.0 <= m["maxTempC"] <= 92.0 for m in after)


def test_thermal_stale_and_cool_goes_overheated_after_fail_hot_time(monkeypatch):
  _short_thresholds(monkeypatch)
  _policy(monkeypatch, "nap")
  stuck = OneHang(hang_s=30.0)
  h = Harness(monkeypatch, zones(45.0, block_cpu0=stuck))
  h.run(6.5, during=_stuck_after_onroad(stuck))
  stuck.release.set()
  msgs = h.onroad_msgs()
  assert stuck.started_at is not None and msgs
  s0 = stuck.started_at
  held = [m for m in msgs if s0 + 1.6 < m["t"] < s0 + 2.4]     # stale (1 s), not yet past the fail-hot time (2 s)
  hot = [m for m in msgs if m["t"] > s0 + 3.7]
  assert held and hot
  assert all(m["thermalStatus"] == ThermalStatus.ok and m["fan"] == 100 for m in held)
  assert all(m["thermalStatus"] >= ThermalStatus.overheated and m["fan"] == 100 for m in hot)


def test_thermal_fresh_stays_normal(monkeypatch):
  _short_thresholds(monkeypatch)
  h = Harness(monkeypatch, zones(45.0))
  h.run(4.0)
  msgs = h.onroad_msgs()
  assert len(msgs) >= 4
  assert all(m["thermalStatus"] == ThermalStatus.ok and m["fan"] < 100 for m in msgs)
  assert "hardwared thermal stale" not in [e[1] for e in h.events]


def test_slow_loop_iteration_logs_each_step(monkeypatch):
  h = Harness(monkeypatch, zones(45.0))
  armed = {"done": False}

  def during(h, t):
    if not armed["done"] and h.onroad_msgs():
      h.sm.slow_once_s = 1.3
      armed["done"] = True
  h.run(4.0, during=during)
  slow = [kw for _, name, kw in h.events if name == "hardwared slow loop"]
  assert slow, "no slow-loop log for a 1.3 s iteration"
  hit = [kw for kw in slow if kw["steps_ms"].get("sm_update", 0.0) >= 1250.0]
  assert len(hit) == 1, slow
  assert hit[0]["total_ms"] >= hit[0]["steps_ms"]["sm_update"] and len(hit[0]["steps_ms"]) >= 2


BLOCKING_READS = {"get_msg", "get_som_power_draw", "get_current_power_draw", "get_gpu_usage_percent", "get_screen_brightness",
                  "booted", "get_available_percent", "memory_usage_percent", "cpu_usage_percent", "get_device_type"}


def test_device_state_loop_makes_no_direct_device_reads():
  tree = ast.parse(textwrap.dedent(inspect.getsource(hwd.hardware_thread)))
  loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
  assert loops
  found = set()
  for loop in loops:
    for n in ast.walk(loop):
      if isinstance(n, ast.Call):
        name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
        if name in BLOCKING_READS:
          found.add(name)
  assert not found, f"device reads on the deviceState loop: {sorted(found)}"


class FirstCallBlocks:
  """Blocks the first call for block_s (or until released), returns at once after that."""

  def __init__(self, block_s):
    self.block_s = block_s
    self.calls = 0
    self.release = threading.Event()
    self.done_at = None

  def __call__(self):
    self.calls += 1
    if self.calls == 1:
      self.release.wait(self.block_s)
      self.done_at = time.monotonic()


def test_slow_first_thermal_read_seeds_filters_from_the_real_reading(monkeypatch):
  # the first thermal read takes 3 s (longer than the 2 s startup wait) on an 85 C device
  first = FirstCallBlocks(3.0)
  z = zones(85.0, block_cpu0=first)
  every_zone = z["cpu"] + z["gpu"] + z["pmic"] + [z["memory"]]
  h = Harness(monkeypatch, z)
  cooled = {"t": None}

  def during(h, t):
    if t > 6.0 and cooled["t"] is None:
      for zone in every_zone:
        zone.temp = 60.0
      cooled["t"] = time.monotonic()
  h.run(14.0, during=during)
  first.release.set()
  sent = h.pm.sent
  assert first.done_at is not None and sent
  before = [m for m in sent if not m["cpuTempC"]]
  with_temps = [m for m in sent if m["cpuTempC"]]
  assert before, "expected deviceState before the first thermal reading (first read slower than the startup wait)"
  # no temperatures yet: fan full, never an engageable band, never onroad
  assert all(m["fan"] == 100 and m["thermalStatus"] >= ThermalStatus.overheated and not m["started"] for m in before)
  # the first published temperature is the real one, not a filter seeded at 0 C
  assert with_temps[0]["maxTempC"] >= 85.0, with_temps[0]
  first = [kw for _, name, kw in h.events if name == "hardwared first thermal reading"]
  assert len(first) == 1 and first[0]["wait_s"] >= 0.5
  # hot offroad device: no onroad until the filtered temperature is below the offroad danger temperature (75 C)
  onroad = h.onroad_msgs()
  assert onroad, "never went onroad after cooling"
  assert onroad[0]["t"] > cooled["t"] + 2.0
  assert onroad[0]["maxTempC"] < 75.0
  after_cool_s = onroad[0]['t'] - cooled['t']
  print(f"B1_GATE first_temp={with_temps[0]['maxTempC']:.1f} pre_reading_msgs={len(before)} onroad_after_cool_s={after_cool_s:.2f}",
        f"onroad_temp={onroad[0]['maxTempC']:.1f}")


def test_never_onroad_without_a_thermal_reading(monkeypatch):
  never = FirstCallBlocks(60.0)
  h = Harness(monkeypatch, zones(45.0, block_cpu0=never))
  h.run(5.0)
  never.release.set()
  sent = h.pm.sent
  assert len(sent) >= 4
  assert not h.onroad_msgs()
  assert all(m["fan"] == 100 and m["thermalStatus"] >= ThermalStatus.overheated for m in sent)
  names = [e[1] for e in h.events]
  # a clear log line, and the existing stock temperature alert (no new UI) with "no reading" instead of a temperature
  assert names.count("hardwared no thermal reading yet: offroad, fan 100 % until it arrives") == 1
  assert ("Offroad_TemperatureTooHigh", True, "no reading") in h.alerts
  # the dedicated startup gate itself reports the missing reading (not only the thermal band)
  blocked = [kw for _, name, kw in h.events if name == "Startup blocked"]
  assert blocked and blocked[-1]["startup_conditions"].get("thermal_read") is False


class ReaderKilled(SystemExit):
  """Ends the reader thread itself (not a per-read error, which the reader catches)."""


def test_thermal_reader_thread_death_goes_stale_full_fan_then_fail_hot(monkeypatch):
  _short_thresholds(monkeypatch)
  _policy(monkeypatch, "nap")
  z = zones(45.0)
  kill = {"armed": False, "at": None}
  real_read = z["cpu"][0].read

  def read():
    if kill["armed"]:
      kill["at"] = time.monotonic()
      raise ReaderKilled()
    return real_read()
  z["cpu"][0].read = read
  h = Harness(monkeypatch, z)

  def during(h, t):
    if h.onroad_msgs() and not kill["armed"]:
      kill["armed"] = True
  h.run(6.5, during=during)
  assert kill["at"] is not None
  assert not any(th.name == "hardwared-thermal" and th.is_alive() for th in threading.enumerate())
  msgs = h.onroad_msgs()
  k0 = kill["at"]
  held = [m for m in msgs if k0 + 1.6 < m["t"] < k0 + 2.4]
  hot = [m for m in msgs if m["t"] > k0 + 3.7]
  assert held and hot
  assert all(m["thermalStatus"] == ThermalStatus.ok and m["fan"] == 100 and m["cpuTempC"] == [45.0, 45.0] for m in held)
  assert all(m["thermalStatus"] >= ThermalStatus.overheated and m["fan"] == 100 for m in hot)


def test_device_reads_hung_from_start_never_report_healthy(monkeypatch):
  if bg is not None and hasattr(bg, "DEVICE_STALE_S"):
    monkeypatch.setattr(bg, "DEVICE_STALE_S", 1.0)
  hung = FirstCallBlocks(60.0)

  def free_space(default):
    hung()
    return 50.0
  monkeypatch.setattr(hwd, "get_available_percent", free_space)
  h = Harness(monkeypatch, zones(45.0))
  h.run(4.0)
  hung.release.set()
  sent = h.pm.sent
  assert len(sent) >= 3
  assert not h.onroad_msgs()
  # unknown free space and memory are published fail-closed, never as healthy defaults
  assert all(m["freeSpacePercent"] == 0.0 and m["memoryUsagePercent"] == 100 for m in sent)
  stale = [kw for _, name, kw in h.events if name == "hardwared device reads stale"]
  assert stale and "free_space" in stale[0]["keys"] and "free_space" in stale[0]["never_read"]


def test_booted_latches_on_the_device_reader(monkeypatch):
  seq = iter([False, True, False, False])
  calls = {"n": 0}

  def booted():
    calls["n"] += 1
    return next(seq)
  monkeypatch.setattr(hwd.HARDWARE, "booted", booted)
  reads, defaults = hwd.device_reads(None)
  assert defaults["booted"] is False
  assert [reads["booted"]() for _ in range(4)] == [False, True, True, True]
  assert calls["n"] == 2  # stops polling once booted
  # fail-closed placeholders until the first real read
  assert defaults["free_space"] == 0.0 and defaults["memory"] == 100.0


@pytest.mark.parametrize("policy", ["strict", "nap"])
def test_onroad_stale_cool_thermal_by_policy(monkeypatch, policy):
  # cool reading stuck once onroad: strict goes overheated as soon as stale (1 s here, 10 s real); nap holds ok until fail-hot (2 s more)
  _short_thresholds(monkeypatch)
  _policy(monkeypatch, policy)
  stuck = OneHang(hang_s=30.0)
  h = Harness(monkeypatch, zones(45.0, block_cpu0=stuck))
  h.run(6.5, during=_stuck_after_onroad(stuck))
  stuck.release.set()
  msgs = h.onroad_msgs()
  assert stuck.started_at is not None and msgs
  s0 = stuck.started_at
  fresh = [m for m in msgs if m["t"] < s0 + 0.3]  # the last fresh reading can be up to 0.5 s before s0, so stale from s0 + 0.5 at the earliest
  stale_early = [m for m in msgs if s0 + 1.6 < m["t"] < s0 + 2.4]
  hot = [m for m in msgs if m["t"] > s0 + 3.7]
  assert fresh and stale_early and hot
  assert all(m["thermalStatus"] == ThermalStatus.ok for m in fresh)
  want_early = ThermalStatus.overheated if policy == "strict" else ThermalStatus.ok
  assert all(m["thermalStatus"] == want_early and m["fan"] == 100 for m in stale_early)
  assert all(m["thermalStatus"] >= ThermalStatus.overheated and m["fan"] == 100 for m in hot)
  pol = [kw["policy"] for _, name, kw in h.events if name == "hardwared stale thermal policy"]
  assert pol == [policy]


def test_default_stale_thermal_policy_is_nap():
  assert bg is not None and bg.STALE_THERMAL_POLICY == "nap" and bg.stale_thermal_policy() == "nap"
  assert "strict" in bg.STALE_THERMAL_POLICIES


def test_startup_gate_waits_for_a_real_thermal_reading_independently_of_the_band(monkeypatch):
  # The thermal band alone also blocks without temperatures; this pins the thermal_read startup condition itself:
  # with the band forced engageable, the device must still not go onroad before the first reading.
  never = FirstCallBlocks(60.0)
  h = Harness(monkeypatch, zones(45.0, block_cpu0=never))
  monkeypatch.setattr(hwd, "fail_hot_thermal_status", lambda status, *a, **k: status, raising=False)
  real_max = max

  def max_no_overheat(*args, **kw):
    # hardwared's "no temperatures yet" rule is max(thermal_status, overheated); keep it at ok for this test only
    if len(args) == 2 and args[1] == ThermalStatus.overheated and not kw:
      return args[0]
    return real_max(*args, **kw)
  monkeypatch.setattr(hwd, "max", max_no_overheat, raising=False)
  h.run(4.0)
  never.release.set()
  sent = h.pm.sent
  assert sent and all(m["thermalStatus"] == ThermalStatus.ok for m in sent), [m["thermalStatus"] for m in sent]
  assert not h.onroad_msgs()
  blocked = [kw for _, name, kw in h.events if name == "Startup blocked"]
  assert blocked and blocked[-1]["startup_conditions"]["thermal_read"] is False
  assert blocked[-1]["startup_conditions"]["device_temp_engageable"] is True


def test_device_reader_thread_death_is_logged_and_goes_stale(monkeypatch):
  if bg is not None and hasattr(bg, "DEVICE_STALE_S"):
    monkeypatch.setattr(bg, "DEVICE_STALE_S", 1.0)
  state = {"armed": False}

  def gpu():
    if state["armed"]:
      raise ReaderKilled()
    return 10.0
  h = Harness(monkeypatch, zones(45.0))
  monkeypatch.setattr(hwd.HARDWARE, "get_gpu_usage_percent", gpu)
  h.run(5.0, during=lambda h, t: state.update(armed=True) if h.onroad_msgs() else None)
  died = [kw for _, name, kw in h.events if name == "hardwared reader thread died"]
  assert died and died[0]["reader"] == "device"
  stale = [kw for _, name, kw in h.events if name == "hardwared device reads stale"]
  assert stale and "gpu" in stale[0]["keys"]
