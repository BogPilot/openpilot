from cereal import car
from opendbc.can.packer import CANPacker
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.car.interfaces import CarControllerBase
from openpilot.selfdrive.car.tesla.actuator_plan import (
  AP1_ENGAGE_SOFT_START_FRAMES,
  DAS_CONTROL_POWERTRAIN,
  ap1_should_send_hold_clear,
  build_actuator_plan,
  longitudinal_command_allowed,
)
from openpilot.selfdrive.car.tesla.cluster import CLUSTER_BUS, ClusterController, HudInputs
from openpilot.selfdrive.car.tesla.hso import ap1_lat_active, ap1_steering_pressed
from openpilot.selfdrive.car.tesla.teslacan import TeslaCAN
from openpilot.selfdrive.car.tesla.values import DBC, CANBUS, CAR

VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert


class CarController(CarControllerBase):
  def __init__(self, dbc_name, CP, VM):
    self.CP = CP
    self.frame = 0
    self.apply_angle_last = 0
    self.packer = CANPacker(dbc_name)
    self.pt_packer = CANPacker(DBC[CP.carFingerprint]['pt'])
    self.tesla_can = TeslaCAN(self.packer, self.pt_packer)
    # AP1 only. Tinkla-style cluster frames (cluster.py).
    self.cluster = ClusterController() if CP.carFingerprint == CAR.TESLA_AP1_MODELS else None
    # AP1 engage soft-start: hold measured ANGLE for ~300 ms after enable.
    self.ap1_prev_enabled = False
    self.ap1_engage_frame = None

  def update(self, CC, CS, now_nanos, frogpilot_toggles):
    actuators = CC.actuators

    # Model 3/Y still cancels cruise when HANDS_ON and hands_on_level >= 3.
    # AP1 does not. Tinkla HSO pauses lateral and leaves long engaged.
    ap1 = self.CP.carFingerprint == CAR.TESLA_AP1_MODELS
    hands_on_fault = (not ap1) and CS.steer_warning == "EAC_ERROR_HANDS_ON" and CS.hands_on_level >= 3
    lat_active = ap1_lat_active(CC.latActive, CS.hands_on_level) if ap1 else CC.latActive
    # AP1 longitudinal is chassis 0x2b9. Do not also plan powertrain 0x2bf.
    chassis_das_only = ap1
    soft_start = False
    if ap1:
      enabled = bool(CC.enabled)
      if enabled and not self.ap1_prev_enabled:
        self.ap1_engage_frame = self.frame
      if not enabled:
        self.ap1_engage_frame = None
      self.ap1_prev_enabled = enabled
      if self.ap1_engage_frame is not None:
        soft_start = (self.frame - self.ap1_engage_frame) < AP1_ENGAGE_SOFT_START_FRAMES
    plan = build_actuator_plan(
      self.frame,
      lat_active,
      hands_on_fault,
      self.CP.openpilotLongitudinalControl,
      CC.enabled,
      CC.longActive,
      CS.out.steeringAngleDeg,
      actuators.steeringAngleDeg,
      self.apply_angle_last,
      CS.out.vEgo,
      actuators.accel,
      CS.acc_state,
      CS.das_control_counters,
      CC.cruiseControl.cancel,
      chassis_das_only=chassis_das_only,
      # Code 6 is AP1-only. Model 3/Y still treats it as a temporary fault
      # and does not take the measured-angle ANGLE fallback.
      epas_error=CS.steer_warning if ap1 else None,
      eac_fault=bool(CS.eac_fault) if ap1 else False,
      hands_on_level=CS.hands_on_level if ap1 else 0,
      eac_status=CS.eac_status if ap1 else None,
      soft_start=soft_start,
    )
    self.apply_angle_last = plan.apply_angle_last

    can_sends = []

    if plan.steer is not None:
      can_sends.append(self.tesla_can.create_steering_control(plan.steer.angle_deg, plan.steer.enabled, plan.steer.counter))

    # Longitudinal control (in sync with stock message, about 40Hz)
    chassis_only = DAS_CONTROL_POWERTRAIN not in plan.longitudinal_addrs
    for cmd in plan.longitudinal:
      can_sends.extend(self.tesla_can.create_longitudinal_commands(cmd.acc_state, cmd.target_speed, cmd.min_accel, cmd.max_accel, cmd.counter, chassis_only=chassis_only))

    # Cancel on user steering override, since there is no steering torque blending
    if plan.cancel:
      # Spam every possible counter value, otherwise it might not be accepted
      for counter in range(16):
        can_sends.append(self.tesla_can.create_action_request(CS.msg_stw_actn_req, True, CANBUS.chassis, counter))
        can_sends.append(self.tesla_can.create_action_request(CS.msg_stw_actn_req, True, CANBUS.autopilot_chassis, counter))

    # AP1 Hold clear. Tinkla HUD_module zeros DAS_gas_to_resume (bit 1 of
    # 0x349 byte 0) and sends the frame. Not sent unless longitudinal is allowed.
    long_allowed = longitudinal_command_allowed(
      self.CP.openpilotLongitudinalControl, CC.enabled, CC.longActive)
    if ap1_should_send_hold_clear(chassis_das_only, long_allowed, CS.acc_state, self.frame):
      can_sends.append(self.tesla_can.create_ap1_hold_clear())

    # AP1 cluster frames. Display only. Added after every actuator frame and
    # never read by the actuator plan above.
    if self.cluster is not None:
      can_sends.extend(self.cluster_frames(CC, CS, now_nanos))

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = self.apply_angle_last

    self.frame += 1
    return new_actuators, can_sends

  def cluster_frames(self, CC, CS, now_nanos):
    """Cluster frames for this step. A failure here turns them off for the
    rest of the drive (stock frames then flow through the panda). It must not
    stop the steering and longitudinal frames already built."""
    try:
      hud = CC.hudControl
      h = HudInputs(
        enabled=bool(CC.enabled),
        fcw=hud.visualAlert == VisualAlert.fcw,
        steer_required=hud.visualAlert == VisualAlert.steerRequired,
        audible=hud.audibleAlert != AudibleAlert.none,
        human_steering=ap1_steering_pressed(CS.hands_on_level),
        left_lane_depart=bool(hud.leftLaneDepart),
        right_lane_depart=bool(hud.rightLaneDepart),
        left_blinker=bool(CC.leftBlinker),
        right_blinker=bool(CC.rightBlinker),
        curvature=float(CC.actuators.curvature),
      )
      frames = self.cluster.update(h, CS.cluster_stock, now_nanos)
      return [[addr, 0, dat, CLUSTER_BUS] for addr, dat in frames]
    except Exception:
      cloudlog.exception("tesla ap1 cluster frames disabled")
      self.cluster = None
      return []
