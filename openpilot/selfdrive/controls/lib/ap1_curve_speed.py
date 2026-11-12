"""AP1 curve speed control for the 0.11.2 C3X planner (regular and Experimental mode alike).

Wires BogPilot's daily CSC (bogpilot_csc.py: target from road geometry + the learned cornering limit)
and the AP1 look-ahead curve brake (ap1_curve_brake.py) into LongitudinalPlanner, and fills the
bogpilotPlan CSC fields the cluster's CSC MAX slot reads.

Authority (can only slow the car down, only for curves):
  * the CSC target only ever lowers the cruise speed: v_cruise_out = min(csc_target, v_cruise)
    (daily bogpilot_vcruise merge); the driver's set speed is never raised
  * the curve brake is an extra min() candidate (<= 0, -1.2 m/s^2 floor, jerk limited); the lead MPC,
    cruise and Experimental (e2e) candidates are untouched, so lead following is never weakened
  * the existing reactive turn limit in get_cruise_accel and the ACCEL_MIN/MAX clip stay as they are

Active only for TESLA_AP1_MODELS with openpilot longitudinal and CurveSpeedController on (367e1fe
tuning-level rule via ParamStore). Everything fails closed: stock ACC, other cars, toggle off, a
stale / invalid modelV2 or carState, short or non-finite model arrays, or a non-finite speed leave
the cruise speed alone, release the curve brake and publish bogpilotPlan.valid = False so the UI
blanks. ShowCSCStatus is display only and is read by the UI, never here.

Units: speeds m/s, road curvature 1/m (signed, daily sign convention), accelerations m/s^2.
"""
from __future__ import annotations

import math

from openpilot.cereal import log

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.ap1_curve_arbitration import ModelClock
from openpilot.selfdrive.controls.lib.ap1_curve_brake import TESLA_CSC_MAX_LAT_ACCEL, ap1_curve_brake_for
from openpilot.selfdrive.controls.lib.bogpilot_csc import (CRUISING_SPEED, MINIMUM_LATERAL_ACCELERATION, CurveSpeedController,
                                                           CurveDetector, RoadCurvatureFilter, TrackingLead)

AP1 = "TESLA_AP1_MODELS"
TOGGLE = "CurveSpeedController"
TOGGLE_CACHE_S = 1.0
# Keep the last CSC cap this long after the curve is no longer detected / in-curve,
# so vCruise does not snap back to the SLC cap mid-curve.
CSC_HOLD_S = 2.0


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
  def __init__(self, CP, dt: float = DT_MDL, store=None):
    self.available = str(CP.carFingerprint) == AP1 and bool(CP.openpilotLongitudinalControl)
    self.dt = dt
    self.brake = ap1_curve_brake_for(CP, dt) if self.available else None
    if self.available and store is None:
      from openpilot.common.bogpilot_store import ParamStore
      store = ParamStore(cache_ttl=TOGGLE_CACHE_S)
    self.store = store if self.available else None
    self.csc = CurveSpeedController(self.store, TESLA_CSC_MAX_LAT_ACCEL) if self.available else None
    self.tracking_lead = TrackingLead(dt)
    self.curvature_filter = RoadCurvatureFilter()
    self.detector = CurveDetector()
    self.clock = ModelClock(dt)   # elapsed model time between updates (asynchronous publication)

    self.enabled_toggle = False
    self.valid = False            # bogpilotPlan.valid: CSC is available, on and has fresh inputs
    self.controlling = False      # bogpilotPlan.cscControllingSpeed
    self._hold_s = 0.0            # seconds since the curve last looked active, while still holding the cap
    self.training = False         # bogpilotPlan.cscTraining
    self.target = 0.0             # bogpilotPlan.cscSpeed (m/s)
    self.road_curvature = 0.0     # bogpilotPlan.roadCurvature (1/m)
    self.v_cruise_out = 0.0       # bogpilotPlan.vCruise (m/s), after the CSC cap
    self.a_brake = 0.0            # curve brake request (<= 0, m/s^2)

  def _toggle_on(self) -> bool:
    try:
      return bool(self.store.toggle_bool(TOGGLE))
    except Exception:
      return False

  def _inactive(self, v_cruise, reset_state):
    self.curvature_filter.reset()
    self.detector.reset()
    if self.csc is not None:
      self.csc.target_set = False
      if self.csc.training_timer > 0:
        self.csc.log_data(0.0, False, False, False, False, 0.0, 0.0)  # ends (and saves) a training segment
      self.csc.enable_training = False
    self.valid = False
    self.controlling = False
    self._hold_s = 0.0
    self.training = False
    self.target = v_cruise
    self.road_curvature = 0.0
    self.v_cruise_out = v_cruise
    if self.brake is not None:
      if reset_state:
        self.brake.reset()
        self.a_brake = 0.0
      else:
        # No new braking without fresh inputs: the request only decays (release jerk) to 0.
        self.a_brake = self.brake.update(False, 0.0, [], [], [], [])
    else:
      self.a_brake = 0.0
    return v_cruise

  def update(self, sm, v_ego, v_cruise, reset_state) -> float:
    """Returns the cruise speed (m/s) for the cruise candidate, never above v_cruise."""
    if not self.available:
      return self._inactive(v_cruise, reset_state)

    dt_s = self.clock.step(sm)
    self.enabled_toggle = self._toggle_on()
    path = model_path(sm['modelV2']) if _service_ok(sm, 'modelV2') else None
    fresh = path is not None and _service_ok(sm, 'carState') and math.isfinite(v_ego) and math.isfinite(v_cruise)
    if not self.enabled_toggle or not fresh:
      return self._inactive(v_cruise, reset_state)

    t, x, v, yaw, yaw_t = path
    CS = sm['carState']
    # The model may continue a lane change after the stalk signal is released.
    # Use the existing blinker cancellation/release path; do not change tuning.
    try:
      lane_change = sm["modelV2"].meta.laneChangeState != log.LaneChangeState.off
    except AttributeError:
      return self._inactive(v_cruise, reset_state)
    blinker = bool(CS.leftBlinker or CS.rightBlinker or lane_change)
    v_ego = max(float(v_ego), 0.0)

    self.road_curvature, time_to_curve = self.curvature_filter.update(yaw, v, yaw_t, dt_s)
    # limiting: the curve speed (learned cornering limit, Tesla cap applied) is already below the car's speed
    limiting = (math.isfinite(self.road_curvature) and self.road_curvature != 0.0 and
                (self.csc.effective_lateral_acceleration() / abs(self.road_curvature)) ** 0.5 < v_ego)
    detected = self.detector.update(self.road_curvature, v_ego, blinker, limiting, dt_s)

    lead = sm['radarState'].leadOne
    present = bool(lead.present)
    tracking_lead = self.tracking_lead.update(present, float(lead.dRel), float(lead.vRel), x[-1], bool(CS.standstill))

    enabled = bool(sm['selfdriveState'].enabled)
    try:
      meas_curv = float(sm['controlsState'].curvature)
    except (KeyError, AttributeError, TypeError):
      meas_curv = float('nan')
    lateral_acceleration = v_ego ** 2 * meas_curv if math.isfinite(meas_curv) else float('nan')
    driving_in_curve = math.isfinite(lateral_acceleration) and abs(lateral_acceleration) >= MINIMUM_LATERAL_ACCELERATION
    # Blinker still suspends CSC (existing behaviour). Otherwise keep or start the cap while the
    # curve is active, and hold the last target for CSC_HOLD_S after it goes quiet so the plan
    # never jumps back to the SLC cap mid-curve.
    in_curve = (not blinker) and (detected or driving_in_curve or limiting)
    keep = enabled and (not reset_state) and (v_ego > CRUISING_SPEED) and (not blinker) and (
        detected or in_curve or (self.controlling and self._hold_s < CSC_HOLD_S))
    if keep:
      if detected or limiting or (in_curve and not self.controlling):
        previous = self.target if self.controlling else None
        self.csc.update_target(v_ego, self.road_curvature, time_to_curve, v_cruise, dt_s)
        # Already capping: do not raise as filtered curvature drops mid-curve.
        if previous is not None and self.csc.target > previous:
          self.csc.target = previous
        self.target = self.csc.target
      if in_curve or detected:
        self._hold_s = 0.0
      else:
        self._hold_s += dt_s
      self.controlling = True
    else:
      if not (enabled and not reset_state):
        self.detector.reset()   # not engaged / state reset: the next curve is a fresh activation
      self.csc.log_data(v_ego, tracking_lead, bool(sm['carControl'].longActive), driving_in_curve, blinker,
                        lateral_acceleration, self.road_curvature)
      self.controlling = False
      self._hold_s = 0.0
      self.csc.target_set = False
      self.target = v_cruise
    self.training = bool(self.csc.enable_training)

    # Daily merge: a target below CRUISING_SPEED never applies; the result is never above v_cruise.
    self.v_cruise_out = min(self.target, v_cruise) if self.target >= CRUISING_SPEED else v_cruise

    if reset_state:
      self.brake.reset()
      self.a_brake = 0.0
    else:
      self.a_brake = self.brake.update(self.controlling, v_ego, t, x, v, yaw)
    self.valid = True
    return self.v_cruise_out

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
