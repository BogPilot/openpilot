"""AP1 set-speed reaction shaping in get_cruise_accel."""
import types
import numpy as np
import pytest
from openpilot.selfdrive.controls.lib import longitudinal_planner as lp
from openpilot.selfdrive.controls.lib.ap1_planning import AP1_CRUISE_GAIN, AP1_CRUISE_J_SCALE

CP = types.SimpleNamespace(steerRatio=15.0, wheelbase=2.96)
MPH = 0.44704


def run(v_set, v, shape, prev=0.0, profile=None, e2e=False, steps=1, dt=0.05):
  a = prev
  for _ in range(steps):
    a = lp.get_cruise_accel(e2e, v_set, v, a, 0.0, CP, dt, -0.3, True, profile, ap1_shape=shape)
  return a


def test_ap1_cruise_constants_are_pinned():
  # The tests below use the imported constants; pin them so a changed value cannot pass silently.
  assert (AP1_CRUISE_J_SCALE, AP1_CRUISE_GAIN) == (0.40, 0.30)   # pinned: ap1_planning.py:14-15, intentional AP1 shaping


def test_default_is_the_stock_law_for_every_other_car():
  # shape off (the default argument): the stock proportional law, stock jerk, stock floor
  a = lp.get_cruise_accel(False, 15.0, 14.0, 0.0, 0.0, CP, 0.05, -0.3, True, None)
  assert a == pytest.approx(float(np.interp(14.0, lp.A_CRUISE_MAX_BP, lp.J_CRUISE_VALS)) * 0.05)
  assert run(15.0, 14.0, False, steps=400) == pytest.approx(1.0)
  assert run(5.0, 30.0, False, steps=2000) == pytest.approx(lp.A_CRUISE_MIN)


def test_plateau_is_gain_times_error_when_shaped():
  # +5 mph at 28 mph (error 2.24 m/s): plateau = gain * error, below the stock max accel
  v = 28 * MPH
  a = run(v + 5 * MPH, v, True, steps=400)
  assert a == pytest.approx(AP1_CRUISE_GAIN * 5 * MPH, abs=1e-6)
  assert a < 0.7


def test_one_mph_tap_is_gentle():
  v = 33 * MPH
  down = run(v - 1 * MPH, v, True, steps=400)
  assert down == pytest.approx(-AP1_CRUISE_GAIN * MPH, abs=1e-6)
  assert abs(down) < 0.15
  assert abs(run(v - 1 * MPH, v, False, steps=400)) > 0.4   # stock 0.11.2 reaction for comparison


def test_there_is_no_extra_shape_floor_the_profile_or_the_stock_floor_decides():
  # rc5: the temporary -0.875 shape floor is gone; with no profile the stock A_CRUISE_MIN (-1.2) applies
  v = 30.0
  assert run(5.0, v, True, steps=2000) == pytest.approx(lp.A_CRUISE_MIN)
  assert run(5.0, v, False, steps=2000) == pytest.approx(lp.A_CRUISE_MIN)
  # an adopted Gas/Brake profile owns the floor (Eco+ -0.875 by default on the legacy Tesla platforms)
  assert run(5.0, v, True, profile=(-1.0, 1.0), steps=2000) == pytest.approx(-1.0)
  assert run(5.0, v, True, profile=(-0.875, 1.0), steps=2000) == pytest.approx(-0.875)


def test_jerk_is_scaled_and_bounded():
  v = 12.5
  j_stock = float(np.interp(v, lp.A_CRUISE_MAX_BP, lp.J_CRUISE_VALS))
  a1 = run(v + 10.0, v, True, steps=1)
  assert a1 == pytest.approx(j_stock * AP1_CRUISE_J_SCALE * 0.05)
  a2 = run(v - 10.0, v, True, steps=1)
  assert a2 == pytest.approx(-j_stock * AP1_CRUISE_J_SCALE * 0.05)


def test_max_accel_and_throttle_cut_limits_still_apply():
  v = 3.0
  a = run(30.0, v, True, steps=2000)
  assert a <= float(np.interp(v, lp.A_CRUISE_MAX_BP, lp.A_CRUISE_MAX_VALS)) + 1e-9


def test_experimental_mode_is_unshaped():
  assert run(5.0, 30.0, True, e2e=True, steps=2000) == run(5.0, 30.0, False, e2e=True, steps=2000)
  assert run(20.0, 19.0, True, e2e=True, steps=5) == run(20.0, 19.0, False, e2e=True, steps=5)


def test_planner_flag_is_ap1_only():
  import inspect
  src = inspect.getsource(lp.LongitudinalPlanner.update)
  assert "ap1_shape=self.ap1_plan.active" in src


def test_hands_over_to_stock_when_error_closes():
  # approaching the set speed the shaped law converges monotonically (no overshoot or sign flip)
  v, vset, a, out = 20.0, 22.0, 0.0, []
  for _ in range(600):
    a = lp.get_cruise_accel(False, vset, v, a, 0.0, CP, 0.05, -0.3, True, None, ap1_shape=True)
    v += a * 0.05
    out.append(v)
  assert max(out) <= vset + 1e-3
  assert out[-1] == pytest.approx(vset, abs=0.1)
