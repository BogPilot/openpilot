"""A user-fixed AP1 model is taken as given: no live re-check sets dashcam. 0x399 is not part of AP1 detection."""
import pytest
from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.modelx_fingerprint import detect_ap1_candidate
from opendbc.car.tesla_ap1.values import AP1_CHASSIS_SIGNATURE, CAR, ForcedFingerprint, match_ap1_chassis

FP_SOURCE = structs.CarParams.FingerprintSource


def fp(bus2=None, bus0=True):
  out = gen_empty_fingerprint()
  if bus0:
    out[0] = dict(AP1_CHASSIS_SIGNATURE)
  out[2] = {0x2B9: 8, 0x488: 4} if bus2 is None else dict(bus2)
  return out


def select(monkeypatch, candidate, finger, source, override=None):
  from opendbc.car import car_helpers
  from opendbc.car.vin import VIN_UNKNOWN
  monkeypatch.setattr(car_helpers, "fingerprint", lambda *args: (candidate, finger, VIN_UNKNOWN, [], source, True))
  return car_helpers.get_car(lambda *args: [], lambda *args: None, lambda *args: None, False, False,
                             cached_params=None, fingerprint_override=override)


def forced(model):
  return lambda detected: (model, True)


def assert_drivable(cp):
  assert not cp.dashcamOnly
  assert str(cp.safetyConfigs[0].safetyModel) == "tesla"


# forced model (CarModel + ForceFingerprint), live bus not yet complete
@pytest.mark.parametrize("finger", [
  fp(),                                                 # 0x399 has not arrived yet
  fp({0x399: 8, 0x2B9: 8, 0x488: 4}),                   # everything arrived
  fp({}),                                               # camera messages missing
  fp({0x2B9: 8}),                                       # only one camera message so far
  fp(bus0=False),                                       # chassis messages missing
  gen_empty_fingerprint(),                              # nothing seen
])
def test_forced_ap1_is_never_dashcam_from_the_live_fingerprint(monkeypatch, finger):
  ci = select(monkeypatch, None, finger, FP_SOURCE.can, forced(CAR.TESLA_AP1_MODELS))
  assert ci.CP.carFingerprint == CAR.TESLA_AP1_MODELS
  assert ci.CP.fingerprintSource == FP_SOURCE.fixed
  assert_drivable(ci.CP)
  assert ci.CP.openpilotLongitudinalControl and ci.CP.safetyConfigs[0].safetyParam == 25


def test_forced_over_a_failed_detection_keeps_model_s_params_identical_to_a_detected_car(monkeypatch):
  detected = select(monkeypatch, None, fp({0x399: 8, 0x2B9: 8, 0x488: 4}), FP_SOURCE.can)
  late = select(monkeypatch, None, fp(), FP_SOURCE.can, forced(CAR.TESLA_AP1_MODELS))
  assert detected.CP.fingerprintSource == FP_SOURCE.can and late.CP.fingerprintSource == FP_SOURCE.fixed
  for field in ("dashcamOnly", "openpilotLongitudinalControl", "steerControlType", "steerActuatorDelay", "steerLimitTimer"):
    assert getattr(detected.CP, field) == getattr(late.CP, field)
  assert detected.CP.safetyConfigs[0].safetyParam == late.CP.safetyConfigs[0].safetyParam


def test_fixed_fingerprint_env_source_is_also_forced(monkeypatch):
  ci = select(monkeypatch, CAR.TESLA_AP1_MODELS, fp(), FP_SOURCE.fixed)
  assert_drivable(ci.CP)
  ci = select(monkeypatch, CAR.TESLA_AP1_MODELS, gen_empty_fingerprint(), FP_SOURCE.fixed)
  assert_drivable(ci.CP)


def test_forced_model_x_keeps_the_model_s_only_traffic_rule(monkeypatch):
  # the S-vs-X contradiction check is a different rule and is kept
  clean = select(monkeypatch, None, fp(), FP_SOURCE.can, forced(CAR.TESLA_AP1_MODELX))
  assert not clean.CP.dashcamOnly and clean.CP.fingerprintSource == FP_SOURCE.fixed
  finger = fp()
  finger[0][0x165] = 8                                  # Model S-only message on a forced Model X
  contradicted = select(monkeypatch, None, finger, FP_SOURCE.can, forced(CAR.TESLA_AP1_MODELX))
  assert contradicted.CP.dashcamOnly and str(contradicted.CP.safetyConfigs[0].safetyModel) == "noOutput"


def test_forcing_a_stock_tesla_does_not_wrap_the_fingerprint(monkeypatch):
  from opendbc.car.tesla.interface import CarInterface as StockInterface
  from opendbc.car.tesla.values import CAR as TESLA
  seen = []
  original = StockInterface.get_params.__func__

  def spy(cls, candidate, fingerprint, *args, **kwargs):
    seen.append(type(fingerprint))
    return original(cls, candidate, fingerprint, *args, **kwargs)
  monkeypatch.setattr(StockInterface, "get_params", classmethod(spy))
  select(monkeypatch, None, fp(), FP_SOURCE.can, forced(TESLA.TESLA_MODEL_3))
  assert seen and set(seen) == {dict}


# unforced: behavior is unchanged except that 0x399 is no longer required
def test_unforced_detection_without_0x399_is_ap1(monkeypatch):
  finger = fp()
  assert match_ap1_chassis(finger) and detect_ap1_candidate(finger) == CAR.TESLA_AP1_MODELS
  ci = select(monkeypatch, None, finger, FP_SOURCE.can)
  assert ci.CP.carFingerprint == CAR.TESLA_AP1_MODELS and ci.CP.fingerprintSource == FP_SOURCE.can
  assert_drivable(ci.CP)


def test_unforced_with_0x399_is_unchanged(monkeypatch):
  finger = fp({0x399: 8, 0x2B9: 8, 0x488: 4})
  assert match_ap1_chassis(finger)
  assert_drivable(select(monkeypatch, None, finger, FP_SOURCE.can).CP)


@pytest.mark.parametrize("finger", [
  fp({0x399: 8, 0x488: 4}),                             # 0x2B9 missing
  fp({0x399: 8, 0x2B9: 8}),                             # 0x488 missing
  fp({0x2B9: 8, 0x488: 5}),                             # wrong length
  fp({0x399: 8}),                                       # 0x399 alone is not Mobileye evidence
  fp({}),
  fp(bus0=False),
  gen_empty_fingerprint(),
])
def test_unforced_still_needs_chassis_and_the_two_camera_messages(finger):
  assert not match_ap1_chassis(finger)
  cp = CarInterface.get_params(CAR.TESLA_AP1_MODELS, finger, [], False, False, False)
  assert cp.dashcamOnly and str(cp.safetyConfigs[0].safetyModel) == "noOutput"


def test_unforced_params_path_with_a_plain_dict_is_unchanged_without_chassis():
  finger = fp()
  assert not isinstance(finger, ForcedFingerprint)
  assert not CarInterface.get_params(CAR.TESLA_AP1_MODELS, finger, [], False, False, False).dashcamOnly
  del finger[0][0x45]
  assert CarInterface.get_params(CAR.TESLA_AP1_MODELS, finger, [], False, False, False).dashcamOnly
  assert not CarInterface.get_params(CAR.TESLA_AP1_MODELS, ForcedFingerprint(finger), [], False, False, False).dashcamOnly


def test_preap_chassis_without_mobileye_is_still_not_ap1_and_not_forced_by_0x399_removal(monkeypatch):
  finger = gen_empty_fingerprint()
  finger[0] = dict(AP1_CHASSIS_SIGNATURE)
  assert not match_ap1_chassis(finger) and detect_ap1_candidate(finger) is None
  assert select(monkeypatch, None, finger, FP_SOURCE.can).CP.brand == "mock"
