"""t1394: Pre-AP pedal set-speed capture. NAP rounding to the display unit, the AP1 from-stop setting on the standstill-hold release,
and the from-stop speed replacing the 40 km/h first-pull floor. AP1 / stock paths unchanged."""
import unittest
from types import SimpleNamespace as NS

from openpilot.common.constants import CV
from openpilot.selfdrive.car import cruise as cr

PREAP = NS(pcmCruise=False)
MPH = CV.MPH_TO_KPH


def helper():
  return cr.VCruiseHelper(PREAP)


class TestRounding(unittest.TestCase):
  def test_nap_rounding_mph_and_kph(self):
    self.assertAlmostEqual(cr.preap_round_kph(37.4 * CV.MPH_TO_MS, False), 37 * MPH)
    self.assertAlmostEqual(cr.preap_round_kph(37.5 * CV.MPH_TO_MS, False), 38 * MPH)
    self.assertAlmostEqual(cr.preap_round_kph(61.6 / 3.6, True), 62.0)
    self.assertEqual(cr.preap_round_kph(-1.0, False), 0.0)

  def test_full_capture_rounds_when_the_unit_is_given(self):
    h = helper()
    h.capture_preap_full(37.4 * CV.MPH_TO_MS, 0.0, is_metric=False)
    self.assertAlmostEqual(h.v_cruise_kph, 37 * MPH)
    h.capture_preap_full(61.6 / 3.6, 0.0, is_metric=True)
    self.assertAlmostEqual(h.v_cruise_kph, 62.0)

  def test_legacy_call_is_exact_vego(self):
    h = helper()
    h.capture_preap_full(10.0, 0.0)
    self.assertAlmostEqual(h.v_cruise_kph, 36.0)

  def test_set_speed_limit_still_wins(self):
    h = helper()
    h.capture_preap_full(10.0, 72.4, is_metric=False, from_stop_kph=24.14)
    self.assertEqual(h.v_cruise_kph, 72)


class TestFromStop(unittest.TestCase):
  def test_hold_release_is_at_least_the_from_stop_speed(self):
    h = helper()
    h.capture_preap_full(3.0 * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=15 * MPH)
    self.assertAlmostEqual(h.v_cruise_kph, 15 * MPH)
    h.capture_preap_full(22.0 * CV.MPH_TO_MS, 0.0, is_metric=False, from_stop_kph=15 * MPH)
    self.assertAlmostEqual(h.v_cruise_kph, 22 * MPH)   # released faster than the setting: the rounded speed

  def test_first_pull_no_floor_and_from_stop_at_a_stop(self):
    h = helper()
    h.initialize_v_cruise(NS(vEgo=12.0 * CV.MPH_TO_MS, buttonEvents=[]), False, 0.0, preap_from_stop_kph=15 * MPH, is_metric=False)
    self.assertAlmostEqual(h.v_cruise_kph, 12 * MPH)   # no 40 km/h floor
    h.initialize_v_cruise(NS(vEgo=0.0, buttonEvents=[]), False, 0.0, preap_from_stop_kph=20 * MPH, is_metric=False)
    self.assertAlmostEqual(h.v_cruise_kph, 20 * MPH)

  def test_without_preap_arg_the_stock_floor_stays(self):
    h = helper()
    h.initialize_v_cruise(NS(vEgo=5.0, buttonEvents=[]), False, 0.0)
    self.assertEqual(h.v_cruise_kph, cr.V_CRUISE_INITIAL)


class TestEngagementFlag(unittest.TestCase):
  def test_decision_carries_capture_from_stop(self):
    from opendbc.car.tesla_ap1.preap.engagement import Decision
    self.assertFalse(Decision().capture_from_stop)
    self.assertTrue(Decision(capture_edge=True, capture_from_stop=True).capture_from_stop)


if __name__ == "__main__":
  unittest.main()
