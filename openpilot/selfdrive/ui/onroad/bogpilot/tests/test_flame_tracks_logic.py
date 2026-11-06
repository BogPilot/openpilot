"""Unit tests for Bog to the Future flame-track trigger (no pyray).

Mirrors bogpilot-tesla bsm_flame_tracks.h FlameTrigger: 88 mph, 0.5 s grace, 3 s burn,
flame height 0.55, toggle default ON.
"""
from __future__ import annotations
import math
import unittest

from openpilot.selfdrive.ui.onroad.bogpilot.flame_tracks_logic import (
  DURATION_MS,
  FLAME_HEIGHT_SCALE,
  GRACE_MS,
  MPH_TO_MS,
  TOGGLE_DEFAULT,
  TOGGLE_KEY,
  TRIGGER_SPEED_MS,
  FlameSideInput,
  FlameTrigger,
)


def _in(red: bool = False, status: bool = False, v: float = 0.0) -> FlameSideInput:
  return FlameSideInput(red_fill_shown=red, lead_status=status, lead_v=v)


class TestFlameConstants(unittest.TestCase):
  def test_trigger_is_88_mph(self):
    self.assertAlmostEqual(TRIGGER_SPEED_MS, 88.0 * 0.44704, places=5)
    self.assertAlmostEqual(MPH_TO_MS, 0.44704, places=5)

  def test_duration_and_grace(self):
    self.assertEqual(DURATION_MS, 3000)
    self.assertEqual(GRACE_MS, 500)

  def test_flame_height_classic(self):
    self.assertAlmostEqual(FLAME_HEIGHT_SCALE, 0.55, places=5)

  def test_toggle_default_on(self):
    self.assertEqual(TOGGLE_KEY, "BSMFlameTracks")
    self.assertTrue(TOGGLE_DEFAULT)


class TestFlameTrigger(unittest.TestCase):
  def setUp(self):
    self.t = FlameTrigger()

  def test_no_fire_while_fill_shown(self):
    fast = 89.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True, True, fast), _in()])
    self.assertFalse(self.t.any_active())

  def test_fires_on_fill_off_with_fast_lead(self):
    fast = 89.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True, True, fast), _in()])
    self.t.update(100, True, [_in(False, True, fast), _in()])
    self.assertTrue(self.t.active(0))
    self.assertFalse(self.t.active(1))
    self.assertAlmostEqual(self.t.progress(0, 100), 0.0, places=5)

  def test_no_fire_at_exactly_88(self):
    # strictly faster than 88 mph
    exact = 88.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True, True, exact), _in()])
    self.t.update(100, True, [_in(False, True, exact), _in()])
    self.assertFalse(self.t.any_active())

  def test_no_fire_without_lead_status(self):
    fast = 100.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True, False, fast), _in()])
    self.t.update(100, True, [_in(False, False, fast), _in()])
    self.assertFalse(self.t.any_active())

  def test_grace_window_allows_late_speed(self):
    slow = 50.0 * MPH_TO_MS
    fast = 90.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True), _in()])
    self.t.update(100, True, [_in(False, True, slow), _in()])  # arm, but slow
    self.assertFalse(self.t.any_active())
    self.t.update(400, True, [_in(False, True, fast), _in()])  # within 500 ms grace
    self.assertTrue(self.t.active(0))

  def test_grace_expires(self):
    fast = 90.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True), _in()])
    self.t.update(100, True, [_in(False, True, 0.0), _in()])  # arm
    self.t.update(700, True, [_in(False, True, fast), _in()])  # 600 ms after off > grace
    self.assertFalse(self.t.any_active())

  def test_burn_ends_after_duration(self):
    fast = 90.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True, True, fast), _in()])
    self.t.update(50, True, [_in(False, True, fast), _in()])
    self.assertTrue(self.t.active(0))
    self.assertAlmostEqual(self.t.progress(0, 50 + 1500), 0.5, places=5)
    self.t.update(50 + DURATION_MS, True, [_in(False, True, fast), _in()])
    self.assertFalse(self.t.active(0))
    self.assertEqual(self.t.progress(0, 50 + DURATION_MS), -1.0)

  def test_disabled_clears(self):
    fast = 90.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True, True, fast), _in()])
    self.t.update(50, True, [_in(False, True, fast), _in()])
    self.assertTrue(self.t.active(0))
    self.t.update(60, False, [_in(False, True, fast), _in()])
    self.assertFalse(self.t.any_active())

  def test_right_side_independent(self):
    fast = 90.0 * MPH_TO_MS
    self.t.update(0, True, [_in(), _in(True, True, fast)])
    self.t.update(50, True, [_in(), _in(False, True, fast)])
    self.assertFalse(self.t.active(0))
    self.assertTrue(self.t.active(1))

  def test_rearm_requires_new_off_edge(self):
    fast = 90.0 * MPH_TO_MS
    self.t.update(0, True, [_in(True, True, fast), _in()])
    self.t.update(50, True, [_in(False, True, fast), _in()])
    self.t.update(50 + DURATION_MS, True, [_in(False, True, fast), _in()])
    self.assertFalse(self.t.any_active())
    # still off + fast: no second burn without a new on->off edge
    self.t.update(50 + DURATION_MS + 100, True, [_in(False, True, fast), _in()])
    self.assertFalse(self.t.any_active())
    # new fill then off
    self.t.update(4000, True, [_in(True, True, fast), _in()])
    self.t.update(4100, True, [_in(False, True, fast), _in()])
    self.assertTrue(self.t.active(0))


if __name__ == "__main__":
  unittest.main()
