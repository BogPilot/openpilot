"""AP1 Model X with Disable openpilot Longitudinal Control on: stock TACC with openpilot steering. Disable wins over
AP1XOpenpilotLong at car start, the car keeps the stock cruise engage state (pcmCruise), the panda gets the lateral-only flag
and the controller never plans DAS_control (0x2b9)."""
from collections import deque
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller, record_requests
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.values import CAR

X = CAR.TESLA_AP1_MODELX
MOBILEYE = {0x399: 8, 0x2B9: 8, 0x488: 4}
AP1_FLAG, LONG_FLAG = 8, 1
DAS = 0x2B9


@pytest.fixture(autouse=True)
def _files(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "_ap1_standstill_path", tmp_path / "AP1StandstillEngage")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (tmp_path / "Disable1", tmp_path / "Disable2"))
  return tmp_path


def _x():
  return CarInterface.get_params(X, {0: dict(TINKLA_AP1_MODELX), 2: dict(MOBILEYE)}, [], False, False, False)


def _cs():
  return SimpleNamespace(
    out=SimpleNamespace(steeringAngleDeg=1.0, vEgo=10.0, gasPressed=False, standstill=False),
    steer_warning="EAC_ERROR_IDLE", hands_on_level=0, eac_fault=False, eac_status="EAC_ACTIVE",
    acc_state=4, das_control_counters=deque([1]), msg_stw_actn_req={}, cluster_stock={},
    stock_steer_counters=[3], stock_ap_active=False,
  )


def _sent(cp):
  ctl = make_controller(long=cp.openpilotLongitudinalControl, fingerprint=X, safety_param=cp.safetyConfigs[0].safetyParam)
  CC = structs.CarControl()
  CC.enabled = CC.latActive = CC.longActive = True
  CC.actuators.accel = 0.4
  CC.actuators.steeringAngleDeg = 4.0
  reqs = record_requests(ctl)
  _out, can = ctl.update(CC, _cs(), 10_000_000)
  return [name for name, _v, _b in reqs], [frame[0] for frame in can]


@pytest.mark.parametrize("x_long", ["", "1", "0"])
@pytest.mark.parametrize("where", ["Disable1", "Disable2"])
def test_disable_on_is_stock_tacc_whatever_the_model_x_row_says(_files, x_long, where):
  if x_long:
    (_files / "AP1XOpenpilotLong").write_text(x_long)
  (_files / where).write_text("1")
  cp = _x()
  assert cp.openpilotLongitudinalControl is False
  assert cp.pcmCruise is True                                   # engage follows the car's own cruise (DI_state)
  assert cp.safetyConfigs[0].safetyParam == AP1_FLAG             # lateral only: the panda refuses any 0x2b9 from openpilot
  names, addrs = _sent(cp)
  assert "DAS_control" not in names and DAS not in addrs
  assert "DAS_steeringControl" in names                         # openpilot still steers


def test_disable_off_gives_openpilot_long_back(_files):
  (_files / "Disable1").write_text("0")
  cp = _x()
  assert cp.openpilotLongitudinalControl is True and cp.safetyConfigs[0].safetyParam == AP1_FLAG | LONG_FLAG
  names, addrs = _sent(cp)
  assert "DAS_control" in names and DAS in addrs


def test_min_enable_speed_is_unset_on_the_x_and_the_s(_files):
  # No openpilot engage-speed gate on either car, openpilot long on or off: engagement follows the car's cruise state.
  assert _x().minEnableSpeed == -1.0
  (_files / "Disable1").write_text("1")
  assert _x().minEnableSpeed == -1.0
  assert X.config.specs.minEnableSpeed == -1.0 and CAR.TESLA_AP1_MODELS.config.specs.minEnableSpeed == -1.0
