"""Lead-aware accel cap (AdaptiveAccelLead): pure maths, NAP-equivalent values, and the Profiles read. No planner, runs anywhere."""
import math

import pytest

from openpilot.selfdrive.controls.lib import lead_accel_cap as lac
from openpilot.selfdrive.controls.lib.phase3_long_accel import Profiles


def test_values_are_nap_s_follow_table_unchanged():
  # Credit: NAP (MIT) opendbc/car/tesla/preap/constants.py ACCEL_PREAP_BP / ACCEL_PREAP_FOLLOW and the 1.2x..1.5x blend.
  assert lac.FOLLOW_BP == (0.0, 1.3, 7.5, 15.0, 25.0, 30.0, 40.0)
  assert lac.FOLLOW_ACCEL == (0.3, 0.6, 0.9, 0.8, 0.7, 0.5, 0.45)
  assert (lac.FULL_RATIO, lac.NONE_RATIO) == (1.2, 1.5)


def test_constants_match_the_mpc():
  try:
    from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib import long_mpc as mpc
  except Exception as e:   # no native msgq/acados on this machine (a Mac): the AGNOS run covers it
    pytest.skip(f"mpc not importable here: {type(e).__name__}")
  assert (lac.COMFORT_BRAKE, lac.STOP_DISTANCE) == (mpc.COMFORT_BRAKE, mpc.STOP_DISTANCE)


def test_follow_limit_interpolates_the_table():
  assert lac.follow_limit(0.0) == pytest.approx(0.3)
  assert lac.follow_limit(7.5) == pytest.approx(0.9)
  assert lac.follow_limit(11.25) == pytest.approx(0.85)
  assert lac.follow_limit(100.0) == pytest.approx(0.45)


def safe_gap(v, t_follow=1.45):
  return v ** 2 / (2 * lac.COMFORT_BRAKE) + t_follow * v + lac.STOP_DISTANCE


def test_far_lead_is_not_capped_close_lead_is():
  v, t = 20.0, 1.45
  far = 1.6 * safe_gap(v, t)
  assert lac.cap_strength(v, far, v, t) == 0.0 and lac.lead_accel_cap(1.0, v, far, v, t) is None
  near = 1.0 * safe_gap(v, t)
  assert lac.cap_strength(v, near, 0.0, t) == pytest.approx(1.0)
  assert lac.lead_accel_cap(1.2, v, near, 0.0, t) == pytest.approx(lac.follow_limit(v))


def test_blend_is_linear_between_the_two_ratios():
  v, t = 15.0, 1.45
  mid = 1.35 * safe_gap(v, t)      # lead speed 0 -> obstacle == distance
  assert lac.cap_strength(v, mid, 0.0, t) == pytest.approx(0.5)
  assert lac.lead_accel_cap(1.4, v, mid, 0.0, t) == pytest.approx(0.5 * 1.4 + 0.5 * lac.follow_limit(v))


def test_never_raises_the_ceiling_and_never_negative():
  for v in (0.0, 1.0, 5.0, 12.0, 25.0, 40.0):
    for gap in (0.0, 3.0, 10.0, 40.0, 80.0, 200.0):
      for ceiling in (0.2, 0.9, 1.6, 2.0):
        cap = lac.lead_accel_cap(ceiling, v, gap, 0.0, 1.45)
        assert cap is None or 0.0 <= cap <= ceiling


def test_stopped_lead_is_closer_than_it_looks_but_a_fast_lead_counts_as_farther():
  v, t, gap = 20.0, 1.45, 1.3 * safe_gap(20.0)
  assert lac.cap_strength(v, gap, 0.0, t) > lac.cap_strength(v, gap, 20.0, t)


def test_bad_inputs_leave_the_plan_alone():
  for bad in (math.nan, math.inf):
    assert lac.lead_accel_cap(bad, 10.0, 20.0, 5.0, 1.45) is None
    assert lac.lead_accel_cap(1.0, bad, 20.0, 5.0, 1.45) is None
    assert lac.lead_accel_cap(1.0, 10.0, bad, 5.0, 1.45) is None


class Store:
  def __init__(self, adaptive=None, raises=False):
    self.adaptive, self.raises = adaptive, raises
    self.acked = True

  def get_bool(self, key, default=False):
    return True

  def toggle_bool(self, key, level=None):
    if key == "AdaptiveAccelLead":
      if self.raises:
        raise KeyError(key)
      return bool(self.adaptive)
    return True

  def toggle_int(self, key, level=None):
    return 0


def test_profiles_read_default_is_off():
  assert Profiles().adaptive_lead is False
  assert Profiles.read(Store(adaptive=False), "TESLA_AP1_MODELS").adaptive_lead is False
  assert Profiles.read(Store(adaptive=True), "TESLA_AP1_MODELS").adaptive_lead is True


def test_a_params_library_without_the_key_keeps_the_other_profiles():
  prof = Profiles.read(Store(raises=True), "TESLA_AP1_MODELS")
  assert prof is not None and prof.adaptive_lead is False
