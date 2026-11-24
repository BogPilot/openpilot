"""CSC curve detection hysteresis and entry debounce (CurveDetector) and its use in the planner."""
import pytest

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.curve_speed_planner import TESLA_CSC_MAX_LAT_ACCEL
from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed
from openpilot.selfdrive.controls.lib.bogpilot_csc import CurveDetector, road_curvature_detected
from openpilot.selfdrive.controls.tests.csc_replay_helpers import Store, csc_sm, ns

V = 30.0


def k_ratio(r, v=V):
  return r / v ** 2


def run(det, ratios, limiting=False, dt=DT_MDL, v=V, blinker=False):
  return [det.update(k_ratio(r, v), v, blinker, limiting, dt) for r in ratios]


def test_entry_matches_the_daily_threshold_after_the_debounce():
  det = CurveDetector()
  out = run(det, [1.05] * 10)
  assert not out[0] and out[-1]
  assert road_curvature_detected(k_ratio(1.05), V, False) and not road_curvature_detected(k_ratio(0.99), V, False)
  assert run(CurveDetector(), [0.99] * 20) == [False] * 20


def test_a_limiting_curve_starts_immediately():
  assert run(CurveDetector(), [2.5], limiting=True) == [True]


def test_threshold_chatter_does_not_start_or_stop_it():
  det = CurveDetector()
  assert not any(run(det, [1.05, 0.95] * 12))             # never holds 0.25 s above threshold
  run(det, [1.5] * 10, limiting=True)
  out = run(det, [1.05, 0.9] * 20)                         # between 0.8 and 1.0: stays on
  assert all(out)


def test_exit_needs_the_hold_below_the_exit_ratio():
  det = CurveDetector()
  run(det, [1.5] * 6, limiting=True)
  out = run(det, [0.7] * 20)
  n_on = sum(out)
  assert 0.4 <= n_on * DT_MDL <= 0.55 and not out[-1]
  det2 = CurveDetector(); run(det2, [1.5] * 6, limiting=True)
  assert all(run(det2, [0.7] * 9 + [1.0] + [0.7] * 9))   # one recovery frame restarts the hold


def test_blinker_and_slow_speed_release_at_once():
  det = CurveDetector(); run(det, [2.0] * 5, limiting=True)
  assert run(det, [2.0], blinker=True, limiting=True) == [False]
  det = CurveDetector(); run(det, [2.0] * 5, limiting=True)
  assert det.update(k_ratio(2.0), 4.0, False, True, DT_MDL) is False


def test_straight_path_or_non_finite_never_detects():
  det = CurveDetector()
  assert det.update(0.0, V, False, False, DT_MDL) is False
  assert det.update(float('nan'), V, False, False, DT_MDL) is False


def test_elapsed_time_scales_the_debounce():
  slow = CurveDetector(); fast = CurveDetector()
  assert run(slow, [1.2], dt=0.2)[0] is False
  assert run(slow, [1.2], dt=0.1)[0] is True
  assert not any(run(fast, [1.2] * 5, dt=0.01))


def planner():
  return Ap1CurveSpeed(ns(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True), DT_MDL, store=Store())


def test_planner_starts_a_limiting_curve_on_the_first_frame():
  p = planner()
  p.update(csc_sm(25.0, k=TESLA_CSC_MAX_LAT_ACCEL / 15.0 ** 2), 25.0, 31.0, False)
  assert p.controlling


def test_planner_debounces_a_curve_that_does_not_limit_the_car():
  # v^2 k = 1.2 (> 1) but the curve speed (sqrt(2/k) = 1.29 v) is above v_ego
  v = 25.0
  p = planner()
  seen = [p.update(csc_sm(v, k=1.2 / v ** 2), v, 31.0, False) and p.controlling for _ in range(8)]
  assert not seen[0] and seen[-1]


def test_planner_not_enabled_resets_the_detector():
  p = planner()
  p.update(csc_sm(25.0, k=0.01), 25.0, 31.0, False)
  assert p.detector.active
  p.update(csc_sm(25.0, k=0.01, enabled=False), 25.0, 31.0, False)
  assert not p.detector.active
