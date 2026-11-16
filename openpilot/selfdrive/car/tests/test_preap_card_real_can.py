"""Pre-AP card.py on real-format CAN: Car.state_update and Car.controls_update with the Read Radar VIN runner and the 0x560 stream.

The frames take the same path as on a car: can_list_to_can_capnp builds the capnp bytes that pandad publishes on 'can',
card.py's can_capnp_to_list turns them into (address, dat, src) tuples, and state_update / controls_update run on a real
Pre-AP CarInterface and RadarInterface. What card sends is read back out of the real 'sendcan' bytes.
Only the socket drain, the clock, the panda state and 'sendcan' publishing are stubbed. No capnp-like objects.
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

  def step(frames=(), enabled=False, gear=GEAR_P):
    """One card step on the background traffic plus these frames; returns every (address, dat, src) card put in 'sendcan'."""
    inbox.append(can_list_to_can_capnp(background(gear) + list(frames), msgtype="can"))
    CS, _ = c.state_update()
    c.sm.alive["carControl"] = True
    c.sm.valid["pandaStates"] = True
    c.sm.data["pandaStates"] = [log.PandaState.new_message(controlsAllowed=False)]
    cc = car.CarControl.new_message()
    cc.enabled = enabled
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
def test_0x560_stream_follows_donor_type_only_disengaged_and_not_in_drive(make_rig, donor_type):
  rig = make_rig(donor_type=donor_type, donor_vin=VIN)
  frames = [m for _ in range(60) for m in rig.step(gear=GEAR_P) if m[0] == 0x560]
  assert len(frames) == 6 and all(s == 0 and len(d) == 8 for _, d, s in frames)
  r0 = [d for _, d, _ in frames if d[0] == 0]
  assert r0 and all((d[2] >> 1) & 3 == donor_type and d[2] & 1 == 1 for d in r0)
  assert not [m for _ in range(60) for m in rig.step(gear=GEAR_D) if m[0] == 0x560]                 # in Drive
  assert not [m for _ in range(60) for m in rig.step(gear=GEAR_P, enabled=True) if m[0] == 0x560]   # engaged


def test_0x560_stream_off_without_radar_flag(make_rig):
  rig = make_rig(radar=False, donor_type=2, donor_vin=VIN)
  assert not [m for _ in range(60) for m in rig.step(gear=GEAR_P) if m[0] == 0x560]
