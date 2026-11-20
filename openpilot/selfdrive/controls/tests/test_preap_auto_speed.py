"""Pre AP Auto Speed (TeslaPreApAutoSpeed, default OFF).

OFF: NAP-style engage. The engage / FULL capture set is the exact vEgo and the planner SLC is the bit-exact passthrough.
ON: today's behaviour (Set Speed Limit engage at limit + offset, SLC raises / lowers). AP1 S/X never read the key.
"""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import Sm, make, run, toggles, MPH
from openpilot.selfdrive.controls.tests.test_preap_set_speed_limit import CP_PREAP, MOVING, engage

CP_AP1 = NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True, pcmCruise=True, radarUnavailable=False, enableBsm=False)


class TestDefaultOff(unittest.TestCase):
  def test_default_is_off_when_the_file_is_missing(self):
    with mock.patch("opendbc.car.tesla_ap1.preap.params.get_bool", return_value=False):
      self.assertFalse(sc.preap_auto_speed_on())

  def test_read_error_is_off(self):
    with mock.patch("opendbc.car.tesla_ap1.preap.params.get_bool", side_effect=OSError):
      self.assertFalse(sc.preap_auto_speed_on())

  def test_registered_with_default_false(self):
    from opendbc.car.tesla_ap1.preap import params as pp
    from openpilot.common.bogpilot_toggles import FILE_TOGGLES
    from openpilot.system.bogpilot import settings_backup as sb
    from openpilot.system.bogpilot.toggle_reset import FILE_RESET_KEYS
    self.assertIs(pp.DEFAULTS[pp.PreApParamKeys.AUTO_SPEED], False)
    self.assertIs(FILE_TOGGLES["TeslaPreApAutoSpeed"][0], False)
    self.assertIn("TeslaPreApAutoSpeed", sb.FILE_KEYS)
    self.assertNotIn("TeslaPreApAutoSpeed", FILE_RESET_KEYS)   # backed up, never reset (user choice kept)


class TestEngageSet(unittest.TestCase):
  def test_off_engage_set_is_zero_so_capture_takes_vego(self):
    e = sc.PreapEngageSetLimit(CP_PREAP, toggles_fn=lambda: toggles(SetSpeedLimit="1"), adopted=True, auto_speed=False)
    self.assertFalse(e.active)
    self.assertEqual(e.kph(MOVING, 20.0), 0.0)

  def test_on_keeps_limit_plus_offset(self):
    self.assertGreater(engage(SetSpeedLimit="1").kph(MOVING, 20.0), 0.0)


class TestPlanner(unittest.TestCase):
  def test_off_is_passthrough_even_with_a_limit(self):
    ctl, sm = make(cp=CP_PREAP, auto_speed=False), Sm()
    out = run(ctl, sm, 30.0, 20.0, limit=35 * MPH, cruise=True)
    self.assertFalse(ctl.active)
    self.assertEqual(out, 30.0)

  def test_on_follows_the_limit(self):
    ctl, sm = make(cp=CP_PREAP, auto_speed=True), Sm()
    run(ctl, sm, 30.0, 20.0, limit=35 * MPH, cruise=True)
    self.assertTrue(ctl.active)

  def test_off_never_forces_experimental(self):
    ctl = make(toggles(SLCFallback="1"), cp=CP_PREAP, auto_speed=False)
    self.assertIs(ctl.resolve_experimental(False), False)

  def test_ap1_never_reads_the_key(self):
    with mock.patch.object(sc, "preap_auto_speed_on", side_effect=AssertionError("AP1 read the Pre-AP key")):
      self.assertTrue(sc.Ap1SpeedControl(CP_AP1, toggles_fn=lambda: toggles(), clock=lambda: 0.0, adopted=True).ap1)


class TestNoLimitFallback(unittest.TestCase):
  """t1385 decision 5: ON + no posted limit -> Experimental Mode's planned speed; the toggle and the rc7 policy are untouched."""

  def test_on_no_limit_is_experimental_for_every_fallback_choice(self):
    for fb in ("0", "1", "2"):
      ctl, sm = make(toggles(SLCFallback=fb), cp=CP_PREAP, auto_speed=True), Sm()
      run(ctl, sm, 25.0, 25.0, limit=0.0, cruise=True)
      self.assertTrue(ctl.active, fb)
      self.assertIs(ctl.resolve_experimental(False), True, fb)

  def test_on_with_a_limit_keeps_the_manual_flag(self):
    ctl, sm = make(toggles(SLCFallback="0"), cp=CP_PREAP, auto_speed=True), Sm()
    run(ctl, sm, 25.0, 25.0, limit=35 * MPH, cruise=True, n=5)
    self.assertIs(ctl.resolve_experimental(False), False)
    self.assertIs(ctl.resolve_experimental(True), True)    # rc7 "or": a manual Experimental on is never cancelled

  def test_fallback_never_writes_the_experimental_param(self):
    t = toggles(SLCFallback="0")
    ctl, sm = make(t, cp=CP_PREAP, auto_speed=True), Sm()
    run(ctl, sm, 25.0, 25.0, limit=0.0, cruise=True)
    self.assertTrue(t.slc_fallback_set_speed)               # the shared snapshot is not mutated
    self.assertFalse(t.slc_fallback_experimental_mode)

  def test_set_speed_stays_the_cap_and_a_stalk_tip_lowers_it(self):
    ctl, sm = make(toggles(SLCFallback="2"), cp=CP_PREAP, auto_speed=True), Sm()
    top = 56 * MPH   # a whole-mph speed (v6: the engage latch is a whole display unit)
    self.assertLessEqual(run(ctl, sm, top, top, limit=0.0, cruise=True, n=5), top + 1e-6)
    low = top - MPH                                              # one stalk-down tip: cruise.py lowers carState.vCruise 1 mph
    tip = run(ctl, sm, low, top, limit=0.0, cruise=True, dn=True)
    self.assertLessEqual(tip, low + 1e-6)                          # the planner set follows the tip
    out = run(ctl, sm, low, top, limit=0.0, cruise=True, n=50)   # released: the lower set stays latched
    self.assertLessEqual(out, low + 1e-6)
    self.assertLess(out, top - 0.4)
    self.assertIs(ctl.resolve_experimental(False), True)

  def test_off_and_ap1_unchanged(self):
    ctl, sm = make(toggles(SLCFallback="0"), cp=CP_PREAP, auto_speed=False), Sm()
    run(ctl, sm, 25.0, 25.0, limit=0.0, cruise=True)
    self.assertIs(ctl.resolve_experimental(False), False)
    ctl, sm = make(toggles(SLCFallback="0"), cp=CP_AP1), Sm()
    run(ctl, sm, 25.0, 25.0, limit=0.0, cruise=True)
    self.assertIs(ctl.resolve_experimental(False), False)


if __name__ == "__main__":
  unittest.main()
