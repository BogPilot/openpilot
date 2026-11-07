"""CSC target, road curvature and learning (bogpilot_csc.py, ported from BogPilot daily / FrogPilot 0.9.7)."""
import json
import math

import numpy as np
import pytest

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.ap1_curve_brake import (TESLA_CSC_MAX_LAT_ACCEL, curve_brake_request, curve_target_speed,
                                                              tesla_csc_lateral_accel)
from openpilot.selfdrive.controls.lib.bogpilot_csc import (CALIBRATION_PROGRESS_THRESHOLD, CRUISING_SPEED, DEFAULT_LATERAL_ACCELERATION,
                                                           MINIMUM_LATERAL_ACCELERATION, PLANNER_TIME, THRESHOLD, CurveSpeedController,
                                                           TrackingLead, calculate_road_curvature, load_curvature_data,
                                                           road_curvature_detected)

T = np.array(ModelConstants.T_IDXS)


class Store:
  def __init__(self, **vals):
    self.vals = dict(vals)
    self.puts = []

  def get(self, key, default=None):
    return self.vals.get(key, default)

  def put(self, key, value):
    self.puts.append((key, value))
    self.vals[key] = value


def curve(v, k_at_t):
  """Yaw rate for a path at speed v whose curvature is k_at_t(t) (1/m)."""
  return np.array([k_at_t(t) * v for t in T])


# --- constants are the daily / FrogPilot values ---

def test_constants_match_daily():
  assert (CRUISING_SPEED, DEFAULT_LATERAL_ACCELERATION, MINIMUM_LATERAL_ACCELERATION, THRESHOLD) == (5, 2.0, 1.3, 0.63)
  assert PLANNER_TIME == ModelConstants.T_IDXS[-1] == 10.0
  assert CALIBRATION_PROGRESS_THRESHOLD == pytest.approx(10 / DT_MDL)


# --- road curvature from path geometry ---

def test_road_curvature_is_yaw_rate_over_speed_with_sign():
  v = 20.0
  yaw = curve(v, lambda t: 0.01 if t >= 3.0 else 0.0)
  k, ttc = calculate_road_curvature(yaw, np.full(len(T), v), T)
  assert k == pytest.approx(0.01)
  assert ttc == pytest.approx(min(t for t in T if t >= 3.0))
  k_right, _ = calculate_road_curvature(-yaw, np.full(len(T), v), T)
  assert k_right == pytest.approx(-0.01)


def test_road_curvature_independent_of_model_speed_choice():
  # Same road shape, the model planning to slow down (lights/leads) or not: same curvature.
  def k_at(t):
    return 0.02 if 4.0 <= t <= 6.0 else 0.0
  v_fast = np.full(len(T), 25.0)
  v_slow = np.linspace(25.0, 12.0, len(T))
  k_fast, _ = calculate_road_curvature(np.array([k_at(t) * vv for t, vv in zip(T, v_fast, strict=True)]), v_fast, T)
  k_slow, _ = calculate_road_curvature(np.array([k_at(t) * vv for t, vv in zip(T, v_slow, strict=True)]), v_slow, T)
  assert k_fast == pytest.approx(0.02) and k_slow == pytest.approx(0.02)


def test_time_to_curve_floor_one_second():
  v = 20.0
  _, ttc = calculate_road_curvature(curve(v, lambda t: 0.01), np.full(len(T), v), T)
  assert ttc == 1


def test_detection_threshold_and_blinker():
  # detected when the curve speed at 1 m/s^2 is below v_ego and v_ego > CRUISING_SPEED
  assert road_curvature_detected(0.01, 11.0, False)          # sqrt(100) = 10 < 11
  assert not road_curvature_detected(0.01, 9.0, False)
  assert not road_curvature_detected(0.01, 11.0, True)       # blinker
  assert not road_curvature_detected(1.0, 4.9, False)        # below cruising speed
  assert not road_curvature_detected(0.0, 30.0, False)       # straight: no ZeroDivisionError
  assert not road_curvature_detected(float('nan'), 30.0, False)


# --- target ---

def test_cap_applies_to_learned_limit():
  csc = CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)
  csc.lateral_acceleration = 2.6
  assert csc.effective_lateral_acceleration() == pytest.approx(2.0) == tesla_csc_lateral_accel(2.6)
  csc.lateral_acceleration = 1.6
  assert csc.effective_lateral_acceleration() == pytest.approx(1.6)


def test_first_target_is_current_speed_then_ramps_to_curve_speed():
  csc = CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)
  k, ttc, v = 0.02, 4.0, 20.0
  csc.update_target(v, k, ttc)
  assert csc.target_set and csc.target == v
  v_curve = (2.0 / k) ** 0.5
  csc.update_target(v, k, ttc)
  assert csc.target == pytest.approx(v - (v - v_curve) / ttc * DT_MDL)
  for _ in range(400):
    csc.update_target(v, k, ttc)
  assert csc.target == pytest.approx(v_curve)


def test_target_clip():
  csc = CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)
  csc.update_target(30.0, 1.0, 1.0)
  for _ in range(100):
    csc.update_target(30.0, 1.0, 1.0)        # sqrt(2) m/s curve: clipped at CRUISING_SPEED
  assert csc.target == CRUISING_SPEED
  csc = CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)
  csc.update_target(10.0, 0.001, 1.0)        # gentle: curve speed 44.7 m/s, never above max(v_ego, csc)
  for _ in range(100):
    csc.update_target(10.0, 0.001, 1.0)
  assert csc.target <= (2.0 / 0.001) ** 0.5 + 1e-9


def test_target_and_brake_share_the_curve_speed():
  v = 20.0
  yaw = curve(v, lambda t: 0.02 if t >= 3.0 else 0.0)
  vv = np.full(len(T), v)
  k, _ = calculate_road_curvature(yaw, vv, T)
  assert curve_target_speed(T, vv * T, vv, yaw) == pytest.approx((TESLA_CSC_MAX_LAT_ACCEL / abs(k)) ** 0.5)


def test_brake_ignores_non_finite_nodes():
  v = 20.0
  vv = np.full(len(T), v)
  yaw = curve(v, lambda t: 0.05 if t >= 2.0 else 0.0)
  yaw[5] = float('nan')
  assert math.isfinite(curve_brake_request(v, T, vv * T, vv, yaw))
  assert curve_brake_request(float('nan'), T, vv * T, vv, yaw) == 0.0
  assert curve_target_speed(T, vv * T, vv, yaw) == float('inf')


# --- learning ---

def train(csc, steps, lat=1.8, k=0.012, lead=False, long_active=False, curve_on=True, blinker=False, v=15.0):
  for _ in range(steps):
    csc.log_data(v, lead, long_active, curve_on, blinker, lat, k)


def train_until_first_sample(csc, **kw):
  for i in range(int(round(PLANNER_TIME / DT_MDL)) + 3):
    train(csc, 1, **kw)
    if csc.curvature_data:
      return i + 1
  return None


def test_learning_needs_planner_time_of_manual_driving():
  csc = CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)
  steps = train_until_first_sample(csc)
  assert steps is not None and abs(steps * DT_MDL - PLANNER_TIME) <= DT_MDL + 1e-9
  assert csc.curvature_data == {"0.012": {"average": 1.8, "count": 1}} and csc.enable_training


@pytest.mark.parametrize("kw", [{"lead": True}, {"long_active": True}, {"v": CRUISING_SPEED}, {"curve_on": False},
                                {"blinker": True}, {"lat": float('nan')}])
def test_learning_gates(kw):
  csc = CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)
  train(csc, int(round(PLANNER_TIME / DT_MDL)) + 40, **kw)
  assert csc.curvature_data == {}


def test_learning_running_average_percentile_and_persist_at_segment_end():
  store = Store()
  csc = CurveSpeedController(store, TESLA_CSC_MAX_LAT_ACCEL)
  train_until_first_sample(csc, lat=1.6)
  train(csc, 1, lat=1.6)                     # 2 samples at 1.6
  train(csc, 1, lat=2.2)                     # running average (1.6 * 2 + 2.2) / 3
  assert csc.curvature_data["0.012"]["count"] == 3
  assert csc.curvature_data["0.012"]["average"] == pytest.approx((1.6 * 2 + 2.2) / 3)
  assert store.puts == []                    # nothing written while the segment runs
  csc.log_data(15.0, False, True, True, False, 1.8, 0.012)   # engaged: segment ends
  keys = [k for k, _ in store.puts]
  assert keys == ["CalibrationProgress", "CurvatureData", "CalibratedLateralAcceleration"]
  assert json.loads(store.vals["CurvatureData"]) == csc.curvature_data
  assert store.vals["CalibratedLateralAcceleration"] == pytest.approx(csc.lateral_acceleration)
  assert store.vals["CalibrationProgress"] == pytest.approx(3 / CALIBRATION_PROGRESS_THRESHOLD / 100 * 100)
  assert csc.training_timer == 0


def test_learned_limit_is_90th_percentile_and_capped_for_target():
  data = {str(round(0.001 * i, 5)): {"average": a, "count": 5} for i, a in enumerate([1.5, 1.7, 1.9, 2.1, 2.5], start=1)}
  csc = CurveSpeedController(Store(CurvatureData=json.dumps(data)), TESLA_CSC_MAX_LAT_ACCEL)
  assert csc.lateral_acceleration == pytest.approx(float(np.percentile([1.5, 1.7, 1.9, 2.1, 2.5], 90)))
  assert csc.effective_lateral_acceleration() == pytest.approx(2.0)


def test_no_data_uses_default():
  assert CurveSpeedController(Store(), None).lateral_acceleration == DEFAULT_LATERAL_ACCELERATION


@pytest.mark.parametrize("text", ["", "not json", "[]", json.dumps({"0.01": {"average": "nan", "count": 2}}),
                                  json.dumps({"0.01": {"average": 1.0, "count": 0}}), json.dumps({"x": {"average": 1.0, "count": 1}})])
def test_corrupt_learning_data_is_ignored(text):
  assert load_curvature_data(text) == {}
  assert CurveSpeedController(Store(CurvatureData=text), TESLA_CSC_MAX_LAT_ACCEL).lateral_acceleration == DEFAULT_LATERAL_ACCELERATION


def test_tracking_lead_filter():
  tl = TrackingLead()
  assert tl.update(True, 30.0, -5.0, 150.0, False)            # closing in on a lead inside the model's view
  tl = TrackingLead()
  out = [tl.update(True, 40.0, 0.0, 150.0, False) for _ in range(40)]
  assert not out[0] and out[-1]                               # following: after the 0.5 s filter passes 0.63
  tl = TrackingLead()
  assert not any(tl.update(False, 40.0, 0.0, 150.0, False) for _ in range(40))
