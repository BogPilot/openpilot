"""Gas/Brake stopping helpers for the raylib tree; historical contract 04d560f3e.

No process starts, Params writes, legacy imports, CAN messages, or default migrations.
Consumers must keep stock engagement, brake, throttle, MPC and actuator limit guards.
Missing starting-state fields are represented as None, never invented CP values.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math


FOOT_TO_METER = 0.3048
CITY_SPEED_LIMIT = 25.0  # Historical constant is m/s, NOT 25 mph.
WEATHER_RANGES = (
  ("Rain", ((300, 321), (500, 504))),
  ("RainStorm", ((200, 232), (511, 511), (520, 531))),
  ("Snow", ((600, 622),)),
  ("LowVisibility", ((701, 762),)),
)
# INT t994 safety bounds (review BLOCKER): a saved/legacy value of 0 m/s^2 would hold no brake command at standstill and a
# ~0 rate would ramp braking ~1000x slower than stock. Reads clamp to these; the UI rows use the same limits.
# t1003u: Stop Acceleration / Stopping Rate rows are registered with these floors (UI range AND consumer clamp).
STOP_TUNING_ENABLED = True
STOP_ACCEL_CEILING = -0.5
STOPPING_RATE_FLOOR = 0.1
MIN_LEAD_DISTANCE_M = 0.5  # stopped-distance offset never drives a present lead's dRel below this (or below its own value)

STOPPING_KEYS = ("StartAccel", "VEgoStarting", "StopAccel", "StoppingDecelRate", "VEgoStopping")
WEATHER_KEYS = ("WeatherPresets", "SetWeatherKey", *(
  key for suffix in ("LowVisibility", "Rain", "RainStorm", "Snow")
  for key in (suffix + "Offsets", "IncreaseFollowing" + suffix, "IncreasedStoppedDistance" + suffix,
              "ReduceAcceleration" + suffix, "ReduceLateralAcceleration" + suffix)))
OWNED_KEYS = (*STOPPING_KEYS, "HumanAcceleration", "QOLLongitudinal", "ForceStops", "IncreasedStoppedDistance",
              "MapGears", "ReverseCruise", *WEATHER_KEYS)
DELEGATED_KEYS = {"HumanFollowing": "lane7: frogpilot_following.update_follow_values + radar/model-version guards",
                  "MapAcceleration": "lane4: acceleration profile consumer; map gate supplied here",
                  "MapDeceleration": "lane4: deceleration profile consumer; map gate supplied here"}


def _number(value, fallback):
  try:
    number = float(value)
    return number if math.isfinite(number) else fallback
  except (TypeError, ValueError):
    return fallback


def _bool(value):
  return str(value).strip().lower() in ("1", "true", "yes", "on")


def _value(store, key, parent=True):
  # Historical inactive parent/too-low tuning level uses the registered default,
  # not the stored child. No setting is ever reset or overwritten.
  if parent and store.honoured(key, store.tuning_level()):
    return store.get(key)
  return store.default(key)


def _toggle(store, key, parent=True):
  return parent and _bool(_value(store, key))


def _distance(store, key, parent, metric):
  selected = parent and store.honoured(key, store.tuning_level())
  value = _number(store.get(key) if selected else store.default(key), 0.0)
  # Defaults in the historical variable loader always used feet, even metric.
  return value * (1.0 if selected and metric else FOOT_TO_METER)


@dataclass(frozen=True)
class StoppingTune:
  start_accel: float | None
  v_ego_starting: float | None
  stop_accel: float
  stopping_decel_rate: float
  v_ego_stopping: float | None


def read_stopping_tune(store, CP):
  """Read historical bounds; retain native CP defaults for unavailable/disabled keys.

  Current 0.11.2 has no starting state in LongControl. Returning its missing fields
  as None deliberately prevents pretending those rows are functional.
  """
  op_long = bool(CP.openpilotLongitudinalControl)
  op_long &= not _toggle(store, "DisableOpenpilotLongitudinal")
  advanced = _toggle(store, "AdvancedLongitudinalTune", op_long)
  def val(key, attr, low, high, fallback=None):
    stock = getattr(CP, attr, fallback)
    if not advanced or not store.honoured(key, store.tuning_level()):
      return stock
    value = _number(store.get(key), stock)
    return stock if value is None else max(low, min(high, value))
  return StoppingTune(val("StartAccel", "startAccel", 0.0, 4.0),
                      val("VEgoStarting", "vEgoStarting", 0.01, 1.0),
                      val("StopAccel", "stopAccel", -4.0, STOP_ACCEL_CEILING),
                      val("StoppingDecelRate", "stoppingDecelRate", STOPPING_RATE_FLOOR, 1.0, 1.0),
                      val("VEgoStopping", "vEgoStopping", 0.01, 1.0))


@dataclass(frozen=True)
class LongStoppingOptions:
  human_acceleration: bool = False
  force_stops: bool = False
  stopped_distance: float = 0.0  # metres
  map_acceleration: bool = False
  map_deceleration: bool = False
  reverse_cruise: bool = False
  weather_presets: bool = False


def read_options(store, CP, *, is_metric):
  op_long = bool(CP.openpilotLongitudinalControl) and not _toggle(store, "DisableOpenpilotLongitudinal")
  longitudinal = _toggle(store, "LongitudinalTune", op_long)
  qol = _toggle(store, "QOLLongitudinal", op_long)
  gears = _toggle(store, "MapGears", qol)
  return LongStoppingOptions(
    human_acceleration=_toggle(store, "HumanAcceleration", longitudinal),
    force_stops=_toggle(store, "ForceStops", qol),
    stopped_distance=_distance(store, "IncreasedStoppedDistance", qol, is_metric) if op_long else 0.0,
    map_acceleration=_toggle(store, "MapAcceleration", gears),
    map_deceleration=_toggle(store, "MapDeceleration", gears),
    # This never means drive in reverse: it is Toyota's cruise long-press mapping.
    reverse_cruise=_toggle(store, "ReverseCruise", qol and getattr(CP, "brand", getattr(CP, "carName", "")) == "toyota" and CP.pcmCruise),
    weather_presets=_toggle(store, "WeatherPresets", qol),
  )


def _interp(x, xs, ys):
  if x <= xs[0]:
    return ys[0]
  for i in range(1, len(xs)):
    if x <= xs[i]:
      return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1])
  return ys[-1]


def human_accel_limit(max_accel, v_cruise, v_ego, enabled):
  """Historical low-speed taper then cruise-gap ramp, m/s and m/s².

  Profile choice, turn/throttle envelope and negative braking authority stay with
  the stock planner/lane4. Apply only to its positive acceleration ceiling.
  """
  if not enabled or max_accel <= 0 or not all(math.isfinite(x) for x in (max_accel, v_cruise, v_ego)):
    return max_accel
  ceiling = min(_interp(v_cruise, (0.0, CITY_SPEED_LIMIT / 2, CITY_SPEED_LIMIT),
                        (max_accel / 4, max_accel / 2, max_accel)), max_accel)
  return min(_interp(v_cruise - v_ego, (0.0, 1.0, 5.0), (0.0, 0.5, ceiling)), ceiling)


def stopping_accel(last_output, tune, dt, accel_limits):
  """Only for the existing stock stopping state; never chooses engagement/state."""
  output = last_output
  if output > tune.stop_accel:
    output = min(output, 0.0) - tune.stopping_decel_rate * dt
  return max(accel_limits[0], min(accel_limits[1], output))


@dataclass(frozen=True)
class WeatherOffsets:
  following_seconds: float = 0.0
  stopped_metres: float = 0.0
  acceleration_reduction: float = 0.0
  lateral_reduction: float = 0.0


def weather_offsets(store, options, weather_id, *, is_metric, valid):
  """Offline offset selector. Caller owns time/GPS validity and weather source.

  No shared token, location upload, HTTP fetch or invented weather detections.
  """
  if not options.weather_presets or not valid:
    return WeatherOffsets()
  suffix = next((suffix for suffix, ranges in WEATHER_RANGES
                 if any(lo <= weather_id <= hi for lo, hi in ranges)), None)
  if suffix is None:
    return WeatherOffsets()
  # The *Offsets keys are MANAGE navigation rows, NOT enable switches.
  following = _number(_value(store, "IncreaseFollowing" + suffix), 0.0)
  distance = _distance(store, "IncreasedStoppedDistance" + suffix, True, is_metric)
  acceleration = _number(_value(store, "ReduceAcceleration" + suffix), 0.0) / 100
  lateral = _number(_value(store, "ReduceLateralAcceleration" + suffix), 0.0) / 100
  return WeatherOffsets(following, distance, acceleration, lateral)


def stopped_distance(options, weather=WeatherOffsets(), *, traffic_mode=False):
  return 0.0 if traffic_mode else options.stopped_distance + weather.stopped_metres


def offset_lead(lead, distance):
  """Historical radard dRel subtraction, copied message/dict; never mutate tracks.

  Apply ONCE to final selected leads, after matching, before publication. Do not
  use adjusted distances for association or adjacent-lane selection.
  """
  result = dict(lead)
  if result.get("present", result.get("status", False)):
    original = result["dRel"]
    result["dRel"] = max(original - distance, min(original, MIN_LEAD_DISTANCE_M))
  return result


@dataclass(frozen=True)
class ForceStopResult:
  target: float
  forcing_stop: bool
  tracked_model_length: float


class ForceStopController:
  """One-second model stop confirmation, gas/accel override and 10s holdoff.

  Expects CEM stop-light predicate AND model-stopped predicate, never raw model
  position alone. Inputs are SI. Stock disengagement and driver override win.
  This produces a reduced planner cruise target, NOT brake/CAN commands.
  """
  def __init__(self):
    self.confirmation_time = 0.0
    self.override_timer = 0.0
    self.override = False
    self.forcing_stop = False
    self.tracked_model_length = 0.0

  def update(self, *, enabled, option, stop_light_detected, model_stopped,
             gas_pressed, accel_pressed, standstill, model_length, v_ego,
             v_cruise, planner_time, dt=0.05):
    # Invalid/missing planner inputs must not manufacture a stop request.
    valid = all(math.isfinite(x) for x in (model_length, v_ego, v_cruise, planner_time, dt))
    valid &= planner_time > 0 and dt > 0 and model_length >= 0
    request = valid and enabled and option and stop_light_detected and model_stopped and self.override_timer <= 0
    self.confirmation_time = self.confirmation_time + dt if request else 0.0
    confirmed = self.confirmation_time >= 1.0
    self.override = (self.override or gas_pressed or accel_pressed) and confirmed
    if self.override:
      self.override_timer = 10.0
    elif self.override_timer > 0:
      self.override_timer -= dt
    if confirmed and not self.override:
      self.forcing_stop |= not standstill
      self.tracked_model_length = max(self.tracked_model_length - v_ego * dt, 0.0)
      target = min(self.tracked_model_length // planner_time, v_cruise)
    else:
      self.forcing_stop = False
      self.tracked_model_length = model_length if valid else 0.0
      target = v_cruise
    return ForceStopResult(target, self.forcing_stop, self.tracked_model_length)


def native_stopping_tune(CP):
  """Exact current-tree defaults: fixed 1 m/s³ ramp, no starting state."""
  return StoppingTune(None, None, CP.stopAccel, 1.0, None)


def read_runtime_stopping(store, CP):
  """Supported 0.11.2 subset only; absent starting state stays absent."""
  stock = native_stopping_tune(CP)
  if not STOP_TUNING_ENABLED:
    return stock
  if not store.get_bool(STOPPING_ACK, False):
    return stock
  if not CP.openpilotLongitudinalControl or _toggle(store, "DisableOpenpilotLongitudinal"):
    return stock
  if not _toggle(store, "AdvancedLongitudinalTune"):
    return stock
  def value(key, fallback, low, high):
    # Dormant until the user changes THIS row (per-row marker); stale/out-of-range saved values are clamped to the floor.
    if not store.get_bool(ROW_ACKS[key], False) or not store.honoured(key, store.tuning_level()):
      return fallback
    return max(low, min(high, _number(store.get(key), fallback)))
  return StoppingTune(None, None, value("StopAccel", stock.stop_accel, -4, STOP_ACCEL_CEILING),
                      value("StoppingDecelRate", 1.0, STOPPING_RATE_FLOOR, 1.0), None)


from openpilot.selfdrive.controls.lib.phase3_long_accel import ADVANCED_ACK, ROW_ACKS
# Single adoption marker for the whole Advanced Longitudinal Tuning group (delay, max accel, stop accel, stopping rate).
STOPPING_ACK = ADVANCED_ACK
DISTANCE_ACK = "Phase3StoppedDistanceEnabled"
FORCE_ACK = "Phase3ForceStopsEnabled"
WEATHER_ACK = "Phase3ManualWeatherEnabled"
MANUAL_WEATHER_KEY = "BogPilotManualWeather"
MANUAL_WEATHER = {"clear": 0, "low_visibility": 701, "rain": 500, "rain_storm": 200, "snow": 600}


def manual_weather_offsets(store, options, *, is_metric):
  """Explicit local source adapter: manual selection, no GPS/network/key reads."""
  selected = store.get(MANUAL_WEATHER_KEY, "clear")
  return weather_offsets(store, options, MANUAL_WEATHER.get(selected, 0),
                         is_metric=is_metric, valid=selected in MANUAL_WEATHER)


@dataclass(frozen=True)
class ModelStopInputs:
  stop_light_detected: bool
  model_stopped: bool
  model_length: float
  planner_time: float
  valid: bool


class LongStoppingRuntime:
  """Actual daemon-facing boundary; inputs must come from authoritative producers."""
  def __init__(self, store, CP, dt=.05):
    self.store, self.CP, self.dt = store, CP, dt
    self.force_stop = ForceStopController()
    self.observer = None

  def snapshot(self):
    metric = self.store.get_bool("IsMetric")
    options = read_options(self.store, self.CP, is_metric=metric)
    options = replace(options,
                      force_stops=options.force_stops and self.store.get_bool(FORCE_ACK, False),
                      stopped_distance=options.stopped_distance if self.store.get_bool(DISTANCE_ACK, False) else 0.0,
                      weather_presets=options.weather_presets and self.store.get_bool(WEATHER_ACK, False))
    weather = manual_weather_offsets(self.store, options, is_metric=metric)
    return options, weather

  def adjust_radar_state(self, radar_state, *, traffic_mode):
    # Missing/unhealthy traffic source cannot be assumed to mean "off".
    if traffic_mode is None:
      return
    options, weather = self.snapshot()
    distance = stopped_distance(options, weather, traffic_mode=traffic_mode)
    if not distance:
      return
    for field in ("leadOne", "leadTwo"):
      lead = getattr(radar_state, field).to_dict()
      setattr(radar_state, field, offset_lead(lead, distance))

  def observe_model_stop(self, sm, long_accel, *, active):
    if self.observer is None:
      self.observer = ForceStopObserver(self.dt)
    options, _ = self.snapshot()
    return self.observer.observe(sm, long_accel, active=active and options.force_stops)

  def arbitrate_force_stop(self, target, *, model_stop, longitudinal_active, gas_pressed,
                           accel_pressed, standstill, v_ego, dt=0.05):
    """Call LAST after normal/CSC/SLC arbitration; cannot raise that target.

    CEM lane supplies the complete ModelStopInputs from its actual model state.
    None/invalid input disables force stop; never synthesize a light detection.
    Stock LongControl/driver override still has final authority over actuation.
    """
    options, _ = self.snapshot()
    usable = model_stop is not None and model_stop.valid
    # The fresh-input bridge invalidates model observations on pedal override.
    # Preserve historical holdoff when that override interrupts an active stop.
    if options.force_stops and (gas_pressed or accel_pressed) and (self.force_stop.forcing_stop or self.force_stop.confirmation_time >= 1):
      self.force_stop.override_timer = 10.0
      self.force_stop.confirmation_time = 0.0
      self.force_stop.forcing_stop = False
      self.force_stop.override = False
      return ForceStopResult(target, False, self.force_stop.tracked_model_length)
    return self.force_stop.update(
      enabled=longitudinal_active and usable, option=options.force_stops,
      stop_light_detected=model_stop.stop_light_detected if usable else False,
      model_stopped=model_stop.model_stopped if usable else False,
      gas_pressed=gas_pressed, accel_pressed=accel_pressed, standstill=standstill,
      model_length=model_stop.model_length if usable else 0.0,
      planner_time=model_stop.planner_time if usable else 0.0,
      v_ego=v_ego, v_cruise=target, dt=dt)


class ForceStopObserver:
  """Historical disabled-CEM stop_sign_and_light observer; NEVER enables CEM.

  04d560f3e frogpilot_planner.py calls stop_sign_and_light(PLANNER_TIME-2)
  with curve_detected=False while CEM is off. Its .5s filter/.63 threshold,
  tracking-lead exclusion and traffic-mode suppression are retained here.
  """
  def __init__(self, dt=.05):
    from openpilot.common.filter_simple import FirstOrderFilter
    self.filter = FirstOrderFilter(0, .5, dt)

  def observe(self, sm, long_accel, *, active):
    from openpilot.selfdrive.modeld.constants import ModelConstants
    options_valid = active and long_accel.model_valid
    if not options_valid or sm["carState"].bogpilot.trafficModeEnabled:
      self.filter.x = 0
      return ModelStopInputs(False, False, 0., 0., False)
    if long_accel.conditions is not None:
      self.filter.x = 0
      red_light = long_accel.cem.red_light
    else:
      model_time = float(ModelConstants.T_IDXS[-1]) - 2
      v_ego = max(sm["carState"].vEgo, 0)
      slow_hint = any(v <= .5 * v_ego for t, v in zip(ModelConstants.T_IDXS, sm["modelV2"].velocity.x) if t > model_time)
      stopping = long_accel.model_stopped or long_accel.model_length < v_ego * model_time or slow_hint
      red_light = self.filter.update(stopping) >= .63 and not long_accel.tracking_lead
    return ModelStopInputs(bool(red_light), long_accel.model_stopped,
                           long_accel.model_length, long_accel.model_horizon, True)
