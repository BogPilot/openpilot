"""CSC target, road curvature and learning (bogpilot_csc.py, ported from BogPilot daily / FrogPilot 0.9.7)."""
import json
import math

import numpy as np
import pytest

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.curve_speed_planner import (TESLA_CSC_MAX_LAT_ACCEL, CurveSpeedPlanner,
                                                                  tesla_csc_lateral_accel, vision_curve_points)
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


# --- constants are the daily / BogPilot values ---

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


def test_hud_curvature_and_planner_share_the_curve_speed():
  v = 20.0
  yaw = curve(v, lambda t: 0.02 if t >= 3.0 else 0.0)
  vv = np.full(len(T), v)
  k, _ = calculate_road_curvature(yaw, vv, T)
  _, vc = vision_curve_points(vv * T, vv, yaw, T, TESLA_CSC_MAX_LAT_ACCEL)
  assert vc.min() == pytest.approx((TESLA_CSC_MAX_LAT_ACCEL / abs(k)) ** 0.5)


def test_planner_ignores_non_finite_nodes():
  v = 20.0
  vv = np.full(len(T), v)
  yaw = curve(v, lambda t: 0.05 if t >= 2.0 else 0.0)
  yaw[5] = float('nan')
  d, vc = vision_curve_points(vv * T, vv, yaw, T, TESLA_CSC_MAX_LAT_ACCEL)
  assert np.all(np.isfinite(d)) and np.all(np.isfinite(vc)) and len(vc)
  p = CurveSpeedPlanner()
  assert math.isfinite(p.update(v, DT_MDL, TESLA_CSC_MAX_LAT_ACCEL, 0.35, vision=(d, vc)))
  assert CurveSpeedPlanner().update(float('nan'), DT_MDL, TESLA_CSC_MAX_LAT_ACCEL, 0.35, vision=(d, vc)) == 0.0


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
  assert csc.curvature_data == {"0.012": {"average": 1.8, "count": 1, "last": 1}} and csc.enable_training


@pytest.mark.parametrize("kw", [{"lead": True}, {"long_active": True}, {"v": CRUISING_SPEED}, {"curve_on": False},
                                {"blinker": True}, {"lat": float('nan')}])
def test_learning_gates(kw):
  csc = CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)
  train(csc, int(round(PLANNER_TIME / DT_MDL)) + 40, **kw)
  assert csc.curvature_data == {}


class FakeClock:
  def __init__(self, t=1000.0):
    self.t = t

  def __call__(self):
    return self.t


def test_learning_running_average_percentile_and_checkpoint_every_60_s():
  store, clock = Store(), FakeClock()
  csc = CurveSpeedController(store, TESLA_CSC_MAX_LAT_ACCEL, clock=clock)
  train_until_first_sample(csc, lat=1.6)
  train(csc, 1, lat=1.6)                     # 2 samples at 1.6
  train(csc, 1, lat=2.2)                     # running average (1.6 * 2 + 2.2) / 3
  assert csc.curvature_data["0.012"]["count"] == 3
  assert csc.curvature_data["0.012"]["average"] == pytest.approx((1.6 * 2 + 2.2) / 3)
  assert store.puts == []                    # nothing written while the segment runs
  csc.log_data(15.0, False, True, True, False, 1.8, 0.012)   # engaged: segment ends
  assert store.puts == []                    # segment end no longer saves by itself
  assert csc.training_timer == 0
  clock.t += 60.0                            # the 60 s checkpoint (paramsd cadence) comes due
  csc.log_data(15.0, False, True, True, False, 1.8, 0.012)
  keys = [k for k, _ in store.puts]
  assert keys == ["CalibrationProgress", "CurvatureData", "CalibratedLateralAcceleration"]
  assert json.loads(store.vals["CurvatureData"]) == csc.curvature_data
  assert store.vals["CalibratedLateralAcceleration"] == pytest.approx(csc.lateral_acceleration)
  assert store.vals["CalibrationProgress"] == pytest.approx(3 / CALIBRATION_PROGRESS_THRESHOLD / 100 * 100)
  clock.t += 600.0                           # nothing new learned: no more writes
  csc.log_data(15.0, False, True, True, False, 1.8, 0.012)
  assert len(store.puts) == 3


def test_no_save_without_a_new_sample():
  store, clock = Store(), FakeClock()
  csc = CurveSpeedController(store, TESLA_CSC_MAX_LAT_ACCEL, clock=clock)
  for _ in range(5):
    train(csc, int(round(PLANNER_TIME / DT_MDL)) + 40, curve_on=False)   # windows with no curve sample
    csc.log_data(15.0, False, True, True, False, 1.8, 0.012)
    clock.t += 120.0
  assert store.puts == []
  assert csc.flush() is False and store.puts == []


def test_long_training_saves_at_most_once_a_minute():
  store, clock = Store(), FakeClock()
  csc = CurveSpeedController(store, TESLA_CSC_MAX_LAT_ACCEL, clock=clock)
  for _ in range(int(600 / DT_MDL)):         # 10 min of steady learning in one curve
    clock.t += DT_MDL
    csc.log_data(15.0, False, False, True, False, 1.8, 0.012)
  saves = sum(1 for k, _ in store.puts if k == "CurvatureData")
  assert 9 <= saves <= 10


def test_flush_saves_pending_samples_once():
  store, clock = Store(), FakeClock()
  csc = CurveSpeedController(store, TESLA_CSC_MAX_LAT_ACCEL, clock=clock)
  train_until_first_sample(csc, lat=1.6)
  assert csc.flush() is True
  assert [k for k, _ in store.puts] == ["CalibrationProgress", "CurvatureData", "CalibratedLateralAcceleration"]
  assert csc.flush() is False and len(store.puts) == 3


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


def test_planner_flushes_curve_data_on_the_edge_into_park():
  from types import SimpleNamespace
  from opendbc.car.structs import car
  from openpilot.cereal import messaging
  from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed
  store, clock = Store(), FakeClock()
  acs = Ap1CurveSpeed.__new__(Ap1CurveSpeed)
  acs.csc = CurveSpeedController(store, TESLA_CSC_MAX_LAT_ACCEL, clock=clock)
  acs._parked = None
  G = car.CarState.GearShifter
  sm = lambda gear: {"carState": SimpleNamespace(gearShifter=gear)}
  acs._flush_on_park(sm(G.park))               # starting in Park is not an edge
  train_until_first_sample(acs.csc, lat=1.6)
  acs._flush_on_park(sm(G.drive))
  assert store.puts == []
  acs._flush_on_park(sm(G.park))               # edge into Park: unsaved samples are written
  assert [k for k, _ in store.puts] == ["CalibrationProgress", "CurvatureData", "CalibratedLateralAcceleration"]
  acs._flush_on_park(sm(G.park))
  assert len(store.puts) == 3
  # the real carState message (capnp enum) reads the same way
  msg = messaging.new_message("carState")
  msg.carState.gearShifter = "drive"
  acs._flush_on_park({"carState": msg.carState})
  assert acs._parked is False
  msg.carState.gearShifter = "park"
  acs._flush_on_park({"carState": msg.carState})
  assert acs._parked is True


# --- bucket cap: last seen, least recently seen goes first, old files ---

def _warm(csc):
  train_until_first_sample(csc, k=0.0105)        # PLANNER_TIME of manual driving, then one sample per call


def test_cap_drops_the_least_recently_seen_bucket(monkeypatch):
  import openpilot.selfdrive.controls.lib.bogpilot_csc as CSC
  monkeypatch.setattr(CSC, "MAX_BUCKETS", 3)
  csc = CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)
  _warm(csc)                                     # 0.0105 seen at 1
  train(csc, 1, k=0.011)                         # 2
  train(csc, 1, k=0.012)                         # 3
  train(csc, 1, k=0.0105)                        # 4: seen again, now the most recent
  train(csc, 1, k=0.013)                         # 5: over the cap, 0.011 (seen at 2) goes
  assert list(csc.curvature_data) == ["0.012", "0.0105", "0.013"]
  assert [d["last"] for d in csc.curvature_data.values()] == [3, 4, 5]
  assert csc.curvature_data["0.0105"]["count"] == 2


def test_cap_holds_while_learning_at_the_default(monkeypatch):
  import openpilot.selfdrive.controls.lib.bogpilot_csc as CSC
  assert CSC.MAX_BUCKETS == 5000
  store = Store()
  csc = CurveSpeedController(store, TESLA_CSC_MAX_LAT_ACCEL)
  _warm(csc)
  for i in range(6200):                          # distinct 1e-5 buckets, like real driving
    csc.log_data(15.0, False, False, True, False, 1.3 + (i % 97) / 101.0, 0.002 + i * 1e-5)
  assert len(csc.curvature_data) == 5000
  first = next(iter(csc.curvature_data.values()))
  assert first["last"] == csc.sample_number - 4999           # exactly the 5,000 most recent
  csc.persist()
  text = store.vals["CurvatureData"]
  assert 250_000 < len(text) < 400_000, len(text)            # ~70 B per bucket with "last"
  assert load_curvature_data(text) == csc.curvature_data
  assert list(load_curvature_data(text)) == list(csc.curvature_data)


def test_a_file_from_before_the_cap_loads_oldest_first_and_keeps_learning():
  old = {"0.004": {"average": 1.5, "count": 3}, "0.002": {"average": 1.7, "count": 1},
         "0.003": {"average": 2.0, "count": 2, "last": 7}, "0.005": {"average": 1.9, "count": 1}}
  data = load_curvature_data(json.dumps(old))
  assert list(data) == ["0.004", "0.002", "0.005", "0.003"]   # no "last" = oldest, in file (creation) order
  assert [d["last"] for d in data.values()] == [0, 0, 0, 7]
  assert data["0.004"] == {"average": 1.5, "count": 3, "last": 0}
  csc = CurveSpeedController(Store(CurvatureData=json.dumps(old)), TESLA_CSC_MAX_LAT_ACCEL)
  assert csc.sample_number == 7
  assert csc.lateral_acceleration == pytest.approx(float(np.percentile([1.5, 1.7, 2.0, 1.9], 90)))   # learning unchanged
  train(csc, int(round(PLANNER_TIME / DT_MDL)) + 2, k=0.0105)
  new = csc.curvature_data["0.0105"]
  assert new["count"] >= 1 and new["last"] == 7 + new["count"] == csc.sample_number   # numbering carries on from the file
  assert list(csc.curvature_data)[-1] == "0.0105"


def test_load_trims_to_the_cap_oldest_first_and_cleans_bad_last_values():
  raw = {"0.001": {"average": 1.0, "count": 1, "last": -3}, "0.002": {"average": 1.0, "count": 1, "last": "x"},
         "0.003": {"average": 1.0, "count": 1, "last": True}, "0.004": {"average": 1.0, "count": 1, "last": 9},
         "0.005": {"average": 1.0, "count": 1, "last": 4}}
  data = load_curvature_data(json.dumps(raw), max_buckets=2)
  assert list(data) == ["0.005", "0.004"]
  data = load_curvature_data(json.dumps(raw))
  assert [d["last"] for d in data.values()] == [0, 0, 0, 4, 9]
