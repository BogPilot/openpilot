"""Auto Height, Drive part (ride_height.py HeightOnDrive): one 2 s 0x308 burst per shift from Park into Drive, at standstill."""
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1 import ride_height as rh
from opendbc.car.tesla_ap1.values import CAR

GearShifter = structs.CarState.GearShifter
SCREEN = bytes.fromhex("4066ad0b3200f500")      # idle screen frame (byte 0 = 0x40)
LOW = rh.LEVEL_LOW
MED = rh.LEVEL_MEDIUM
HIGH = rh.LEVEL_HIGH
VHIGH = rh.LEVEL_VERY_HIGH


@pytest.fixture(autouse=True)
def _settings_saved_at_once(monkeypatch):
  # these tests read and write the setting files directly; the background save is tested in test_auto_height_durable_save.py
  monkeypatch.setattr(rh, "_save", rh._durable_write)


def step(hod, gear="drive", *, tx=True, active=False, v=0.0, gas=False, src=SCREEN, age=0.05, new=(), level=MED):
  return hod.update(gear=gear, can_tx=tx, controls_active=active, v_ego=v, gas_pressed=gas, source=src, source_age_s=age,
                    new_sources=new, prefs=lambda: (level is not None, level))   # level None = Auto Height off


def shift_p_to_d(hod, **kw):
  step(hod, "park")
  return step(hod, "drive", **kw)


def run(hod, ticks=400, **kw):
  return [step(hod, **kw) for _ in range(ticks)]


# ---- settings file ----
def test_drive_height_file_default_medium_and_round_trip(tmp_path):
  f = tmp_path / rh.DRIVE_HEIGHT_KEY
  assert rh.DRIVE_HEIGHT_KEY == "AutoHeightDrive"
  assert rh.drive_height(path=f) == "medium" and rh.drive_level_for(path=f) == MED
  for value, level in (("low", LOW), ("medium", MED), ("high", HIGH), ("very_high", VHIGH)):
    rh.set_drive_height(value, path=f)
    assert f.read_text() == value and rh.drive_height(path=f) == value and rh.drive_level_for(path=f) == level
  for junk in ("", "1", "3", "off", "garbage"):
    f.write_text(junk)
    assert rh.drive_height(path=f) == "medium" and rh.drive_level_for(path=f) == MED
  with pytest.raises(ValueError):
    rh.set_drive_height("off", path=f)


@pytest.mark.parametrize("old", [{"LowerOnPark": "1"}, {"LowerOnPark": "0"}, {"LowerOnParkHeight": "low"},
                                 {"LowerOnPark": "1", "LowerOnParkHeight": "medium"}])
def test_drive_height_starts_at_none_after_lower_on_park(tmp_path, old):
  for name, value in old.items():
    (tmp_path / name).write_text(value)
  f = tmp_path / "AutoHeightDrive"
  assert rh.drive_height(path=f) == "none" and rh.drive_level_for(path=f) is None
  assert {n: (tmp_path / n).read_text() for n in old} == old and not f.exists()      # reading writes nothing
  rh.set_drive_height("high", path=f)                                                # a picked height wins
  assert rh.drive_level_for(path=f) == HIGH
  assert {n: (tmp_path / n).read_text() for n in old} == old


def test_fresh_setup_drive_default_is_medium(tmp_path):
  assert rh.drive_height(path=tmp_path / "AutoHeightDrive") == "medium"
  (tmp_path / "AutoHeight").write_text("1")                          # a fresh setup turning Auto Height on
  assert rh.drive_height(path=tmp_path / "AutoHeightDrive") == "medium"


def test_drive_none_round_trip_and_no_burst(tmp_path):
  f = tmp_path / "AutoHeightDrive"
  rh.set_drive_height("none", path=f)
  assert f.read_text() == "none" and rh.drive_height(path=f) == "none" and rh.drive_level_for(path=f) is None
  hod = rh.HeightOnDrive()
  for _ in range(3):
    hod.update(gear="park", can_tx=True, controls_active=False, v_ego=0.0, gas_pressed=False, source=SCREEN, source_age_s=0.05,
               prefs=lambda: (True, None))
    out = [hod.update(gear="drive", can_tx=True, controls_active=False, v_ego=0.0, gas_pressed=False, source=SCREEN,
                      source_age_s=0.05, prefs=lambda: (True, None)) for _ in range(300)]
    assert all(f is None for f in out) and hod.last_result == "none"


@pytest.mark.parametrize("level,byte0", [(LOW, 0x41), (MED, 0x42), (HIGH, 0x43), (VHIGH, 0x44)])
def test_every_level_builds_its_frame(level, byte0):
  assert rh.frame_with_level(SCREEN, level) == bytes([byte0]) + SCREEN[1:]


def test_drive_choices_follow_the_panda_gate(monkeypatch):
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", False)
  assert rh.drive_choices() == ()
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  assert rh.drive_choices() == ("low", "medium", "high", "very_high", "none")


def test_own_flag_bit_and_capability_gate(monkeypatch):
  assert rh.FLAG_TESLA_AP1_RIDE_HEIGHT_DRIVE == 2048
  assert rh.FLAG_TESLA_AP1_RIDE_HEIGHT_DRIVE & rh.FLAG_TESLA_AP1_RIDE_HEIGHT == 0
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", False)
  assert rh.drive_tx_supported(8 | 1024 | 2048) is False and rh.drive_tx_supported() is False
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  assert rh.drive_tx_supported(8 | 2048) is True and rh.drive_tx_supported() is True
  assert rh.drive_tx_supported(8 | 1024) is False      # the Park bit alone never allows Drive


# ---- burst state machine ----
@pytest.mark.parametrize("level,byte0", [(LOW, 0x41), (MED, 0x42), (HIGH, 0x43), (VHIGH, 0x44)])
def test_one_burst_per_shift_100_frames_at_50hz(level, byte0):
  hod = rh.HeightOnDrive()
  first = shift_p_to_d(hod, level=level)
  assert first == bytes([byte0]) + SCREEN[1:]
  rest = run(hod, 400, level=level)
  sent = [first] + [f for f in rest if f is not None]
  assert len(sent) == 100 and all(f == first for f in sent)
  idx = [i for i, f in enumerate(rest) if f is not None]
  assert all(b - a == 2 for a, b in zip(idx, idx[1:], strict=False))
  assert hod.state == hod.DONE and hod.last_result == "sent"
  assert all(step(hod) is None for _ in range(300))                  # staying in Drive never sends again


def test_next_shift_from_park_sends_again():
  hod = rh.HeightOnDrive()
  assert shift_p_to_d(hod) is not None
  run(hod, 300)
  assert shift_p_to_d(hod) is not None


def test_off_sends_nothing():
  hod = rh.HeightOnDrive()
  assert shift_p_to_d(hod, level=None) is None and hod.last_result == "off"
  assert all(f is None for f in run(hod, 300))


def test_bad_level_sends_nothing():
  for bad in (0, 5, 6, -1):
    hod = rh.HeightOnDrive()
    assert shift_p_to_d(hod, level=bad) is None and hod.last_result == "bad level"


def test_only_a_shift_from_park_counts():
  # Starting up already in Drive is not a shift.
  hod = rh.HeightOnDrive()
  assert all(f is None for f in run(hod, 50))
  # Reverse to Drive (three-point turn) is not a shift from Park.
  hod = rh.HeightOnDrive()
  step(hod, "park")
  step(hod, "reverse")
  assert step(hod, "drive") is None
  # Park, Neutral, Drive while stopped counts.
  hod = rh.HeightOnDrive()
  step(hod, "park")
  step(hod, "neutral")
  assert step(hod, "drive") is not None
  # Unknown gear on the way changes nothing.
  hod = rh.HeightOnDrive()
  step(hod, "park")
  step(hod, "unknown")
  assert step(hod, "drive") is not None


def test_rolling_disarms_and_entry_needs_standstill():
  hod = rh.HeightOnDrive()
  step(hod, "park")
  step(hod, "neutral", v=0.5)                                         # rolling in Neutral disarms
  assert step(hod, "drive") is None
  hod = rh.HeightOnDrive()
  assert shift_p_to_d(hod, v=0.2) is None                             # already moving at the shift
  assert step(hod, v=0.0) is None                                     # stopping later does not start it


@pytest.mark.parametrize("kw,why", [({"active": True}, "engaged, moving or gas pressed"),
                                    ({"gas": True}, "engaged, moving or gas pressed"),
                                    ({"tx": False}, "no panda permission"),
                                    ({"src": None}, "screen busy or 0x308 missing"),
                                    ({"age": 0.6}, "screen busy or 0x308 missing"),
                                    ({"src": bytes.fromhex("4266ad0b3200f500")}, "screen busy or 0x308 missing"),
                                    ({"new": (bytes.fromhex("4266ad0b3200f500"),)}, "screen busy or 0x308 missing")])
def test_refused_at_the_shift(kw, why):
  hod = rh.HeightOnDrive()
  assert shift_p_to_d(hod, **kw) is None and hod.last_result == why
  assert all(f is None for f in run(hod, 300))                        # decided once per shift


@pytest.mark.parametrize("kw,why", [({"new": (bytes.fromhex("4366ad0b3200f500"),)}, "driver tapped a height"),
                                    ({"active": True}, "engaged"),
                                    ({"v": 0.3}, "moving"),
                                    ({"gas": True}, "gas pressed"),
                                    ({"age": 0.6}, "0x308 stale"),
                                    ({"tx": False}, "no panda permission")])
def test_burst_stops_at_once(kw, why):
  hod = rh.HeightOnDrive()
  assert shift_p_to_d(hod) is not None
  run(hod, 9)
  assert step(hod, **kw) is None and hod.state == hod.DONE and hod.last_result == why
  assert all(f is None for f in run(hod, 300))


@pytest.mark.parametrize("gear", ["park", "neutral", "reverse", "unknown"])
def test_leaving_drive_stops_the_burst(gear):
  hod = rh.HeightOnDrive()
  assert shift_p_to_d(hod) is not None
  run(hod, 9)
  assert step(hod, gear) is None and hod.last_result == "left Drive"


def test_frames_follow_the_newest_screen_frame():
  hod = rh.HeightOnDrive()
  assert shift_p_to_d(hod) == bytes.fromhex("4266ad0b3200f500")
  newer = bytes.fromhex("4066d20b3200f400")
  out = [f for f in run(hod, 10, src=newer) if f is not None]
  assert out and all(f == bytes.fromhex("4266d20b3200f400") for f in out)


# ---- car controller ----
def _cc(enabled=False):
  return SimpleNamespace(enabled=enabled, latActive=False, longActive=False)


def _cs(gear, src=SCREEN, v=0.0, gas=False):
  return SimpleNamespace(out=SimpleNamespace(gearShifter=gear, vEgo=v, gasPressed=gas), ride_height_last=src,
                         ride_height_age_s=0.05, ride_height_frames=[])


def _controller(fp, param):
  from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller
  return make_controller(fingerprint=fp, safety_param=param)


def test_controller_inert_until_the_panda_rule_ships(monkeypatch):
  monkeypatch.setattr(rh, "enabled", lambda *a, **k: True)
  monkeypatch.setattr(rh, "drive_level_for", lambda *a, **k: MED)
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", False)
  c = _controller(CAR.TESLA_AP1_MODELS, 9 | 2048)
  c.height_on_drive_frame(_cc(), _cs(GearShifter.park))
  assert c.height_on_drive_frame(_cc(), _cs(GearShifter.drive)) is None


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_controller_sends_on_park_to_drive_when_the_panda_allows(monkeypatch, fp):
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "enabled", lambda *a, **k: True)
  for level, frame in ((LOW, "4166ad0b3200f500"), (MED, "4266ad0b3200f500"), (HIGH, "4366ad0b3200f500"),
                       (VHIGH, "4466ad0b3200f500")):
    monkeypatch.setattr(rh, "drive_level_for", lambda *a, level=level, **k: level)
    c = _controller(fp, 8 | 2048)
    assert c.height_on_drive_frame(_cc(), _cs(GearShifter.park)) is None
    assert c.height_on_drive_frame(_cc(), _cs(GearShifter.drive)) == bytes.fromhex(frame)
    tx = c.tesla_can.create_ride_height_request(bytes.fromhex(frame))
    assert (tx.address, bytes(tx.dat), tx.src) == (0x308, bytes.fromhex(frame), 0)
  # Without its bit (Auto Height was off at car start), and with only the Park bit: nothing.
  for param in (8, 8 | 1024):
    c2 = _controller(fp, param)
    c2.height_on_drive_frame(_cc(), _cs(GearShifter.park))
    assert c2.height_on_drive_frame(_cc(), _cs(GearShifter.drive)) is None
  # Engaged or gas pressed at the shift: nothing.
  for cc, cs in ((_cc(enabled=True), _cs(GearShifter.drive)), (_cc(), _cs(GearShifter.drive, gas=True))):
    c3 = _controller(fp, 8 | 2048)
    c3.height_on_drive_frame(_cc(), _cs(GearShifter.park))
    assert c3.height_on_drive_frame(cc, cs) is None


@pytest.mark.parametrize("fp", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_controller_step_tolerates_minimal_carstate(monkeypatch, fp):
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  stub = SimpleNamespace(out=SimpleNamespace())
  assert _controller(fp, 8 | 2048).height_on_drive_frame(_cc(), stub) is None


def test_park_and_drive_parts_never_send_in_the_same_step(monkeypatch):
  monkeypatch.setattr(rh, "enabled", lambda *a, **k: True)
  monkeypatch.setattr(rh, "level_for", lambda *a, **k: LOW)
  monkeypatch.setattr(rh, "drive_level_for", lambda *a, **k: MED)
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  c = _controller(CAR.TESLA_AP1_MODELS, 9 | 1024 | 2048)
  for gear in (GearShifter.drive, GearShifter.park, GearShifter.park, GearShifter.drive, GearShifter.drive):
    a = c.lower_on_park_frame(_cc(), _cs(gear))
    b = c.height_on_drive_frame(_cc(), _cs(gear))
    assert a is None or b is None


def test_controller_master_switch_off_sends_nothing(monkeypatch):
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "enabled", lambda *a, **k: False)
  monkeypatch.setattr(rh, "drive_level_for", lambda *a, **k: MED)
  c = _controller(CAR.TESLA_AP1_MODELS, 8 | 1024 | 2048)
  c.height_on_drive_frame(_cc(), _cs(GearShifter.park))
  assert c.height_on_drive_frame(_cc(), _cs(GearShifter.drive)) is None and c.height_on_drive.last_result == "off"


def test_controller_reads_the_real_files(monkeypatch, tmp_path):
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "_enable_path", tmp_path / "AutoHeight")
  monkeypatch.setattr(rh, "_drive_height_path", tmp_path / "AutoHeightDrive")
  (tmp_path / "AutoHeight").write_text("1")                          # fresh setup: Drive default Medium
  c = _controller(CAR.TESLA_AP1_MODELX, 8 | 1024 | 2048)
  c.height_on_drive_frame(_cc(), _cs(GearShifter.park))
  assert c.height_on_drive_frame(_cc(), _cs(GearShifter.drive)) == bytes.fromhex("4266ad0b3200f500")
  (tmp_path / "AutoHeight").unlink()
  (tmp_path / "LowerOnPark").write_text("1")                         # moved over from Lower on Park: on, Drive at None
  c = _controller(CAR.TESLA_AP1_MODELX, 8 | 1024 | 2048)
  c.height_on_drive_frame(_cc(), _cs(GearShifter.park))
  assert c.height_on_drive_frame(_cc(), _cs(GearShifter.drive)) is None and c.height_on_drive.last_result == "none"
  (tmp_path / "AutoHeightDrive").write_text("medium")                 # until a Drive height is picked
  c.height_on_drive_frame(_cc(), _cs(GearShifter.park))
  assert c.height_on_drive_frame(_cc(), _cs(GearShifter.drive)) == bytes.fromhex("4266ad0b3200f500")


def test_both_none_never_send_anything(monkeypatch, tmp_path):
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "PANDA_PARK_LEVELS", (1, 2, 3, 4))
  monkeypatch.setattr(rh, "_enable_path", tmp_path / "AutoHeight")
  monkeypatch.setattr(rh, "_height_path", tmp_path / "AutoHeightPark")
  monkeypatch.setattr(rh, "_drive_height_path", tmp_path / "AutoHeightDrive")
  rh.set_enabled(True); rh.set_height("none"); rh.set_drive_height("none")
  c = _controller(CAR.TESLA_AP1_MODELS, 9 | 1024 | 2048)          # even with both panda bits
  sent = []
  for _ in range(3):
    for gear in [GearShifter.drive] * 50 + [GearShifter.park] * 300 + [GearShifter.drive] * 300:
      sent.append(c.lower_on_park_frame(_cc(), _cs(gear)))
      sent.append(c.height_on_drive_frame(_cc(), _cs(gear)))
  assert all(f is None for f in sent)
  assert c.lower_on_park.last_result == "none" and c.height_on_drive.last_result == "none"
