"""Lower on Park (ride_height.py): the 0x308 burst logic, the frame it builds, car state parsing and the controller gate."""
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus, structs
from opendbc.car.tesla_ap1 import ride_height as rh
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.values import CAR

GearShifter = structs.CarState.GearShifter
SCREEN = bytes.fromhex("4066ad0b3200f500")      # idle screen frame (byte 0 = 0x40)
LOW = rh.LEVEL_LOW
MED = rh.LEVEL_MEDIUM


def step(lop, *, park=True, known=True, tx=True, active=False, v=0.0, src=SCREEN, age=0.05, new=(), prefs=(True, LOW)):
  return lop.update(in_park=park, gear_known=known, can_tx=tx, controls_active=active, v_ego=v, source=src,
                    source_age_s=age, new_sources=new, prefs=lambda: prefs)


def enter_park(lop, **kw):
  step(lop, park=False)
  return step(lop, park=True, **kw)


def run_burst(lop, ticks=400, **kw):
  out = []
  for _ in range(ticks):
    out.append(step(lop, **kw))
  return out


# ---- frame building ----
def test_frame_replaces_only_byte0():
  assert rh.frame_with_level(SCREEN, LOW) == bytes.fromhex("4166ad0b3200f500")
  assert rh.frame_with_level(bytes.fromhex("4066d20b3200f400"), MED) == bytes.fromhex("4266d20b3200f400")
  for bad in (0, 3, 4, 5):
    with pytest.raises(ValueError):
      rh.frame_with_level(SCREEN, bad)
  with pytest.raises(ValueError):
    rh.frame_with_level(SCREEN[:7], LOW)


def test_constants_match_the_proven_burst():
  assert rh.RIDE_HEIGHT_ADDR == 0x308 and rh.RIDE_HEIGHT_BUS == 0
  assert rh.BURST_FRAMES == 100 and rh.BURST_PERIOD_FRAMES == 2      # 50 Hz for 2 s at the 100 Hz card rate
  assert rh.FLAG_TESLA_AP1_RIDE_HEIGHT == 1024


# ---- burst state machine ----
def test_one_burst_per_park_entry_100_frames_at_50hz():
  lop = rh.LowerOnPark()
  first = enter_park(lop)
  assert first == rh.frame_with_level(SCREEN, LOW)
  rest = run_burst(lop, 400)
  sent = [first] + [f for f in rest if f is not None]
  assert len(sent) == 100 and all(f == bytes.fromhex("4166ad0b3200f500") for f in sent)
  idx = [i for i, f in enumerate(rest) if f is not None]
  assert all(b - a == 2 for a, b in zip(idx, idx[1:], strict=False))   # every other 100 Hz step
  assert lop.state == lop.DONE and lop.last_result == "sent"
  assert all(f is None for f in run_burst(lop, 300))                 # still in Park: nothing more


def test_rearms_after_leaving_park():
  lop = rh.LowerOnPark()
  enter_park(lop); run_burst(lop, 300)
  assert enter_park(lop) is not None                                 # D -> P again: one more burst


def test_starting_up_in_park_is_not_an_entry():
  lop = rh.LowerOnPark()
  assert all(step(lop) is None for _ in range(50))
  assert enter_park(lop) is not None


def test_unknown_gear_neither_enters_nor_rearms():
  lop = rh.LowerOnPark()
  step(lop, park=False)
  assert step(lop, park=False, known=False) is None
  assert step(lop, park=True) is not None                            # prev stays "not Park" through the unknown frame
  assert step(lop, park=False, known=False) is None and lop.state == lop.DONE and lop.last_result == "left Park"


def test_medium_level_and_bytes_follow_the_newest_screen_frame():
  lop = rh.LowerOnPark()
  assert enter_park(lop, prefs=(True, MED)) == rh.frame_with_level(SCREEN, MED)
  newer = bytes.fromhex("4067b30b3200f400")
  out = [step(lop, src=newer, new=(newer,)) for _ in range(4)]
  assert [f for f in out if f is not None] == [bytes.fromhex("4267b30b3200f400")] * 2


@pytest.mark.parametrize("abort", [
  dict(park=False), dict(known=False), dict(active=True), dict(v=0.5), dict(age=0.6), dict(src=None), dict(tx=False),
  dict(new=(bytes.fromhex("4366ad0b3200f500"),)),      # driver tapped High on the screen
  dict(new=(bytes.fromhex("4266ad0b3200f500"),)),      # or any height
])
def test_burst_aborts(abort):
  lop = rh.LowerOnPark()
  assert enter_park(lop) is not None
  run_burst(lop, 10)
  assert step(lop, **abort) is None
  after = {"park": False} if abort.get("park") is False else {}
  assert all(f is None for f in run_burst(lop, 300, **after))        # and does not resume in the same Park stay
  assert lop.state in (lop.DONE, lop.IDLE)


@pytest.mark.parametrize("why,kw", [
  ("no panda permission", dict(tx=False)),
  ("off", dict(prefs=(False, LOW))),
  ("bad level", dict(prefs=(True, 3))),
  ("engaged or moving", dict(active=True)),
  ("engaged or moving", dict(v=0.3)),
  ("screen busy or 0x308 missing", dict(src=None)),
  ("screen busy or 0x308 missing", dict(age=1.0)),
  ("screen busy or 0x308 missing", dict(src=bytes.fromhex("4366ad0b3200f500"))),
  ("screen busy or 0x308 missing", dict(new=(bytes.fromhex("4466ad0b3200f500"),))),
])
def test_no_burst_when_not_allowed_at_entry(why, kw):
  lop = rh.LowerOnPark()
  assert enter_park(lop, **kw) is None
  assert lop.last_result == why
  assert all(step(lop) is None for _ in range(300))                  # decided once per Park entry


def test_prefs_read_only_at_park_entry():
  calls = []
  lop = rh.LowerOnPark()
  def prefs():
    calls.append(1)
    return (True, LOW)
  for _ in range(5):
    lop.update(in_park=False, gear_known=True, can_tx=True, controls_active=False, v_ego=0, source=SCREEN, source_age_s=0,
               prefs=prefs)
  lop.update(in_park=True, gear_known=True, can_tx=True, controls_active=False, v_ego=0, source=SCREEN, source_age_s=0, prefs=prefs)
  for _ in range(50):
    lop.update(in_park=True, gear_known=True, can_tx=True, controls_active=False, v_ego=0, source=SCREEN, source_age_s=0,
               prefs=prefs)
  assert len(calls) == 1


# ---- files ----
def test_files_defaults_and_round_trip(tmp_path):
  e, h, d = tmp_path / "LowerOnPark", tmp_path / "LowerOnParkHeight", tmp_path / "AirSuspensionDetected"
  assert rh.enabled(path=e) is False and rh.height(path=h) == "low" and rh.level_for(path=h) == LOW
  assert rh.air_suspension_detected(path=d) is False
  rh.set_enabled(True, path=e); rh.set_height("medium", path=h)
  assert rh.enabled(path=e) is True and rh.height(path=h) == "medium" and rh.level_for(path=h) == MED
  for junk in ("", "2", "high", "very high", "garbage"):
    assert rh.height(junk) == "low"
  with pytest.raises(ValueError):
    rh.set_height("high", path=h)
  assert rh.write_air_suspension_detected(True, path=d) is True and rh.write_air_suspension_detected(True, path=d) is False
  assert rh.air_suspension_detected(path=d) is True


def test_car_config_flag():
  assert rh.air_suspension_from_car_config(1) is True and rh.air_suspension_from_car_config(0) is False
  assert rh.air_suspension_from_car_config(None) is None


def test_tx_supported_needs_the_build_gate_and_the_drive_bit(monkeypatch):
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", False)
  assert rh.tx_supported(9 | 1024) is False
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)
  assert rh.tx_supported(9 | 1024) is True and rh.tx_supported(9) is False and rh.tx_supported(8 | 1024) is True


# ---- car state ----
def _send(parser, name, values, t):
  addr, dat, _ = CANPacker("tesla_ap1_can").make_can_msg(name, parser.bus, values)
  parser.update([(t, [(addr, dat, parser.bus)])])


def _send_many(parser, items, t):
  packer = CANPacker("tesla_ap1_can")
  frames = []
  for name, values in items:
    addr, dat, _ = packer.make_can_msg(name, parser.bus, values)
    frames.append((addr, dat, parser.bus))
  parser.update([(t, frames)])


def _rh_values(data):
  return {f"UI_rideHeightByte{i}": data[i] for i in range(8)}


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_carstate_rebuilds_0x308_and_reads_air_suspension(fp, tmp_path, monkeypatch):
  monkeypatch.setattr(rh, "_detected_path", tmp_path / "AirSuspensionDetected")
  cp = SimpleNamespace(carFingerprint=fp)
  state, parsers = CarState(cp), CarState.get_can_parsers(cp)
  chassis = parsers[Bus.chassis]
  assert 0x308 in chassis.message_states
  _send_many(chassis, [("UI_rideHeightRequest", _rh_values(SCREEN)), ("GTW_carConfig", {"GTW_airSuspensionInstalled": 1})],
             1_000_000_000)
  state.update(parsers)
  assert state.ride_height_last == SCREEN and state.ride_height_frames == [SCREEN]
  assert state.ride_height_age_s == 0.0
  assert state.air_suspension is True and rh.air_suspension_detected() is True
  _send(chassis, "GTW_carState", {}, 1_050_000_000)                 # a step with no 0x308: the newest is kept, 50 ms old
  state.update(parsers)
  assert state.ride_height_frames == [] and state.ride_height_last == SCREEN and abs(state.ride_height_age_s - 0.05) < 1e-6
  tap = bytes.fromhex("4366ad0b3200f500")
  _send(chassis, "UI_rideHeightRequest", _rh_values(tap), 1_100_000_000)
  state.update(parsers)
  assert state.ride_height_frames == [tap] and state.ride_height_last == tap
  _send(chassis, "GTW_carConfig", {"GTW_airSuspensionInstalled": 0}, 1_200_000_000)
  state.update(parsers)
  assert state.air_suspension is False and rh.air_suspension_detected() is False


def test_carstate_without_0x308_has_no_source(tmp_path, monkeypatch):
  monkeypatch.setattr(rh, "_detected_path", tmp_path / "AirSuspensionDetected")
  cp = SimpleNamespace(carFingerprint=CAR.TESLA_AP1_MODELS)
  state, parsers = CarState(cp), CarState.get_can_parsers(cp)
  _send(parsers[Bus.chassis], "GTW_carState", {}, 1_000_000_000)
  state.update(parsers)
  assert state.ride_height_last is None and state.ride_height_age_s == float("inf") and state.air_suspension is None


# ---- controller gate ----
def _cc(enabled=False):
  return SimpleNamespace(enabled=enabled, latActive=False, longActive=False)


def _cs(gear, src=SCREEN, new=()):
  return SimpleNamespace(out=SimpleNamespace(gearShifter=gear, vEgo=0.0), ride_height_last=src, ride_height_age_s=0.05,
                         ride_height_frames=list(new))


def _controller(fp, param):
  from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller
  return make_controller(fingerprint=fp, safety_param=param)


def test_controller_inert_in_this_build_even_with_the_bit(monkeypatch):
  monkeypatch.setattr(rh, "enabled", lambda *a, **k: True)
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", False)
  c = _controller(CAR.TESLA_AP1_MODELS, 9 | 1024)
  c.lower_on_park_frame(_cc(), _cs(GearShifter.drive))
  assert c.lower_on_park_frame(_cc(), _cs(GearShifter.park)) is None


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_controller_sends_on_park_entry_when_the_panda_allows(monkeypatch, fp):
  monkeypatch.setattr(rh, "enabled", lambda *a, **k: True)
  monkeypatch.setattr(rh, "level_for", lambda *a, **k: LOW)
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)
  c = _controller(fp, 8 | 1024)
  assert c.lower_on_park_frame(_cc(), _cs(GearShifter.drive)) is None
  assert c.lower_on_park_frame(_cc(), _cs(GearShifter.park)) == bytes.fromhex("4166ad0b3200f500")
  frame = c.tesla_can.create_ride_height_request(bytes.fromhex("4166ad0b3200f500"))
  assert (frame.address, bytes(frame.dat), frame.src) == (0x308, bytes.fromhex("4166ad0b3200f500"), 0)
  # No bit in this drive's safety param (Lower on Park was off at car start): nothing.
  c2 = _controller(fp, 8)
  c2.lower_on_park_frame(_cc(), _cs(GearShifter.drive))
  assert c2.lower_on_park_frame(_cc(), _cs(GearShifter.park)) is None
  # Engaged at the Park entry: nothing.
  c3 = _controller(fp, 8 | 1024)
  c3.lower_on_park_frame(_cc(), _cs(GearShifter.drive))
  assert c3.lower_on_park_frame(_cc(enabled=True), _cs(GearShifter.park)) is None


def test_preap_controller_never_builds_0x308():
  from opendbc.car.tesla_ap1.carcontroller import CarController
  from opendbc.car.tesla_ap1.values import DBC
  CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=False, safetyConfigs=[])
  try:
    c = CarController(DBC[CAR.TESLA_PREAP_MODELS], CP)
  except Exception:
    pytest.skip("Pre-AP uses its own controller")
  assert c.lower_on_park is None


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_controller_step_tolerates_minimal_carstate(monkeypatch, fp):
  # Other controller tests pass minimal CarState stubs (no gearShifter). The step must never raise on them.
  from types import SimpleNamespace
  monkeypatch.setattr(rh, "enabled", lambda *a, **k: True)
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)
  stub = SimpleNamespace(out=SimpleNamespace())
  assert _controller(fp, 8).lower_on_park_frame(_cc(), stub) is None
  assert _controller(fp, 8 | 1024).lower_on_park_frame(_cc(), stub) is None
