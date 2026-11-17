"""Pre-AP card.py on real-format CAN: Car.state_update and Car.controls_update with the Read Radar VIN runner and the 0x560 stream.

The frames take the same path as on a car: can_list_to_can_capnp builds the capnp bytes that pandad publishes on 'can',
card.py's can_capnp_to_list turns them into (address, dat, src) tuples, and state_update / controls_update run on a real
Pre-AP CarInterface and RadarInterface. What card sends is read back out of the real 'sendcan' bytes.
Only the socket drain, the clock, the panda state and 'sendcan' publishing are stubbed. No capnp-like objects.
The radar gateway tests use the compiled panda safety code (libsafety) as the panda: card's real 0x560 frames go to its tx hook.
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

  def step(frames=(), enabled=False, gear=GEAR_P, lat=False, tx_total=None, sample=None):
    """One card step on the background traffic plus these frames; returns every (address, dat, src) card put in 'sendcan'.
    tx_total: the panda's blocked-TX total (pandaStates.safetyTxBlocked) card sees in this step; sample: that pandaStates
    message's logMonoTime (a new value = a new sample)."""
    ps = [log.PandaState.new_message(controlsAllowed=False, safetyTxBlocked=int(tx_total or 0) & 0xFFFFFFFF)]
    if tx_total is not None:
      c.sm.valid["pandaStates"] = True
      c.sm.data["pandaStates"] = ps
    if sample is not None:
      c.sm.logMonoTime["pandaStates"] = int(sample)
    inbox.append(can_list_to_can_capnp(background(gear) + list(frames), msgtype="can"))
    CS, _ = c.state_update()
    c.sm.alive["carControl"] = True
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


# ---- radar gateway after a safety init in Drive (compiled panda safety code as the panda) ----

ELM327_PARAM = 1
SWITCH = 300           # card step of the panda's switch to the car's safety mode (~15 s after start on a car, shortened here)
CONFIG_398 = bytes((0x02, 0x81, 0x55, 0x53, 0, 0, 0, 0))   # car 0x398, as in the panda donor tests


class _Panda:
  """libsafety as the panda: ELM327 until switch(), then tesla with Pre-AP + radar gateway (flag 256). Every 0x560 card sends
  goes to its tx hook; gateway_open() feeds one car 0x398 and reports whether the panda put its 0x2A9 on the radar bus."""

  def __init__(self):
    from opendbc.car.structs import CarParams
    from opendbc.safety.tests.libsafety import libsafety_py
    from opendbc.safety.tests.test_tesla_preap import PREAP, SAFETY_TESLA, pkt
    from opendbc.safety.tests.test_tesla_preap_radar import RADAR, sent
    self.l, self.pkt, self.sent = libsafety_py.libsafety, pkt, sent
    self.mode_args = (SAFETY_TESLA, PREAP | RADAR)
    assert self.l.set_safety_hooks(int(CarParams.SafetyModel.elm327), ELM327_PARAM) == 0
    self.l.init_tests()
    self.tesla = False
    self.consumed = 0

  def switch(self):
    """The switch to the car's mode, and any later re-init: the panda clears the 0x560 config."""
    assert self.l.set_safety_hooks(*self.mode_args) == 0
    self.l.init_tests()
    self.l.set_timer(1_000_000)
    self.l.set_controls_allowed(False)
    self.tesla = True

  def tx(self, out):
    for addr, dat, src in out:
      if addr == 0x560 and self.tesla:
        assert not self.l.safety_tx_hook(self.pkt(addr, bytearray(dat), src))   # consumed, never on the car
        self.consumed += 1

  def gateway_open(self):
    if not self.tesla:
      return False
    self.l.safety_can_send_log_reset()
    self.l.safety_rx_hook(self.pkt(0x398, bytearray(CONFIG_398), 0))
    return any(addr == 0x2A9 and bus == 1 for addr, bus, _, _ in self.sent())


def _first_open(rig, panda, steps, gear_at, switch_at=SWITCH, reinit_at=None, enabled_at=lambda i: False):
  """{init step: first step the gateway was open after it (None if never)}, for the switch and an optional re-init."""
  opened, cur = {}, None
  for i in range(steps):
    if i in (switch_at, reinit_at):
      panda.switch()
      assert not panda.gateway_open()                   # config cleared: the gateway stays closed until 0x560 is complete
      cur = i
      opened[cur] = None
    panda.tx(rig.step(gear=gear_at(i), enabled=enabled_at(i)))
    if cur is not None and opened[cur] is None and panda.gateway_open():
      opened[cur] = i
  return opened


@pytest.mark.parametrize("drive_from", [0, 160, 240, 299, SWITCH + 5])
def test_drive_before_safety_switch_releases_radar_within_0_5s(make_rig, drive_from):
  # Fresh install: no donor VIN, no donor type. 92aa9ee1f sent no 0x560 in Drive: the gateway never opened for the drive.
  rig = make_rig()
  panda = _Panda()
  opened = _first_open(rig, panda, SWITCH + 200, lambda i: GEAR_D if i >= drive_from else GEAR_P)
  assert opened[SWITCH] is not None, "radar gateway never opened"
  assert (opened[SWITCH] - SWITCH) * 0.01 <= 0.5
  assert panda.consumed >= 3


def test_safety_reinit_while_in_drive_releases_radar_within_0_5s(make_rig):
  rig = make_rig(donor_type=2, donor_vin=VIN)
  panda = _Panda()
  reinit = 600
  opened = _first_open(rig, panda, reinit + 200, lambda i: GEAR_P if i < 400 else GEAR_D, switch_at=100, reinit_at=reinit)
  assert opened[100] is not None and (opened[100] - 100) * 0.01 <= 0.5
  assert opened[reinit] is not None, "radar gateway never reopened after the re-init in Drive"
  assert (opened[reinit] - reinit) * 0.01 <= 0.5


def test_reinit_while_engaged_waits_for_disengage(make_rig):
  # Engaged (or steering): no 0x560 from card, and the panda would ignore it. The gateway reopens <= 1 s after disengaging.
  rig = make_rig()
  panda = _Panda()
  reinit, release = 300, 500
  opened = _first_open(rig, panda, release + 150, lambda i: GEAR_D, switch_at=50, reinit_at=reinit,
                       enabled_at=lambda i: 200 <= i < release)
  assert opened[reinit] is not None and release <= opened[reinit] <= release + 100


# ---- the pedal FSM's blocked-TX input: card takes its own 0x560 frames back out ----

def _count_run(rig, steps, gear=GEAR_P, real=None, counted=lambda i: True, reset_at=None, start=0):
  """Model the panda counter: every 0x560 card sends is a blocked TX (counted unless counted(i) is False), plus real[i] other
  blocked frames; card sees the total in a new pandaStates sample every 10 steps. Returns what card fed the FSM
  (CS.preap_panda_tx_blocked) at each step."""
  real = real or {}
  live = sampled = start
  fed, own = [], 0
  ci, update = rig.car.CI, rig.car.CI.update

  def spy(*a, **kw):
    # what card hands the FSM this step, read just before CarInterface.update (the FSM consumes it inside, preap/carstate.py)
    fed.append(int(ci.CS.preap_panda_tx_blocked))
    ret = update(*a, **kw)
    ci.CS.preap_panda_tx_blocked = 0
    return ret
  ci.update = spy
  for i in range(steps):
    if i == reset_at:
      live = 0                                           # panda safety init clears its counter
    if i % 10 == 0:
      sampled = live
    out = rig.step(gear=gear, tx_total=sampled, sample=1 + i // 10)
    n560 = sum(1 for m in out if m[0] == 0x560)
    own += n560
    live += real.get(i, 0) + (n560 if counted(i) else 0)
  return fed, own


@pytest.mark.parametrize("gear", [GEAR_P, GEAR_D])
def test_own_0x560_blocks_never_reach_the_pedal_fsm(make_rig, gear):
  rig = make_rig()
  fed, own = _count_run(rig, 600, gear=gear)
  assert len(fed) == 600 and own >= 55                                       # the stream ran (any gear) and the panda counted every frame
  assert sum(fed) == 0 and min(fed) == 0


def test_real_blocked_tx_still_reaches_the_pedal_fsm_with_0x560_in_the_count(make_rig):
  rig = make_rig()
  real = {105: 1, 333: 1, 334: 1, 450: 5, 517: 25}       # e.g. refused pedal 0x551 frames, mixed with our 0x560
  fed, own = _count_run(rig, 600, gear=GEAR_D, real=real)
  assert own >= 55
  assert sum(fed) == sum(real.values())
  for i, n in real.items():
    nxt = (i // 10 + 1) * 10                            # next 10 Hz sample
    assert sum(fed[i:nxt + 1]) >= n, (i, fed[i:nxt + 1])


def test_uncounted_0x560_never_hides_a_later_block(make_rig):
  rig = make_rig()
  fed, _ = _count_run(rig, 400, real={200: 1, 300: 3}, counted=lambda i: i >= 150)   # sendcan lost before step 150
  assert sum(fed) == 4


def test_fewer_counted_than_sent_carries_nothing_into_the_next_sample(make_rig):
  # The 0x560 sent in steps 100-109 are never counted (blocked < sent: fed 0, never negative). The next sample has our counted
  # 0x560 plus one refused frame: the refusal reaches the FSM, no leftover credit from the window before hides it.
  rig = make_rig()
  fed, own = _count_run(rig, 200, gear=GEAR_D, real={115: 1}, counted=lambda i: not 100 <= i < 110)
  assert own >= 18 and min(fed) == 0
  assert sum(fed[100:111]) == 0 and sum(fed[111:121]) == 1 and sum(fed) == 1


def test_block_over_own_0x560_logs_a_warning_with_counts_only(make_rig, monkeypatch):
  rig = make_rig()
  warned = []
  monkeypatch.setattr(card.cloudlog, "warning", lambda msg, *a, **kw: warned.append(str(msg)))
  fed, _ = _count_run(rig, 300, gear=GEAR_D, real={150: 2})
  assert sum(fed) == 2
  assert len(warned) == 1 and "passed 2" in warned[0] and VIN not in warned[0]


def test_counter_reset_and_wrap(make_rig):
  rig = make_rig()
  fed, _ = _count_run(rig, 400, real={150: 1, 250: 2}, reset_at=200)
  assert min(fed) == 0 and sum(fed) == 3
  rig = make_rig()
  fed, _ = _count_run(rig, 300, real={150: 4, 250: 1}, start=0xFFFFFFFF - 20)   # the u32 total wraps at the step-170 sample
  assert min(fed) >= 0 and max(fed) <= 4
  assert sum(fed[150:]) == 5
