from opendbc.car import get_safety_config, structs
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.tesla_ap1.carcontroller import CarController
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.modelx_fingerprint import s_contradicts_x
from opendbc.car.tesla_ap1.safety_flags import dashcam_only_for_candidate, flags_for_candidate
from opendbc.car.tesla_ap1.toggles import ap1_standstill_engage, disable_openpilot_long
from opendbc.car.tesla_ap1.values import CAR, match_ap1_chassis


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "tesla_ap1"

    # There is no safe way to do steer blending with user torque, so the
    # steering behaves like autopilot. AP1 is an explicit user exception for
    # the Mobileye chassis port (HSO pause instead of blending).
    ret.dashcamOnly = dashcam_only_for_candidate(candidate) or (not docs and not match_ap1_chassis(fingerprint))
    if candidate == CAR.TESLA_AP1_MODELX:
      # S-only CAN on a manually selected Model X stays dashcam (no output).
      ret.dashcamOnly = ret.dashcamOnly or s_contradicts_x(fingerprint)

    ret.steerControlType = structs.CarParams.SteerControlType.angle

    # AP1 reads the blind spot from the Mobileye/radar path (blindspot.py), as in 367e1fe.

    ret.longitudinalActuatorDelay = 0.5  # s

    # 0.9.7: openpilot long = not DisableOpenpilotLongitudinal (default off, so
    # long is ON). Chassis 0x2b9 only, no 0x2bf powertrain DAS. AP1StandstillEngage
    # only matters with openpilot long on.
    # Model X is lateral-only until bench/vehicle verification. Tinkla's X long
    # path also sends AP2-style DAS_control on powertrain bus 4, which needs a
    # second panda this tree does not have. Chassis-only long is unverified on X,
    # so openpilot longitudinal stays off and the car keeps stock ACC.
    long_on = candidate == CAR.TESLA_AP1_MODELS and not ret.dashcamOnly and not disable_openpilot_long()
    standstill = long_on and ap1_standstill_engage(candidate)
    safety_params = flags_for_candidate(candidate, fingerprint, standstill=standstill)
    ret.openpilotLongitudinalControl = long_on
    if ret.dashcamOnly:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.noOutput)]
    else:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.tesla, safety_params[0])]

    ret.steerLimitTimer = 1.0
    ret.steerActuatorDelay = 0.25
    return ret

  def update(self, can_packets) -> structs.CarState:
    ret = super().update(can_packets)
    # Hands pause / resume hold from CarController's last step. openpilot's
    # car_events adds steerOverride from this so the border stays grey.
    ret.bogpilot.ap1DriverYield = bool(getattr(getattr(self.CC, "ap1_yield", None), "active", False))
    return ret
