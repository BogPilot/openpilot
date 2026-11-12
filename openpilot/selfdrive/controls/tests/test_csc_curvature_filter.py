"""CSC road-curvature sensor filter: spike rejection, argmax hysteresis, confidence gating, never-late entry."""
import numpy as np
import pytest

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.ap1_curve_brake import TESLA_CSC_MAX_LAT_ACCEL
from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed
from openpilot.selfdrive.controls.lib.bogpilot_csc import RoadCurvatureFilter, calculate_road_curvature
from openpilot.selfdrive.controls.tests.csc_replay_helpers import T, Store, csc_sm, ns

N = len(T)


def flt():
  return RoadCurvatureFilter()


def ramp(v, k, t_start=0.0):
  return np.where(T >= t_start, k * v, 0.0)


def test_genuine_curve_matches_the_unfiltered_formula_on_first_sample():
  v = np.full(N, 30.0)
  yaw = ramp(30.0, 0.004, 2.0)
  k, ttc = flt().update(yaw, v, T)
  k0, ttc0 = calculate_road_curvature(yaw, v, T)
  assert k == pytest.approx(k0) and ttc == pytest.approx(ttc0)


def test_sign_follows_the_curve_direction():
  v = np.full(N, 25.0)
  assert flt().update(ramp(25.0, 0.01), v, T)[0] > 0
  assert flt().update(-ramp(25.0, 0.01), v, T)[0] < 0


def test_single_node_spike_never_wins():
  v = np.full(N, 33.0)
  yaw = ramp(33.0, 0.0005)
  yaw[17] = 0.02            # one wild node
  k, _ = flt().update(yaw, v, T)
  assert abs(k) < 0.001      # raw argmax would report 0.02 / 33
  assert abs(calculate_road_curvature(yaw, v, T)[0]) > 0.0005


def test_two_node_wide_feature_is_not_lowered():
  v = np.full(N, 30.0)
  yaw = ramp(30.0, 0.001)
  yaw[20:23] = 0.01 * 30.0
  k, _ = flt().update(yaw, v, T)
  assert abs(k) == pytest.approx(0.01)


def test_last_node_peak_is_not_lowered():
  v = np.full(N, 30.0)
  yaw = np.zeros(N); yaw[-1] = 0.01 * 30.0
  assert abs(flt().update(yaw, v, T)[0]) == pytest.approx(0.01)


def test_argmax_holds_through_a_small_swap_and_moves_on_a_real_one():
  v = np.full(N, 30.0)
  f = flt()
  a = np.zeros(N); a[10:13] = 0.0100 * 30.0; a[24:27] = 0.0098 * 30.0
  _, t1 = f.update(a, v, T)
  b = np.zeros(N); b[10:13] = 0.0100 * 30.0; b[24:27] = 0.0104 * 30.0   # +4%: not enough to hop
  _, t2 = f.update(b, v, T)
  assert t2 == pytest.approx(t1)
  c = np.zeros(N); c[10:13] = 0.0100 * 30.0; c[24:27] = 0.0125 * 30.0   # +25%: hop
  _, t3 = f.update(c, v, T)
  assert T[24] <= t3 <= T[26]


def test_nodes_slower_than_the_gate_are_ignored():
  v = np.full(N, 30.0); v[-6:] = 2.0
  yaw = np.zeros(N); yaw[-6:] = 0.5
  k, _ = flt().update(yaw, v, T)
  assert k == 0.0


def test_non_finite_nodes_fail_to_no_curve():
  v = np.full(N, 30.0); yaw = ramp(30.0, 0.01); yaw[5] = np.nan
  k, _ = flt().update(yaw, v, T)
  assert np.isfinite(k)


def test_rise_is_immediate_and_fall_decays_with_elapsed_time():
  v = np.full(N, 30.0)
  f = flt()
  f.update(ramp(30.0, 0.001), v, T)
  assert abs(f.update(ramp(30.0, 0.01), v, T)[0]) == pytest.approx(0.01)       # entry never late
  fall = [abs(f.update(ramp(30.0, 0.001), v, T, DT_MDL)[0]) for _ in range(40)]
  assert all(a >= b for a, b in zip(fall, fall[1:], strict=False))
  assert fall[0] > 0.0085 and fall[-1] < 0.0025
  g = flt(); g.update(ramp(30.0, 0.01), v, T)
  slow = abs(g.update(ramp(30.0, 0.001), v, T, 0.1)[0])
  h = flt(); h.update(ramp(30.0, 0.01), v, T)
  fast = abs(h.update(ramp(30.0, 0.001), v, T, 0.025)[0])
  assert slow < fast


def test_reset_forgets_the_held_node_and_magnitude():
  v = np.full(N, 30.0)
  f = flt(); f.update(ramp(30.0, 0.01), v, T); f.reset()
  assert abs(f.update(ramp(30.0, 0.001), v, T)[0]) == pytest.approx(0.001)


def planner():
  return Ap1CurveSpeed(ns(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True), DT_MDL, store=Store())


def test_planner_still_controls_a_genuine_curve_from_the_first_frame():
  v_ego = 25.0
  k = TESLA_CSC_MAX_LAT_ACCEL / 15.0 ** 2
  p = planner()
  p.update(csc_sm(v_ego, k=k), v_ego, 31.0, False)
  assert p.controlling and p.road_curvature == pytest.approx(k)


def test_planner_inactive_resets_the_filter():
  p = planner()
  p.update(csc_sm(25.0, k=0.01), 25.0, 31.0, False)
  assert p.curvature_filter.index is not None
  p.update(csc_sm(25.0, k=0.01), 25.0, 31.0, True)   # reset_state: still runs (inputs fresh) ...
  sm = csc_sm(25.0, k=0.01); sm.alive["modelV2"] = False
  p.update(sm, 25.0, 31.0, False)                       # ... stale inputs release it
  assert p.curvature_filter.index is None and p.curvature_filter.magnitude == 0.0
