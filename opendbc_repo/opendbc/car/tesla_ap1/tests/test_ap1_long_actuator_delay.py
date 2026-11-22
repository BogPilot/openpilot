"""longitudinalActuatorDelay per platform: AP1 Model S 0.35 s and AP1 Model X 0.35 s (both were 0.5), Pre-AP 0.4 s."""
import pytest

from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.interface import CarInterface, AP1_S_LONG_ACTUATOR_DELAY
from opendbc.car.tesla_ap1.tests.test_release_interface import params as model_s_params
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.values import CAR


@pytest.fixture(autouse=True)
def _no_device_files(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (tmp_path / "Disable1", tmp_path / "Disable2"))


def test_model_s_uses_the_measured_delay():
  assert AP1_S_LONG_ACTUATOR_DELAY == pytest.approx(0.35)
  cp = model_s_params()
  assert cp.openpilotLongitudinalControl
  assert cp.longitudinalActuatorDelay == pytest.approx(0.35)


def test_model_x_uses_the_same_delay_as_the_model_s():
  fp = {0: dict(TINKLA_AP1_MODELX), 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}
  cp = CarInterface.get_params(CAR.TESLA_AP1_MODELX, fp, [], False, False, False)
  assert cp.longitudinalActuatorDelay == pytest.approx(0.35)


def test_preap_keeps_its_own_delay():
  cp = CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)
  assert cp.longitudinalActuatorDelay == pytest.approx(0.4)


def test_lateral_delays_unchanged():
  assert model_s_params().steerActuatorDelay == pytest.approx(0.25)
  assert CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False).steerActuatorDelay == pytest.approx(0.1)
  fp = {0: dict(TINKLA_AP1_MODELX), 2: {0x399: 8, 0x2B9: 8, 0x488: 4}}
  assert CarInterface.get_params(CAR.TESLA_AP1_MODELX, fp, [], False, False, False).steerActuatorDelay == pytest.approx(0.15)
