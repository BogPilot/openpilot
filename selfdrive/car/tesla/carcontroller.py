from opendbc.can.packer import CANPacker
from openpilot.selfdrive.car.interfaces import CarControllerBase
from openpilot.selfdrive.car.tesla.actuator_plan import (
  DAS_CONTROL_POWERTRAIN,
  ap1_should_send_hold_clear,
  build_actuator_plan,
  longitudinal_command_allowed,
)
from openpilot.selfdrive.car.tesla.teslacan import TeslaCAN
from openpilot.selfdrive.car.tesla.values import DBC, CANBUS, CAR


class CarController(CarControllerBase):
  def __init__(self, dbc_name, CP, VM):
    self.CP = CP
    self.frame = 0
    self.apply_angle_last = 0
    self.packer = CANPacker(dbc_name)
    self.pt_packer = CANPacker(DBC[CP.carFingerprint]['pt'])
    self.tesla_can = TeslaCAN(self.packer, self.pt_packer)

  def update(self, CC, CS, now_nanos, frogpilot_toggles):
    actuators = CC.actuators

    # Temp disable steering on a hands_on_fault, and allow for user override
    hands_on_fault = CS.steer_warning == "EAC_ERROR_HANDS_ON" and CS.hands_on_level >= 3
    # AP1 longitudinal is chassis 0x2b9. Do not also plan powertrain 0x2bf.
    chassis_das_only = self.CP.carFingerprint == CAR.TESLA_AP1_MODELS
    plan = build_actuator_plan(
      self.frame,
      CC.latActive,
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

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = self.apply_angle_last

    self.frame += 1
    return new_actuators, can_sends
