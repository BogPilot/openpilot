"""CSC entry seed: start from the speed the curve allows, not from v_ego (no one-frame dip under the set speed)."""
import math

import pytest

from openpilot.selfdrive.controls.lib.ap1_curve_brake import TESLA_CSC_MAX_LAT_ACCEL
from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed
from openpilot.selfdrive.controls.lib.bogpilot_csc import CurveSpeedController
from openpilot.selfdrive.controls.tests.csc_replay_helpers import DT_MDL, Store, csc_sm, ns

LAT = TESLA_CSC_MAX_LAT_ACCEL


def k_for(speed):
  return LAT / speed ** 2


def csc():
  return CurveSpeedController(Store(), TESLA_CSC_MAX_LAT_ACCEL)


def test_legacy_call_still_seeds_at_v_ego():
  c = csc()
  c.update_target(30.0, k_for(45.0), 2.0)
  assert c.target == 30.0


@pytest.mark.parametrize("v_ego,curve_speed,cap,expected", [
  (32.57, 45.4, 34.88, 34.88),   # curve allows more than the set speed: start AT the set speed (was v_ego: the dip)
  (30.0, 33.0, 35.0, 33.0),      # curve allows a bit more than the car: start at the curve speed
  (30.0, 20.0, 35.0, 30.0),      # curve slower than the car: v_ego start, ramp down unchanged
  (36.0, 45.0, 34.0, 36.0),      # car already above the set speed: v_ego (min with the cap still gives the cap)
])
def test_seed_is_the_curve_envelope_inside_v_ego_and_cap(v_ego, curve_speed, cap, expected):
  c = csc()
  c.update_target(v_ego, k_for(curve_speed), 2.0, cap)
  assert c.target == pytest.approx(expected)
  assert min(c.target, cap) >= min(v_ego, cap) - 1e-9  # the cruise speed never starts below the car or the cap


@pytest.mark.parametrize("cap", [None, float("nan"), float("inf"), 0.0, 3.0])
def test_invalid_cap_falls_back_to_v_ego(cap):
  c = csc()
  c.update_target(30.0, k_for(45.0), 2.0, cap)
  assert c.target == 30.0


def test_genuine_curve_ramp_is_unchanged_by_the_seed():
  a, b = csc(), csc()
  for i in range(60):
    a.update_target(30.0, k_for(15.0), 4.0)
    b.update_target(30.0, k_for(15.0), 4.0, 35.0)
    assert a.target == b.target


def planner_csc():
  cp = ns(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True)
  return Ap1CurveSpeed(cp, DT_MDL, store=Store())


def test_entry_does_not_dip_below_the_set_speed_when_the_curve_allows_it():
  # logged case: ego 72.866 mph, set 78 mph, steady-state curve speed 101.6 mph
  mph = 0.44704
  v_ego, cap = 72.866 * mph, 78.0 * mph
  curve_speed = 101.631 * mph
  p = planner_csc()
  out = []
  for _ in range(10):
    out.append(p.update(csc_sm(v_ego, k=k_for(curve_speed)), v_ego, cap, False))
  assert p.controlling
  assert all(v == pytest.approx(cap) for v in out)


def test_entry_with_a_slower_curve_still_starts_at_v_ego_and_never_exceeds_the_cap():
  mph = 0.44704
  v_ego, cap = 70.0 * mph, 78.0 * mph
  p = planner_csc()
  first = p.update(csc_sm(v_ego, k=k_for(40.0 * mph)), v_ego, cap, False)
  assert first == pytest.approx(v_ego)
  later = [p.update(csc_sm(v_ego, k=k_for(40.0 * mph)), v_ego, cap, False) for _ in range(200)]
  assert max(later) <= v_ego + 1e-9 and min(later) < v_ego
