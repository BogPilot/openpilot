"""Actuator decision for Tesla CarController.

CarController.update packs exactly the messages this plan names. No CAN
packing happens here. DAS_control is planned only when the car params allow
openpilot longitudinal control and CarControl.enabled and CarControl.longActive
are both true. Otherwise the plan has no longitudinal command.
"""

from dataclasses import dataclass

from openpilot.common.numpy_fast import clip
from openpilot.selfdrive.car import apply_std_steer_angle_limits
from openpilot.selfdrive.car.tesla.values import CarControllerParams

# safety_tesla.h tesla_tx_hook: type 0 is NONE and type 3 is DISABLED.
# Neither one sets steer_control_enabled.
STEERING_CONTROL_NONE = 0
STEERING_CONTROL_ANGLE = 1


@dataclass(frozen=True)
class SteerCommand:
  angle_deg: float
  enabled: bool
  counter: int

  @property
  def control_type(self) -> int:
    if self.enabled:
      return STEERING_CONTROL_ANGLE
    return STEERING_CONTROL_NONE


@dataclass(frozen=True)
class LongCommand:
  acc_state: int
  target_speed: float
  min_accel: float
  max_accel: float
  counter: int


@dataclass(frozen=True)
class ActuatorPlan:
  steer: SteerCommand | None
  longitudinal: tuple[LongCommand, ...]
  cancel: bool
  apply_angle_last: float


def steering_control_type(enabled: bool) -> int:
  if enabled:
    return STEERING_CONTROL_ANGLE
  return STEERING_CONTROL_NONE


def longitudinal_command_allowed(openpilot_longitudinal_control, enabled, long_active):
  """True only when a DAS_control command may be planned.

  CarControl.enabled must be true for actuator commands. longActive is the
  longitudinal engage bit from controlsd. The openpilot-long car param is
  required as well. Any false input means no DAS_control frame.
  """
  return bool(openpilot_longitudinal_control) and bool(enabled) and bool(long_active)


def build_actuator_plan(frame, lat_active, hands_on_fault, openpilot_longitudinal_control,
                        enabled, long_active,
                        measured_angle_deg, requested_angle_deg, last_angle_deg, v_ego, accel,
                        acc_state, das_counters, pcm_cancel):
  """Same steering branches CarController.update had before this function existed.

  Disengaged lateral (lat_active false, or hands_on_fault): the steering
  frame echoes measured_angle_deg and enabled is false. Longitudinal
  messages are built only when longitudinal_command_allowed is true.
  An inactive long plan is empty. It does not send a zeroed DAS_control.
  """

  lkas_enabled = lat_active and not hands_on_fault
  apply_angle_last = last_angle_deg
  steer = None

  if frame % 2 == 0:
    if lkas_enabled:
      # Angular rate limit based on speed
      apply_angle = apply_std_steer_angle_limits(requested_angle_deg, last_angle_deg, v_ego, CarControllerParams)
      # To not fault the EPS
      apply_angle = clip(apply_angle, measured_angle_deg - 20, measured_angle_deg + 20)
    else:
      apply_angle = measured_angle_deg

    apply_angle_last = apply_angle
    steer = SteerCommand(apply_angle, lkas_enabled, (frame // 2) % 16)

  longitudinal = []
  if longitudinal_command_allowed(openpilot_longitudinal_control, enabled, long_active):
    target_accel = accel
    target_speed = max(v_ego + (target_accel * CarControllerParams.ACCEL_TO_SPEED_MULTIPLIER), 0)
    max_accel = 0 if target_accel < 0 else target_accel
    min_accel = 0 if target_accel > 0 else target_accel

    while len(das_counters) > 0:
      longitudinal.append(LongCommand(acc_state, target_speed, min_accel, max_accel, das_counters.popleft()))

  # Cancel on user steering override, since there is no steering torque blending
  if hands_on_fault:
    pcm_cancel = True

  cancel = frame % 10 == 0 and pcm_cancel
  return ActuatorPlan(steer, tuple(longitudinal), bool(cancel), apply_angle_last)
