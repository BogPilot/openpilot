#!/usr/bin/env python3
from cereal import car
from openpilot.selfdrive.car.tesla.hso import ap1_hso_event_names
from openpilot.selfdrive.car.tesla.safety_flags import dashcam_only_for_candidate, flags_for_candidate
from openpilot.selfdrive.car.tesla.values import CANBUS, CAR
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

    # 0x2bf on the auxiliary powertrain bus is the second-panda Model 3/Y harness.
    # AP1 does not need that frame. flags_for_candidate sets AP1|LONG (10) for
    # TESLA_AP1_MODELS with no powertrain bit. The command is still planned only
    # when this param, CC.enabled, and CC.longActive are all true.
    safety_params = flags_for_candidate(candidate, fingerprint)
    has_powertrain_das = (CANBUS.autopilot_powertrain in fingerprint.keys()) and (0x2bf in fingerprint[CANBUS.autopilot_powertrain].keys())
    if has_powertrain_das:
      ret.openpilotLongitudinalControl = not frogpilot_toggles.disable_openpilot_long
      ret.safetyConfigs = [
        get_safety_config(car.CarParams.SafetyModel.tesla, safety_params[0]),
        get_safety_config(car.CarParams.SafetyModel.tesla, safety_params[1]),
      ]
    elif candidate == CAR.TESLA_AP1_MODELS:
      # Chassis 0x2b9 only. Same toggle as the powertrain branch. No 0x2bf.
      ret.openpilotLongitudinalControl = not frogpilot_toggles.disable_openpilot_long
      ret.safetyConfigs = [get_safety_config(car.CarParams.SafetyModel.tesla, safety_params[0])]
    else:
      ret.openpilotLongitudinalControl = False
      ret.safetyConfigs = [get_safety_config(car.CarParams.SafetyModel.tesla, safety_params[0])]

    ret.steerLimitTimer = 1.0
    ret.steerActuatorDelay = 0.25
    return ret

  def _update(self, c, frogpilot_toggles):
    ret, fp_ret = self.CS.update(self.cp, self.cp_cam, frogpilot_toggles)

    events = self.create_common_events(ret)
    if self.CP.carFingerprint == CAR.TESLA_AP1_MODELS:
      events = self._ap1_hso_events(events)
    ret.events = events.to_msg()

    return ret, fp_ret

  def _ap1_hso_events(self, events):
    """Tinkla HSO: a temporary steer warning does not soft-disable or block entry.

    steerUnavailable from EAC_FAULT is not rewritten.
    """
    from openpilot.selfdrive.controls.lib.events import Events
    EventName = car.CarEvent.EventName
    by_raw = {int(v): k for k, v in EventName.schema.enumerants.items()}
    names = ap1_hso_event_names([by_raw[int(name)] for name in events.names])
    rebuilt = Events()
    for name in names:
      rebuilt.add(getattr(EventName, name))
    return rebuilt
