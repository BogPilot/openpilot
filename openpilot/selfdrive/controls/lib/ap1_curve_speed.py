"""AP1 / Pre-AP curve speed control for the 0.11.2 C3X planner (regular and Experimental mode alike).

Wires the curve speed planner (curve_speed_planner.py: one fused vision + map envelope, one braking stage, one shaping)
into LongitudinalPlanner, keeps BogPilot's CSC learning (bogpilot_csc.py) and fills the bogpilotPlan CSC fields the
cluster's CSC MAX slot and the IC set digit read.

Authority (can only slow the car down, only for curves):
  * the curve request a_curve (<= 0, CurveMaxDecel floor, jerk limited) is one more min() candidate in CurveArbiter;
    the lead MPC, cruise and Experimental (e2e) candidates are untouched, so lead following is never weakened
  * the cruise speed is not lowered for curves; cap_cruise_accel() only limits POSITIVE cruise accel to the planner's
    cruise_ceiling while a curve is ahead, so cruise never accelerates against the curve braking
  * the existing reactive turn limit in get_cruise_accel and the ACCEL_MIN/MAX clip stay as they are
  * no exit hold and no no-raise latch: when the envelope ahead clears the request releases at CurveReleaseJerk

Active only where csc_platform.csc_supported allows it (TESLA_AP1_MODELS / TESLA_AP1_MODELX with openpilot longitudinal,
or TESLA_PREAP_MODELS with openpilot longitudinal and a calibrated Comma Pedal) and CurveSpeedController is on. On Pre-AP
it controls speed only while the pedal is live and the pull FSM is in FULL (csc_platform.csc_gate); in steering only it
never brakes, but may still learn (training). Control also needs: engaged, no state reset, above CRUISING_SPEED, no
blinker or model lane change. Everything fails closed: stock ACC, other cars, no-pedal Pre-AP, toggle off, a stale /
invalid modelV2 or carState, short or non-finite model arrays, or a non-finite speed release the curve request (at the
release jerk; a state reset drops it at once) and publish bogpilotPlan.cscActive = False so the UI blanks.

Map Curve Speed (CSCMapCurvature, mapd v2 only): mapd v2's mapCurveSpeed, rescaled from mapd's 2.0 m/s^2 to the one
lateral limit (never up) and floored at CRUISING_SPEED, is a point of the same envelope as the vision nodes, so a curve
only the map knows about brakes the same way (no vision gate). Only with a fresh mapdOut (<= 0.5 s). Toggle off (or
mapd v1): nothing is read.

CurveDetector and RoadCurvatureFilter remain for the HUD (cscControllingSpeed, roadCurvature) only; the braking never
reads them. ShowCSCStatus is display only and is read by the UI, never here.

Units: speeds m/s, road curvature 1/m (signed, daily sign convention), accelerations m/s^2.
"""
from __future__ import annotations

import math

from openpilot.cereal import log

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.ap1_curve_arbitration import ModelClock
from openpilot.selfdrive.controls.lib.curve_speed_planner import (DEFAULT_ACTION_DELAY, ONSET_JERK, RELEASE_JERK,
                                                                  TESLA_CSC_MAX_LAT_ACCEL, curve_speed_planner_for,
                                                                  vision_curve_points)
from openpilot.selfdrive.controls.lib.bogpilot_csc import (CRUISING_SPEED, MINIMUM_LATERAL_ACCELERATION, CurveSpeedController,
                                                           CurveDetector, RoadCurvatureFilter, TrackingLead)
from openpilot.selfdrive.controls.lib.csc_platform import csc_gate, csc_supported, is_preap

AP1 = "TESLA_AP1_MODELS"
TOGGLE = "CurveSpeedController"
TOGGLE_CACHE_S = 1.0
MAP_TOGGLE = "CSCMapCurvature"
MAP_ENGINE = "MapdV2"


def _service_ok(sm, name) -> bool:
  """alive and valid on a real SubMaster (or a test double with the same dicts). A plain dict fails closed."""
  try:
    return bool(sm.alive[name]) and bool(sm.valid[name])
  except (AttributeError, KeyError, TypeError):
    return False


def _finite_list(values, n):
  try:
    out = [float(v) for v in values]
  except (TypeError, ValueError):
    return None
  if len(out) != n or not all(math.isfinite(v) for v in out):
    return None
  return out


def model_path(model):
  """(t, x, v, yaw_rate, yaw_t) lists of IDX_N finite values from modelV2, or None."""
  n = ModelConstants.IDX_N
  try:
    x = _finite_list(model.position.x, n)
    v = _finite_list(model.velocity.x, n)
    yaw = _finite_list(model.orientationRate.z, n)
    yaw_t = _finite_list(model.orientationRate.t, n)
  except AttributeError:
    return None
  if x is None or v is None or yaw is None or yaw_t is None:
    return None
  return list(ModelConstants.T_IDXS[:n]), x, v, yaw, yaw_t


class Ap1CurveSpeed:
  def __init__(self, CP, dt: float = DT_MDL, store=None, pedal_ok: bool | None = None):
    self.available = csc_supported(CP, pedal_ok)
    self.preap = self.available and is_preap(CP)
    self.dt = dt
    self.default_delay = float(getattr(CP, "longitudinalActuatorDelay", DEFAULT_ACTION_DELAY) or DEFAULT_ACTION_DELAY)
    self.planner = curve_speed_planner_for(CP, pedal_ok=True if self.preap else None) if self.available else None
    if self.available and store is None:
      from openpilot.common.bogpilot_store import ParamStore
      store = ParamStore(cache_ttl=TOGGLE_CACHE_S)
    self.store = store if self.available else None
    self.csc = CurveSpeedController(self.store, TESLA_CSC_MAX_LAT_ACCEL) if self.available else None
    self.tracking_lead = TrackingLead(dt)
    self.curvature_filter = RoadCurvatureFilter()   # HUD roadCurvature + learning sample only
    self.detector = CurveDetector()                 # HUD cscControllingSpeed only
    self.clock = ModelClock(dt)   # elapsed model time between updates (asynchronous publication)

    self.enabled_toggle = False
    self.valid = False            # bogpilotPlan.cscActive: CSC is available, on and has fresh inputs
    self.controlling = False      # bogpilotPlan.cscControllingSpeed
    self.training = False         # bogpilotPlan.cscTraining
    self.target = 0.0             # bogpilotPlan.cscSpeed (m/s): lowest curve speed ahead while controlling
    self.road_curvature = 0.0     # bogpilotPlan.roadCurvature (1/m)
    self.v_cruise_out = 0.0       # bogpilotPlan.vCruise (m/s): display set speed (cruise, or the curve speed while controlling)
    self.a_curve = 0.0            # curve request (<= 0, m/s^2), the planner candidate
    self.cruise_ceiling = math.inf  # m/s^2, cap on positive cruise accel while controlling
    self._cap_prev = 0.0            # last cruise accel handed back (the cap eases accel off, never steps it down)
    self.curve_ahead = False        # a curve slower than the set speed is in the envelope (positive accel rises gently)
    self._rising = False            # the rise limit is still catching up after the curve left the envelope
    self._dt_s = dt
    self.map_cap = 0.0            # Map Curve Speed point speed used this tick (m/s), 0 = none
    self._map_tick = None         # mapd_v2.SharedTick, created on first use with the toggle on
    self._parked = None           # last carState gear was Park (the learned curve data is flushed on the edge into Park)

  @property
  def a_brake(self) -> float:
    """Former name of the curve request, kept for readers and logs."""
    return self.a_curve

  def _map_on(self) -> bool:
    try:
      return bool(self.store.toggle_bool(MAP_TOGGLE)) and bool(self.store.get_bool(MAP_ENGINE))
    except Exception:
      return False

  def _map_curve_speed(self) -> float:
    try:
      if self._map_tick is None:
        from openpilot.system.bogpilot.osm.mapd_v2 import SharedTick
        self._map_tick = SharedTick()
      d = self._map_tick.get()
      return float(d.curve_speed) if d.fresh else 0.0
    except Exception:
      return 0.0

  def _map_point(self, allowed: bool, lat: float) -> tuple[float, float]:
    """(rescaled map curve speed, mapd's own value); (0, 0) = none. Any problem = none."""
    if not allowed or not self._map_on():
      if self.planner is not None:
        self.planner.map_point.reset()   # Map Curve Speed off: no point is kept through a gap
      return 0.0, 0.0
    try:
      from openpilot.system.bogpilot.osm.mapd_v2 import map_curve_cap
      raw = self._map_curve_speed()
      cap = map_curve_cap(raw, lat)
    except Exception:
      return 0.0, 0.0
    if not (cap > 0.0 and math.isfinite(cap)):
      return 0.0, 0.0
    return max(cap, float(CRUISING_SPEED)), raw

  def _toggle_on(self) -> bool:
    try:
      return bool(self.store.toggle_bool(TOGGLE))
    except Exception:
      return False

  def _release(self, reset_state: bool, dt_s: float) -> None:
    if self.planner is None:
      self.a_curve = 0.0
    elif reset_state:
      self.planner.reset()
      self.a_curve = 0.0
    else:
      # No new braking without fresh inputs: the request only releases (release jerk) to 0.
      self.a_curve = self.planner.update(0.0, dt_s, 0.0, active=False)
    self.cruise_ceiling = math.inf
    self.curve_ahead = False
    if reset_state:
      self._rising = False
    self.map_cap = 0.0

  def _inactive(self, v_cruise, reset_state, dt_s=None):
    self.curvature_filter.reset()
    self.detector.reset()
    if self.csc is not None:
      if self.csc.training_timer > 0:
        self.csc.log_data(0.0, False, False, False, False, 0.0, 0.0)  # ends (and saves) a training segment
      self.csc.enable_training = False
    self.valid = False
    self.controlling = False
    self.training = False
    self.target = v_cruise
    self.road_curvature = 0.0
    self.v_cruise_out = v_cruise
    self._release(reset_state, self.dt if dt_s is None else dt_s)
    return v_cruise

  def cap_cruise_accel(self, a_cruise: float, a_prev: float | None = None) -> float:
    """Positive cruise accel capped for a curve ahead. Braking is never touched.

    * Kinematic ceiling: no more accel than keeps every curve point reachable (planner cruise_ceiling). When the ceiling
      drops (a curve node comes into view) the cap eases accel off at CurveOnsetJerk instead of stepping it down.
    * Rise limit: while a curve slower than the set speed is in the envelope, positive accel may only rise above the
      previous plan output (a_prev, from 0 when it was braking) at CurveReleaseJerk. Without it a candidate switch in a
      curve (Experimental mode off, a lead MPC plan giving way to cruise) steps the plan from a gentle e2e / lead accel
      straight to a saturated cruise accel. Once the curve leaves the envelope the limit keeps ramping until it has
      caught up, so the exit is a jerk limited ramp, never a step and never a hold.
    Any speed the cap lets through is braked by the curve request."""
    out = a_cruise
    if a_cruise > 0.0:
      limit = math.inf
      if math.isfinite(self.cruise_ceiling) and a_cruise > self.cruise_ceiling:
        limit = max(self.cruise_ceiling, 0.0, self._cap_prev - ONSET_JERK * self._dt_s)
      try:
        prev = float(a_prev) if a_prev is not None else math.nan
      except (TypeError, ValueError):
        prev = math.nan
      if (self.curve_ahead or self._rising) and math.isfinite(prev):
        limit = min(limit, max(prev, 0.0) + RELEASE_JERK * self._dt_s)
      out = min(a_cruise, limit)
    self._rising = bool(a_cruise > 0.0 and out < a_cruise - 1e-9 and (self.curve_ahead or self._rising))
    self._cap_prev = out
    return out

  def _flush_on_park(self, sm) -> None:
    """plannerd stops at offroad, so unsaved curve samples are also saved on the edge into Park."""
    if self.csc is None:
      return
    try:
      from opendbc.car.structs import car
      parked = bool(sm['carState'].gearShifter == car.CarState.GearShifter.park)
    except Exception:
      return
    if parked and self._parked is False:
      self.csc.flush()
    self._parked = bool(parked)

  def update(self, sm, v_ego, v_cruise, reset_state, action_delay=None) -> float:
    """Returns the cruise speed for the cruise candidate: always v_cruise (curves no longer lower it)."""
    if not self.available:
      return self._inactive(v_cruise, reset_state)
    self._flush_on_park(sm)

    dt_s = self.clock.step(sm)
    self._dt_s = self.dt if dt_s is None else dt_s
    self.enabled_toggle = self._toggle_on()
    path = model_path(sm['modelV2']) if _service_ok(sm, 'modelV2') else None
    fresh = path is not None and _service_ok(sm, 'carState') and math.isfinite(v_ego) and math.isfinite(v_cruise)
    if not self.enabled_toggle or not fresh:
      return self._inactive(v_cruise, reset_state, dt_s)

    t, x, v, yaw, yaw_t = path
    CS = sm['carState']
    # Pre-AP: no live pedal on its latched bus = inactive (fail closed). Outside FULL (steering only) never brake.
    active, speed_control_ok = csc_gate(self.preap, CS)
    if not active:
      return self._inactive(v_cruise, reset_state, dt_s)
    # The model may continue a lane change after the stalk signal is released.
    try:
      lane_change = sm["modelV2"].meta.laneChangeState != log.LaneChangeState.off
    except AttributeError:
      return self._inactive(v_cruise, reset_state, dt_s)
    blinker = bool(CS.leftBlinker or CS.rightBlinker or lane_change)
    v_ego = max(float(v_ego), 0.0)
    try:
      a_ego = float(CS.aEgo)
    except (AttributeError, TypeError, ValueError):
      a_ego = 0.0
    a_ego = a_ego if math.isfinite(a_ego) else 0.0

    lat = self.csc.effective_lateral_acceleration()   # min(learned, CurveMaxLatAccel): the one cornering limit

    # HUD and learning only (the braking below never reads these).
    self.road_curvature, _ = self.curvature_filter.update(yaw, v, yaw_t, dt_s)
    hud_limiting = (math.isfinite(self.road_curvature) and self.road_curvature != 0.0 and
                    (lat / abs(self.road_curvature)) ** 0.5 < v_ego)
    detected = self.detector.update(self.road_curvature, v_ego, blinker, hud_limiting, dt_s)

    lead = sm['radarState'].leadOne
    tracking_lead = self.tracking_lead.update(bool(lead.present), float(lead.dRel), float(lead.vRel), x[-1], bool(CS.standstill))

    enabled = bool(sm['selfdriveState'].enabled)
    try:
      meas_curv = float(sm['controlsState'].curvature)
    except (KeyError, AttributeError, TypeError):
      meas_curv = float('nan')
    lateral_acceleration = v_ego ** 2 * meas_curv if math.isfinite(meas_curv) else float('nan')
    driving_in_curve = math.isfinite(lateral_acceleration) and abs(lateral_acceleration) >= MINIMUM_LATERAL_ACCELERATION

    control = speed_control_ok and enabled and (not reset_state) and (v_ego > CRUISING_SPEED) and (not blinker)
    if reset_state:
      self._release(True, dt_s)
    elif not control:
      self._release(False, dt_s)
    else:
      try:
        delay = self.default_delay if action_delay is None else float(action_delay)
      except (TypeError, ValueError):
        delay = self.default_delay
      delay = delay if math.isfinite(delay) else self.default_delay
      map_speed, map_raw = self._map_point(True, lat)
      self.map_cap = map_speed
      self.a_curve = self.planner.update(v_ego, dt_s, lat, delay, vision=vision_curve_points(x, v, yaw, yaw_t, lat),
                                         map_speed=map_speed, map_speed_raw=map_raw, a_ego=a_ego, active=True)
      self.cruise_ceiling = self.planner.cruise_ceiling

    v_limit = self.planner.v_limit if self.planner is not None else math.inf
    self.curve_ahead = bool(control and math.isfinite(v_limit) and v_limit < v_cruise)
    self.controlling = bool(control and (self.a_curve < 0.0 or self.planner.limiting or detected))
    if self.controlling:
      self.target = min(v_limit, v_cruise) if math.isfinite(v_limit) else v_cruise
      self.v_cruise_out = min(self.target, v_cruise)   # IC set digit follows the curve speed (display only)
    else:
      self.csc.log_data(v_ego, tracking_lead, bool(sm['carControl'].longActive), driving_in_curve, blinker,
                        lateral_acceleration, self.road_curvature)
      if not (enabled and not reset_state):
        self.detector.reset()   # not engaged / state reset: the next curve is a fresh activation
      self.target = v_cruise
      self.v_cruise_out = v_cruise
      if not control:
        self.cruise_ceiling = math.inf
    self.training = bool(self.csc.enable_training)
    self.valid = True
    return v_cruise

  def fill(self, plan) -> None:
    """bogpilotPlan CSC fields (m/s, 1/m). cscActive is the CSC-specific validity (CSC available, on, fresh inputs).
    The message valid bit also covers speed limit control, CEM and force stop, so readers must use cscActive."""
    plan.cscActive = bool(self.valid)
    plan.cscControllingSpeed = bool(self.controlling)
    plan.cscSpeed = float(self.target) if math.isfinite(self.target) else 0.0
    plan.cscTraining = bool(self.training)
    plan.roadCurvature = float(self.road_curvature) if math.isfinite(self.road_curvature) else 0.0
    plan.vCruise = float(self.v_cruise_out) if math.isfinite(self.v_cruise_out) else 0.0
    plan.trackingLead = bool(self.tracking_lead.tracking)
