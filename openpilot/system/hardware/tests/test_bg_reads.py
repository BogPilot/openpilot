"""Unit tests for hardwared's background device reads (bg_reads.py)."""
import threading
import time

from openpilot.cereal import log
from openpilot.common.hardware.base import ThermalConfig
import openpilot.system.hardware.bg_reads as bg

ThermalStatus = log.DeviceState.ThermalStatus
OK, OVERHEATED, CRITICAL = ThermalStatus.ok, ThermalStatus.overheated, ThermalStatus.critical
WARM_C = 88.0


class FakeClock:
  def __init__(self):
    self.t = 100.0

  def __call__(self):
    return self.t


class Zone:
  def __init__(self, name, value, clock=None, cost_s=0.0):
    self.name = name
    self.value = value
    self.clock = clock
    self.cost_s = cost_s

  def read(self):
    if self.clock is not None:
      self.clock.t += self.cost_s
    return self.value


def capture_events(monkeypatch):
  events = []
  monkeypatch.setattr(bg.cloudlog, "event", lambda name, **kw: events.append((name, kw)))
  return events


def test_background_reads_cache_and_keep_last_value_on_error(monkeypatch):
  monkeypatch.setattr(bg.cloudlog, "exception", lambda *a, **k: None)
  state = {"fail": False}

  def flaky():
    if state["fail"]:
      raise OSError("sysfs gone")
    return 7

  r = bg.BackgroundReads("t", {"a": flaky}, {"a": 0})
  assert r.get("a") == 0 and not r.has_value("a") and r.age_s("a") is None
  r.run_once()
  assert r.get("a") == 7 and r.has_value("a") and r.age_s("a") is not None
  state["fail"] = True
  r.run_once()
  assert r.get("a") == 7


def test_background_reads_name_the_slow_read(monkeypatch):
  events = capture_events(monkeypatch)
  clock = FakeClock()

  def slow():
    clock.t += 0.4
    return 1

  r = bg.BackgroundReads("device", {"fast": lambda: 2, "som_power_draw": slow}, {}, clock=clock)
  slow_reads = r.run_once()
  assert list(slow_reads) == ["som_power_draw"]
  assert events and events[0][0] == "hardwared slow read"
  assert events[0][1]["reads_ms"] == {"som_power_draw": 400.0} and events[0][1]["reader"] == "device"


def test_hung_read_never_blocks_get():
  release = threading.Event()
  entered = threading.Event()

  def hung():
    entered.set()
    release.wait(5.0)
    return 9

  r = bg.BackgroundReads("t", {"x": hung}, {"x": 1}, period_s=0.05)
  end = threading.Event()
  r.start(end)
  assert entered.wait(2.0)
  t0 = time.monotonic()
  for _ in range(100):
    assert r.get("x") == 1
  assert time.monotonic() - t0 < 0.1
  release.set()
  end.set()
  r.thread.join(2.0)


def test_read_thermal_zones_matches_get_msg_and_names_slow_zone(monkeypatch):
  events = capture_events(monkeypatch)
  clock = FakeClock()
  cfg = ThermalConfig(cpu=[Zone("cpu0", 40.0), Zone("cpu1", 41.0)], gpu=[Zone("gpu0", 42.0, clock, 0.5)], memory=Zone("ddr", 43.0),
                      pmic=[Zone("pm8998", 44.0)])
  assert bg.read_thermal_zones(cfg, clock=clock) == cfg.get_msg()
  assert events == [("hardwared slow thermal zone", {"error": True, "zones_ms": {"gpu0": 500.0}})]


def test_staleness_uses_the_real_10s_threshold_and_logs_edges(monkeypatch):
  events = capture_events(monkeypatch)
  clock = FakeClock()
  s = bg.ThermalStaleness(clock=clock)
  assert not s.update(None)            # no reading yet, just started
  assert not s.update(9.9)
  assert s.update(10.1) and s.stale_s == 0.0
  clock.t += 30.0
  assert s.update(40.1) and s.stale_s == 30.0
  assert not s.update(0.2) and s.stale_s == 0.0
  assert [e[0] for e in events] == ["hardwared thermal stale", "hardwared thermal fresh again"]


def test_staleness_counts_from_start_when_the_first_read_never_returns(monkeypatch):
  capture_events(monkeypatch)
  clock = FakeClock()
  s = bg.ThermalStaleness(clock=clock)
  clock.t += 10.5
  assert s.update(None)


def test_fail_hot_policy():
  f = bg.fail_hot_thermal_status
  # fresh: unchanged, whatever the temperature
  assert f(OK, False, 0.0, 95.0, WARM_C, OK, OVERHEATED) == OK
  assert f(CRITICAL, False, 0.0, 30.0, WARM_C, OK, OVERHEATED) == CRITICAL
  # stale and cool: held up to the real 60 s, then fail hot
  assert f(OK, True, 0.0, 50.0, WARM_C, OK, OVERHEATED) == OK
  assert f(OK, True, 59.9, 50.0, WARM_C, OK, OVERHEATED) == OK
  assert f(OK, True, 60.0, 50.0, WARM_C, OK, OVERHEATED) == OVERHEATED
  # stale and already warm: fail hot at once
  assert f(OK, True, 0.0, WARM_C, WARM_C, OK, OVERHEATED) == OVERHEATED
  assert f(OVERHEATED, True, 0.0, 50.0, WARM_C, OK, OVERHEATED) == OVERHEATED
  # never cooler than the band logic
  assert f(CRITICAL, True, 0.0, 99.0, WARM_C, OK, OVERHEATED) == CRITICAL
  assert f(CRITICAL, True, 70.0, 50.0, WARM_C, OK, OVERHEATED) == CRITICAL


def test_loop_timer_logs_every_step_only_when_over_1s(monkeypatch):
  events = capture_events(monkeypatch)
  clock = FakeClock()
  t = bg.LoopStepTimer(clock=clock)
  clock.t += 0.2
  t.mark("sm_update")
  clock.t += 0.7
  t.mark("thermal")
  assert not t.report_if_slow() and not events          # 0.9 s
  clock.t += 0.3
  t.mark("send")
  assert t.report_if_slow()
  name, kw = events[0]
  assert name == "hardwared slow loop" and kw["error"] is True
  assert kw["steps_ms"] == {"sm_update": 200.0, "thermal": 700.0, "send": 300.0}
  assert kw["total_ms"] == 1200.0


def test_reader_thread_death_goes_stale_and_fails_hot_at_the_real_thresholds(monkeypatch):
  capture_events(monkeypatch)
  clock = FakeClock()
  n = {"calls": 0}

  def read():
    n["calls"] += 1
    if n["calls"] > 1:
      raise SystemExit  # kills the reader thread itself
    return 45.0
  r = bg.BackgroundReads("thermal", {"temps": read}, {"temps": None}, period_s=0.01, clock=clock)
  end = threading.Event()
  th = r.start(end)
  th.join(2.0)
  assert not th.is_alive() and r.get("temps") == 45.0
  age = bg.ThermalStaleness(clock=clock)
  t_read = clock.t
  clock.t = t_read + 9.9
  assert not age.update(r.age_s("temps"))
  clock.t = t_read + 10.1
  assert age.update(r.age_s("temps"))
  ok, hot = OK, OVERHEATED
  # cool held reading: holds ok until 60 s stale (about 70 s after the last reading), then fails hot
  clock.t = t_read + 10.1 + 59.9
  assert age.update(r.age_s("temps"))
  assert bg.fail_hot_thermal_status(ok, age.stale, age.stale_s, 45.0, WARM_C, ok, hot) == ok
  clock.t = t_read + 10.1 + 60.0
  assert bg.fail_hot_thermal_status(ok, age.stale, age.stale_s, 45.0, WARM_C, ok, hot) == hot
  end.set()


def test_device_read_staleness_real_threshold_and_never_read(monkeypatch):
  events = capture_events(monkeypatch)
  clock = FakeClock()
  s = bg.ReadStaleness("device", clock=clock)
  assert s.update({"free_space": 3.0, "memory": None}) == set()
  clock.t += 10.5
  assert s.update({"free_space": 9.9, "memory": None}) == {"memory"}
  assert s.update({"free_space": 10.1, "memory": None}) == {"free_space", "memory"}
  assert s.update({"free_space": 0.1, "memory": 0.2}) == set()
  names = [e[0] for e in events]
  assert names.count("hardwared device reads stale") == 2 and names.count("hardwared device reads fresh again") == 1
  assert events[0][1]["never_read"] == ["memory"]


def test_strict_policy_fails_hot_as_soon_as_stale_and_unknown_policy_is_strict(monkeypatch):
  events = capture_events(monkeypatch)
  # fresh: unchanged either way; stale and cool: strict -> overheated at once, nap -> ok until 60 s
  assert bg.fail_hot_thermal_status(OK, False, 0.0, 45.0, WARM_C, OK, OVERHEATED, strict=True) == OK
  assert bg.fail_hot_thermal_status(OK, True, 0.0, 45.0, WARM_C, OK, OVERHEATED, strict=True) == OVERHEATED
  assert bg.fail_hot_thermal_status(OK, True, 0.0, 45.0, WARM_C, OK, OVERHEATED, strict=False) == OK
  assert bg.fail_hot_thermal_status(CRITICAL, True, 0.0, 45.0, WARM_C, OK, OVERHEATED, strict=True) == CRITICAL
  assert bg.stale_thermal_policy() == "strict"
  monkeypatch.setattr(bg, "STALE_THERMAL_POLICY", "nap")
  assert bg.stale_thermal_policy() == "nap"
  monkeypatch.setattr(bg, "STALE_THERMAL_POLICY", "bogus")
  assert bg.stale_thermal_policy() == "strict"
  assert [e[0] for e in events] == ["hardwared unknown stale thermal policy, using strict"]


def test_snapshot_value_and_freshness_agree():
  r = bg.BackgroundReads("thermal", {"temps": lambda: {"cpuTempC": [50.0]}}, {"temps": {}})
  assert r.snapshot("temps", {}) == ({}, False)
  r.run_once()
  assert r.snapshot("temps", {}) == ({"cpuTempC": [50.0]}, True)
