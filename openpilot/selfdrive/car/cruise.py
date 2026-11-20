import math
import numpy as np

from opendbc.car.structs import car
from openpilot.common.constants import CV


# WARNING: this value was determined based on the model's training distribution,
#          model predictions above this speed can be unpredictable
# V_CRUISE's are in kph
V_CRUISE_MIN = 8
V_CRUISE_MAX = 145
V_CRUISE_UNSET = 255
V_CRUISE_INITIAL = 40
# Open choice (pedal capture speed): Pre-AP pedal FULL capture uses SetSpeedLimit (limit + offset) when it is on and fresh (True,
# default) or always the exact vEgo (False).
PREAP_FULL_USE_SET_SPEED_LIMIT = True
# t1394: Pre-AP pedal, no SetSpeedLimit: the first pull (steering only) and the FULL capture use the current speed rounded to the
# display unit (NAP preap/engagement.py:243-246 @ cc39c7fa), with no 25 mph (V_CRUISE_INITIAL) floor; from a stop the driver's
# from-stop speed (AP1TapFromZeroMph, the AP1 Standstill Tap Speed row) replaces the floor. False = the v2 behaviour (40 km/h floor).
PREAP_FROM_STOP_REPLACES_FLOOR = True
PREAP_STANDSTILL_MS = 0.1   # same bound as preap/engagement.py STANDSTILL_SPEED_MS


def preap_round_kph(v_ego_ms: float, is_metric: bool) -> float:
  """NAP _capture_target_speed: current speed rounded half-up to whole km/h or whole mph, returned in km/h, never below 0."""
  uom = 1.0 if is_metric else CV.MPH_TO_KPH
  return max(int(max(float(v_ego_ms), 0.0) * CV.MS_TO_KPH / uom + 0.5) * uom, 0.0)
IMPERIAL_INCREMENT = round(CV.MPH_TO_KPH, 1)  # round here to avoid rounding errors incrementing set speed

ButtonEvent = car.CarState.ButtonEvent
ButtonType = car.CarState.ButtonEvent.Type
CRUISE_LONG_PRESS = 50
CRUISE_NEAREST_FUNC = {
  ButtonType.accelCruise: math.ceil,
  ButtonType.decelCruise: math.floor,
}
CRUISE_INTERVAL_SIGN = {
  ButtonType.accelCruise: +1,
  ButtonType.decelCruise: -1,
}


class VCruiseHelper:
  def __init__(self, CP):
    self.CP = CP
    self.v_cruise_kph = V_CRUISE_UNSET
    self.v_cruise_cluster_kph = V_CRUISE_UNSET
    self.v_cruise_kph_last = 0
    self.button_timers = {ButtonType.decelCruise: 0, ButtonType.accelCruise: 0}
    self.button_change_states = {btn: {"standstill": False, "enabled": False} for btn in self.button_timers}

  @property
  def v_cruise_initialized(self):
    return self.v_cruise_kph != V_CRUISE_UNSET

  def update_v_cruise(self, CS, enabled, is_metric):
    self.v_cruise_kph_last = self.v_cruise_kph

    if CS.cruiseState.available:
      if not self.CP.pcmCruise:
        # if stock cruise is completely disabled, then we can use our own set speed logic
        self._update_v_cruise_non_pcm(CS, enabled, is_metric)
        self.v_cruise_cluster_kph = self.v_cruise_kph
        self.update_button_timers(CS, enabled)
      else:
        self.v_cruise_kph = CS.cruiseState.speed * CV.MS_TO_KPH
        self.v_cruise_cluster_kph = CS.cruiseState.speedCluster * CV.MS_TO_KPH
        if CS.cruiseState.speed == 0:
          self.v_cruise_kph = V_CRUISE_UNSET
          self.v_cruise_cluster_kph = V_CRUISE_UNSET
        elif CS.cruiseState.speed == -1:
          self.v_cruise_kph = -1
          self.v_cruise_cluster_kph = -1
    else:
      self.v_cruise_kph = V_CRUISE_UNSET
      self.v_cruise_cluster_kph = V_CRUISE_UNSET

  def _update_v_cruise_non_pcm(self, CS, enabled, is_metric):
    # handle button presses. TODO: this should be in state_control, but a decelCruise press
    # would have the effect of both enabling and changing speed is checked after the state transition
    if not enabled:
      return

    long_press = False
    button_type = None

    v_cruise_delta = 1. if is_metric else IMPERIAL_INCREMENT

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers and not b.pressed:
        if self.button_timers[b.type.raw] > CRUISE_LONG_PRESS:
          return  # end long press
        button_type = b.type.raw
        break
    else:
      for k, timer in self.button_timers.items():
        if timer and timer % CRUISE_LONG_PRESS == 0:
          button_type = k
          long_press = True
          break

    if button_type is None:
      return

    # Don't adjust speed when pressing resume to exit standstill
    cruise_standstill = self.button_change_states[button_type]["standstill"] or CS.cruiseState.standstill
    if button_type == ButtonType.accelCruise and cruise_standstill:
      return

    # Don't adjust speed if we've enabled since the button was depressed (some ports enable on rising edge)
    if not self.button_change_states[button_type]["enabled"]:
      return

    v_cruise_delta = v_cruise_delta * (5 if long_press else 1)
    if long_press and self.v_cruise_kph % v_cruise_delta != 0:  # partial interval
      self.v_cruise_kph = CRUISE_NEAREST_FUNC[button_type](self.v_cruise_kph / v_cruise_delta) * v_cruise_delta
    else:
      self.v_cruise_kph += v_cruise_delta * CRUISE_INTERVAL_SIGN[button_type]

    # If set is pressed while overriding, clip cruise speed to minimum of vEgo
    if CS.gasPressed and button_type in (ButtonType.decelCruise, ButtonType.setCruise):
      self.v_cruise_kph = max(self.v_cruise_kph, CS.vEgo * CV.MS_TO_KPH)

    self.v_cruise_kph = np.clip(round(self.v_cruise_kph, 1), V_CRUISE_MIN, V_CRUISE_MAX)

  def update_button_timers(self, CS, enabled):
    # increment timer for buttons still pressed
    for k in self.button_timers:
      if self.button_timers[k] > 0:
        self.button_timers[k] += 1

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers:
        # Start/end timer and store current state on change of button pressed
        self.button_timers[b.type.raw] = 1 if b.pressed else 0
        self.button_change_states[b.type.raw] = {"standstill": CS.cruiseState.standstill, "enabled": enabled}

  def capture_preap_full(self, v_ego_ms: float, set_limit_kph: float = 0.0, is_metric: bool | None = None,
                         from_stop_kph: float = 0.0) -> None:
    """Pre-AP pedal: set speed on the FULL capture edge (second pull while moving, or the standstill hold released by the
    accelerator). SetSpeedLimit fresh -> limit + offset (clipped as initialize_v_cruise does); otherwise the exact vEgo, as NAP
    captures the current speed (NAP preap/engagement.py:142,243-246 @ e99f4dc75; NAP rounds to the display unit). Never
    V_CRUISE_INITIAL (40) and never the V_CRUISE_MIN (8) floor. No resume path: the old set speed is never restored here."""
    if set_limit_kph > 0.0:
      self.v_cruise_kph = int(round(np.clip(set_limit_kph, V_CRUISE_MIN, V_CRUISE_MAX)))
    elif is_metric is None:
      self.v_cruise_kph = float(min(max(float(v_ego_ms), 0.0) * CV.MS_TO_KPH, V_CRUISE_MAX))
    else:
      # t1394: NAP rounding to the display unit. from_stop_kph > 0 only for a FULL that started at a stop. t1401 (default): passed on
      # the FULL entry itself (vEgo ~0), so the set is exactly the from-stop value; v3 option: on the hold release, as a minimum.
      v = preap_round_kph(v_ego_ms, bool(is_metric))
      if from_stop_kph > 0.0:
        v = max(v, float(from_stop_kph))
      self.v_cruise_kph = float(min(v, V_CRUISE_MAX))
    self.v_cruise_cluster_kph = self.v_cruise_kph

  def initialize_v_cruise(self, CS, experimental_mode: bool, set_limit_kph: float = 0.0, preap_from_stop_kph: float | None = None,
                          is_metric: bool = False) -> None:
    # initializing is handled by the PCM
    if self.CP.pcmCruise:
      return

    if preap_from_stop_kph is not None and PREAP_FROM_STOP_REPLACES_FLOOR and set_limit_kph <= 0.0:
      # Pre-AP pedal first pull (steering only; card passes preap_from_stop_kph only there). Moving: the rounded current speed.
      # At a stop: the from-stop speed. Never the 40 km/h floor. The FULL capture re-sets it (capture_preap_full).
      v = float(getattr(CS, "vEgo", 0.0) or 0.0)
      self.v_cruise_kph = float(min(preap_round_kph(v, is_metric) if v >= PREAP_STANDSTILL_MS else float(preap_from_stop_kph),
                                    V_CRUISE_MAX))
      self.v_cruise_cluster_kph = self.v_cruise_kph
      return

    if any(b.type in (ButtonType.accelCruise, ButtonType.resumeCruise) for b in CS.buttonEvents) and self.v_cruise_initialized:
      self.v_cruise_kph = self.v_cruise_kph_last
    elif set_limit_kph > 0.0:
      # BogPilot: SetSpeedLimit (0.9.7 drive_helpers.py:157-158 @568fea947): posted limit + SLC offset, clipped as below.
      self.v_cruise_kph = int(round(np.clip(set_limit_kph, V_CRUISE_MIN, V_CRUISE_MAX)))
    else:
      self.v_cruise_kph = int(round(np.clip(CS.vEgo * CV.MS_TO_KPH, V_CRUISE_INITIAL, V_CRUISE_MAX)))

    self.v_cruise_cluster_kph = self.v_cruise_kph
