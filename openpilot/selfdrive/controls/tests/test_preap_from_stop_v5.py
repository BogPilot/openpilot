"""Card wiring for the Pre-AP from-stop rule and the tip latch (source checks; card.py imports msgq, not in this env)."""
import pathlib
import unittest

from openpilot.common.constants import CV
from openpilot.selfdrive.car import cruise as cr
from openpilot.selfdrive.car.cruise import VCruiseHelper

MPH = CV.MPH_TO_KPH


class NS:
  def __init__(self, **kw):
    self.__dict__.update(kw)


class TestCapture(unittest.TestCase):
  def helper(self):
    return VCruiseHelper(NS(pcmCruise=False))

  def test_from_stop_on_the_entry_is_exact(self):
    h = self.helper()
    h.capture_preap_full(0.0, 0.0, is_metric=False, from_stop_kph=15 * MPH)
    self.assertAlmostEqual(h.v_cruise_kph, 15 * MPH)
    h.capture_preap_full(0.0, 0.0, is_metric=True, from_stop_kph=5 * MPH)
    self.assertAlmostEqual(h.v_cruise_kph, 5 * MPH)

  def test_tip_latch_is_rounded_current_speed_below_from_stop(self):
    h = self.helper()
    h.capture_preap_full(8.4 * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=0.0)
    self.assertAlmostEqual(h.v_cruise_kph, 8 * MPH)

  def test_moving_double_pull_below_from_stop_is_raised_and_above_is_kept(self):
    h = self.helper()
    h.capture_preap_full(8.4 * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=15 * MPH)   # raised
    self.assertAlmostEqual(h.v_cruise_kph, 15 * MPH)
    h.capture_preap_full(22.4 * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=15 * MPH)  # above from-stop: current speed
    self.assertAlmostEqual(h.v_cruise_kph, 22 * MPH)

  def test_down_tips_reach_the_stock_minimum(self):
    h = self.helper()
    self.assertEqual(cr.V_CRUISE_MIN, 8)


class TestCardWiring(unittest.TestCase):
  SRC = (pathlib.Path(__file__).resolve().parents[2] / "car" / "card.py").read_text()

  def test_tip_entry_skips_set_speed_limit(self):
    self.assertIn('tip_entry = bool(getattr(self.CI.CS, "preap_capture_tip", False))', self.SRC)
    self.assertIn("self.preap_engage_set_limit is not None and not tip_entry:", self.SRC)

  def test_from_stop_still_only_with_the_stop_flag(self):
    self.assertIn('getattr(self.CI.CS, "preap_capture_from_stop", False)', self.SRC)


if __name__ == "__main__":
  unittest.main()
