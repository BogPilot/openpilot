"""Curve speed planner: one module for curve braking on the legacy Tesla planner (AP1 Model S and X with openpilot
longitudinal, Pre-AP with a calibrated pedal).

It replaces the stacked curve paths of earlier builds: the CSC cruise-speed cap (with its 2 s exit hold and no-raise
latch), the separate look-ahead curve brake (gated on that cap, with its own curvature estimate, a debounced deadband
and a hardcoded 0.3 s lag) and the second Smooth Curve Braking envelope that ran beside it.

1. One speed envelope: every point ahead that limits speed, as (distance m, curve speed m/s).
   * Vision: each model path node. Curve speed sqrt(a_lat / k) with k = |lateral accel| / v^2; the lateral accel is
     3-node median filtered along the path (a one-node spike never limits, a real curve spans several nodes), nodes the
     model plans to drive slower than MIN_NODE_SPEED are skipped (yaw rate / speed near a stop is a false curve).
   * Map (mapd v2 mapCurveSpeed, Map Curve Speed on): mapd reports a curve's speed, without its distance, from the
     moment the curve is inside mapd's trigger distance (map_curve.go: jerk-limited distance at MAPD_ACCEL / MAPD_JERK
     plus MAPD_TIME_OFFSET seconds at the curve speed; the settings BogPilot writes, mapd_v2.settings_json). MapCurvePoint
     seeds the distance from that same rule when a new value appears and counts it down with the distance driven.
   Both use one lateral limit: a_lat = min(learned cornering limit, CurveMaxLatAccel).
2. One braking stage. For each point, the steady decel that reaches its speed (CURVE_LEAD_S + action_delay) before it:
   (v^2 - v_curve^2) / (2 * (d - v * (CURVE_LEAD_S + action_delay))). The strongest one is the request, so braking
   starts as soon as a curve is known, at the gentlest steady pull that makes it. It is capped so the car lands on the
   lowest curve speed ahead (landing cap: the speed shed during action_delay plus the release ramp must fit in the gap)
   and never asks for more than CurveMaxDecel.
3. One shaping (the Smooth Curve Braking behaviour, now the only one): braking starts as soon as the request passes
   START_DECEL (no debounce), ramps in at CurveOnsetJerk; while the car is still above the lowest curve speed ahead the
   held request may only ease at HOLD_LEAK (no brake / ease / brake); it releases at CurveReleaseJerk.
4. One output. a_curve (<= 0) is a single candidate for CurveArbiter, whose min() means it can only ever add braking.
   The cruise speed is NOT lowered for curves. Instead the positive cruise accel is capped at cruise_ceiling: the most
   accel that still keeps every point ahead reachable (0 while any point is slower than the car), so cruise never
   fights the curve braking and resumes on its own as the envelope clears. There is no exit hold: when the envelope
   ahead clears the request releases at CurveReleaseJerk, and an S-bend keeps limiting because its next curve is
   already in the envelope.

Identical under every Deceleration Profile (Standard, Eco, Eco+): the profile only sets the cruise candidate's floor in
get_cruise_accel; nothing here reads it. Panda safety is not touched. Units: m, m/s, m/s^2, m/s^3, s.
"""
from __future__ import annotations

import math

import numpy as np

from opendbc.car.tesla_ap1 import tesla_tuning as _tt   # Settings > Vehicle > Tesla Tuning (shipped value unless saved)

TESLA_CSC_MAX_LAT_ACCEL = _tt.get("CurveMaxLatAccel", 2.0)   # m/s^2, cap on the learned cornering limit
A_MIN = _tt.get("CurveMaxDecel", -1.2)                        # m/s^2, stays in the regen range (no friction thunk)
ONSET_JERK = _tt.get("CurveOnsetJerk", 1.5)                   # m/s^3
RELEASE_JERK = _tt.get("CurveReleaseJerk", 1.2)               # m/s^3
CURVE_LEAD_S = 0.5             # s, reach the curve speed this long (plus the actuator delay) before the point
START_DECEL = 0.15             # m/s^2, braking starts once the request is stronger than this (no debounce)
HOLD_LEAK = 0.3                # m/s^3, how fast held braking may ease while the car is still above the curve speed
MIN_NODE_SPEED = 5.0           # m/s, skip nodes the model plans to drive slower than this
MIN_CURVATURE = 1e-4           # 1/m, straighter than this never limits speed
MIN_DISTANCE = 5.0             # m, floor on the braking distance
DEFAULT_ACTION_DELAY = 0.35    # s, AP1 longitudinalActuatorDelay (Pre-AP 0.4 comes from CarParams)
MAX_ACTION_DELAY = 1.0         # s, same bound as the Actuator Delay row
DT_MIN, DT_MAX = 0.01, 0.2     # s, elapsed model time bounds (ap1_curve_arbitration.ModelClock)

# mapd v2 trigger rule for mapCurveSpeed (map_curve.go): the values mapd_v2.settings_json writes for every personality.
MAPD_ACCEL = 1.2               # m/s^2, target_speed_accel
MAPD_JERK = 0.6                # m/s^3, target_speed_jerk
MAPD_TIME_OFFSET = 10.0        # s, curve_target_speed_time_offset (mapd_v2.MAP_CURVE_TIME_OFFSET, test_mapd_v2 checks)
MAP_HORIZON_M = 500.0          # m, road mapd always has loaded ahead (mapd_v2.MAP_HORIZON_M, mapd MIN_WAY_DIST)
MAP_SPEED_STEP = 0.1           # m/s, a mapCurveSpeed change larger than this is a different curve (distance re-seeded)
MAP_SEED_MARGIN_S = 1.0        # s of travel taken off the seed: mapd checks its trigger once per GPS fix, with its own aEgo


def tesla_csc_lateral_accel(learned: float, cap: float = TESLA_CSC_MAX_LAT_ACCEL) -> float:
  """The one cornering limit: learned value with the Tesla cap applied (lower value wins)."""
  return min(float(learned), float(cap))


def _finite(x, fallback):
  try:
    x = float(x)
  except (TypeError, ValueError):
    return fallback
  return x if math.isfinite(x) else fallback


def _median3(a):
  """3-point running median along the path; the end nodes keep their own value."""
  if len(a) < 3:
    return a
  p = np.concatenate([a[:1], a, a[-1:]])
  return np.median(np.stack([p[:-2], p[1:-1], p[2:]]), axis=0)


def vision_curve_points(x_path, v_path, yaw_rate_path, t_path, a_lat):
  """(distance m, curve speed m/s) arrays for the model path nodes that limit speed (both empty when none do)."""
  try:
    x, v, yaw, t = (np.asarray(a, dtype=float) for a in (x_path, v_path, yaw_rate_path, t_path))
  except (TypeError, ValueError):
    return np.zeros(0), np.zeros(0)
  n = min(len(x), len(v), len(yaw), len(t))
  if n == 0 or not (math.isfinite(a_lat) and a_lat > 0.0):
    return np.zeros(0), np.zeros(0)
  x, v, yaw, t = x[:n], v[:n], yaw[:n], t[:n]
  usable = np.isfinite(x) & np.isfinite(v) & np.isfinite(yaw) & np.isfinite(t) & (v >= MIN_NODE_SPEED) & (t > 0.0)
  lat = np.where(usable, np.abs(np.where(usable, yaw * v, 0.0)), 0.0)
  lat = np.where(usable, _median3(lat), 0.0)
  k = lat / np.clip(np.where(usable, v, MIN_NODE_SPEED), MIN_NODE_SPEED, None) ** 2
  limit = usable & (k > MIN_CURVATURE)
  v_curve = np.sqrt(a_lat / np.where(limit, k, 1.0))
  return x[limit], v_curve[limit]


def jerk_limited_distance(v0: float, a0: float, v_target: float, a_max: float = MAPD_ACCEL, j_max: float = MAPD_JERK) -> float:
  """mapd v2 CalculateJerkLimitedDistance for slowing down (v_target < v0): jerk from a0 to -a_max, then constant
  -a_max until v_target (no final jerk phase, as in mapd). Distance in m, >= 0."""
  v0, a0, v_target = float(v0), float(a0), float(v_target)
  if not (math.isfinite(v0) and math.isfinite(a0) and math.isfinite(v_target)) or v_target >= v0:
    return 0.0
  a_t = -a_max
  j = j_max if a0 < a_t else -j_max
  t1 = abs((a_t - a0) / j) if abs(a_t - a0) >= 1e-3 else 0.0
  v1 = v0 + a0 * t1 + 0.5 * j * t1 * t1
  a1 = a_t
  if t1 > 0.0 and v1 <= v_target:
    disc = a0 * a0 - 2.0 * j * (v0 - v_target)
    if disc >= 0.0:
      roots = [r for r in ((-a0 + math.sqrt(disc)) / j, (-a0 - math.sqrt(disc)) / j) if r > 0.0]
      if roots:
        t1 = min(roots)
    v1, a1 = v_target, a0 + j * t1
  d1 = v0 * t1 + 0.5 * a0 * t1 * t1 + j * t1 ** 3 / 6.0
  d2 = 0.0
  if v1 - v_target > 1e-3 and abs(a1) > 1e-3:
    t2 = (v_target - v1) / a1
    d2 = v1 * t2 + 0.5 * a1 * t2 * t2
  return max(d1 + d2, 0.0)


def map_trigger_distance(v_ego: float, a_ego: float, v_map: float) -> float:
  """Distance (m) at which mapd v2 starts reporting a curve whose speed is v_map (at mapd's own lateral accel). Never
  more than the road mapd is sure to have loaded (MAP_HORIZON_M): a curve that only comes into the loaded map is
  reported there, and a shorter seed only brakes earlier."""
  return min(jerk_limited_distance(v_ego, a_ego, v_map) + MAPD_TIME_OFFSET * max(float(v_map), 0.0), MAP_HORIZON_M)


class MapCurvePoint:
  """Distance to the curve mapd reports. Seeded from mapd's trigger rule when a new value appears, then counted down
  with the distance driven (floored at 0: the curve is here). No value from mapd = no point."""

  def __init__(self):
    self.reset()

  def reset(self):
    self.speed = 0.0       # mapd's value this point was seeded for (m/s, mapd's lateral accel)
    self.distance = 0.0    # m

  def update(self, v_map_raw: float, v_ego: float, a_ego: float, dt: float) -> float | None:
    v_map_raw = _finite(v_map_raw, 0.0)
    if v_map_raw <= 0.0:
      self.reset()
      return None
    if self.speed <= 0.0 or v_map_raw < self.speed - MAP_SPEED_STEP:
      # New or slower: that curve has just come inside mapd's trigger distance, so it is at most that far (a little
      # closer by the time mapd notices: MAP_SEED_MARGIN_S).
      self.speed = v_map_raw
      self.distance = max(map_trigger_distance(v_ego, a_ego, v_map_raw) - max(float(v_ego), 0.0) * MAP_SEED_MARGIN_S, 0.0)
    elif v_map_raw > self.speed + MAP_SPEED_STEP:
      # Faster: the slower curve (or its tightest part) is behind the car and mapd now reports a curve it triggered
      # earlier, while the slower one hid it. How far it is is unknown (at most its trigger distance), so take it as here.
      self.speed, self.distance = v_map_raw, 0.0
    else:
      self.distance = max(self.distance - max(float(v_ego), 0.0) * dt, 0.0)
    return self.distance


def landing_decel(speed_gap: float, action_delay: float = DEFAULT_ACTION_DELAY, release_jerk: float = RELEASE_JERK) -> float:
  """Strongest decel (>= 0, m/s^2) that still lands the car on the curve speed when it is speed_gap above it: the speed
  shed during the actuator delay plus the release ramp (a * delay + a^2 / (2 * release_jerk)) must fit inside the gap."""
  g = float(speed_gap)
  if math.isnan(g):
    return 0.0
  if g == math.inf:
    return math.inf
  if g <= 0.0:
    return 0.0
  return release_jerk * (math.sqrt(action_delay ** 2 + 2.0 * g / release_jerk) - action_delay)


class CurveSpeedPlanner:
  """The curve candidate (a_curve <= 0) and the cruise accel ceiling, from the fused envelope."""

  def __init__(self):
    self.map_point = MapCurvePoint()
    self.reset()

  def reset(self):
    self.a_curve = 0.0                 # shaped request (<= 0), the planner candidate
    self.env = 0.0                     # held envelope before the onset / release ramps (<= 0)
    self.raw = 0.0                     # strongest kinematic request this tick (<= 0)
    self.v_limit = math.inf            # lowest curve speed ahead (m/s)
    self.landing_cap = 0.0             # m/s^2 (>= 0)
    self.cruise_ceiling = math.inf     # m/s^2, cap on positive cruise accel
    self.limiting = False              # the car is above the lowest curve speed ahead
    self.map_distance = None           # m to the mapd curve, None = none
    self.map_point.reset()

  @property
  def braking(self) -> bool:
    return self.a_curve < 0.0

  def update(self, v_ego, dt, a_lat, action_delay=DEFAULT_ACTION_DELAY, vision=None, map_speed=0.0, map_speed_raw=0.0,
             a_ego=0.0, active=True) -> float:
    """vision: (distance array, curve speed array) from vision_curve_points; map_speed: mapd curve speed rescaled to
    a_lat (0 = none), map_speed_raw: mapd's own value (for its trigger distance). Returns a_curve."""
    dt = float(np.clip(_finite(dt, DT_MAX), DT_MIN, DT_MAX))
    delay = float(np.clip(_finite(action_delay, DEFAULT_ACTION_DELAY), 0.0, MAX_ACTION_DELAY))
    v_ego = _finite(v_ego, math.nan)
    if not active or not math.isfinite(v_ego):
      self.map_point.reset()
      self.map_distance = None
      d, vc = np.zeros(0), np.zeros(0)
      v_ego = max(_finite(v_ego, 0.0), 0.0)
    else:
      v_ego = max(v_ego, 0.0)
      d, vc = vision if vision is not None else (np.zeros(0), np.zeros(0))
      d, vc = np.asarray(d, dtype=float), np.asarray(vc, dtype=float)
      map_speed = _finite(map_speed, 0.0)
      self.map_distance = self.map_point.update(map_speed_raw, v_ego, a_ego, dt) if map_speed > 0.0 else None
      if map_speed <= 0.0:
        self.map_point.reset()
      if self.map_distance is not None:
        d, vc = np.append(d, self.map_distance), np.append(vc, map_speed)

    if len(vc):
      d_eff = np.clip(d - v_ego * (CURVE_LEAD_S + delay), MIN_DISTANCE, None)
      margin = (vc ** 2 - v_ego ** 2) / (2.0 * d_eff)    # < 0: decel needed, > 0: accel still allowed
      self.v_limit = float(np.min(vc))
      self.raw = float(min(np.min(margin), 0.0))
      self.cruise_ceiling = float(max(np.min(margin), 0.0))
    else:
      self.v_limit, self.raw, self.cruise_ceiling = math.inf, 0.0, math.inf
    if not active:
      self.v_limit, self.raw, self.cruise_ceiling = math.inf, 0.0, math.inf

    gap = v_ego - self.v_limit if math.isfinite(self.v_limit) else -math.inf
    self.landing_cap = landing_decel(gap, delay)
    self.limiting = self.landing_cap > 0.0

    e = max(self.raw, A_MIN, -self.landing_cap)
    if e > -START_DECEL:
      e = 0.0
    if self.limiting:
      env = min(e, self.env + HOLD_LEAK * dt)      # hold: ease only slowly while the car is above the curve speed
    else:
      env = e if e < self.env else min(0.0, self.env + RELEASE_JERK * dt)
    self.env = max(env, -self.landing_cap, A_MIN)

    if self.env < self.a_curve:
      self.a_curve = max(self.env, self.a_curve - ONSET_JERK * dt)
    else:
      self.a_curve = min(self.env, self.a_curve + RELEASE_JERK * dt)
    return self.a_curve


def curve_speed_planner_for(CP, pedal_ok: bool | None = None):
  """CurveSpeedPlanner where CSC is supported (csc_platform.csc_supported: AP1 with openpilot longitudinal, or Pre-AP
  with openpilot longitudinal and a calibrated pedal). None for every other car, stock ACC and no-pedal Pre-AP."""
  from openpilot.selfdrive.controls.lib.csc_platform import csc_supported
  return CurveSpeedPlanner() if csc_supported(CP, pedal_ok) else None
