"""Actuator decision for Tesla CarController.

CarController.update packs exactly the messages this plan names. No CAN
packing happens here. While disengaged, the plan has no steering frame so
stock Mobileye 0x488 can keep flowing (AP1 interceptor). While AP1 cruise is
enabled but path lateral is not, 0x488 is still sent: the measured angle and
control type NONE. That is Tinkla's human-control and non-idle EPAS path,
except EAC_ERROR_HIGH_ANGLE_REQ (6) and a latched EAC_ERROR_HANDS_ON (3).
Those two are not path blocks once hands are below the HSO threshold. While
enabled, hands are below that threshold, and EPAS is not EAC_FAULT, 0x488 is
ANGLE. If EPAS is not yet EAC_ACTIVE, a latched code 6/3 is set, or we are
inside the engage soft-start window, the angle is the measured wheel so EPAS
can accept control. Otherwise the planned angle is used when lat is active.
Always rate limited and clipped to measured +/- 20 deg. DAS_control is planned
only when the car params allow openpilot
longitudinal control and CarControl.enabled and CarControl.longActive are
both true. Otherwise the plan has no longitudinal command.
"""

from dataclasses import dataclass

from openpilot.common.numpy_fast import clip
from openpilot.selfdrive.car import apply_std_steer_angle_limits
from openpilot.selfdrive.car.tesla.hso import AP1_HANDS_ON_LEVEL
from openpilot.selfdrive.car.tesla.steer_fault import AP1_LATCHED_ANGLE_ERRORS
from openpilot.selfdrive.car.tesla.values import CarControllerParams

# safety_tesla.h tesla_tx_hook: type 0 is NONE and type 3 is DISABLED.
# Neither one sets steer_control_enabled.
STEERING_CONTROL_NONE = 0
STEERING_CONTROL_ANGLE = 1

# 11-bit DAS_control. Chassis is 0x2b9 (tesla_can.dbc). Powertrain is 0x2bf
# (tesla_powertrain.dbc). AP1 plans the chassis id only. tesla_tx_hook uses
# 0x2b9 when TESLA_FLAG_POWERTRAIN is unset.
DAS_CONTROL_CHASSIS = 0x2B9
DAS_CONTROL_POWERTRAIN = 0x2BF

# tesla_can.dbc VAL_ 697 DAS_accState. Tinkla create_ap1_long_control uses
# 4 (ACC_ON) in drive and 3 (ACC_HOLD) only for static cruise.
ACC_HOLD = 3
ACC_ON = 4

# ~300 ms at 100 Hz CarController. Rising edge of enabled holds measured
# ANGLE before the planner angle so EPAS can leave AVAILABLE/INHIBITED.
AP1_ENGAGE_SOFT_START_FRAMES = 30

# tesla_can.dbc VAL_ 880 EPAS_eacStatus.
EAC_ACTIVE = "EAC_ACTIVE"


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
  # Empty unless a DAS_control command is planned. AP1 is (0x2b9,) only.
  longitudinal_addrs: tuple[int, ...] = ()


def steering_control_type(enabled: bool) -> int:
  if enabled:
    return STEERING_CONTROL_ANGLE
  return STEERING_CONTROL_NONE


def ap1_long_acc_state(camera_acc_state, chassis_das_only):
  """ACC state openpilot may put in chassis DAS_control.

  AP1 openpilot longitudinal is adaptive cruise in drive, not Tinkla static
  cruise. Tinkla selfdrive/car/tesla/teslacan.py create_ap1_long_control sets
  DAS_accState to 4 while in drive, and to 3 only when static_cruise and
  cruise are both on. Copying the camera ACC_HOLD (3) made the car wait for
  the accelerator at a stop. Non-AP1 still passes the camera state through.
  """
  if chassis_das_only and camera_acc_state == ACC_HOLD:
    return ACC_ON
  return camera_acc_state


def ap1_should_send_hold_clear(ap1, long_allowed, camera_acc_state, frame):
  """When to TX the all-zero 0x349 clear.

  Tinkla HUD_module sends warning matrix 3 at 1 Hz with DAS_gas_to_resume
  forced to 0. Also send while the camera is still reporting ACC_HOLD so the
  clear is on the bus for that stop, not only on the 1 Hz tick.
  Disengaged longitudinal does not send it.
  """
  if not ap1 or not long_allowed:
    return False
  return camera_acc_state == ACC_HOLD or (frame % 100) == 0


def longitudinal_command_allowed(openpilot_longitudinal_control, enabled, long_active):
  """True only when a DAS_control command may be planned.

  CarControl.enabled must be true for actuator commands. longActive is the
  longitudinal engage bit from controlsd. The openpilot-long car param is
  required as well. Any false input means no DAS_control frame.
  """
  return bool(openpilot_longitudinal_control) and bool(enabled) and bool(long_active)


def _ap1_limited_angle(requested_angle_deg, last_angle_deg, measured_angle_deg, v_ego):
  """Rate limit, then Tinkla's +/- 20 deg clip around the measured wheel.

  The clip is the "to not fault the EPS" bound. It is applied after the
  speed-based rate limit. A requested angle inside that window is unchanged
  aside from the rate step.
  """
  apply_angle = apply_std_steer_angle_limits(requested_angle_deg, last_angle_deg, v_ego, CarControllerParams)
  return clip(apply_angle, measured_angle_deg - 20, measured_angle_deg + 20)


def ap1_hold_measured_angle(chassis_das_only, enabled, eac_fault, hands_pause,
                           eac_status, epas_error, soft_start):
  """True when AP1 must command ANGLE at the measured wheel, not the planner.

  EPAS on route 0000000e stayed EAC_INHIBITED with code 6 while openpilot kept
  sending planner ANGLE; the wheel never moved and there was no UI fault.
  Hold measured until EAC_ACTIVE (and after soft-start / latched 6 or 3).
  """
  if not chassis_das_only or not enabled or eac_fault or hands_pause:
    return False
  if soft_start:
    return True
  # None means the caller did not pass status (non-AP1 tests). Only a known
  # non-ACTIVE status forces the measured hold.
  if eac_status is not None and eac_status != EAC_ACTIVE:
    return True
  if epas_error in AP1_LATCHED_ANGLE_ERRORS:
    return True
  return False


def build_actuator_plan(frame, lat_active, hands_on_fault, openpilot_longitudinal_control,
                        enabled, long_active,
                        measured_angle_deg, requested_angle_deg, last_angle_deg, v_ego, accel,
                        acc_state, das_counters, pcm_cancel, chassis_das_only=False,
                        epas_error=None, eac_fault=False, hands_on_level=0,
                        eac_status=None, soft_start=False):
  """Same steering branches CarController.update had before this function existed.

  Disengaged lateral: no steering frame. Sending type-NONE 0x488 while
  disengaged replaced stock Mobileye commands on AP1. AP1 with cruise enabled
  and lat inactive still sends 0x488 at the measured angle with type NONE,
  except when ap1_hold_measured_angle is true (not ACTIVE, latched 6/3, or
  soft-start): then type is ANGLE at the measured wheel. While EPAS is
  EAC_ACTIVE, hands are below 2, and there is no latch/soft-start, lat active
  sends the planned angle. Other non-idle codes with lat inactive still take
  the NONE branch. Hands at or above 2 also take NONE and do not cancel.
  apply_angle_last tracks the commanded angle so the next path command starts
  from the wheel. Longitudinal messages are built only when
  longitudinal_command_allowed is true. An inactive long plan is empty.
  """

  lkas_enabled = lat_active and not hands_on_fault
  apply_angle_last = last_angle_deg
  steer = None
  # AP1 only. Hands pause and EAC_FAULT still win over a latched code 6 or 3.
  # Code 3 takes this path only after hands drop; at or above 2, hands_pause
  # keeps type NONE even though code 3 is not itself a temporary fault.
  hands_pause = bool(chassis_das_only) and hands_on_level >= AP1_HANDS_ON_LEVEL
  hold_measured = ap1_hold_measured_angle(
    chassis_das_only, enabled, eac_fault, hands_pause, eac_status, epas_error, soft_start)
  if chassis_das_only and eac_fault:
    lkas_enabled = False

  if frame % 2 == 0:
    if hold_measured:
      # Measured ANGLE: EPAS inhibit recovery, latched 6/3, or engage soft-start.
      apply_angle = _ap1_limited_angle(measured_angle_deg, last_angle_deg, measured_angle_deg, v_ego)
      apply_angle_last = apply_angle
      steer = SteerCommand(apply_angle, True, (frame // 2) % 16)
    elif lkas_enabled and not hands_pause:
      # Angular rate limit based on speed, then the EPS clip.
      apply_angle = _ap1_limited_angle(requested_angle_deg, last_angle_deg, measured_angle_deg, v_ego)
      apply_angle_last = apply_angle
      steer = SteerCommand(apply_angle, True, (frame // 2) % 16)
    elif chassis_das_only and enabled and not hands_on_fault:
      # Cruise stays up. Do not send the planned path angle.
      apply_angle_last = measured_angle_deg
      steer = SteerCommand(measured_angle_deg, False, (frame // 2) % 16)
    else:
      # Interceptor: do not TX 0x488 while disengaged; stock DAS must pass.
      apply_angle_last = measured_angle_deg

  longitudinal = []
  longitudinal_addrs = ()
  if longitudinal_command_allowed(openpilot_longitudinal_control, enabled, long_active):
    target_accel = accel
    target_speed = max(v_ego + (target_accel * CarControllerParams.ACCEL_TO_SPEED_MULTIPLIER), 0)
    max_accel = 0 if target_accel < 0 else target_accel
    min_accel = 0 if target_accel > 0 else target_accel

    acc_state = ap1_long_acc_state(acc_state, chassis_das_only)
    while len(das_counters) > 0:
      longitudinal.append(LongCommand(acc_state, target_speed, min_accel, max_accel, das_counters.popleft()))
    if longitudinal:
      if chassis_das_only:
        longitudinal_addrs = (DAS_CONTROL_CHASSIS,)
      else:
        longitudinal_addrs = (DAS_CONTROL_CHASSIS, DAS_CONTROL_POWERTRAIN)

  # Cancel on user steering override, since there is no steering torque blending
  if hands_on_fault:
    pcm_cancel = True

  cancel = frame % 10 == 0 and pcm_cancel
  return ActuatorPlan(steer, tuple(longitudinal), bool(cancel), apply_angle_last, longitudinal_addrs)
