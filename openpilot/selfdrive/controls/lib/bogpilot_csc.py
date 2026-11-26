"""BogPilot Curve Speed Controller (CSC) core for the 0.11.2 C3X planner.

Derived from BogPilot daily (bogpilot-tesla@04d560f3e), which carries FrogPilot 0.9.7 code by FrogAi
under this repository's MIT license (see LICENSE):
  bogpilot/controls/lib/curve_speed_controller.py   "FrogsGoMoo's Curve Speed Controller" (learning
                                                     and target), plus BogPilot's Tesla cap hook
  bogpilot/common/bogpilot_utilities.py            calculate_road_curvature() (credited there to Pfeiferj)
  bogpilot/controls/bogpilot_planner.py            road_curvature_detected, driving_in_curve and the
                                                     tracked-lead check used to gate learning
  bogpilot/common/bogpilot_variables.py            CRUISING_SPEED, DEFAULT/MINIMUM_LATERAL_ACCELERATION,
                                                     PLANNER_TIME, THRESHOLD

Behaviour and every number are unchanged from that source. Not ported: the weather reduction (C3X has
no weather source) and the speed limit controller. Changes for C3X: the Params store is injected,
stored learning data is validated before use, and CurvatureData, CalibrationProgress and
CalibratedLateralAcceleration are saved together at most every 60 s after a new sample (plus once on
the edge into Park) instead of after every training window.

The road curvature (1/m) comes from the model's path geometry: lateral acceleration along the path
(yaw rate * node speed) divided by node speed squared, i.e. yaw rate / speed. The model's own speed
choice is never a target; the CSC target is sqrt(cornering limit / curvature).
"""
from __future__ import annotations

import json
import math
import time

import numpy as np

from openpilot.common.bogpilot_checkpoint import LEARNED_INTERVAL_S, Checkpoint
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import STOP_DISTANCE
from openpilot.selfdrive.modeld.constants import ModelConstants

CRUISING_SPEED = 5                        # m/s, roughly the speed cars go when not touching the gas while in drive
DEFAULT_LATERAL_ACCELERATION = 2.0        # m/s^2, typical lateral acceleration when taking curves
MINIMUM_LATERAL_ACCELERATION = 1.3        # m/s^2, typical minimum lateral acceleration when taking curves
PLANNER_TIME = ModelConstants.T_IDXS[-1]  # s, length of time the model projects out for
THRESHOLD = 0.63                          # requires the condition to be true for ~1 second

CALIBRATION_PROGRESS_THRESHOLD = 10 / DT_MDL
MAX_CURVATURE = 0.1
MIN_CURVATURE = 0.001
PERCENTILE = 90
ROUNDING_PRECISION = 5
STEP = 0.001


def calculate_road_curvature(orientation_rate_z, velocity_x, timebase):
  """(signed road curvature 1/m, time to the curve s) at the path node with the most lateral accel."""
  orientation_rate = np.asarray(orientation_rate_z, dtype=float)
  velocity = np.asarray(velocity_x, dtype=float)
  t = np.asarray(timebase, dtype=float)

  lateral_acceleration = orientation_rate * velocity
  index = int(np.argmax(np.abs(lateral_acceleration)))
  predicted_lateral_acc = float(lateral_acceleration[index])
  time_to_curve = float(t[index])

  return float(predicted_lateral_acc / max(velocity[index], 1) ** 2), max(time_to_curve, 1)


def _median3(a):
  """3-point running median along the path; the end nodes keep their own value (a real peak on the last node is never lowered)."""
  p = np.concatenate([a[:1], a, a[-1:]])
  return np.median(np.stack([p[:-2], p[1:-1], p[2:]]), axis=0)


class RoadCurvatureFilter:
  """calculate_road_curvature() with the sensor noise taken out, for the CSC.

  The raw estimate is the curvature at the path node with the largest lateral acceleration. Two things make it noisy:
  a single node can spike (the argmax jumps onto it), and the argmax hops between two nodes of nearly equal lateral
  acceleration. Here
    * lateral acceleration is median filtered across 3 neighbouring nodes before the argmax (a one-node spike never wins,
      a real curve spans several nodes and passes unchanged),
    * the argmax node only changes when another node is more than NODE_SWITCH_RATIO above the held node,
    * nodes the model plans to drive slower than MIN_NODE_SPEED are ignored (yaw rate / speed near a stop is a false curve),
    * |curvature| is filtered asymmetrically: a rise is taken immediately (entry is never late), a fall decays with
      RELEASE_TAU seconds of elapsed time.
  Everything fails closed to the unfiltered formula's value of 0 (no curve) when no node qualifies.
  """
  NODE_SWITCH_RATIO = 1.10
  MIN_NODE_SPEED = CRUISING_SPEED    # m/s
  RELEASE_TAU = 0.5                  # s

  def __init__(self):
    self.reset()

  def reset(self):
    self.index = None
    self.magnitude = 0.0

  def update(self, orientation_rate_z, velocity_x, timebase, dt: float = DT_MDL):
    """(signed road curvature 1/m, time to the curve s) -- same contract as calculate_road_curvature()."""
    orientation_rate = np.asarray(orientation_rate_z, dtype=float)
    velocity = np.asarray(velocity_x, dtype=float)
    t = np.asarray(timebase, dtype=float)

    lateral_acceleration = orientation_rate * velocity
    usable = (velocity >= self.MIN_NODE_SPEED) & (t > 0.0) & np.isfinite(lateral_acceleration)
    magnitude = _median3(np.abs(np.where(usable, lateral_acceleration, 0.0)))
    magnitude = np.where(usable, magnitude, 0.0)
    best = int(np.argmax(magnitude))
    if self.index is not None and self.index < len(magnitude) and magnitude[best] <= magnitude[self.index] * self.NODE_SWITCH_RATIO:
      best = self.index
    self.index = best

    if magnitude[best] <= 0.0:
      curvature, time_to_curve = 0.0, 1.0
      self.magnitude = 0.0
    else:
      raw = magnitude[best] / max(velocity[best], 1) ** 2
      if raw >= self.magnitude:
        self.magnitude = float(raw)
      else:
        self.magnitude += (float(raw) - self.magnitude) * (1.0 - math.exp(-max(dt, 0.0) / self.RELEASE_TAU))
      curvature = math.copysign(self.magnitude, float(lateral_acceleration[best]))
      time_to_curve = max(float(t[best]), 1)
    return float(curvature), time_to_curve


def road_curvature_detected(road_curvature: float, v_ego: float, blinker: bool) -> bool:
  """Daily: (1 / |k|) ** 0.5 < v_ego > CRUISING_SPEED and no blinker. A straight path never detects."""
  if not math.isfinite(road_curvature) or road_curvature == 0.0:
    return False
  return (1 / abs(road_curvature)) ** 0.5 < v_ego > CRUISING_SPEED and not blinker


class CurveDetector:
  """road_curvature_detected() with hysteresis and an entry debounce, so a path that hovers at the detection threshold does
  not flip the CSC on and off.

  Detection is v_ego^2 * |k| > 1 (the daily rule). Once a curve is being controlled it is only released after
  v_ego^2 * |k| has been below EXIT_RATIO for EXIT_HOLD_S seconds of elapsed time (a blinker or lane change releases at once,
  as before). A new activation must hold ENTRY_DEBOUNCE_S before it starts, EXCEPT when the curve already limits the car
  (the curve speed is below v_ego): that starts immediately, so braking for a real curve is never delayed."""
  EXIT_RATIO = 0.8
  EXIT_HOLD_S = 0.5
  ENTRY_DEBOUNCE_S = 0.25

  def __init__(self):
    self.reset()

  def reset(self):
    self.active = False
    self.entry_time = 0.0
    self.exit_time = 0.0

  def update(self, road_curvature: float, v_ego: float, blinker: bool, limiting: bool, dt: float) -> bool:
    raw = road_curvature_detected(road_curvature, v_ego, blinker)
    ratio = v_ego * v_ego * abs(road_curvature) if math.isfinite(road_curvature) else 0.0
    if blinker or not math.isfinite(road_curvature) or road_curvature == 0.0 or v_ego <= CRUISING_SPEED:
      self.reset()
      return False
    if self.active:
      self.exit_time = self.exit_time + dt if ratio < self.EXIT_RATIO else 0.0
      if self.exit_time >= self.EXIT_HOLD_S - 1e-9:
        self.reset()
      return self.active
    if not raw:
      self.entry_time = 0.0
      return False
    self.entry_time += dt
    if limiting or self.entry_time >= self.ENTRY_DEBOUNCE_S - 1e-9:
      self.active, self.exit_time = True, 0.0
    return self.active


def load_curvature_data(text) -> dict:
  """CurvatureData json -> {key: {"average": float, "count": int}}; malformed entries are dropped."""
  try:
    raw = json.loads(text) if text else {}
  except (TypeError, ValueError):
    return {}
  if not isinstance(raw, dict):
    return {}
  out = {}
  for key, data in raw.items():
    try:
      average, count = float(data["average"]), int(data["count"])
      float(key)
    except (KeyError, TypeError, ValueError):
      continue
    if math.isfinite(average) and average >= 0.0 and count > 0:
      out[str(key)] = {"average": average, "count": count}
  return out


class TrackingLead:
  """bogpilot_planner.update_lead_status(): closing in on, or following, a lead inside the model's view."""

  def __init__(self, dt: float = DT_MDL):
    self.dt = dt
    self.filter = FirstOrderFilter(0, 0.5, dt)
    self.tracking = False

  def update(self, present: bool, d_rel: float, v_rel: float, model_length: float, standstill: bool) -> bool:
    if standstill:
      return self.tracking
    closing_lead = present and v_rel < 0 and d_rel + (v_rel * PLANNER_TIME) < model_length + STOP_DISTANCE
    following_lead = present and d_rel < model_length + STOP_DISTANCE
    self.filter.update(following_lead)
    self.tracking = bool(closing_lead or self.filter.x >= THRESHOLD)
    return self.tracking

  def reset(self):
    self.filter.x = 0.0
    self.tracking = False


class CurveSpeedController:
  def __init__(self, store, max_lateral_acceleration: float | None = None, clock=time.monotonic):
    self.store = store
    # Learned data saves like paramsd LiveParametersV2: at most every 60 s, only when a sample was added, plus flush() on park.
    self.checkpoint = Checkpoint("CurvatureData", LEARNED_INTERVAL_S, clock=clock)

    self.enable_training = False
    self.training_timer = 0.0

    # Optional brand cap on the learned cornering limit (AP1: curve_speed_planner.TESLA_CSC_MAX_LAT_ACCEL).
    self.max_lateral_acceleration = max_lateral_acceleration

    self.curvature_data = load_curvature_data(self._read("CurvatureData"))

    self.required_curvatures = [str(round(float(road_curvature), ROUNDING_PRECISION))
                                for road_curvature in np.arange(MIN_CURVATURE, MAX_CURVATURE + STEP, STEP)]

    self.update_lateral_acceleration()

  def _read(self, key):
    try:
      return self.store.get(key, "") if self.store is not None else ""
    except Exception:
      return ""

  def _put(self, key, value):
    if self.store is None:
      return
    try:
      self.store.put(key, value)
    except Exception:
      pass

  def log_data(self, v_ego, tracking_lead, long_active, driving_in_curve, blinker, lateral_acceleration, road_curvature):
    self.enable_training = v_ego > CRUISING_SPEED
    self.enable_training &= not tracking_lead
    self.enable_training &= not long_active

    if self.enable_training:
      self.training_timer += DT_MDL

      sample_ok = math.isfinite(lateral_acceleration) and math.isfinite(road_curvature)
      if self.training_timer >= PLANNER_TIME and driving_in_curve and not blinker and sample_ok:
        lateral_acceleration = abs(lateral_acceleration)
        road_curvature = abs(round(road_curvature, ROUNDING_PRECISION))

        key = str(road_curvature)
        if key in self.curvature_data:
          data = self.curvature_data[key]

          average = data["average"]
          count = data["count"]

          self.curvature_data[key] = {
            "average": ((average * count) + lateral_acceleration) / (count + 1),
            "count": count + 1
          }
        else:
          self.curvature_data[key] = {
            "average": lateral_acceleration,
            "count": 1
          }

        self.update_lateral_acceleration()
        self.checkpoint.mark()
      else:
        self.enable_training = False

    elif self.training_timer >= PLANNER_TIME:
      self.enable_training = False

      self.training_timer = 0

    else:
      self.enable_training = False

      self.training_timer = 0

    if self.checkpoint.due():
      self.persist()

  def calibration_progress(self) -> float:
    progress = 0.0
    for key in self.required_curvatures:
      if key in self.curvature_data:
        progress += min(self.curvature_data[key]["count"] / CALIBRATION_PROGRESS_THRESHOLD, 1.0)
    return (progress / len(self.required_curvatures)) * 100

  def persist(self):
    self._put("CalibrationProgress", float(self.calibration_progress()))
    self._put("CurvatureData", json.dumps(self.curvature_data))
    self._put("CalibratedLateralAcceleration", float(self.lateral_acceleration))
    self.checkpoint.saved()

  def flush(self) -> bool:
    """Extra save of unsaved samples (park edge). True when it wrote."""
    if not self.checkpoint.dirty:
      return False
    self.persist()
    return True

  def update_lateral_acceleration(self):
    if self.curvature_data:
      all_samples = [data["average"] for data in self.curvature_data.values()]
      self.lateral_acceleration = float(np.percentile(all_samples, PERCENTILE))
    else:
      self.lateral_acceleration = DEFAULT_LATERAL_ACCELERATION

  def effective_lateral_acceleration(self) -> float:
    lateral_acceleration = self.lateral_acceleration
    if self.max_lateral_acceleration is not None:
      lateral_acceleration = min(lateral_acceleration, self.max_lateral_acceleration)
    return lateral_acceleration
