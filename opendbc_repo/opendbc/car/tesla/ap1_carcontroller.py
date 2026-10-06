"""AP1 Model S CarController. Chassis 0x488 / 0x2b9 / 0x45 / 0x349 and the cluster frames.

Ported from BogPilot/openpilot tag ap1-driving-milestone-2 (92e84996)
selfdrive/car/tesla/carcontroller.py AP1 path:

- Engage soft-start: ~300 ms of ANGLE at the measured wheel after engage.
- Hands pause at EPAS level >= 2 plus the resume hold (ap1_hso.Ap1DriverYield):
  0x488 stays type NONE until the hands level has been 0 for 0.5 s, then the
  same soft-start. Not engaged clears it at once.
- EPAS not EAC_ACTIVE, or a latched code 6 / 3: ANGLE at the measured wheel.
- AP1 cluster frames (ap1_cluster). StarPilot/BogStar: always on for AP1 (BogPilot
  enableICIntegration default). There is no StarPilot toggle for it and adding a param key
  would need a C++ rebuild of the prebuilt params module.

StarPilot: "engaged" for the steering decisions is CarControl.enabled or an active
Always On Lateral (CC.latActive without CC.enabled), so an AOL lateral-only state gets the
same pause, resume hold and soft-start. Longitudinal still uses CC.enabled.

The cluster path (0x239) uses modelV2 position x / y that StarPilot's card copies into
model_path_x / model_path_y before each apply (AP1 only). Empty -> actuator curvature + 50 m.
"""

from opendbc.can import CANPacker
from opendbc.car import Bus, structs
from opendbc.car.can_definitions import CanData
from opendbc.car.carlog import carlog
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.tesla.ap1_actuator_plan import (
  AP1_ENGAGE_SOFT_START_FRAMES,
  ap1_should_send_hold_clear,
  build_actuator_plan,
  longitudinal_command_allowed,
)
from opendbc.car.tesla.ap1_cluster import CLUSTER_BUS, ClusterController, HudInputs, path_from_xy
from opendbc.car.tesla.ap1_hso import Ap1DriverYield, ap1_lat_active, ap1_steering_pressed
from opendbc.car.tesla.ap1_teslacan import Ap1TeslaCAN
from opendbc.car.tesla.values import CANBUS, DBC

VisualAlert = structs.CarControl.HUDControl.VisualAlert
AudibleAlert = structs.CarControl.HUDControl.AudibleAlert


def ap1_lat_engaged(CC) -> bool:
  """Steering engagement for AP1: openpilot engaged, or StarPilot Always On Lateral active."""
  return bool(CC.enabled) or bool(CC.latActive)


class Ap1CarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    # CarControllerBase expects dbc_names; AP1 only has Bus.chassis
    super().__init__(dbc_names, CP)
    self.apply_angle_last = 0.0
    self.packer = CANPacker(dbc_names[Bus.chassis] if Bus.chassis in dbc_names else DBC[CP.carFingerprint][Bus.chassis])
    self.tesla_can = Ap1TeslaCAN(self.packer)
    # AP1 engage soft-start: hold measured ANGLE for ~300 ms after engage.
    self.ap1_prev_enabled = False
    self.ap1_engage_frame = None
    # Hands pause + resume hold. Read by the interface for the override-hold flag.
    self.ap1_yield = Ap1DriverYield()
    # Last step's lateral intent, read by the interface for the EPAS inhibit warning.
    self.lat_wanted = False
    # Cluster substitution: always on for AP1 on StarPilot/BogStar (see module docstring).
    self.ic_integration = True
    self.cluster = ClusterController() if self.ic_integration else None
    # modelV2 position x / y (ego frame), filled by StarPilot's card for the 0x239 path.
    self.model_path_x: list[float] = []
    self.model_path_y: list[float] = []

  def update(self, CC, CS, now_nanos, starpilot_toggles=None):
    actuators = CC.actuators
    lat_engaged = ap1_lat_engaged(CC)

    # Hands >= 2 starts it; level 0 for AP1_RESUME_HOLD_S ends it. Only while
    # engaged, so it never holds off disengage or a new engage.
    driver_yield = self.ap1_yield.update(lat_engaged, CS.hands_on_level)
    if lat_engaged and not self.ap1_prev_enabled:
      self.ap1_engage_frame = self.frame
    if self.ap1_yield.resumed:
      # Resume from the measured wheel through the engage soft-start.
      self.ap1_engage_frame = self.frame
    if not lat_engaged:
      self.ap1_engage_frame = None
    self.ap1_prev_enabled = lat_engaged
    soft_start = False
    if self.ap1_engage_frame is not None:
      soft_start = (self.frame - self.ap1_engage_frame) < AP1_ENGAGE_SOFT_START_FRAMES

    lat_active = ap1_lat_active(CC.latActive, CS.hands_on_level) and not driver_yield
    self.lat_wanted = lat_engaged and bool(CC.latActive)
    plan = build_actuator_plan(
      self.frame,
      lat_active,
      False,  # AP1 never cancels cruise on hands-on
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
      chassis_das_only=True,
      epas_error=CS.steer_warning,
      eac_fault=bool(CS.eac_fault),
      hands_on_level=CS.hands_on_level,
      eac_status=CS.eac_status,
      soft_start=soft_start,
      driver_yield=driver_yield,
      lat_enabled=lat_engaged,
    )
    self.apply_angle_last = plan.apply_angle_last

    can_sends = []

    if plan.steer is not None:
      can_sends.append(self.tesla_can.create_steering_control(
        plan.steer.angle_deg, plan.steer.enabled, plan.steer.counter))

    for cmd in plan.longitudinal:
      can_sends.extend(self.tesla_can.create_longitudinal_commands(
        cmd.acc_state, cmd.target_speed, cmd.min_accel, cmd.max_accel, cmd.counter))

    if plan.cancel and CS.msg_stw_actn_req is not None:
      for counter in range(16):
        can_sends.append(self.tesla_can.create_action_request(
          CS.msg_stw_actn_req, True, CANBUS.chassis, counter))
        can_sends.append(self.tesla_can.create_action_request(
          CS.msg_stw_actn_req, True, CANBUS.autopilot_chassis, counter))

    # AP1 Hold clear. Tinkla HUD_module zeros DAS_gas_to_resume (bit 1 of
    # 0x349 byte 0) and sends the frame. Not sent unless longitudinal is allowed.
    long_allowed = longitudinal_command_allowed(
      self.CP.openpilotLongitudinalControl, CC.enabled, CC.longActive)
    if ap1_should_send_hold_clear(True, long_allowed, CS.acc_state, self.frame):
      can_sends.append(self.tesla_can.create_ap1_hold_clear())

    # AP1 cluster frames. Display only. Added after every actuator frame and
    # never read by the actuator plan above.
    if self.cluster is not None:
      can_sends.extend(self.cluster_frames(CC, CS, now_nanos))

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = float(self.apply_angle_last)
    self.frame += 1
    return new_actuators, can_sends

  def cluster_frames(self, CC, CS, now_nanos):
    """Cluster frames for this step. A failure here turns them off for the
    rest of the drive (stock frames then flow through the panda). It must not
    stop the steering and longitudinal frames already built.

    The cluster shows openpilot as engaged only for CarControl.enabled (the
    panda also rejects an active 0x399 state without controls allowed).
    """
    try:
      enabled = bool(CC.enabled)
      model_path = None
      if enabled:
        # Empty unless card filled it from a valid modelV2: falls back
        # to actuator curvature + 50 m.
        model_path = path_from_xy(self.model_path_x, self.model_path_y)
      hud = CC.hudControl
      h = HudInputs(
        enabled=enabled,
        fcw=hud.visualAlert == VisualAlert.fcw,
        steer_required=hud.visualAlert == VisualAlert.steerRequired,
        audible=hud.audibleAlert != AudibleAlert.none,
        human_steering=ap1_steering_pressed(CS.hands_on_level),
        left_lane_depart=bool(hud.leftLaneDepart),
        right_lane_depart=bool(hud.rightLaneDepart),
        left_blinker=bool(CC.leftBlinker),
        right_blinker=bool(CC.rightBlinker),
        curvature=float(CC.actuators.curvature),
        ic_integration=self.ic_integration,
        model_path=model_path,
      )
      frames = self.cluster.update(h, CS.cluster_stock, now_nanos)
      return [CanData(addr, dat, CLUSTER_BUS) for addr, dat in frames]
    except Exception:
      carlog.exception("tesla ap1 cluster frames disabled")
      self.cluster = None
      return []
