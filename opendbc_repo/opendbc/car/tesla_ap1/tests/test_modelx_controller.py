"""Model X uses the structural AP1 lateral pieces and emits no DAS_control."""
from collections import deque
from types import SimpleNamespace

from opendbc.car import structs
from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller, record_requests
from opendbc.car.tesla_ap1.values import CAR, TeslaAp1SafetyFlags

X = CAR.TESLA_AP1_MODELX
S = CAR.TESLA_AP1_MODELS
STANDSTILL = int(TeslaAp1SafetyFlags.AP1 | TeslaAp1SafetyFlags.LONG_CONTROL | TeslaAp1SafetyFlags.STANDSTILL)
DAS = 0x2B9


def _cs():
  return SimpleNamespace(
    out=SimpleNamespace(steeringAngleDeg=1.0, vEgo=10.0, gasPressed=False, standstill=False),
    steer_warning="EAC_ERROR_IDLE", hands_on_level=0, eac_fault=False, eac_status="EAC_ACTIVE",
    acc_state=4, das_control_counters=deque([1]), msg_stw_actn_req={}, cluster_stock={},
    stock_steer_counters=[3], stock_ap_active=False,
  )


def _step(controller):
  CC = structs.CarControl()
  CC.enabled = True
  CC.latActive = True
  CC.longActive = True
  CC.actuators.accel = 0.4
  CC.actuators.steeringAngleDeg = 4.0
  reqs = record_requests(controller)
  _out, can = controller.update(CC, _cs(), 10_000_000)
  names = [name for name, _vals, _bus in reqs]
  addrs = [frame[0] for frame in can]
  return names, addrs


def test_model_x_structural_only_and_no_das():
  ctl = make_controller(long=False, fingerprint=X)
  assert ctl.ap1_steer_ramp is not None
  assert ctl.ap1_steer_sync is not None
  assert ctl.ap1_yield is not None
  assert ctl.cluster is None
  assert ctl.ap1_accel_smoother is None
  assert ctl.ap1_jerk_limit is None
  assert ctl.ap1_standstill is False

  flagged = make_controller(long=False, fingerprint=X, safety_param=STANDSTILL)
  assert flagged.ap1_standstill is False

  names, addrs = _step(ctl)
  assert "DAS_control" not in names
  assert DAS not in addrs


def test_model_s_controller_unchanged():
  ctl = make_controller(long=True)
  assert ctl.cluster is not None
  assert ctl.ap1_accel_smoother is not None
  assert ctl.ap1_jerk_limit is not None
  assert ctl.ap1_steer_ramp is not None
  assert ctl.ap1_steer_sync is not None
  assert ctl.ap1_standstill is False

  flagged = make_controller(long=True, fingerprint=S, safety_param=STANDSTILL)
  assert flagged.ap1_standstill is True

  ctl.cluster = None
  names, addrs = _step(ctl)
  assert "DAS_control" in names
  assert DAS in addrs
