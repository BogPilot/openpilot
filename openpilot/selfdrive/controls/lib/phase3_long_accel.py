"""Opt-in 0.9.7 consumers. Source: own 04d560f3e. Never writes defaults.

configure() must be called by an explicit UI config action; merely deploying this
module does not activate dormant stored tuning. Other lanes own stopping, SLC,
following/jerk, gear acquisition and weather acquisition.
"""
from dataclasses import dataclass, replace
import math
import numpy as np
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL

PROFILE_ACK = "Phase3LongAccelProfilesEnabled"
ADVANCED_ACK = "Phase3AdvancedLongEnabled"
CEM_ACK = "Phase3CEMEnabled"
# Per-row adoption markers for the two stop rows (file-only, cleared by reset/backup): a saved 0.9.7 StopAccel /
# StoppingDecelRate stays dormant until the user changes THAT row, even if another Advanced row already adopted the group.
STOP_ACCEL_ACK = "Phase3StopAccelEnabled"
STOPPING_RATE_ACK = "Phase3StoppingRateEnabled"
ROW_ACKS = {"StopAccel": STOP_ACCEL_ACK, "StoppingDecelRate": STOPPING_RATE_ACK}
PROFILE_KEYS = ("LongitudinalTune", "AccelerationProfile", "DecelerationProfile", "HumanAcceleration")
# Stop Acceleration / Stopping Rate share the Advanced parent and its single adoption marker
# (consumed by phase3_long_stopping.read_runtime_stopping in LongControl).
ADVANCED_KEYS = ("AdvancedLongitudinalTune", "LongitudinalActuatorDelay", "MaxDesiredAcceleration",
                 "StopAccel", "StoppingDecelRate")
CEM_KEYS = ("ConditionalExperimental", "CESpeed", "CESpeedLead", "CECurves", "CECurvesLead",
            "CEStopLights", "CELead", "CESlowerLead", "CEStoppedLead", "CENavigation",
            "CENavigationIntersections", "CENavigationTurns", "CENavigationLead", "CEModelStopTime",
            "CESignalSpeed", "CESignalLaneDetection", "ShowCEMStatus")


def configure(store, key, value):
  """Explicit config only: commit and verify preference BEFORE enabling adoption."""
  def write(method, name, datum):
    try:
      method(name, datum, block=True)
    except TypeError:
      from openpilot.common.bogpilot_store import ParamStore
      if isinstance(store, ParamStore):
        raise RuntimeError("Explicit UI adoption requires the optional blocking ParamStore integration patch")
      method(name, datum)  # small injected non-ParamStore test interfaces only

  for keys, ack in ((PROFILE_KEYS, PROFILE_ACK), (ADVANCED_KEYS, ADVANCED_ACK), (CEM_KEYS, CEM_ACK)):
    if key in keys:
      write(store.put, key, value)
      store.invalidate()
      if not math.isclose(store.get_float(key), float(value), rel_tol=0, abs_tol=1e-6):
        raise RuntimeError("Preference was not committed; adoption marker left unchanged")
      if key in ROW_ACKS:
        write(store.put_bool, ROW_ACKS[key], True)
      write(store.put_bool, ack, True)
      store.invalidate()
      return
  raise ValueError(key)


def finite_clip(value, low, high, fallback):
  return float(np.clip(value, low, high)) if math.isfinite(value) else fallback


@dataclass(frozen=True)
class Profiles:
  acceleration: int = 0
  deceleration: int = 0
  human: bool = False

  @classmethod
  def read(cls, store):
    if not store.get_bool(PROFILE_ACK, False) or not store.toggle_bool("LongitudinalTune"):
      return None
    return cls(store.toggle_int("AccelerationProfile"), store.toggle_int("DecelerationProfile"),
               store.toggle_bool("HumanAcceleration"))

  def limits(self, v_ego, v_cruise, accel_min, tracking_lead=False, *, eco=False, sport=False,
             map_acceleration=False, map_deceleration=False, force_coast=False, weather_reduction=0.0):
    """04d560f3e frogpilot_acceleration lookups/precedence. All inputs SI.

    Lead tracking always restores full braking. Gear/weather flags require real
    publishers; callers must not synthesize them from a vehicle make.
    """
    profile = self.acceleration
    if (eco or sport) and map_acceleration:
      profile = 1 if eco else (2 if profile == 2 else 3)
    if profile == 1:
      maximum = np.interp(v_ego, [0, 5, 10, 15, 20, 25, 40], [2, 1.5, 1, .8, .6, .4, .2])
    elif profile == 2:
      maximum = np.interp(v_ego, [0, 5, 10, 15, 20, 25, 40], [3, 2.5, 2, 1.5, 1, .8, .6])
    elif profile == 3:
      maximum = np.interp(v_ego, [0, 5, 20], [4, 4, 2])
    else:
      maximum = np.interp(v_ego, [0, 10, 25, 40], [2, 1.6, .8, .6])
    if self.human:
      maximum = min(np.interp(v_cruise, [0, 12.5, 25], [maximum / 4, maximum / 2, maximum]), maximum)
      maximum = min(np.interp(v_cruise - v_ego, [0, 1, 5], [0, .5, maximum]), maximum)
    maximum -= maximum * weather_reduction
    if tracking_lead:
      minimum = accel_min
    elif force_coast:
      minimum = accel_min / 2
    elif (eco or sport) and map_deceleration:
      minimum = accel_min / (2 if eco else 4)
    else:
      minimum = accel_min / (2 if self.deceleration == 1 else 4 if self.deceleration == 2 else 1)
    return float(minimum), float(maximum)


def advanced_values(store, cp):
  """Delay seconds / actuator acceleration cap m/s²; absence preserves current baseline."""
  if not store.get_bool(ADVANCED_ACK, False) or not store.toggle_bool("AdvancedLongitudinalTune"):
    return float(cp.longitudinalActuatorDelay), None
  # An unwritten delay keeps the CarParams value: enabling the parent must not silently zero it.
  written = store.honoured("LongitudinalActuatorDelay") and (not hasattr(store, "raw") or store.raw("LongitudinalActuatorDelay") not in (None, ""))
  delay = (finite_clip(store.get_float("LongitudinalActuatorDelay"), 0, 1, cp.longitudinalActuatorDelay)
           if written else float(cp.longitudinalActuatorDelay))
  cap = (finite_clip(store.get_float("MaxDesiredAcceleration"), .1, 4, 4)
         if store.honoured("MaxDesiredAcceleration") else None)
  return delay, cap


@dataclass(frozen=True)
class Conditions:
  below: float = 0
  below_lead: float = 0
  curves: bool = False
  curves_lead: bool = False
  lead: bool = False
  slower_lead: bool = False
  stopped_lead: bool = False
  navigation: bool = False
  navigation_lead: bool = False
  model_stop_time: float = 0
  signal: float = 0
  signal_lane_detection: bool = False
  lane_width: float = 0
  status_widget: bool = False
  navigation_intersections: bool = False
  navigation_turns: bool = False

  @classmethod
  def read(cls, store):
    if not store.get_bool(CEM_ACK, False) or not store.toggle_bool("ConditionalExperimental"):
      return None
    conversion = 1 / 3.6 if store.get_bool("IsMetric", False) else .44704
    def speed(key):
      # Registry/default-store speeds are MPH, even while current display units
      # are metric. Only a real stored preference is in current display units.
      missing = hasattr(store, "raw") and store.raw(key) is None
      return (store.get_float(key) * conversion if store.honoured(key) and not missing else
              float(store.default(key) or 0) * .44704)
    stop_time = (store.get_int("CEModelStopTime") if store.honoured("CEModelStopTime") else
                 float(store.default("CEModelStopTime") or 0) if store.get_bool("CEStopLights") else 0)
    lane_width = (store.get_float("LaneDetectionWidth") * (1 if store.get_bool("IsMetric", False) else .3048)
                  if store.toggle_bool("LaneChanges") and store.honoured("LaneDetectionWidth") else
                  float(store.default("LaneDetectionWidth") or 0) * .3048)
    b = store.toggle_bool
    curves, lead, navigation = b("CECurves"), b("CELead"), b("CENavigation")
    return cls(speed("CESpeed"), speed("CESpeedLead"), curves, curves and b("CECurvesLead"),
               lead, lead and b("CESlowerLead"), lead and b("CEStoppedLead"), navigation,
               navigation and b("CENavigationLead"), stop_time, speed("CESignalSpeed"),
               speed("CESignalSpeed") != 0 and b("CESignalLaneDetection"),
               lane_width, b("ShowCEMStatus"), navigation and b("CENavigationIntersections"),
               navigation and b("CENavigationTurns"))


@dataclass(frozen=True)
class Scene:
  v_ego: float
  standstill: bool = False
  following_lead: bool = False
  tracking_lead: bool = False
  lead_speed: float = 0
  curve: bool = False
  blinker: bool = False
  desired_lane_width: float = 0
  intersection: bool = False
  turn: bool = False
  model_length: float = 0
  model_stopped: bool = False
  model_t: tuple = ()
  model_v: tuple = ()
  traffic_mode: bool = False
  forcing_stop: bool = False
  slc_experimental: bool = False
  predicted_slower_lead: bool = False
  predicted_stopped_lead: bool = False


class ConditionalMode:
  """04d560f3e filters, ordering and statuses; does NOT detect traffic light colors.

  Navigation subtype gating belongs to the historical navigation producer.
  Predicted-lead inputs require the old v9-only prediction path, not a guessed model.
  """
  def __init__(self, dt=DT_MDL):
    self.curve_filter = FirstOrderFilter(0, 1, dt)
    self.lead_filter = FirstOrderFilter(0, .5, dt)
    self.stop_filter = FirstOrderFilter(0, .5, dt)
    self.experimental = False
    self.status = 0
    self.red_light = False

  def reset(self):
    self.curve_filter.x = self.lead_filter.x = self.stop_filter.x = 0
    self.experimental = self.red_light = False
    self.status = 0

  def update(self, s, c, override=0):
    self.status = override
    if override in (1, 2) or s.standstill:
      self.experimental = override == 2 or (s.standstill and self.experimental and s.model_stopped)
      self.red_light &= override not in (1, 2)
      self.stop_filter.x = 0
      return self.experimental
    curve = self.curve_filter.update(s.curve) >= .63 and s.v_ego > 5
    if s.tracking_lead:
      slower = s.v_ego - s.lead_speed > 5 and c.slower_lead
      stopped = s.lead_speed < 1 and c.stopped_lead
      slow = self.lead_filter.update(slower or stopped or (s.predicted_slower_lead and c.slower_lead) or
                                     (s.predicted_stopped_lead and c.stopped_lead)) >= .63
    else:
      self.lead_filter.x = 0
      slow = False
    if not s.traffic_mode:
      hint = any(v <= .5 * s.v_ego for t, v in zip(s.model_t, s.model_v) if t > c.model_stop_time) and not curve
      self.red_light = (self.stop_filter.update(s.model_stopped or s.model_length < s.v_ego * c.model_stop_time or hint)
                        >= .63 and not s.tracking_lead)
    else:
      self.stop_filter.x = 0
      self.red_light = False
    lane_available = s.desired_lane_width >= c.lane_width or not c.signal_lane_detection
    checks = (
      (1 <= s.v_ego < (c.below_lead if s.following_lead else c.below), 3 if s.following_lead else 4),
      (s.v_ego < c.signal and s.blinker and not lane_available, 5),
      ((s.intersection or s.turn) and (not s.following_lead or c.navigation_lead) and c.navigation,
       6 if s.intersection else 7),
      (curve and (not s.following_lead or c.curves_lead) and c.curves, 8),
      (slow and c.lead, 9 if s.lead_speed < 1 else 10),
      (self.red_light and c.model_stop_time != 0, 12 if s.forcing_stop else 11),
      (s.slc_experimental, 13),
    )
    self.status = next((status for yes, status in checks if yes), 0)
    self.experimental = self.status != 0
    return self.experimental


def lane_width(lane, current_lane, road_edge):
  """Exact historical median width, with validation before numpy interpolation."""
  paths = (lane, current_lane, road_edge)
  for path in paths:
    if not len(path.x) or len(path.x) != len(path.y):
      return None
    if not all(math.isfinite(v) for v in (*path.x, *path.y)):
      return None
  current_x, current_y = np.asarray(current_lane.x), np.asarray(current_lane.y)
  width = float(np.median(np.abs(current_y - np.interp(current_x, lane.x, lane.y))))
  edge = float(np.median(np.abs(current_y - np.interp(current_x, road_edge.x, road_edge.y))))
  return 0.0 if edge < width else width


def predicted_lead_flags(lead, model_lead, v_ego, t_follow, model_version, probability_threshold):
  """Exact old v9-only predicted-lead test; a versionless/new-model trajectory is NOT v9."""
  if model_version != "v9" or model_lead is None or model_lead.prob <= probability_threshold:
    return False, False
  x, v = list(model_lead.x), list(model_lead.v)
  if len(x) < 2 or len(x) != len(v) or not all(math.isfinite(value) for value in (*x, *v)):
    return False, False
  from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import get_safe_obstacle_distance, get_stopped_equivalence_factor
  distances = [lead.dRel + distance - x[0] for distance in x]
  velocities = [max(lead.vLead + velocity - v[0], 0) for velocity in v]
  future_speed = min(velocities[1:])
  obstacles = [distance + get_stopped_equivalence_factor(velocity) for distance, velocity in zip(distances, velocities)]
  relevant = min(obstacles[1:]) < get_safe_obstacle_distance(v_ego, t_follow) + 15
  return velocities[0] - future_speed >= 2 and relevant, future_speed < 1 and relevant


class LongAccelPort:
  """Planner bridge. Missing/stale required sources fail closed, never invent a publisher."""
  def __init__(self, cp, dt=DT_MDL, store=None):
    from openpilot.selfdrive.controls.lib.bogpilot_csc import TrackingLead
    self.cp, self.dt = cp, dt
    if store is None:
      from openpilot.common.bogpilot_store import ParamStore
      store = ParamStore(cache_ttl=1.0)
    self.store = store
    self.cem = ConditionalMode(dt)
    self.tracking = TrackingLead(dt)
    self.profiles = None
    self.tracking_lead = False
    self.conditions = None
    self.model_length = self.model_horizon = 0.0
    self.model_stopped = False
    self.model_valid = False
    self._published_status = None

  def publish_status(self):
    """Existing registered CEStatus only; no schema field or manual-toggle input.

    Change-only writes avoid 20Hz persistent Params IO. Never clear another
    writer at startup when this port has not been explicitly adopted.
    """
    if not self.store.get_bool(CEM_ACK, False) and self._published_status is None:
      return
    status = self.cem.status if self.cem.experimental else 0
    if status != self._published_status:
      self.store.put("CEStatus", int(status))
      self._published_status = status

  def update(self, sm, reset, *, context=None):
    from openpilot.selfdrive.controls.lib.ap1_curve_speed import _service_ok, model_path
    from openpilot.selfdrive.controls.lib.bogpilot_csc import calculate_road_curvature, road_curvature_detected
    self.profiles = self.conditions = None
    self.model_valid = False
    self.model_length = self.model_horizon = 0.0
    self.model_stopped = False
    cs = sm["carState"]
    if (not self.cp.openpilotLongitudinalControl or reset or cs.gasPressed or cs.brakePressed or
        not all(_service_ok(sm, name) for name in ("carState", "modelV2", "radarState", "selfdriveState", "controlsState"))):
      self.cem.reset()
      self.tracking.filter.x = 0
      self.tracking_lead = False
      return False
    path = model_path(sm["modelV2"])
    if path is None or not math.isfinite(cs.vEgo):
      self.cem.reset()
      return False
    t, x, v, yaw, yaw_t = path
    self.model_valid = True
    self.model_length, self.model_horizon = x[-1], t[-1]
    self.model_stopped = self.model_length < 5 * self.model_horizon
    lead = sm["radarState"].leadOne
    self.tracking_lead = self.tracking.update(lead.present, lead.dRel, lead.vRel, x[-1], cs.standstill)
    self.profiles = Profiles.read(self.store)
    self.conditions = Conditions.read(self.store)
    if self.conditions is None:
      self.cem.reset()
      return False
    context = context or {}
    # Caller supplies AP1 detent t_follow; do not read dormant personality knobs.
    # A caller without real following context must not guess a personality/detent.
    t_follow = context.get("t_follow")
    if t_follow is None or not math.isfinite(t_follow):
      self.cem.reset()
      return False
    desired_width = 0.0
    speed_conversion = 1 / 3.6 if self.store.get_bool("IsMetric", False) else .44704
    minimum_lane_speed = (self.store.get_float("MinimumLaneChangeSpeed") * speed_conversion
                          if self.store.toggle_bool("LaneChanges") and self.store.honoured("MinimumLaneChangeSpeed")
                          else float(self.store.default("MinimumLaneChangeSpeed") or 0) * .44704)
    if self.conditions.lane_width > 0 and cs.vEgo >= minimum_lane_speed:
      m = sm["modelV2"]
      if len(m.laneLines) == 4 and len(m.roadEdges) == 2:
        desired_width = lane_width(m.laneLines[0 if cs.leftBlinker else 3],
                                   m.laneLines[1 if cs.leftBlinker else 2], m.roadEdges[0 if cs.leftBlinker else 1])
      else:
        desired_width = None
      if desired_width is None:
        # Missing lane geometry is not proof there is no adjacent lane.
        self.conditions = replace(self.conditions, signal=0)
        desired_width = 0.0
    curvature, _ = calculate_road_curvature(yaw, v, yaw_t)
    curve = road_curvature_detected(curvature, cs.vEgo, cs.leftBlinker or cs.rightBlinker)
    curve |= abs(cs.vEgo ** 2 * sm["controlsState"].curvature) >= 1.3
    scene_extra = dict(context.get("scene", {}))
    # Model-selector lane must supply verified version/threshold; no inferred current-model identity.
    model_leads = sm["modelV2"].leadsV3
    if self.tracking_lead and "model_version" in context and "lead_detection_probability" in context:
      slower, stopped = predicted_lead_flags(lead, model_leads[0] if len(model_leads) else None, cs.vEgo,
                                              t_follow, context["model_version"], context["lead_detection_probability"])
      scene_extra.update(predicted_slower_lead=slower, predicted_stopped_lead=stopped)
    # Old navigation producer gated these two subtypes; do so at this bridge boundary too.
    if "intersection" in scene_extra:
      scene_extra["intersection"] &= self.conditions.navigation_intersections
    if "turn" in scene_extra:
      scene_extra["turn"] &= self.conditions.navigation_turns
    scene = Scene(cs.vEgo, bool(cs.standstill), self.tracking_lead and lead.dRel < t_follow * 2 * cs.vEgo,
                  self.tracking_lead, lead.vLead, curve, cs.leftBlinker or cs.rightBlinker,
                  desired_lane_width=desired_width, **scene_extra,
                  model_length=self.model_length, model_stopped=self.model_stopped,
                  model_t=tuple(t), model_v=tuple(v))
    return self.cem.update(scene, self.conditions, context.get("override", 0))

  def limits(self, v_ego, v_cruise, accel_min, *, weather_reduction=0.0, eco=False, sport=False,
             map_acceleration=False, map_deceleration=False, force_coast=False):
    # Primary supplies only validated real cross-lane snapshots. Human limiting
    # lives inside Profiles.limits; never apply a second human/weather multiplier.
    return None if self.profiles is None else self.profiles.limits(
      v_ego, v_cruise, accel_min, self.tracking_lead, weather_reduction=weather_reduction,
      eco=eco, sport=sport, map_acceleration=map_acceleration, map_deceleration=map_deceleration,
      force_coast=force_coast)

  def delay(self):
    return advanced_values(self.store, self.cp)[0] if self.cp.openpilotLongitudinalControl else self.cp.longitudinalActuatorDelay
