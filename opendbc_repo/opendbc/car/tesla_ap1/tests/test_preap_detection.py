"""Pre-AP detection and the platform/flag plumbing. AP1 must never be detected as Pre-AP."""
from types import SimpleNamespace

from opendbc.car.tesla_ap1.preap.detection import detect_preap_candidate, match_preap
from opendbc.car.tesla_ap1.safety_flags import (FLAG_TESLA_PREAP, FLAG_TESLA_PREAP_PEDAL, dashcam_only_for_candidate,
                                                flags_for_candidate, flags_for_preap)
from opendbc.car.tesla_ap1.values import AP1_CHASSIS_SIGNATURE, CAR, CANBUS, TeslaAp1SafetyFlags, is_ap1_family, is_preap, match_ap1_chassis
from opendbc.car.tesla_ap1.modelx_fingerprint import detect_ap1_candidate

MOBILEYE = {0x399: 8, 0x2B9: 8, 0x488: 4}


def fp(bus2=None, bus0_extra=None):
  bus0 = dict(AP1_CHASSIS_SIGNATURE)
  bus0.update(bus0_extra or {})
  return {CANBUS.chassis: bus0, CANBUS.autopilot_chassis: dict(bus2 or {})}


def test_pedal_on_bus2_no_mobileye_is_preap():
  f = fp({0x552: 6})
  assert match_preap(f) and detect_preap_candidate(f) == CAR.TESLA_PREAP_MODELS
  assert detect_ap1_candidate(f) is None             # AP1 detection says no, so car_helpers falls through to Pre-AP


def test_pedal_on_bus0_is_preap():
  assert detect_preap_candidate(fp(bus0_extra={0x552: 6})) == CAR.TESLA_PREAP_MODELS


def test_chassis_only_without_pedal_is_not_auto_detected():
  assert detect_preap_candidate(fp()) is None


def test_ap1_car_is_never_preap_and_stays_ap1():
  f = fp({**MOBILEYE, 0x552: 6})
  assert not match_preap(f) and detect_preap_candidate(f) is None
  assert match_ap1_chassis(f) and detect_ap1_candidate(f) == CAR.TESLA_AP1_MODELS


def test_any_single_mobileye_frame_blocks_preap():
  for addr, length in MOBILEYE.items():
    assert detect_preap_candidate(fp({0x552: 6, addr: length})) is None


def test_wrong_pedal_length_or_missing_chassis_signature():
  assert detect_preap_candidate(fp({0x552: 8})) is None
  f = fp({0x552: 6}); del f[CANBUS.chassis][0x45]
  assert detect_preap_candidate(f) is None
  assert detect_preap_candidate(None) is None and detect_preap_candidate({}) is None and detect_preap_candidate("x") is None


def test_platform_helpers_and_flags():
  assert is_preap(CAR.TESLA_PREAP_MODELS) and is_preap("TESLA_PREAP_MODELS")
  assert not is_preap(CAR.TESLA_AP1_MODELS) and not is_preap(None) and not is_preap(True)
  assert not is_ap1_family(CAR.TESLA_PREAP_MODELS)
  assert (FLAG_TESLA_PREAP, FLAG_TESLA_PREAP_PEDAL) == (32, 64)
  # no overlap with LONG_CONTROL=1, deprecated bit 2, AP1=8, STANDSTILL=16
  assert FLAG_TESLA_PREAP & (TeslaAp1SafetyFlags.LONG_CONTROL | 2 | TeslaAp1SafetyFlags.AP1 | TeslaAp1SafetyFlags.STANDSTILL) == 0
  assert flags_for_preap(pedal=False) == 32 and flags_for_preap(pedal=True) == 96
  assert not (flags_for_preap(pedal=True) & TeslaAp1SafetyFlags.AP1)
  assert dashcam_only_for_candidate(CAR.TESLA_PREAP_MODELS) is False
  # AP1 flags unchanged
  assert flags_for_candidate(CAR.TESLA_AP1_MODELS) == (TeslaAp1SafetyFlags.AP1 | TeslaAp1SafetyFlags.LONG_CONTROL,)


def test_interface_params(tmp_path, monkeypatch):
  from opendbc.car.tesla_ap1 import toggles
  from opendbc.car.tesla_ap1.interface import CarInterface
  for disabled, pedal in (("0", True), ("1", False)):
    f = tmp_path / f"d{disabled}"; f.write_text(disabled)
    monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (f,))
    CP = CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)
    assert CP.brand == "tesla_ap1" and not CP.dashcamOnly and CP.radarUnavailable
    assert CP.openpilotLongitudinalControl == pedal and CP.pcmCruise == (not pedal)
    sc = CP.safetyConfigs[0]
    assert str(sc.safetyModel) == "tesla"
    assert sc.safetyParam == (96 if pedal else 32)
    assert str(CP.steerControlType) == "angle"
