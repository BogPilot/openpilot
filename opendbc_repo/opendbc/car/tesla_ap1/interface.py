from opendbc.car import get_safety_config, structs
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.tesla_ap1.carcontroller import CarController
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.modelx_fingerprint import s_contradicts_x
from opendbc.car.tesla_ap1.safety_flags import dashcam_only_for_candidate, flags_for_candidate, flags_for_preap
from opendbc.car.tesla_ap1.preap.calib import pedal_can_bus
from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
from opendbc.car.tesla_ap1.preap.vdas_constants import PEDAL_LONG_K_BP, PEDAL_LONG_KI_V
from opendbc.car.tesla_ap1.toggles import ap1_standstill_engage, disable_openpilot_long
from opendbc.car.tesla_ap1.values import CAR, ForcedFingerprint, is_preap, match_ap1_chassis


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  def __init__(self, CP):
    # One brand, two cars: the Pre-AP Model S has its own CarState / CarController (no Autopilot ECU to follow).
    if is_preap(CP.carFingerprint):
      self.CarState = PreApCarState
      self.CarController = PreApCarController
    super().__init__(CP)

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "tesla_ap1"

    if is_preap(candidate):
      return CarInterface._get_preap_params(ret, candidate)

    # There is no safe way to do steer blending with user torque, so the
    # steering behaves like autopilot. AP1 is an explicit user exception for
    # the Mobileye chassis port (HSO pause instead of blending).
    # A user-fixed model is not re-checked against the live bus (0.9.7 behavior); a detected one must match the AP1 chassis.
    fixed = isinstance(fingerprint, ForcedFingerprint)
    ret.dashcamOnly = dashcam_only_for_candidate(candidate) or (not docs and not fixed and not match_ap1_chassis(fingerprint))
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

  @staticmethod
  def _get_preap_params(ret: structs.CarParams, candidate) -> structs.CarParams:
    """Pre-AP Model S. Lateral always. Longitudinal only when the user wants openpilot long (DisableOpenpilotLongitudinal
    off); whether the pedal is then actually driven is gated at CarController time (detected + calibrated + longActive).
    Radar only with the Bosch radar retrofit toggle (default off, read once here at car start)."""
    ret.dashcamOnly = False
    ret.steerControlType = structs.CarParams.SteerControlType.angle
    radar_on = preap_params.get_bool(preap_params.PreApParamKeys.RADAR_ENABLED)
    nosecone = radar_on and preap_params.get_bool(preap_params.PreApParamKeys.RADAR_BEHIND_NOSECONE)
    ret.radarUnavailable = not radar_on  # NotAutopilot preap/interface.py:54@cc39c7fa
    long_on = not disable_openpilot_long()
    ret.openpilotLongitudinalControl = long_on
    ret.pcmCruise = not long_on          # pedal long: openpilot owns the engage state (PreAPEngagement)
    safety_param = flags_for_preap(pedal=long_on, radar=radar_on, behind_nosecone=nosecone)
    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.tesla, safety_param)]
    ret.steerLimitTimer = 0.4
    ret.steerActuatorDelay = 0.1
    ret.longitudinalActuatorDelay = 0.4
    if long_on:
      # Planner accel passes 1:1 into VirtualDAS (it does its own feedback); the stock PID adds nothing.
      ret.longitudinalTuning.kiBP = list(PEDAL_LONG_K_BP)
      ret.longitudinalTuning.kiV = list(PEDAL_LONG_KI_V)
    return ret

  def update(self, can_packets) -> structs.CarState:
    ret = super().update(can_packets)
    # Hands pause / resume hold from CarController's last step. openpilot's
    # car_events adds steerOverride from this so the border stays grey.
    ret.bogpilot.ap1DriverYield = bool(getattr(getattr(self.CC, "ap1_yield", None), "active", False))
    ret.bogpilot.ap1OverrideSignal = (int(getattr(getattr(self.CC, "ap1_yield", None), "signal", 0)) or
                                      int(getattr(getattr(self.CC, "ap1_epas_gate", None), "signal", 0)))
    return ret
