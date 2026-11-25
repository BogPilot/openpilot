"""Auto Height Very Low (ride_height.py): the AP1 Model X level 7 (0x308 byte 0 = 0x47), offered only on a Model X and only once
the panda allows it. A saved Very Low is asked for as Low anywhere else."""
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1 import ride_height as rh
from opendbc.car.tesla_ap1.values import CAR

GearShifter = structs.CarState.GearShifter
SCREEN = bytes.fromhex("407f9ab616010600")      # idle Model X screen frame (byte 0 = 0x40)
VLOW = rh.LEVEL_VERY_LOW


@pytest.fixture
def very_low_panda(monkeypatch):
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "PANDA_PARK_LEVELS", (1, 2, 3, 4))
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "PANDA_VERY_LOW_SUPPORTED", True)


def test_level_and_label():
  assert VLOW == 7 and rh.LEVEL_BY_HEIGHT["very_low"] == 7 and rh.HEIGHT_LABELS["very_low"] == "Very Low"
  assert rh.X_HEIGHTS == ("very_low", "low", "medium", "high", "very_high")
  assert rh.X_CHOICES == ("very_low", "low", "medium", "high", "very_high", "none")
  assert rh.CHOICES == ("low", "medium", "high", "very_high", "none")          # Model S unchanged
  assert rh.frame_with_level(SCREEN, VLOW) == bytes.fromhex("477f9ab616010600")
  for bad in (0, 5, 6, 8):
    with pytest.raises(ValueError):
      rh.frame_with_level(SCREEN, bad)


def test_choices_model_x_only(very_low_panda):
  assert rh.park_choices(model_x=True) == ("very_low", "low", "medium", "high", "very_high", "none")
  assert rh.drive_choices(model_x=True) == ("very_low", "low", "medium", "high", "very_high", "none")
  assert rh.park_choices(model_x=False) == ("low", "medium", "high", "very_high", "none")
  assert rh.drive_choices(model_x=False) == ("low", "medium", "high", "very_high", "none")
  assert rh.park_choices() == rh.CHOICES and rh.drive_choices() == rh.CHOICES


def test_gate_hides_very_low_until_the_panda_allows_it(monkeypatch, very_low_panda):
  monkeypatch.setattr(rh, "PANDA_VERY_LOW_SUPPORTED", False)
  assert rh.very_low_offered(True) is False
  assert rh.park_choices(model_x=True) == rh.CHOICES and rh.drive_choices(model_x=True) == rh.CHOICES
  assert rh.level_for("very_low", model_x=True) == rh.LEVEL_LOW
  lop = rh.LowerOnPark()
  lop.update(in_park=False, gear_known=True, can_tx=True, controls_active=False, v_ego=0, source=SCREEN, source_age_s=0.05)
  out = lop.update(in_park=True, gear_known=True, can_tx=True, controls_active=False, v_ego=0, source=SCREEN, source_age_s=0.05,
                   prefs=lambda: (True, VLOW))
  assert out is None and lop.last_result == "bad level"


def test_saved_very_low_round_trip_and_fallback(tmp_path, very_low_panda):
  park, drive = tmp_path / rh.HEIGHT_KEY, tmp_path / rh.DRIVE_HEIGHT_KEY
  rh.set_height("very_low", path=park); rh.set_drive_height("Very Low", path=drive)
  assert park.read_text() == "very_low" and drive.read_text() == "very_low"
  assert rh.height(path=park) == "very_low" and rh.drive_height(path=drive) == "very_low"
  assert rh.level_for(path=park, model_x=True) == VLOW and rh.drive_level_for(path=drive, model_x=True) == VLOW
  assert rh.level_for(path=park, model_x=False) == rh.LEVEL_LOW                 # Model S: asked for as Low
  assert rh.drive_level_for(path=drive, model_x=False) == rh.LEVEL_LOW
  assert rh.level_for(path=park) == rh.LEVEL_LOW
  assert rh.shown_height("very_low", model_x=True) == "very_low" and rh.shown_height("very_low", model_x=False) == "low"
  assert rh.shown_height("high", model_x=False) == "high"
  assert rh.park_burst_wanted(path=park, enable_path=tmp_path / "missing") is False
  (tmp_path / rh.ENABLE_KEY).write_text("1")
  assert rh.park_burst_wanted(path=park, enable_path=tmp_path / rh.ENABLE_KEY) is True


def test_park_and_drive_bursts_send_0x47(very_low_panda):
  lop = rh.LowerOnPark()
  lop.update(in_park=False, gear_known=True, can_tx=True, controls_active=False, v_ego=0, source=SCREEN, source_age_s=0.05)
  sent = [lop.update(in_park=True, gear_known=True, can_tx=True, controls_active=False, v_ego=0, source=SCREEN,
                     source_age_s=0.05, prefs=lambda: (True, VLOW)) for _ in range(300)]
  sent = [f for f in sent if f is not None]
  assert len(sent) == rh.BURST_FRAMES and {f[0] for f in sent} == {0x47} and lop.last_result == "sent"
  hod = rh.HeightOnDrive()
  hod.update(gear="park", can_tx=True, controls_active=False, v_ego=0, gas_pressed=False, source=SCREEN, source_age_s=0.05)
  sent = [hod.update(gear="drive", can_tx=True, controls_active=False, v_ego=0, gas_pressed=False, source=SCREEN,
                     source_age_s=0.05, prefs=lambda: (True, VLOW)) for _ in range(300)]
  sent = [f for f in sent if f is not None]
  assert len(sent) == rh.BURST_FRAMES and {f[0] for f in sent} == {0x47} and hod.last_result == "sent"


def _cc():
  return SimpleNamespace(enabled=False, latActive=False, longActive=False)


def _cs(gear):
  return SimpleNamespace(out=SimpleNamespace(gearShifter=gear, vEgo=0.0, gasPressed=False), ride_height_last=SCREEN,
                         ride_height_age_s=0.05, ride_height_frames=[])


def _controller(fp, param):
  from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller
  return make_controller(fingerprint=fp, safety_param=param)


@pytest.mark.parametrize("fp,param,byte0", [
  (CAR.TESLA_AP1_MODELX, 8 | 1024 | 2048 | 4096, 0x47),
  (CAR.TESLA_AP1_MODELX, 8 | 1024 | 2048, 0x41),         # no Very Low bit this drive: asked for as Low
  (CAR.TESLA_AP1_MODELS, 9 | 1024 | 2048 | 4096, 0x41),  # never Very Low on the Model S
  (CAR.TESLA_AP1_MODELS, 9 | 1024 | 2048, 0x41),
])
def test_controller_asks_model_x_for_very_low_and_model_s_for_low(monkeypatch, tmp_path, very_low_panda, fp, param, byte0):
  monkeypatch.setattr(rh, "_enable_path", tmp_path / rh.ENABLE_KEY)
  monkeypatch.setattr(rh, "_height_path", tmp_path / rh.HEIGHT_KEY)
  monkeypatch.setattr(rh, "_drive_height_path", tmp_path / rh.DRIVE_HEIGHT_KEY)
  rh.set_enabled(True); rh.set_height("very_low"); rh.set_drive_height("very_low")
  c = _controller(fp, param)
  c.lower_on_park_frame(_cc(), _cs(GearShifter.drive))
  park = c.lower_on_park_frame(_cc(), _cs(GearShifter.park))
  assert park is not None and park[0] == byte0 and park[1:] == SCREEN[1:]
  c = _controller(fp, param)
  c.height_on_drive_frame(_cc(), _cs(GearShifter.park))
  drive = c.height_on_drive_frame(_cc(), _cs(GearShifter.drive))
  assert drive is not None and drive[0] == byte0


def test_panda_rule_ships_and_flag_value():
  from opendbc.car.tesla_ap1.values import TeslaAp1SafetyFlags
  assert rh.PANDA_VERY_LOW_SUPPORTED is True
  assert rh.FLAG_TESLA_AP1_RIDE_HEIGHT_VERY_LOW == int(TeslaAp1SafetyFlags.AP1_RIDE_HEIGHT_VERY_LOW) == 4096
  assert rh.very_low_tx_supported(True, 8 | 1024 | 4096) is True
  assert rh.very_low_tx_supported(True, 8 | 1024) is False and rh.very_low_tx_supported(False, 9 | 1024 | 4096) is False


@pytest.mark.parametrize("candidate,kw,want", [
  (CAR.TESLA_AP1_MODELX, dict(ride_height=True, ride_height_very_low=True), 8 | 1024 | 4096),
  (CAR.TESLA_AP1_MODELX, dict(ride_height_drive=True, ride_height_very_low=True), 8 | 2048 | 4096),
  (CAR.TESLA_AP1_MODELX, dict(ride_height=True, ride_height_drive=True, ride_height_very_low=True), 8 | 1024 | 2048 | 4096),
  (CAR.TESLA_AP1_MODELX, dict(ride_height_very_low=True), 8),                 # never without the Park or Drive bit
  (CAR.TESLA_AP1_MODELX, dict(ride_height=True), 8 | 1024),
  (CAR.TESLA_AP1_MODELS, dict(ride_height=True, ride_height_drive=True, ride_height_very_low=True), 9 | 1024 | 2048),
  (CAR.TESLA_PREAP_MODELS, dict(ride_height=True, ride_height_very_low=True), 0),
])
def test_safety_flag_model_x_only(candidate, kw, want):
  from opendbc.car.tesla_ap1.safety_flags import flags_for_candidate
  assert flags_for_candidate(candidate, **kw) == (want,)
