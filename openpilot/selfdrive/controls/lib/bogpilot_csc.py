"""BogPilot Curve Speed Controller (CSC) core for the 0.11.2 C3X planner.

Derived from BogPilot daily (bogpilot-tesla@04d560f3e), which carries FrogPilot 0.9.7 code by FrogAi
under this repository's MIT license (see LICENSE):
  frogpilot/controls/lib/curve_speed_controller.py   "FrogsGoMoo's Curve Speed Controller" (learning
                                                     and target), plus BogPilot's Tesla cap hook
  frogpilot/common/frogpilot_utilities.py            calculate_road_curvature() (credited there to Pfeiferj)
  frogpilot/controls/frogpilot_planner.py            road_curvature_detected, driving_in_curve and the
                                                     tracked-lead check used to gate learning
  frogpilot/common/frogpilot_variables.py            CRUISING_SPEED, DEFAULT/MINIMUM_LATERAL_ACCELERATION,
                                                     PLANNER_TIME, THRESHOLD

Behaviour and every number are unchanged from that source. Not ported: the weather reduction (C3X has
no weather source) and the speed limit controller. Changes for C3X: the Params store is injected,
stored learning data is validated before use, and CalibratedLateralAcceleration is persisted together
with CurvatureData at the end of a training segment instead of on every sample.

The road curvature (1/m) comes from the model's path geometry: lateral acceleration along the path
(yaw rate * node speed) divided by node speed squared, i.e. yaw rate / speed. The model's own speed
choice is never a target; the CSC target is sqrt(cornering limit / curvature).
"""
from __future__ import annotations

import json
import math

import numpy as np

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


def road_curvature_detected(road_curvature: float, v_ego: float, blinker: bool) -> bool:
  """Daily: (1 / |k|) ** 0.5 < v_ego > CRUISING_SPEED and no blinker. A straight path never detects."""
  if not math.isfinite(road_curvature) or road_curvature == 0.0:
    return False
  return (1 / abs(road_curvature)) ** 0.5 < v_ego > CRUISING_SPEED and not blinker


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
  """frogpilot_planner.update_lead_status(): closing in on, or following, a lead inside the model's view."""

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
  def __init__(self, store, max_lateral_acceleration: float | None = None):
    self.store = store

    self.enable_training = False
    self.target_set = False

    self.target = 0.0
    self.training_timer = 0.0

    # Optional brand cap on the learned cornering limit (AP1: ap1_curve_brake.TESLA_CSC_MAX_LAT_ACCEL).
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
      else:
        self.enable_training = False

    elif self.training_timer >= PLANNER_TIME:
      self.persist()

      self.enable_training = False

      self.training_timer = 0

    else:
      self.enable_training = False

      self.training_timer = 0

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

  def update_target(self, v_ego, road_curvature, time_to_curve):
    lateral_acceleration = self.effective_lateral_acceleration()

    if self.target_set:
      csc_speed = (lateral_acceleration / abs(road_curvature))**0.5
      decel_rate = (v_ego - csc_speed) / time_to_curve

      self.target = max(self.target - decel_rate * DT_MDL, csc_speed)
      self.target = float(np.clip(self.target, CRUISING_SPEED, max(v_ego, csc_speed)))
    else:
      self.target_set = True

      self.target = v_ego
