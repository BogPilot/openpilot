from opendbc.car import Bus, get_safety_config, structs
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.tesla.ap1_carcontroller import Ap1CarController
from opendbc.car.tesla.ap1_carstate import Ap1CarState
from opendbc.car.tesla.carcontroller import CarController
from opendbc.car.tesla.carstate import CarState
from opendbc.car.tesla.radar_interface import RadarInterface
from opendbc.car.tesla.values import AP1_CARS, TeslaAp1SafetyFlags, TeslaFlags, TeslaSafetyFlags, CAR, DBC, LEGACY_CARS
from opendbc.car.tesla.preap.interface import get_preap_accel_limits, get_preap_params


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  def __init__(self, CP: structs.CarParams, FPCP):
    if CP.flags & TeslaFlags.AP1:
      # AP1 Model S: swap in the AP1 chassis stack before CarInterfaceBase builds CS/CC.
      self.CarState = Ap1CarState
      self.CarController = Ap1CarController
    super().__init__(CP, FPCP)

  @staticmethod
  def get_pid_accel_limits(CP, current_speed, cruise_speed):
    if CP.carFingerprint == CAR.TESLA_MODEL_S_PREAP:
      return get_preap_accel_limits(current_speed)
    return CarInterfaceBase.get_pid_accel_limits(CP, current_speed, cruise_speed)

  @classmethod
  def get_params(cls, candidate, fingerprint, car_fw, alpha_long, is_release, docs, starpilot_toggles):
    ret = super().get_params(candidate, fingerprint, car_fw, alpha_long, is_release, docs, starpilot_toggles)
    if candidate == CAR.TESLA_MODEL_3 and getattr(starpilot_toggles, "tesla_cooperative_steering", False):
      ret.safetyConfigs[0].safetyParam |= TeslaSafetyFlags.COOP_STEERING.value
    return ret

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "tesla"

    if candidate == CAR.TESLA_MODEL_S_PREAP:
      return get_preap_params(ret)

    # AP1 Model S is its own port (BogPilot AP1, BogGyver/Tinkla reference). Return before any
    # legacy HW1 or Model 3/Y/X setting is applied.
    if candidate in AP1_CARS:
      return CarInterface._get_params_ap1(ret)

    if candidate in LEGACY_CARS:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.tesla, TeslaSafetyFlags.FLAG_HW1.value)]
      ret.steerLimitTimer = 0.4
      ret.steerActuatorDelay = 0.1
      ret.steerAtStandstill = True
      ret.steerControlType = structs.CarParams.SteerControlType.angle
      ret.radarUnavailable = Bus.radar not in DBC[candidate]
      ret.radarTimeStepDEPRECATED = 0.125
      ret.alphaLongitudinalAvailable = True

      if alpha_long:
        ret.openpilotLongitudinalControl = True
        ret.safetyConfigs[0].safetyParam |= TeslaSafetyFlags.LONG_CONTROL.value
      return ret

    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.tesla)]

    ret.steerLimitTimer = 0.4
    ret.steerActuatorDelay = 0.1
    ret.steerAtStandstill = True

    ret.steerControlType = structs.CarParams.SteerControlType.angle
    ret.radarUnavailable = True

    ret.alphaLongitudinalAvailable = True
    if alpha_long:
      ret.openpilotLongitudinalControl = True
      ret.safetyConfigs[0].safetyParam |= TeslaSafetyFlags.LONG_CONTROL.value

      ret.vEgoStopping = 0.1
      ret.vEgoStarting = 0.1
      ret.stoppingDecelRate = 0.3

    ret.dashcamOnly = candidate in (CAR.TESLA_MODEL_X) # dashcam only, pending find invalidLkasSetting signal

    return ret

  @staticmethod
  def _get_params_ap1(ret: structs.CarParams) -> structs.CarParams:
    """AP1 Model S (Mobileye, chassis bus 0). Nothing shared with Model 3/Y/X or the legacy HW1 stack.

    Reference: BogGyver/Tinkla AP1 (BogGyver/openpilot tesla_unity_dev selfdrive/car/tesla/interface.py and
    BogGyver/panda board/safety/safety_tesla.h), via BogPilot's AP1 port.

    Longitudinal is openpilot's by default and is not gated on alpha long (BogPilot AP1 branch). The panda
    only honors it in a DEBUG (ALLOW_DEBUG) build; a release panda keeps stock ACC.
    """
    ret.flags |= TeslaFlags.AP1.value
    # BogGyver/Tinkla FLAG_TESLA_HAS_AP selects tesla_ap1.h; FLAG_TESLA_LONG_CONTROL allows chassis 0x2b9.
    # Never set TeslaSafetyFlags.FLAG_HW1 (8): that routes to tesla_legacy.h.
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.tesla,
                                           int(TeslaAp1SafetyFlags.HAS_AP | TeslaAp1SafetyFlags.LONG_CONTROL))]
    ret.steerControlType = structs.CarParams.SteerControlType.angle
    ret.openpilotLongitudinalControl = True
    ret.alphaLongitudinalAvailable = False
    ret.radarUnavailable = True
    ret.dashcamOnly = False
    ret.pcmCruise = True
    # BogGyver/Tinkla does not steer at standstill.
    ret.steerAtStandstill = False
    # BogGyver/Tinkla interface.py: steerLimitTimer 1.0, steerActuatorDelay 0.25,
    # longitudinalActuatorDelayUpperBound 0.5
    ret.steerLimitTimer = 1.0
    ret.steerActuatorDelay = 0.25
    ret.longitudinalActuatorDelay = 0.5
    return ret
