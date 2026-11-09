"""Model X specs, safety flags, and get_params. Model S longitudinal stays on."""
import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.safety_flags import flags_for_candidate
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.tests.test_release_interface import params as model_s_params
from opendbc.car.tesla_ap1.values import CAR

X = CAR.TESLA_AP1_MODELX
MOBILEYE = {0x399: 8, 0x2B9: 8, 0x488: 4}


def _x_fp():
  return {0: dict(TINKLA_AP1_MODELX), 2: dict(MOBILEYE)}


def test_model_x_specs():
  specs = X.config.specs
  assert specs.wheelbase == pytest.approx(2.964)
  assert specs.steerRatio == pytest.approx(15.0)
  assert specs.centerToFrontRatio == pytest.approx(0.5)
  cp = CarInterface.get_params(X, _x_fp(), [], False, False, False)
  assert cp.wheelbase == pytest.approx(2.964)
  assert cp.steerRatio == pytest.approx(15.0)
  assert cp.centerToFront == pytest.approx(1.482)


def test_model_x_matching_fingerprint_is_lateral_only():
  cp = CarInterface.get_params(X, _x_fp(), [], False, False, False)
  assert cp.brand == "tesla_ap1"
  assert cp.steerControlType == structs.CarParams.SteerControlType.angle
  assert str(cp.safetyConfigs[0].safetyModel) == "tesla"
  assert cp.safetyConfigs[0].safetyParam == 8
  assert cp.openpilotLongitudinalControl is False
  assert cp.dashcamOnly is False
  assert cp.steerLimitTimer == pytest.approx(1.0)
  assert cp.steerActuatorDelay == pytest.approx(0.25)
  assert flags_for_candidate(X) == (8,)
  assert flags_for_candidate(X, standstill=True) == (8,)


def test_model_x_empty_or_s_evidence_is_dashcam():
  empty = CarInterface.get_params(X, {}, [], False, False, False)
  assert empty.dashcamOnly is True
  assert str(empty.safetyConfigs[0].safetyModel) == "noOutput"

  s_like = {0: {0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8, 0x201: 5}, 2: dict(MOBILEYE)}
  contradicted = CarInterface.get_params(X, s_like, [], False, False, False)
  assert contradicted.dashcamOnly is True
  assert str(contradicted.safetyConfigs[0].safetyModel) == "noOutput"


def test_model_s_params_unchanged():
  cp = model_s_params()
  assert cp.brand == "tesla_ap1"
  assert cp.openpilotLongitudinalControl is True
  assert cp.dashcamOnly is False
  assert str(cp.safetyConfigs[0].safetyModel) == "tesla"
  assert cp.safetyConfigs[0].safetyParam == 25
  assert cp.wheelbase == pytest.approx(2.959)
  assert flags_for_candidate(CAR.TESLA_AP1_MODELS, standstill=True) == (25,)
  assert flags_for_candidate(CAR.TESLA_AP1_MODELS) == (9,)
