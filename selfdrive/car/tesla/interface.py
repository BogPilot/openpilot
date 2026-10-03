#!/usr/bin/env python3
from cereal import car
from openpilot.selfdrive.car.tesla.safety_flags import dashcam_only_for_candidate, flags_for_candidate
from openpilot.selfdrive.car.tesla.values import CANBUS
from openpilot.selfdrive.car import get_safety_config
from openpilot.selfdrive.car.interfaces import CarInterfaceBase


class CarInterface(CarInterfaceBase):
  @staticmethod
  def _get_params(ret, candidate, fingerprint, car_fw, experimental_long, docs, frogpilot_toggles):
    ret.carName = "tesla"

    # There is no safe way to do steer blending with user torque,
    # so the steering behaves like autopilot. This is not
    # how openpilot should be, hence dashcamOnly.
    # AP1 is an explicit user exception for the Mobileye chassis port,
    # not a Model 3 change.
    ret.dashcamOnly = dashcam_only_for_candidate(candidate)

    ret.steerControlType = car.CarParams.SteerControlType.angle

    ret.longitudinalActuatorDelay = 0.5 # s
    ret.radarTimeStep = (1.0 / 8) # 8Hz

    # Check if we have messages on an auxiliary panda, and that 0x2bf (DAS_control) is present on the AP powertrain bus
    # If so, we assume that it is connected to the longitudinal harness.
    # flags_for_candidate adds the AP1 steering bit only for CAR.TESLA_AP1_MODELS.
    # The 0x2bf branch still adds long control and the powertrain config. It does
    # not enable openpilotLongitudinalControl for AP1 unless that bus is present,
    # which AP1 is not expected to have.
    safety_params = flags_for_candidate(candidate, fingerprint)
    if (CANBUS.autopilot_powertrain in fingerprint.keys()) and (0x2bf in fingerprint[CANBUS.autopilot_powertrain].keys()):
      ret.openpilotLongitudinalControl = not frogpilot_toggles.disable_openpilot_long
      ret.safetyConfigs = [
        get_safety_config(car.CarParams.SafetyModel.tesla, safety_params[0]),
        get_safety_config(car.CarParams.SafetyModel.tesla, safety_params[1]),
      ]
    else:
      ret.openpilotLongitudinalControl = False
      ret.safetyConfigs = [get_safety_config(car.CarParams.SafetyModel.tesla, safety_params[0])]

    ret.steerLimitTimer = 1.0
    ret.steerActuatorDelay = 0.25
    return ret

  def _update(self, c, frogpilot_toggles):
    ret, fp_ret = self.CS.update(self.cp, self.cp_cam, frogpilot_toggles)

    ret.events = self.create_common_events(ret).to_msg()

    return ret, fp_ret
