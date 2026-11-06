from opendbc.car.tesla_ap1.values import CAR, AP1_CHASSIS_SIGNATURE, match_ap1_chassis, DBC
from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.safety_flags import flags_for_candidate
from opendbc.car.tesla_ap1.stalk_pull_hold import StalkPullHold, PULL_HOLD_S, RWD
from opendbc.car import Bus


def test_chassis_only_preap_never_matches():
  assert not match_ap1_chassis({0: dict(AP1_CHASSIS_SIGNATURE)})
  assert not match_ap1_chassis(None)


def test_ap1_requires_stock_mobileye_on_camera_bus():
  fp = {0: dict(AP1_CHASSIS_SIGNATURE), 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}
  assert match_ap1_chassis(fp)
  fp[2][0x488] = 8
  assert not match_ap1_chassis(fp)
  fp[1] = fp.pop(2)
  assert not match_ap1_chassis(fp)


def test_default_ic_and_standstill_are_ap1_only(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ic_integration_path", tmp_path / "IC")
  monkeypatch.setattr(toggles, "_ap1_standstill_path", tmp_path / "Standstill")
  assert toggles.enable_ic_integration(CAR.TESLA_AP1_MODELS)
  assert toggles.ap1_standstill_engage(CAR.TESLA_AP1_MODELS)
  assert not toggles.enable_ic_integration("TESLA_MODEL_3", "1")
  assert not toggles.ap1_standstill_engage("TESLA_MODEL_Y", "1")
  assert not toggles.enable_ic_integration(CAR.TESLA_AP1_MODELS, "0")
  assert not toggles.ap1_standstill_engage(CAR.TESLA_AP1_MODELS, "0")
  assert flags_for_candidate(CAR.TESLA_AP1_MODELS, standstill=True) == (25,)
  assert DBC[CAR.TESLA_AP1_MODELS][Bus.chassis] == "tesla_ap1_can"


def test_stalk_hold_does_not_toggle_on_engage_pull():
  hold = StalkPullHold()
  for _ in range(int(PULL_HOLD_S / 0.01) + 20):
    assert not hold.update(RWD, False, 0.01)
