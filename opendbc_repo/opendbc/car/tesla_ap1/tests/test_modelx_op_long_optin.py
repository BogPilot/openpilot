"""AP1 Model X openpilot longitudinal (AP1XOpenpilotLong): default on for a detected X, an explicit Off keeps stock TACC, both
layers together, S and others unchanged."""
import tomllib
from pathlib import Path

import pytest

from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.safety_flags import flags_for_candidate
from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller
from opendbc.car.tesla_ap1.tests.test_release_interface import params as model_s_params
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.values import CAR

X = CAR.TESLA_AP1_MODELX
S = CAR.TESLA_AP1_MODELS
MOBILEYE = {0x399: 8, 0x2B9: 8, 0x488: 4}
AP1_FLAG, LONG_FLAG, STANDSTILL_FLAG = 8, 1, 16
TORQUE_DIR = Path(__file__).resolve().parents[2] / "torque_data"


@pytest.fixture(autouse=True)
def _files(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "_ap1_standstill_path", tmp_path / "AP1StandstillEngage")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (tmp_path / "Disable1", tmp_path / "Disable2"))
  return tmp_path


def _fp():
  return {0: dict(TINKLA_AP1_MODELX), 2: dict(MOBILEYE)}


def _opt_in(tmp_path, text="1"):
  (tmp_path / "AP1XOpenpilotLong").write_text(text)


def _x(fp=None):
  return CarInterface.get_params(X, _fp() if fp is None else fp, [], False, False, False)


def test_default_is_on_with_both_layers():
  cp = _x()                                                         # no file: default on
  assert cp.openpilotLongitudinalControl is True
  assert cp.safetyConfigs[0].safetyParam == AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG   # standstill engage default on, as the S
  assert toggles.ap1x_op_long(X) is True
  assert toggles.AP1X_OP_LONG_DEFAULT is True


@pytest.mark.parametrize("text", ["0", "false", "off", "OFF", "0\n", " off "])
def test_explicit_off_keeps_stock_tacc_lateral_only(_files, text):
  _opt_in(_files, text)
  cp = _x()
  assert cp.openpilotLongitudinalControl is False and cp.safetyConfigs[0].safetyParam == AP1_FLAG


@pytest.mark.parametrize("text", ["", "2", "yes", "garbage", " \n"])
def test_anything_but_off_is_the_default_on(_files, text):
  _opt_in(_files, text)
  cp = _x()
  assert cp.openpilotLongitudinalControl is True and cp.safetyConfigs[0].safetyParam == AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG


@pytest.mark.parametrize("fp", [S, CAR.TESLA_PREAP_MODELS, "TESLA_MODEL_Y", "", None])
def test_never_on_for_any_other_car(fp):
  assert toggles.ap1x_op_long(fp) is False and toggles.ap1x_op_long(fp, stored="1") is False


@pytest.mark.parametrize("text", ["1", "true", "on", "ON", "1\n"])
def test_on_enables_both_layers_together(_files, text):
  _opt_in(_files, text)
  cp = _x()
  assert cp.openpilotLongitudinalControl is True
  assert cp.safetyConfigs[0].safetyParam == AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG   # AP1 + LONG_CONTROL + standstill, as the S
  assert cp.dashcamOnly is False
  assert str(cp.safetyConfigs[0].safetyModel) == "tesla"


def test_flags_helper_default_unchanged_and_on_adds_long():
  assert flags_for_candidate(X) == (AP1_FLAG,)
  assert flags_for_candidate(X, x_long=True) == (AP1_FLAG | LONG_FLAG,)
  assert flags_for_candidate(X, standstill=True) == (AP1_FLAG,)                                        # never without long
  assert flags_for_candidate(X, standstill=True, x_long=True) == (AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG,)


def test_standstill_follows_openpilot_long_on_the_x(_files):
  _opt_in(_files)
  (_files / "AP1StandstillEngage").write_text("1")
  assert toggles.ap1_standstill_engage(X) is True
  assert toggles.ap1_standstill_engage(S) is True
  cp = _x()
  assert cp.safetyConfigs[0].safetyParam & STANDSTILL_FLAG
  ctl = make_controller(long=True, fingerprint=X, safety_param=AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG)
  assert ctl.ap1_standstill is True
  lateral = make_controller(long=False, fingerprint=X, safety_param=AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG)
  assert lateral.ap1_standstill is False


def test_disable_openpilot_long_wins(_files):
  _opt_in(_files)
  (_files / "Disable1").write_text("1")
  cp = _x()
  assert cp.openpilotLongitudinalControl is False and cp.safetyConfigs[0].safetyParam == AP1_FLAG


def test_never_without_strict_detection(_files):
  _opt_in(_files)
  empty = _x({})
  assert empty.dashcamOnly is True and empty.openpilotLongitudinalControl is False
  assert str(empty.safetyConfigs[0].safetyModel) == "noOutput"
  s_like = {0: {0x45: 8, 0x118: 6, 0x370: 8, 0x20A: 8, 0x201: 5}, 2: dict(MOBILEYE)}
  contradicted = _x(s_like)
  assert contradicted.dashcamOnly is True and contradicted.openpilotLongitudinalControl is False
  assert str(contradicted.safetyConfigs[0].safetyModel) == "noOutput"


def test_opt_in_file_does_not_touch_other_cars(_files):
  _opt_in(_files)
  assert toggles.ap1x_op_long(S) is False and toggles.ap1x_op_long("TESLA_MODEL_Y") is False
  assert toggles.ap1x_op_long(CAR.TESLA_PREAP_MODELS) is False and toggles.ap1x_op_long(None) is False
  cp = model_s_params()
  assert cp.openpilotLongitudinalControl is True and cp.safetyConfigs[0].safetyParam == 25
  assert flags_for_candidate(S, standstill=True) == (25,) and flags_for_candidate(S) == (9,)
  preap = CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)
  assert preap.dashcamOnly is False


def test_controller_tuning_follows_the_opt_in():
  off = make_controller(long=False, fingerprint=X)
  assert off.ap1_accel_smoother is None and off.ap1_jerk_limit is None
  on = make_controller(long=True, fingerprint=X, safety_param=AP1_FLAG | LONG_FLAG)
  assert on.ap1_accel_smoother is not None and on.ap1_jerk_limit is not None   # the X never sends raw planner accel with +-8 jerk
  assert on.cluster is not None and on.cluster_set_overlay is True and on.ap1_standstill is False
  assert off.cluster is not None and off.cluster_set_overlay is False


def test_setter_round_trip(_files):
  toggles.set_ap1x_op_long(True)
  assert toggles.ap1x_op_long(X) is True
  toggles.set_ap1x_op_long(False)
  assert toggles.ap1x_op_long(X) is False
  assert (_files / "AP1XOpenpilotLong").read_text() == "0"


def test_x_specs_and_own_torque_row():
  assert X.config.specs.wheelbase == pytest.approx(2.965) and X.config.specs.steerRatio == pytest.approx(16.8)
  override = tomllib.loads((TORQUE_DIR / "override.toml").read_text())
  substitute = tomllib.loads((TORQUE_DIR / "substitute.toml").read_text())
  assert "TESLA_AP1_MODELX" in override and "TESLA_AP1_MODELX" not in substitute          # its own row, not the Model 3 substitution
  assert str(override["TESLA_AP1_MODELX"]) == str(override["TESLA_MODEL_X"])               # same [nan, 2.5, nan] angle-controller stub
  assert substitute["TESLA_AP1_MODELS"] == "TESLA_MODEL_3"                                 # Model S untouched


def test_comfort_regen_v2_model_x_default_on_and_saved_value_kept(_files):
  # The preference is default on for the X (the consumer, comfort_regen.py, also needs X openpilot long).
  from opendbc.car.tesla_ap1 import regen_brake
  _opt_in(_files)
  assert regen_brake.regen_comfort_brake_enabled(X, stored="") is True
  assert regen_brake.regen_comfort_brake_enabled(X, stored="1") is True
  assert regen_brake.regen_comfort_brake_enabled(X, stored="0") is False
  assert regen_brake.regen_comfort_brake_enabled(S, stored="1") is True
  assert regen_brake.regen_comfort_brake_enabled(CAR.TESLA_PREAP_MODELS, stored="1") is True
