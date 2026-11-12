from opendbc.car import DT_CTRL
from opendbc.car.tesla_ap1.long_smooth import AP1_GAS_HANDOFF_MAX, AP1_RISE_JERK, Ap1AccelSmoother


def _press(s, a_ego, v=15.0, n=20):
  for _ in range(n):
    assert s.update(0.8, True, v, gas_neutral=True, a_ego=a_ego) == 0.0


def test_release_continues_from_measured_accel_no_zero_dip():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  out = [s.update(1.5, True, 15.0) for _ in range(5)]
  assert out[0] >= 1.2 and min(out) >= 1.2


def test_release_into_lower_plan_uses_soft_release():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  first = s.update(0.0, True, 15.0)
  assert 1.1 < first < 1.2  # soft start, not a step to 0


def test_hard_brake_after_release_passes_through():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  assert s.update(-2.5, True, 15.0) == -2.5


def test_fcw_ignores_seed():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  assert s.update(-1.5, True, 15.0, urgent=True, fcw=True) == -1.5


def test_seed_clipped_and_low_speed_ignored():
  s = Ap1AccelSmoother()
  _press(s, 5.0)
  assert abs(s.update(3.0, True, 15.0) - AP1_GAS_HANDOFF_MAX) < 0.03
  s = Ap1AccelSmoother()
  _press(s, 1.0, v=0.5)
  assert s.update(0.3, True, 0.5) == 0.3
  s = Ap1AccelSmoother()
  _press(s, -1.0)
  assert s.update(0.5, True, 15.0) <= 0.5


def test_inactive_keeps_seed_across_the_lat_only_gap():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  for _ in range(20):                        # ~200 ms of LongEngageGate, long not yet active
    s.update(0.0, False, 15.0)
  first = s.update(0.0, True, 15.0)
  assert first > 1.1                         # seed survived the gap, not a snap to the plan


def test_first_frame_after_gas_release_starts_at_measured_accel():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  first = s.update(1.5, True, 15.0)
  assert first >= 1.2
  assert first <= 1.2 + AP1_RISE_JERK * DT_CTRL + 1e-9


def test_higher_plan_rises_from_the_seed_at_rise_jerk():
  s = Ap1AccelSmoother()
  _press(s, 0.62)
  out = [s.update(1.15, True, 15.0) for _ in range(60)]
  assert abs(out[0] - 0.62) < AP1_RISE_JERK * DT_CTRL + 1e-9
  # Rise at AP1_RISE_JERK until the plan, then hold (0.62 -> 1.15 is 0.212 s).
  rising = [a for a in out if a < 1.15 - 1e-9]
  assert len(rising) >= 2
  step = AP1_RISE_JERK * DT_CTRL
  assert all(abs((b - a) - step) < 1e-6 for a, b in zip(rising, rising[1:]))
  assert all(b >= a for a, b in zip(out, out[1:]))
  assert max(out) <= 1.15 + 1e-9
  assert out[-1] == 1.15


def test_lower_plan_is_reached_by_the_drive_release_s_curve():
  s = Ap1AccelSmoother()
  _press(s, 0.62)
  out = [s.update(0.15, True, 15.0) for _ in range(200)]
  assert out[0] > 0.5                          # no 0.10 cap
  assert min(out) >= 0.15 - 1e-9
  assert abs(out[-1] - 0.15) < 1e-6


def test_urgent_and_hard_brake_still_pass_through():
  for kw in ({"urgent": True}, {"urgent": True, "fcw": True}):
    s = Ap1AccelSmoother()
    _press(s, 1.2)
    assert s.update(-1.5, True, 15.0, **kw) == -1.5
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  assert s.update(-2.5, True, 15.0) == -2.5


def test_lift_into_shallow_regen_does_not_step_the_request_to_zero():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  first = s.update(-0.4, True, 15.0)
  assert first > 1.0                           # drive-release, not a snap to 0 or 0.10


def test_cold_engage_without_aego_still_takes_the_plan():
  s = Ap1AccelSmoother()
  assert s.update(1.0, True, 15.0) == 1.0
  s = Ap1AccelSmoother()
  _press(s, 1.0, v=0.5)
  assert s.update(0.3, True, 0.5) == 0.3


def test_unused_seed_expires_after_the_hold():
  from opendbc.car.tesla_ap1.long_smooth import AP1_GAS_SEED_HOLD
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  n = int(AP1_GAS_SEED_HOLD / DT_CTRL) + 5
  for _ in range(n):
    s.update(0.0, False, 15.0)
  assert s.update(1.5, True, 15.0) == 1.5   # hold expired: fresh start from the plan


def test_tapered_lift_during_the_lag_keeps_the_peak():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  # Driver eases off over 0.2 s while long is still inactive; last aEgo is 0.
  for i in range(20):
    a = 1.2 * (1.0 - (i + 1) / 20.0)
    s.update(0.0, False, 15.0, a_ego=a, gas_pressed=True)
  s.update(0.0, False, 15.0, a_ego=0.0, gas_pressed=False)
  first = s.update(0.0, True, 15.0, a_ego=-0.1)
  assert first > 1.1                       # peak 1.2, not the last-frame 0


def test_gas_pressed_before_enabled_still_latches():
  s = Ap1AccelSmoother()
  for _ in range(20):
    # Pedal down, CC.enabled still false: gas_neutral is false.
    s.update(0.0, False, 15.0, gas_neutral=False, a_ego=1.1, gas_pressed=True)
  s.update(0.0, False, 15.0, gas_pressed=False, a_ego=0.0)
  first = s.update(0.0, True, 15.0, a_ego=-0.2)
  assert first > 1.0


def test_engage_seeds_from_aego_without_prior_gas_press():
  s = Ap1AccelSmoother()
  first = s.update(0.0, True, 15.0, a_ego=1.1)
  assert 1.0 < first <= 1.1                    # seed, then a gentle slew toward the plan
  out = [first] + [s.update(0.0, True, 15.0, a_ego=1.1) for _ in range(20)]
  assert all(b <= a + 1e-9 for a, b in zip(out, out[1:]))
  assert min(out) >= 0.0
  assert out[0] - out[-1] < 0.6                # not a thump to 0 in 0.2 s


def test_gas_press_during_handoff_relatches_and_the_next_release_reseeds():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  for _ in range(20):
    s.update(1.5, True, 15.0)
  assert s.update(1.5, True, 15.0, gas_neutral=True, a_ego=0.9) == 0.0
  first = s.update(1.5, True, 15.0)
  assert abs(first - 0.9) < AP1_RISE_JERK * DT_CTRL + 1e-9


def test_inactive_then_engage_with_aego_reseeds():
  s = Ap1AccelSmoother()
  _press(s, 1.2)
  s.update(0.0, False, 15.0)
  first = s.update(0.2, True, 15.0, a_ego=1.0)
  assert first >= 0.9
