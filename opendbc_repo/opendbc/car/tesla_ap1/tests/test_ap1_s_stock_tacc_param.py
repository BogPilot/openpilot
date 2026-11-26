"""AP1 Model S with Disable openpilot Longitudinal Control on: the lateral only AP1 safety param 8, the same as the AP1 Model X,
and the controller never plans DAS_control (0x2b9), so the panda forwards the stock DAS_control. With Disable off nothing changes."""
from collections import deque
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.safety_flags import flags_for_candidate
from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller, record_requests
from opendbc.car.tesla_ap1.tests.test_release_interface import params as model_s_params
from opendbc.car.tesla_ap1.values import CAR

S, X = CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX
AP1_FLAG, LONG_FLAG, STANDSTILL_FLAG = 8, 1, 16
DAS = 0x2B9


@pytest.fixture(autouse=True)
def _files(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "_ap1_standstill_path", tmp_path / "AP1StandstillEngage")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (tmp_path / "Disable1", tmp_path / "Disable2"))
  return tmp_path


def _cs():
  return SimpleNamespace(
    out=SimpleNamespace(steeringAngleDeg=1.0, vEgo=10.0, gasPressed=False, standstill=False,
                        gearShifter=structs.CarState.GearShifter.drive),
    steer_warning="EAC_ERROR_IDLE", hands_on_level=0, eac_fault=False, eac_status="EAC_ACTIVE",
    acc_state=4, das_control_counters=deque([1]), msg_stw_actn_req={}, cluster_stock={},
    stock_steer_counters=[3], stock_ap_active=False,
  )


def _sent(cp):
  ctl = make_controller(long=cp.openpilotLongitudinalControl, fingerprint=S, safety_param=cp.safetyConfigs[0].safetyParam)
  CC = structs.CarControl()
  CC.enabled = CC.latActive = CC.longActive = True
  CC.actuators.accel = 0.4
  CC.actuators.steeringAngleDeg = 4.0
  reqs = record_requests(ctl)
  _out, can = ctl.update(CC, _cs(), 10_000_000)
  return [name for name, _v, _b in reqs], [frame[0] for frame in can]


@pytest.mark.parametrize("standstill", ["", "1", "0"])
@pytest.mark.parametrize("where", ["Disable1", "Disable2"])
def test_disable_on_is_param_8_like_the_model_x(_files, standstill, where):
  if standstill:
    (_files / "AP1StandstillEngage").write_text(standstill)
  (_files / where).write_text("1")
  cp = model_s_params()
  assert cp.openpilotLongitudinalControl is False
  assert cp.safetyConfigs[0].safetyParam == AP1_FLAG
  names, addrs = _sent(cp)
  assert "DAS_control" not in names and DAS not in addrs
  assert "DAS_steeringControl" in names


def test_disable_off_unchanged(_files):
  cp = model_s_params()
  assert cp.openpilotLongitudinalControl is True
  assert cp.safetyConfigs[0].safetyParam == AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG
  (_files / "AP1StandstillEngage").write_text("0")
  assert model_s_params().safetyConfigs[0].safetyParam == AP1_FLAG | LONG_FLAG


def test_flags_helper_same_rule_for_both_cars():
  for st in (False, True):
    assert flags_for_candidate(S, standstill=st, s_long=False) == flags_for_candidate(X, standstill=st, x_long=False) == (AP1_FLAG,)
    assert flags_for_candidate(S, standstill=st) == flags_for_candidate(X, standstill=st, x_long=True)
  assert flags_for_candidate(S) == (AP1_FLAG | LONG_FLAG,)                       # default keeps a direct call as before
