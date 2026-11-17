"""Pre-AP card.py on real-format CAN: Car.state_update and Car.controls_update with the Read Radar VIN runner and the 0x560 stream.

The frames take the same path as on a car: can_list_to_can_capnp builds the capnp bytes that pandad publishes on 'can',
card.py's can_capnp_to_list turns them into (address, dat, src) tuples, and state_update / controls_update run on a real
Pre-AP CarInterface and RadarInterface. What card sends is read back out of the real 'sendcan' bytes.
Only the socket drain, the clock, the panda state and 'sendcan' publishing are stubbed. No capnp-like objects.
The startup-order matrix uses the compiled panda safety code (libsafety) as the panda: every frame card sends goes to its tx hook.
VINs are synthetic: each contains I, O and Q, which no real VIN may contain.
"""
from types import SimpleNamespace

import pytest

from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.car import card
from openpilot.selfdrive.pandad import can_capnp_to_list, can_list_to_can_capnp
from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.structs import car
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.safety_flags import FLAG_TESLA_PREAP_RADAR_EMULATION
from opendbc.car.tesla_ap1.values import CAR, DBC

VIN = "TESTQQQ5OIQ000002"
UDS_TX, UDS_RX, UDS_BUS = 0x641, 0x651, 1
REPLIES = {b"\x3e\x00": b"\x7e\x00", b"\x10\x01": b"\x50\x01", b"\x10\x03": b"\x50\x03"}
GEAR_P, GEAR_D = 1, 4      # tesla_ap1_can.dbc VAL_ 280 DI_gear
K = PreApParamKeys


def _single(payload: bytes) -> tuple:
  return (UDS_RX, (bytes([len(payload)]) + payload).ljust(8, b"\x00"), UDS_BUS)


class _Clock:
  def __init__(self):
    self.t = 1000.0

  def monotonic(self):
    return self.t


def _make_rig(tmp_path, monkeypatch, radar=True, donor_type=None, donor_vin=None):
  monkeypatch.setattr(preap_params, "_params_dir", tmp_path / "params_bogpilot")
  if donor_type is not None:
    preap_params.set_str(K.RADAR_DONOR_TYPE, str(donor_type))
  if donor_vin is not None:
    preap_params.set_str(K.RADAR_DONOR_VIN, donor_vin)
  Params().put_bool("OpenpilotEnabledToggle", True)
  CP = CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)
  if radar:
    CP.safetyConfigs[-1].safetyParam = int(CP.safetyConfigs[-1].safetyParam) | FLAG_TESLA_PREAP_RADAR_EMULATION
  c = card.Car(CarInterface(CP), RadarInterface(CP))
  assert c.preap_vin_read is not None and c.preap_vin_read.radar_emulation == radar

  clock = _Clock()
  monkeypatch.setattr(card, "time", SimpleNamespace(monotonic=clock.monotonic))
  inbox: list[bytes] = []
  monkeypatch.setattr(card.messaging, "drain_sock_raw", lambda sock, wait_for_one=False: [inbox.pop(0)] if inbox else [])
  sent: list[bytes] = []
  c.pm.send = lambda name, dat: sent.append(dat) if name == "sendcan" else None
  c.initialized_prev = True
  packer = CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.chassis])
  st = SimpleNamespace(i=0)

  def background(gear):
    st.i += 1
    di = packer.make_can_msg("DI_torque2", 0, {"DI_gear": gear, "DI_torque2Counter": st.i % 16, "DI_vehicleSpeed": 25.0})
    # 0x651 on bus 0 and a radar-bus frame must never reach the reader
    return [di, (0x2A9, bytes(8), 1), (UDS_RX, bytes(8), 0)]

  def step(frames=(), enabled=False, gear=GEAR_P, lat=False, tx_total=None, sample=None, ps_fields=None):
    """One card step on the background traffic plus these frames; returns every (address, dat, src) card put in 'sendcan'.
    tx_total: the panda's blocked-TX total (pandaStates.safetyTxBlocked) card sees in this step; sample: that pandaStates
    message's logMonoTime (a new value = a new sample); ps_fields: the whole pandaStates entry (the libsafety panda)."""
    ps = [log.PandaState.new_message(controlsAllowed=False, safetyTxBlocked=int(tx_total or 0) & 0xFFFFFFFF)]
    if ps_fields is not None:
      ps = [log.PandaState.new_message(**ps_fields)]
    if tx_total is not None or ps_fields is not None:
      c.sm.seen["pandaStates"] = True
      c.sm.valid["pandaStates"] = True
      c.sm.data["pandaStates"] = ps
    if sample is not None:
      c.sm.logMonoTime["pandaStates"] = int(sample)
    inbox.append(can_list_to_can_capnp(background(gear) + list(frames), msgtype="can"))
    CS, _ = c.state_update()
    c.sm.alive["carControl"] = True
    if tx_total is not None or ps_fields is not None:
      c.sm.valid["pandaStates"] = True
      c.sm.data["pandaStates"] = ps
    cc = car.CarControl.new_message()
    cc.enabled = enabled
    cc.latActive = lat
    sent.clear()
    c.controls_update(CS, cc.as_reader())
    out = []
    for _, msgs in can_capnp_to_list(sent, msgtype="sendcan"):
      out += list(msgs)
    clock.t += 0.01
    return out

  return SimpleNamespace(car=c, step=step, clock=clock)


@pytest.fixture
def make_rig(tmp_path, monkeypatch):
  with OpenpilotPrefix(clean_dirs_on_exit=False):
    yield lambda **kw: _make_rig(tmp_path, monkeypatch, **kw)


@pytest.fixture
def rig(make_rig):
  return make_rig()


def _uds(out):
  return [m for m in out if m[0] == UDS_TX and m[2] == UDS_BUS]


def _radar_answers(tx, vin=VIN):
  """What a Bosch radar answers on 0x651; F190 gets a 3-frame ISO-TP reply."""
  rx = []
  for _, dat, _ in _uds(tx):
    if dat[0] == 0x30:            # our flow control: send the consecutive frames
      rest = (b"\x62\xf1\x90" + vin.encode())[6:]
      rx += [(UDS_RX, bytes([0x21]) + rest[:7], UDS_BUS), (UDS_RX, (bytes([0x22]) + rest[7:]).ljust(8, b"\x00"), UDS_BUS)]
      continue
    req = dat[1:1 + dat[0]]
    if req in REPLIES:
      rx.append(_single(REPLIES[req]))
    elif req == b"\x22\xf1\x90":
      payload = b"\x62\xf1\x90" + vin.encode()
      rx.append((UDS_RX, bytes([0x10, len(payload)]) + payload[:6], UDS_BUS))
  return rx


def _idle(rig):
  return not preap_params.get_bool(K.RADAR_READ_VIN) and rig.car.preap_vin_read.reader is None


def _run_read(rig, answer=_radar_answers, max_s=40.0, dt=0.0, press_again_at=None, engage_at=None):
  preap_params.set_bool(K.RADAR_READ_VIN, True)
  rx, t0, n, all_tx = [], rig.clock.t, 0, []
  while rig.clock.t - t0 < max_s:
    if press_again_at is not None and n == press_again_at:
      preap_params.set_bool(K.RADAR_READ_VIN, True)
    tx = rig.step(rx, enabled=(engage_at is not None and n >= engage_at))
    all_tx += _uds(tx)
    rx = answer(tx)
    rig.clock.t += dt
    n += 1
    if _idle(rig):
      return rig.clock.t - t0, all_tx
  return None, all_tx


def _button_usable_again(rig):
  preap_params.set_bool(K.RADAR_READ_VIN, True)
  tx = _uds(rig.step())
  assert tx and tx[-1][1][:3] == b"\x02\x3e\x00"     # a fresh read starts with Tester Present
  preap_params.set_bool(K.RADAR_READ_VIN, False)
  rig.step()
  assert rig.car.preap_vin_read.reader is None


def test_state_update_on_real_can_without_the_button(rig):
  # 4a4de4893: AttributeError 'tuple' object has no attribute 'address' on the first frame, on every Pre-AP car.
  for _ in range(100):
    assert _uds(rig.step([_single(b"\x7e\x00")])) == []
  assert _idle(rig)


@pytest.mark.parametrize("radar", [True, False])
def test_state_update_on_real_can_radar_off(make_rig, radar):
  rig = make_rig(radar=radar)
  for _ in range(50):
    assert _uds(rig.step()) == []


def test_button_read_end_to_end_on_real_can(rig):
  took, tx = _run_read(rig)
  assert took is not None and tx and all(a == UDS_TX and s == UDS_BUS for a, _, s in tx)
  assert preap_params.get_str(K.RADAR_DONOR_VIN) == VIN
  assert preap_params.get_str(K.RADAR_VIN_READ_STATUS) == "saved, restart the car"
  assert _idle(rig)


def test_silent_radar_times_out_and_frees_the_button(rig):
  took, _ = _run_read(rig, answer=lambda tx: [], dt=0.2)
  assert took is not None and took <= 30.0
  assert "timeout" in preap_params.get_str(K.RADAR_VIN_READ_STATUS)
  assert preap_params.get_str(K.RADAR_DONOR_VIN) == ""
  _button_usable_again(rig)


@pytest.mark.parametrize("bad", [b"\x7e", b"\x02\x7e", bytes(9), b"\x10\x05\x62\xf1\x90\x00\x00\x00"])
def test_malformed_or_short_reply_ends_the_read_and_frees_the_button(rig, bad):
  took, _ = _run_read(rig, answer=lambda tx: [(UDS_RX, bad, UDS_BUS)] if _uds(tx) else [], dt=0.2)
  assert took is not None and took <= 30.0
  assert "malformed" in preap_params.get_str(K.RADAR_VIN_READ_STATUS)
  assert preap_params.get_str(K.RADAR_DONOR_VIN) == ""
  _button_usable_again(rig)


def test_engage_mid_read_stops_at_once_and_frees_the_button(rig):
  took, tx = _run_read(rig, engage_at=3)
  assert took is not None
  assert preap_params.get_str(K.RADAR_VIN_READ_STATUS) == "stopped: engaged"
  assert preap_params.get_str(K.RADAR_DONOR_VIN) == ""
  assert _uds(rig.step(enabled=True)) == []
  _button_usable_again(rig)


def test_press_while_engaged_is_refused(rig):
  preap_params.set_bool(K.RADAR_READ_VIN, True)
  assert _uds(rig.step(enabled=True)) == []
  assert preap_params.get_str(K.RADAR_VIN_READ_STATUS) == "disengage first"
  assert _idle(rig)
  _button_usable_again(rig)


def test_press_twice(rig):
  took, _ = _run_read(rig, press_again_at=2)           # a second press during a read changes nothing
  assert took is not None and preap_params.get_str(K.RADAR_DONOR_VIN) == VIN
  preap_params.set_str(K.RADAR_DONOR_VIN, "")
  took, _ = _run_read(rig)                              # pressed again after it finished: a full new read
  assert took is not None and preap_params.get_str(K.RADAR_DONOR_VIN) == VIN
  assert _idle(rig)


def test_button_without_radar_flag_is_refused(make_rig):
  rig = make_rig(radar=False)
  preap_params.set_bool(K.RADAR_READ_VIN, True)
  assert _uds(rig.step()) == []
  assert preap_params.get_str(K.RADAR_VIN_READ_STATUS) == "radar off"
  assert _idle(rig)


@pytest.mark.parametrize("donor_type", [0, 1, 2])
def test_0x560_stream_follows_donor_type_any_gear_only_disengaged_and_not_steering(make_rig, donor_type):
  rig = make_rig(donor_type=donor_type, donor_vin=VIN)
  for gear in (GEAR_P, GEAR_D):
    frames = [m for _ in range(60) for m in rig.step(gear=gear) if m[0] == 0x560]
    assert len(frames) == 6 and all(s == 0 and len(d) == 8 for _, d, s in frames), gear
    r0 = [d for _, d, _ in frames if d[0] == 0]
    assert r0 and all((d[2] >> 1) & 3 == donor_type and d[2] & 1 == 1 for d in r0)
  for gear in (GEAR_P, GEAR_D):
    assert not [m for _ in range(60) for m in rig.step(gear=gear, enabled=True) if m[0] == 0x560]            # engaged
    assert not [m for _ in range(60) for m in rig.step(gear=gear, lat=True) if m[0] == 0x560]                # steering
    assert not [m for _ in range(60) for m in rig.step(gear=gear, enabled=True, lat=True) if m[0] == 0x560]


def test_0x560_stream_off_without_radar_flag(make_rig):
  rig = make_rig(radar=False, donor_type=2, donor_vin=VIN)
  assert not [m for _ in range(60) for m in rig.step(gear=GEAR_P) if m[0] == 0x560]


# ---- the read can never stop card ----

class _LogRecorder:
  def __init__(self):
    self.calls = []

  def __getattr__(self, name):
    return lambda *a, **kw: self.calls.append((name, repr(a), repr(kw)))


def test_internal_error_in_the_read_ends_it_cleanly_and_never_logs_details(rig, monkeypatch):
  rec = _LogRecorder()
  monkeypatch.setattr(card, "cloudlog", rec)
  _, tx = _run_read(rig, max_s=0.03)                           # a read is running
  assert rig.car.preap_vin_read.reader is not None

  def boom(*a, **kw):
    raise RuntimeError(f"decode failed for {VIN} {bytes(8)!r}")
  monkeypatch.setattr(rig.car.preap_vin_read.reader, "update", boom)
  out = rig.step(_radar_answers(tx))                           # card survives this step and still publishes sendcan
  assert isinstance(out, list) and _uds(out) == []
  assert _idle(rig) and preap_params.get_str(K.RADAR_VIN_READ_STATUS) == "read error"
  assert [c[0] for c in rec.calls] == ["error"]
  assert all(VIN not in "".join(c) and "decode failed" not in "".join(c) for c in rec.calls)
  for _ in range(20):
    rig.step()
  _button_usable_again(rig)


def test_rx_filter_error_does_not_stop_card(rig, monkeypatch):
  _run_read(rig, max_s=0.03)

  def bad_candata(*a):
    raise ValueError("bad frame")
  monkeypatch.setattr(card, "CanData", bad_candata)
  took, _ = _run_read(rig, dt=0.2)                              # no replies reach the reader: it times out, card keeps going
  assert took is not None and took <= 30.0
  assert "timeout" in preap_params.get_str(K.RADAR_VIN_READ_STATUS)


def test_read_is_bounded_even_if_the_reader_never_finishes(rig, monkeypatch):
  from opendbc.car.tesla_ap1.preap import radar_vin_read
  from opendbc.car.tesla_ap1.preap.radar_donor_vin import RadarDonorVinOutput, RadarDonorVinState
  preap_params.set_bool(K.RADAR_READ_VIN, True)
  rig.step()
  monkeypatch.setattr(rig.car.preap_vin_read.reader, "update",
                      lambda rx, now: RadarDonorVinOutput(RadarDonorVinState.READ_F190, ()))
  t0 = rig.clock.t
  while not _idle(rig) and rig.clock.t - t0 < 60.0:
    rig.step()
    rig.clock.t += 0.5
  assert _idle(rig) and rig.clock.t - t0 <= radar_vin_read.MAX_READ_S + 1.0
  assert preap_params.get_str(K.RADAR_VIN_READ_STATUS) == "timeout"


def test_rx_only_collected_while_a_read_runs(rig):
  rig.step([_single(b"\x7e\x00")])
  assert rig.car.preap_vin_read_rx == []
  preap_params.set_bool(K.RADAR_READ_VIN, True)
  rig.step()
  rig.step([_single(b"\x7e\x00")])
  assert [(m.address, m.src) for m in rig.car.preap_vin_read_rx] == [(UDS_RX, UDS_BUS)]


def test_runner_accepts_plain_tuples():
  from opendbc.car.tesla_ap1.preap.radar_vin_read import RadarVinReadRunner
  store = {}
  fake = SimpleNamespace(get_bool=lambda k: store.get(k, False), set_bool=store.__setitem__, set_str=store.__setitem__)
  store[K.RADAR_READ_VIN] = True
  r = RadarVinReadRunner(True, params=fake)
  assert _uds(r.update([], 0.0, False))
  r.update([_single(b"\x7e\x00")], 0.01, False)
  assert r.reader is not None and r.reader.state.name == "DEFAULT_SESSION"


# ---- startup-order matrix: card's real sendcan through the compiled panda safety code (libsafety) as the panda ----

ELM327_PARAM = 1
SWITCH = 300           # card step of the panda's switch to the car's safety mode (~15 s after start on a car, shortened here)
CONFIG_398 = bytes((0x02, 0x81, 0x55, 0x53, 0, 0, 0, 0))   # car 0x398, as in the panda donor tests
REJ = 0xC0


class _Panda:
  """libsafety as the panda. ELM327 until switch(), then tesla with Pre-AP + radar gateway (flag 256). Every frame card sends
  goes to the real tx hook; a refused one counts in safety_tx_blocked and comes back as a rejected echo (src bus + 0xC0) on the
  next step, as can_common.h can_send does. Each step one car 0x398 goes to the rx hook; whatever the gateway put on bus 1
  comes back as returned echoes on src 129. pandaStates carries model, param, uptime, controls_allowed and the counter."""

  def __init__(self):
    from opendbc.car.structs import CarParams
    from opendbc.safety.tests.libsafety import libsafety_py
    from opendbc.safety.tests.test_tesla_preap import PREAP, SAFETY_TESLA, pkt
    from opendbc.safety.tests.test_tesla_preap_radar import RADAR, sent
    self.l, self.pkt, self.sent = libsafety_py.libsafety, pkt, sent
    self.elm = int(CarParams.SafetyModel.elm327)
    self.mode_args = (SAFETY_TESLA, PREAP | RADAR)
    self.model, self.param = self.elm, ELM327_PARAM
    assert self.l.set_safety_hooks(self.model, self.param) == 0
    self.l.init_tests()
    self.tesla = False
    self.blocked = 0
    self.uptime = 1
    self.echoes = []
    self.consumed = 0
    self.lose_echoes = False

  def switch(self):
    """The switch to the car's mode, and any later re-init: the panda clears the 0x560 config and controls_allowed."""
    assert self.l.set_safety_hooks(*self.mode_args) == 0
    self.l.init_tests()
    self.l.set_timer(1_000_000)
    self.l.set_controls_allowed(False)
    self.model, self.param = self.mode_args
    self.tesla = True

  def reboot(self):
    self.uptime = 0
    self.blocked = 0
    self.switch()

  def refuse(self, addr, dat, bus):
    if not self.l.safety_tx_hook(self.pkt(addr, bytearray(dat), bus)):
      self.blocked += 1
      if not self.lose_echoes:
        self.echoes.append((addr, bytes(dat), bus + REJ))
      return True
    return False

  def tx(self, out):
    for addr, dat, src in out:
      if self.refuse(addr, dat, src) and addr == 0x560 and self.tesla:
        self.consumed += 1

  def tick(self, i):
    """Gateway output of this step (needs the full 0x560 config), returned as echoes next step."""
    if i % 100 == 0:
      self.uptime += 1
    if self.tesla:
      self.l.safety_can_send_log_reset()
      self.l.safety_rx_hook(self.pkt(0x398, bytearray(CONFIG_398), 0))
      self.echoes += [(addr, b"", 1 + 0x80) for addr, bus, _, _ in self.sent() if bus == 1]

  def take(self):
    e, self.echoes = self.echoes, []
    return e

  def gateway_open(self):
    return any(addr == 0x2A9 and src == 129 for addr, _, src in self.echoes)

  def state(self):
    return {"safetyModel": self.model, "safetyParam": self.param, "uptime": self.uptime,
            "controlsAllowed": bool(self.l.get_controls_allowed()), "safetyTxBlocked": self.blocked & 0xFFFFFFFF}


def _matrix(rig, panda, steps, gear_at, events=None, enabled_at=lambda i: False, inject_551=()):
  """Run card against the panda. events: {step: "switch" | "reinit" | "reboot"}. inject_551: steps at which a real ENABLE=1
  0x551 (as card's pedal path builds it) is offered to the panda. Returns (opened {event step: first open step},
  fed [what card fed the pull FSM per step], sent_560 per step)."""
  from opendbc.car.tesla_ap1.preap.pedal_can import PedalCommandCounter, create_pedal_command
  events = events or {}
  opened, cur, fed, s560 = {}, None, [], []
  ci, update = rig.car.CI, rig.car.CI.update
  counter = PedalCommandCounter()

  def spy(*a, **kw):
    fed.append(int(ci.CS.preap_panda_tx_blocked))
    ret = update(*a, **kw)
    ci.CS.preap_panda_tx_blocked = 0
    return ret
  ci.update = spy
  for i in range(steps):
    ev = events.get(i)
    if ev in ("switch", "reinit"):
      panda.switch()
    elif ev == "reboot":
      panda.reboot()
    if ev:
      cur = i
      opened[cur] = None
    if i in inject_551:
      m = create_pedal_command(20.0, 1, counter, 2)
      assert panda.refuse(m[0], m[1], m[2])
    out = rig.step(panda.take(), gear=gear_at(i), enabled=enabled_at(i), ps_fields=panda.state(), sample=1 + i // 10)
    panda.tx(out)
    s560.append(sum(1 for m in out if m[0] == 0x560))
    panda.tick(i)
    if cur is not None and opened[cur] is None and panda.gateway_open():
      opened[cur] = i
  return opened, fed, s560


def _drive_from(t):
  return lambda i: GEAR_D if i >= t else GEAR_P


@pytest.mark.parametrize("drive_from", [0, 160, 240, 299, SWITCH + 5])
def test_drive_before_safety_switch_releases_radar_within_1s(make_rig, drive_from):
  # Fresh install: no donor VIN, no donor type. 92aa9ee1f sent no 0x560 in Drive: the gateway never opened for the drive.
  rig = make_rig()
  panda = _Panda()
  opened, fed, s560 = _matrix(rig, panda, SWITCH + 200, _drive_from(drive_from), {SWITCH: "switch"})
  assert opened[SWITCH] is not None, "radar gateway never opened"
  assert (opened[SWITCH] - SWITCH) * 0.01 <= 1.0
  assert sum(fed) == 0 and panda.consumed >= 3
  assert sum(s560[:SWITCH]) == 0                       # nothing before the car's mode (ELM327 would refuse it)
  assert sum(s560[opened[SWITCH] + 5:]) == 0           # stops once the gateway echoes


@pytest.mark.parametrize("event", ["reinit", "reboot"])
def test_reinit_or_reboot_in_drive_reopens_within_1s(make_rig, event):
  rig = make_rig(donor_type=2, donor_vin=VIN)
  panda = _Panda()
  at = 600
  opened, fed, _ = _matrix(rig, panda, at + 200, _drive_from(400), {100: "switch", at: event})
  assert opened[100] is not None and (opened[100] - 100) * 0.01 <= 1.0
  assert opened[at] is not None, f"radar gateway never reopened after the {event} in Drive"
  assert (opened[at] - at) * 0.01 <= 1.0
  assert sum(fed) == 0


def test_reinit_while_engaged_waits_for_disengage(make_rig):
  rig = make_rig()
  panda = _Panda()
  reinit, release = 300, 500
  opened, fed, s560 = _matrix(rig, panda, release + 150, lambda i: GEAR_D, {50: "switch", reinit: "reinit"},
                              enabled_at=lambda i: 200 <= i < release)
  assert sum(s560[200:release]) == 0
  assert opened[reinit] is not None and release <= opened[reinit] <= release + 100
  assert sum(fed) == 0


@pytest.mark.parametrize("event", ["switch", "reinit", "reboot"])
@pytest.mark.parametrize("engage_after", [1, 10, 50, 200])
def test_engage_soon_after_each_event_no_radar_frame_reads_as_refusal(make_rig, event, engage_after):
  rig = make_rig()
  panda = _Panda()
  events = {100: "switch"} if event == "switch" else {100: "switch", 400: event}
  at = max(events)
  opened, fed, s560 = _matrix(rig, panda, at + engage_after + 200, _drive_from(50), events,
                              enabled_at=lambda i: i >= at + engage_after)
  assert sum(fed) == 0                                  # zero pedal demotions from radar frames
  assert sum(s560[at + engage_after:]) == 0


def test_real_0x551_refusal_in_the_0x560_stream_reaches_the_fsm(make_rig):
  rig = make_rig()
  panda = _Panda()
  inject = (SWITCH + 2, SWITCH + 13, SWITCH + 27)       # while our 0x560 stream runs (before the gateway opens)
  opened, fed, s560 = _matrix(rig, panda, SWITCH + 200, _drive_from(0), {SWITCH: "switch"}, inject_551=inject)
  assert sum(s560[SWITCH:SWITCH + 30]) >= 2
  assert sum(fed) == len(inject)
  for i in inject:
    assert fed[i + 1] == 1, (i, fed[i:i + 3])           # on the next step: its echo, not a 10 Hz sample


def test_real_0x551_refusal_with_lost_echo_is_passed_on_from_the_counter(make_rig):
  rig = make_rig()
  panda = _Panda()
  opened, _, _ = _matrix(rig, panda, SWITCH + 100, _drive_from(0), {SWITCH: "switch"})
  assert opened[SWITCH] is not None
  panda.lose_echoes = True
  m_at = SWITCH + 150
  opened, fed, s560 = _matrix(rig, panda, SWITCH + 260, _drive_from(0), {}, inject_551=(m_at - SWITCH - 100 + 100,))
  assert sum(s560) == 0 and sum(fed) == 1               # no 0x560 nearby: the lost echo is a refusal (fail-safe)


def test_pandastates_invalid_sends_no_0x560(make_rig):
  rig = make_rig()
  outs = [rig.step(gear=GEAR_D) for _ in range(100)]
  assert not any(m[0] == 0x560 for out in outs for m in out)


def test_lost_echo_warning_is_rate_limited_and_counts_only(make_rig, monkeypatch):
  rig = make_rig()
  warned = []
  monkeypatch.setattr(rig.car.preap_warn, "log_fn", warned.append)
  w = rig.car.preap_refusals
  for k in range(400):
    w.unexplained = 0
    rig.car.preap_sent_560 = 1
    from opendbc.car.tesla_ap1.preap.panda_link import EchoCounts
    refusals, logged = w.step(EchoCounts(), 1, [k])
    if logged:
      rig.car.preap_warn(k * 0.1, f"card: Pre-AP {logged} blocked TX without an echo next to an own 0x560, not a refusal")
  assert 1 <= len(warned) <= 5 and all(VIN not in m for m in warned)
