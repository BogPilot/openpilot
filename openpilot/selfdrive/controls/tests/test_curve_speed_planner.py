"""curve_speed_planner.py unit tests: envelope, braking stage, shaping, map point, exit release (no hold)."""
import math
from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.selfdrive.controls.lib import curve_speed_planner as C
from openpilot.selfdrive.controls.lib.curve_speed_planner import (A_MIN, CURVE_LEAD_S, HOLD_LEAK, MIN_DISTANCE, ONSET_JERK,
                                                                  RELEASE_JERK, START_DECEL, TESLA_CSC_MAX_LAT_ACCEL,
                                                                  CurveSpeedPlanner, MapCurvePoint, curve_speed_planner_for,
                                                                  jerk_limited_distance, landing_decel, map_trigger_distance,
                                                                  tesla_csc_lateral_accel, vision_curve_points)
from openpilot.selfdrive.modeld.constants import ModelConstants

T = np.array(ModelConstants.T_IDXS)
DT = 0.05
LAT = TESLA_CSC_MAX_LAT_ACCEL


def path(v_ego, curvature_at, v_model=None):
  """Constant-speed model path: (x, v, yaw, t); curvature_at(x) -> 1/m along the path."""
  v = np.full(len(T), v_ego if v_model is None else v_model, dtype=float)
  x = v * T
  k = np.array([curvature_at(xi) for xi in x])
  return x, v, k * v, T


def curve_ahead(start_m, k, length=1e9):
  return lambda x: k if start_m <= x < start_m + length else 0.0


def vision(v_ego, curvature_at, lat=LAT, **kw):
  return vision_curve_points(*path(v_ego, curvature_at, **kw), lat)


def step(p, v, curvature_at, delay=0.35, lat=LAT, **kw):
  return p.update(v, DT, lat, delay, vision=vision(v, curvature_at, lat), **kw)


# --- one cornering limit, factory ---

def test_one_lateral_limit_lower_value_wins():
  assert tesla_csc_lateral_accel(2.3) == pytest.approx(TESLA_CSC_MAX_LAT_ACCEL)
  assert tesla_csc_lateral_accel(1.7) == pytest.approx(1.7)
  assert TESLA_CSC_MAX_LAT_ACCEL == 2.0 and CURVE_LEAD_S == 0.5 and MIN_DISTANCE == 5.0


def test_factory_same_platforms_as_before():
  def cp(fp, long):
    return SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=long)
  assert isinstance(curve_speed_planner_for(cp("TESLA_AP1_MODELS", True)), CurveSpeedPlanner)
  for fp, long in (("TESLA_AP1_MODELS", False), ("TESLA_MODEL_3", True), ("HONDA_CIVIC", True), ("", True)):
    assert curve_speed_planner_for(cp(fp, long)) is None
  preap = SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True, pcmCruise=False)
  assert isinstance(curve_speed_planner_for(preap, pedal_ok=True), CurveSpeedPlanner)
  assert curve_speed_planner_for(preap, pedal_ok=False) is None


# --- envelope ---

def test_vision_points_curve_speed_and_cleanup():
  k = 0.02
  d, vc = vision(20.0, curve_ahead(100.0, k))
  assert len(d) and np.all(d >= 100.0 - 1e-9)
  assert vc.min() == pytest.approx((LAT / k) ** 0.5, rel=1e-6)
  # a one-node spike never limits (3-node median along the path)
  x, v, yaw, t = path(20.0, lambda s: 0.0)
  yaw = yaw.copy()
  yaw[10] = 0.5
  d, vc = vision_curve_points(x, v, yaw, t, LAT)
  assert len(d) == 0
  # the model planning a near stop is not a sharp curve
  x, v, _, t = path(13.4, lambda s: 0.0, v_model=3.0)
  assert len(vision_curve_points(x, v, np.full(len(t), 0.3), t, LAT)[0]) == 0
  # non-finite / short input: nothing
  assert len(vision_curve_points([], [], [], [], LAT)[0]) == 0
  x, v, yaw, t = path(20.0, curve_ahead(50.0, k))
  yaw = yaw.copy()
  yaw[5] = float("nan")
  assert np.all(np.isfinite(vision_curve_points(x, v, yaw, t, LAT)[1]))


def test_straight_and_gentle_roads_never_brake():
  for curv in (lambda s: 0.0, lambda s: 1 / 1500):
    p = CurveSpeedPlanner()
    out = [step(p, 29.0, curv) for _ in range(100)]
    assert max(abs(a) for a in out) == 0.0


def test_request_matches_kinematics_with_action_delay():
  v, start, k = 13.4, 60.0, 0.0161
  v_curve = (LAT / k) ** 0.5
  for delay in (0.0, 0.35, 0.4, 0.6):
    p = CurveSpeedPlanner()
    p.update(v, DT, LAT, delay, vision=vision(v, curve_ahead(start, k)))
    x_entry = min(xi for xi in v * T if xi >= start)
    expected = -(v ** 2 - v_curve ** 2) / (2 * (x_entry - v * (CURVE_LEAD_S + delay)))
    assert p.raw == pytest.approx(expected, rel=1e-6)
    assert p.v_limit == pytest.approx(v_curve, rel=1e-6)


def test_longer_delay_brakes_earlier_and_lands_softer():
  v, start, k = 25.0, 180.0, 0.02
  raws, caps = [], []
  for delay in (0.2, 0.35, 0.4, 0.8):
    p = CurveSpeedPlanner()
    p.update(v, DT, LAT, delay, vision=vision(v, curve_ahead(start, k)))
    raws.append(p.raw)
    caps.append(landing_decel(3.0, delay))
  assert raws == sorted(raws, reverse=True)       # more delay: stronger request now
  assert caps == sorted(caps, reverse=True)       # more delay: lower landing cap


def test_landing_cap_math():
  assert landing_decel(0.0) == 0.0 and landing_decel(-1.0) == 0.0
  assert landing_decel(math.inf) == math.inf and landing_decel(math.nan) == 0.0
  for delay in (0.0, 0.35, 0.4):
    prev = 0.0
    for gap in np.linspace(0.05, 3.0, 30):
      a = landing_decel(gap, delay)
      assert a > prev
      assert a * delay + a * a / (2 * RELEASE_JERK) == pytest.approx(gap, rel=1e-9)
      prev = a


# --- shaping (Smooth Curve Braking behaviour) ---

def test_starts_without_debounce_and_ramps_at_onset_jerk():
  p = CurveSpeedPlanner()
  out = [step(p, 25.0, curve_ahead(120.0, 0.02)) for _ in range(30)]
  assert out[0] < 0.0                                  # first frame past START_DECEL already brakes (no 0.3 s wait)
  assert out[0] >= -ONSET_JERK * DT - 1e-9
  assert np.min(np.diff([0.0] + out)) >= -ONSET_JERK * DT - 1e-9
  assert min(out) >= A_MIN - 1e-9


def test_weak_request_ignored():
  p = CurveSpeedPlanner()
  # a mild curve far ahead: steady decel below START_DECEL
  out = [step(p, 20.0, curve_ahead(180.0, 1.4 / 19.5 ** 2)) for _ in range(10)]
  assert p.raw > -START_DECEL and max(abs(a) for a in out) == 0.0


def test_hold_leak_while_above_curve_speed():
  """Model wobble (the curve estimate softens for a moment) only eases the held request at HOLD_LEAK."""
  p = CurveSpeedPlanner()
  for _ in range(40):
    step(p, 22.0, curve_ahead(100.0, 0.02))
  held = p.a_curve
  assert held < -0.5
  # wobble: the far curve looks looser for 0.5 s, still slower than the car
  out = [step(p, 22.0, curve_ahead(100.0, 0.015)) for _ in range(10)]
  assert np.max(np.diff([held] + out)) <= HOLD_LEAK * DT + 1e-9


def test_released_at_curve_speed_and_never_below():
  k = 0.05
  v_curve = (LAT / k) ** 0.5
  p = CurveSpeedPlanner()
  for _ in range(40):
    step(p, v_curve + 3.0, curve_ahead(20.0, k))
  assert p.a_curve == pytest.approx(A_MIN)
  v = v_curve - 0.01
  out = [step(p, v, curve_ahead(3.0, k)) for _ in range(40)]
  assert p.landing_cap == 0.0 and out[-1] == 0.0
  assert np.max(np.diff([A_MIN] + out)) <= RELEASE_JERK * DT + 1e-9


def _closed_loop(curvature_of_s, v0, seconds, delay=0.35, lat=LAT, map_fn=None, lag_s=0.25, dead_steps=2):
  """Point mass with actuator dead time + first-order lag. Returns rows (s, v, a_req, v_limit)."""
  p = CurveSpeedPlanner()
  v, s, a = v0, 0.0, 0.0
  hist = [0.0] * (dead_steps + 1)
  rows = []
  for i in range(int(seconds / DT)):
    vis = vision_curve_points(*path(v, lambda x, s0=s: curvature_of_s(s0 + x)), lat)
    ms = map_fn(s) if map_fn else (0.0, 0.0)
    req = p.update(v, DT, lat, delay, vision=vis, map_speed=ms[0], map_speed_raw=ms[1], a_ego=a)
    hist.append(req)
    a += (1 - np.exp(-DT / lag_s)) * (hist[-1 - dead_steps] - a)
    v = max(0.0, v + a * DT)
    s += v * DT
    rows.append((s, v, req, p.v_limit, i * DT))
  return rows


@pytest.mark.parametrize("delay", [0.35, 0.4])
def test_closed_loop_approach_entry_exit(delay):
  k, x0, length = 0.02, 250.0, 120.0      # 10 m/s curve
  v_curve = (LAT / k) ** 0.5
  rows = _closed_loop(lambda s: k if x0 <= s < x0 + length else 0.0, 25.0, 30.0, delay=delay)
  v_entry = next(v for s, v, *_ in rows if s >= x0)
  in_curve = [v for s, v, *_ in rows if x0 <= s < x0 + length]
  assert v_entry <= v_curve + 0.5
  assert min(in_curve) >= v_curve - 0.5
  assert min(r[2] for r in rows) >= A_MIN - 1e-9
  # exit: once the curve is behind, the request is 0 within the release ramp (no hold)
  t_exit = next(t for s, v, a, vl, t in rows if s >= x0 + length)
  assert all(a == 0.0 for s, v, a, vl, t in rows if t >= t_exit + abs(A_MIN) / RELEASE_JERK + DT)


def test_exit_release_has_no_two_second_hold():
  """At the curve speed with the curve ending: the request is fully released by |a|/RELEASE_JERK, far under 2 s."""
  k = 0.02
  v_curve = (LAT / k) ** 0.5
  p = CurveSpeedPlanner()
  for _ in range(60):
    step(p, v_curve + 2.0, curve_ahead(40.0, k))
  a0 = p.a_curve
  assert a0 < -0.3
  n = 0
  while p.a_curve < 0.0:
    step(p, v_curve, lambda s: 0.0)    # curve gone from the envelope
    n += 1
    assert n < 100
  assert n * DT <= abs(a0) / RELEASE_JERK + DT + 1e-9
  assert n * DT < 2.0
  assert p.cruise_ceiling == math.inf   # cruise free again the moment the envelope clears


def test_s_bend_keeps_limiting_through_the_straight_between():
  k1, k2 = 0.02, 0.03                      # 10 m/s then 8.2 m/s
  def road(s):
    if 200.0 <= s < 260.0:
      return k1
    if 290.0 <= s < 350.0:
      return -k2
    return 0.0
  rows = _closed_loop(road, 25.0, 30.0)
  v_between = [v for s, v, *_ in rows if 260.0 <= s < 290.0]
  v2 = (LAT / k2) ** 0.5
  assert max(v_between) <= (LAT / k1) ** 0.5 + 0.5    # never speeds up between the bends
  assert next(v for s, v, *_ in rows if s >= 290.0) <= v2 + 0.5
  assert min(v for s, v, *_ in rows if 200.0 <= s < 350.0) >= v2 - 0.5


def test_cruise_ceiling():
  p = CurveSpeedPlanner()
  step(p, 20.0, lambda s: 0.0)
  assert p.cruise_ceiling == math.inf
  step(p, 20.0, curve_ahead(150.0, 0.02))          # a slower curve ahead: no positive cruise accel
  assert p.cruise_ceiling == 0.0
  step(p, 9.0, curve_ahead(60.0, 0.02))            # the car slower than the curve: accel allowed, bounded
  v_curve = (LAT / 0.02) ** 0.5
  x_entry = min(xi for xi in 9.0 * T if xi >= 60.0)
  # every curve node must stay reachable at constant accel: the farthest node binds
  x_far = max(xi for xi in 9.0 * T if xi >= 60.0)
  assert p.cruise_ceiling == pytest.approx((v_curve ** 2 - 81.0) / (2 * (x_far - 9.0 * (CURVE_LEAD_S + 0.35))), rel=1e-6)
  assert 0.0 < p.cruise_ceiling < (v_curve ** 2 - 81.0) / (2 * (x_entry - 9.0 * (CURVE_LEAD_S + 0.35)))


def test_inactive_releases_at_release_jerk_and_reset_drops():
  p = CurveSpeedPlanner()
  for _ in range(40):
    step(p, 20.0, curve_ahead(60.0, 0.03))
  a0 = p.a_curve
  assert a0 < -0.5
  a1 = p.update(20.0, DT, LAT, 0.35, active=False)
  assert a1 == pytest.approx(a0 + RELEASE_JERK * DT)
  assert p.cruise_ceiling == math.inf
  p.reset()
  assert p.a_curve == 0.0


def test_non_finite_inputs_fail_closed():
  p = CurveSpeedPlanner()
  assert p.update(float("nan"), DT, LAT, 0.35, vision=vision(20.0, curve_ahead(60.0, 0.03))) == 0.0
  assert p.update(20.0, float("nan"), LAT, float("inf"), vision=None) == 0.0


# --- map point (mapd v2 mapCurveSpeed) ---

def test_jerk_limited_distance_matches_closed_form():
  # from a0 = -a_max straight to constant decel: plain v^2 / 2a
  assert jerk_limited_distance(25.0, -1.2, 15.0) == pytest.approx((625 - 225) / 2.4, rel=1e-6)
  # from a0 = 0: 2 s jerk phase, then constant
  d = jerk_limited_distance(25.0, 0.0, 15.0)
  t1 = 1.2 / 0.6
  v1 = 25.0 - 0.5 * 0.6 * t1 ** 2
  d_expected = 25.0 * t1 - 0.6 * t1 ** 3 / 6 + (v1 ** 2 - 225) / 2.4
  assert d == pytest.approx(d_expected, rel=1e-6)
  # target reached inside the jerk phase
  d = jerk_limited_distance(10.0, 0.0, 9.9)
  assert 0.0 < d < 10.0
  assert jerk_limited_distance(10.0, 0.0, 12.0) == 0.0


def test_map_point_seeds_from_mapd_trigger_rule_and_counts_down():
  m = MapCurvePoint()
  d0 = m.update(15.0, 25.0, 0.0, DT)
  assert d0 == pytest.approx(map_trigger_distance(25.0, 0.0, 15.0)) and d0 > 150.0
  d1 = m.update(15.0, 25.0, 0.0, DT)
  assert d1 == pytest.approx(d0 - 25.0 * DT)
  assert m.update(15.05, 25.0, 0.0, DT) == pytest.approx(d1 - 25.0 * DT)   # same curve
  assert m.update(12.0, 25.0, 0.0, DT) == pytest.approx(map_trigger_distance(25.0, 0.0, 12.0))   # a new curve
  assert m.update(0.0, 25.0, 0.0, DT) is None and m.speed == 0.0


def test_map_only_curve_brakes_and_lands():
  """A curve only the map knows about (vision sees a straight road) brakes through the same stage."""
  x_curve, v_map = 400.0, 12.0
  seen = {}

  def map_fn(s):
    # mapd reports once inside its trigger distance and until the curve node is passed
    if s >= x_curve:
      return 0.0, 0.0
    if "s0" not in seen:
      if x_curve - s > 400.0:
        return 0.0, 0.0
      seen["s0"] = s
    return v_map, v_map
  rows = _closed_loop(lambda s: 0.0, 25.0, 40.0, map_fn=map_fn)
  assert min(r[2] for r in rows) < -0.3                         # it braked
  assert min(r[2] for r in rows) >= A_MIN - 1e-9
  v_at = next(v for s, v, *_ in rows if s >= x_curve - 5.0)
  assert v_at <= v_map + 1.0
  assert min(v for s, v, *_ in rows) >= v_map - 0.6


def test_vision_only_and_map_only_agree_on_the_same_curve_speed():
  p_vis, p_map = CurveSpeedPlanner(), CurveSpeedPlanner()
  k = 0.02
  v_curve = (LAT / k) ** 0.5
  p_vis.update(20.0, DT, LAT, 0.35, vision=vision(20.0, curve_ahead(100.0, k)))
  p_map.update(20.0, DT, LAT, 0.35, vision=None, map_speed=v_curve, map_speed_raw=v_curve)
  assert p_vis.v_limit == pytest.approx(p_map.v_limit, rel=1e-6)
  assert p_map.raw < 0.0


def test_fused_envelope_takes_the_slower_source():
  p = CurveSpeedPlanner()
  p.update(20.0, DT, LAT, 0.35, vision=vision(20.0, curve_ahead(100.0, 0.02)), map_speed=7.0, map_speed_raw=7.0)
  assert p.v_limit == pytest.approx(7.0)


def test_module_reads_no_deceleration_profile():
  import inspect
  src = inspect.getsource(C)
  code = src.split('"""', 2)[2]
  assert "DecelerationProfile" not in code and "profile" not in code.lower()
