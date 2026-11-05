"""NAP-style Pre-AP pedal longitudinal unit tests (host-safe).

Covers PedalZeroTorque learn, compute_pedal_command deadband/ramps/hysteresis,
VirtualDAS feedforward, and PedalAuthority FSM. No CAN / no device.
"""
from __future__ import annotations

import math

from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.car.tesla.preap.pedal_authority import (
  PedalAuthority, PedalAuthorityState, PedalCommandAction,
)
from openpilot.selfdrive.car.tesla.preap.pedal_controller import (
  PedalZeroTorque, compute_pedal_command,
)
from openpilot.selfdrive.car.tesla.preap.pedal_feedback import PedalFeedback
from openpilot.selfdrive.car.tesla.preap.vdas_constants import (
  ACCEL_DEADBAND, PEDAL_DI_ZERO, PEDAL_HYST_GAP,
  PEDAL_RAMP_RATE_DOWN, PEDAL_RAMP_RATE_UP,
)
from openpilot.selfdrive.car.tesla.preap.virtual_das import VirtualDAS


class _FakeFeedback:
  def __init__(self, available=True, state=0, idx=0):
    self.available = available
    self.interceptor_state = state
    self.idx = idx


def test_zero_torque_learns_above_10mph_in_deadband():
  zt = PedalZeroTorque()
  assert zt.get(0.0) == PEDAL_DI_ZERO
  v = 12.0 * CV.MPH_TO_MS
  for _ in range(30):
    zt.update(-5.0, current_pedal_di=3.0, v_ego=v, control_active=True, accel_command=0.0)
  assert abs(zt.value - 3.0) < 0.5
  assert zt.get(4.0 * CV.MPH_TO_MS) == PEDAL_DI_ZERO


def test_zero_torque_ignores_large_accel_command():
  zt = PedalZeroTorque()
  v = 15.0 * CV.MPH_TO_MS
  for _ in range(40):
    zt.update(-5.0, current_pedal_di=4.0, v_ego=v, control_active=True,
              accel_command=ACCEL_DEADBAND + 0.1)
  assert zt.value == PEDAL_DI_ZERO


def test_compute_pedal_deadband_and_ramps():
  import openpilot.selfdrive.car.tesla.preap.pedal_controller as pc
  pc.current_pedal_transform = lambda: (0.0, 1.0)  # type: ignore
  pc._zero_torque = PedalZeroTorque()
  cmd, di = compute_pedal_command(0.0, v_ego=20.0, prev_pedal_di=5.0)
  assert math.isfinite(cmd) and math.isfinite(di)
  _, di_up = compute_pedal_command(2.5, v_ego=20.0, prev_pedal_di=0.0)
  assert di_up <= PEDAL_RAMP_RATE_UP + 1e-6
  _, di_dn = compute_pedal_command(-1.5, v_ego=20.0, prev_pedal_di=10.0)
  assert di_dn >= 10.0 - PEDAL_RAMP_RATE_DOWN - 1e-6


def test_compute_pedal_hysteresis_holds():
  import openpilot.selfdrive.car.tesla.preap.pedal_controller as pc
  pc.current_pedal_transform = lambda: (0.0, 1.0)  # type: ignore
  pc._zero_torque = PedalZeroTorque()
  _, di = compute_pedal_command(0.5, v_ego=20.0, prev_pedal_di=0.0)
  _, di2 = compute_pedal_command(0.5, v_ego=20.0, prev_pedal_di=di)
  assert di2 == di
  assert PEDAL_HYST_GAP > 0


def test_vdas_feedforward_zero_and_positive():
  vdas = VirtualDAS(dt=0.02)
  vdas.reset(measured_accel=0.0, commanded_accel=0.0, pedal_di_init=0.0)
  di = 0.0
  for _ in range(10):
    di = vdas.update(0.0, v_ego=20.0, prev_pedal_di=di, a_ego=0.0,
                     orientation_ned=[0.0, 0.0, 0.0])
  assert abs(di) < 5.0
  for _ in range(40):
    di = vdas.update(1.0, v_ego=20.0, prev_pedal_di=di, a_ego=0.5,
                     orientation_ned=[0.0, 0.0, 0.0])
  assert di > 5.0


def test_pedal_authority_acquire_enable_release():
  auth = PedalAuthority()
  fb = _FakeFeedback(available=True, state=0, idx=1)
  action = auth.update(True, fb)
  assert action == PedalCommandAction.ACQUIRE
  assert auth.state == PedalAuthorityState.ACTIVE
  assert auth.update(True, fb) == PedalCommandAction.ENABLE
  assert auth.update(False, fb) == PedalCommandAction.RELEASE
  assert auth.state == PedalAuthorityState.INACTIVE


def test_pedal_authority_reset_then_fail():
  auth = PedalAuthority()
  fb = _FakeFeedback(available=False, state=1, idx=0)
  assert auth.update(True, fb) == PedalCommandAction.RESET
  assert auth.state == PedalAuthorityState.ACQUIRING
  action = PedalCommandAction.NONE
  for _ in range(PedalAuthority.MAX_RESET_ATTEMPTS):
    action = auth.update(True, fb)
  assert action == PedalCommandAction.FAILURE
  assert auth.state == PedalAuthorityState.FAILED


def test_pedal_feedback_gas_pressed_threshold():
  fb = PedalFeedback()
  fb.interceptor_value = 3.0
  assert fb.gas_pressed is True
  fb.interceptor_value = 0.5
  assert fb.gas_pressed is False


def test_carcontroller_uses_vdas_not_legacy_map():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[1] / "preap" / "carcontroller.py").read_text()
  assert "PreAPLongController" in src
  assert "accel_to_pedal_command" not in src


def test_long_controller_source_has_vdas_and_authority():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[1] / "preap" / "long_controller.py").read_text()
  assert "VirtualDAS" in src
  assert "PedalAuthority" in src
  assert "get_zero_torque" in src
  assert "ENGAGE_GRACE" in src
