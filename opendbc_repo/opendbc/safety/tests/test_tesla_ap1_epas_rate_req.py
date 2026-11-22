#!/usr/bin/env python3
"""BogPilot AP1 safety (TESLA_FLAG_AP1): a latched EAC_ERROR_HIGH_ANGLE_RATE_REQ (7) does not lock lateral out for good.

Recorded on the bench comma: after a 130 ms card stall the EPAS went ACTIVE/0 -> AVAILABLE/0 -> INHIBITED/7 ->
AVAILABLE/7 and kept code 7 for the rest of the drive. The panda refused every ANGLE frame with code 7, and the car side
never sent one, so lateral stayed off. The panda now lets an active steering frame through with code 7 only while the
same EPAS_sysStatus (0x370) frame says AVAILABLE (not ACTIVE) and the last EPB_epasControl (0x214, bus 0) said
EPB_epasEACAllow == 1 less than 250 ms ago: the code 4 rule with a tighter status. Rate tables, the lateral-accel
bound and controls_allowed still apply. Raw-wire tests.
"""
import itertools
import unittest

from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_ap1_epas_tmp_fault import (AP1, AP1_NO_LONG, ACTIVE, AVAILABLE, EPB_CASES, EPB_TIMEOUT_US,
                                                               FAULT, HANDS_ON, HIGH_ANGLE_REQ, IDLE, INHIBITED, SAFETY_TESLA,
                                                               SNA, T0, TMP_FAULT, TestTeslaAp1EpasTmpFault, di_state, epas, epb)

l = libsafety_py.libsafety
RATE_REQ = 7


class TestTeslaAp1EpasRateReq(TestTeslaAp1EpasTmpFault):
  # Inherits the helpers only; the code 4 tests run in their own module (disabled below).

  def test_code7_matrix_status_epb_controls_allowed(self):
    for param, status, epb_case, allowed, ctype in itertools.product(
        (AP1, AP1_NO_LONG), range(8), EPB_CASES, (True, False), (1, 2)):
      self.init(param)
      self.wheel(0.0, status, RATE_REQ)
      self.set_epb(epb_case)
      if not allowed:
        l.set_controls_allowed(False)
      fresh = epb_case is not None and epb_case[0] == 1 and epb_case[1] < EPB_TIMEOUT_US
      want = allowed and status == AVAILABLE and fresh
      self.assertEqual(self.tx(0, ctype), want, (param, status, epb_case, allowed, ctype))

  def test_code7_active_inhibited_fault_sna_stay_blocked(self):
    for status in (ACTIVE, INHIBITED, FAULT, SNA, 5, 6, 7):
      self.init()
      self.wheel(0.0, status, RATE_REQ)
      self.set_epb((1, 0))
      self.assertFalse(self.tx(0), status)

  def test_code7_needs_the_epb_allow(self):
    self.init()
    self.wheel(0.0, AVAILABLE, RATE_REQ)
    self.assertFalse(self.tx(0), "no 0x214 since init")
    self.set_epb((0, 0))
    self.assertFalse(self.tx(0), "EPB not allowing")
    self.set_epb((1, EPB_TIMEOUT_US))
    self.assertFalse(self.tx(0), "stale EPB allow")
    self.set_epb((1, EPB_TIMEOUT_US - 1))
    self.assertTrue(self.tx(0))

  def test_code7_never_engaged_is_dropped(self):
    self.init(engage=False)
    self.wheel(0.0, AVAILABLE, RATE_REQ)
    self.set_epb((1, 0))
    self.assertFalse(l.get_controls_allowed())
    self.assertFalse(self.tx(0))

  def test_code7_rate_table_and_lat_accel_still_apply(self):
    self.init()
    self.wheel(0.0, AVAILABLE, RATE_REQ)
    self.set_epb((1, 0))
    self.assertTrue(self.tx(0))
    self.assertFalse(self.tx(400), "rate table still applies")

  def test_code7_flag_follows_each_0x370_frame(self):
    self.init()
    self.set_epb((1, 0))
    self.wheel(0.0, AVAILABLE, RATE_REQ)
    self.assertTrue(self.tx(0))
    self.wheel(0.0, ACTIVE, RATE_REQ)
    self.assertFalse(self.tx(0), "ACTIVE with code 7 is not the latched-AVAILABLE case")
    self.wheel(0.0, AVAILABLE, 9)
    self.assertFalse(self.tx(0), "a new error replaces the latched code 7")
    self.wheel(0.0, AVAILABLE, RATE_REQ)
    self.assertTrue(self.tx(0))

  def test_init_clears_the_code7_state(self):
    self.init()
    self.wheel(0.0, AVAILABLE, RATE_REQ)
    self.set_epb((1, 0))
    self.assertTrue(self.tx(0))
    self.init()
    self.assertTrue(self.tx(0), "clean status after re-init")
    self.wheel(0.0, AVAILABLE, RATE_REQ)
    self.assertFalse(self.tx(0), "no EPB frame since init")

  def test_recorded_sequence(self):
    # Bench comma, combined build 3: ACTIVE/IDLE -> AVAILABLE/IDLE -> INHIBITED/7 -> AVAILABLE/7 (latched), EPB allow 1 at
    # 10 Hz throughout. Then the recovery request clears it: AVAILABLE/IDLE -> ACTIVE/IDLE.
    self.init()
    self.set_epb((1, 0))
    for status, error, want in ((ACTIVE, IDLE, True), (AVAILABLE, IDLE, True), (INHIBITED, RATE_REQ, False),
                                (AVAILABLE, RATE_REQ, True), (AVAILABLE, IDLE, True), (ACTIVE, IDLE, True)):
      self.assertTrue(l.safety_rx_hook(epb(1)))
      self.wheel(0.0, status, error)
      self.assertEqual(self.tx(0), want, (status, error))

  def test_other_codes_unchanged(self):
    # 0/3/6 pass from AVAILABLE/ACTIVE without EPB; 4 keeps its own rule; every other code stays blocked
    for status, error in itertools.product((AVAILABLE, ACTIVE), range(16)):
      if error in (TMP_FAULT, RATE_REQ):
        continue
      self.init()
      self.wheel(0.0, status, error)
      self.set_epb((1, 0))
      self.assertEqual(self.tx(0), error in (IDLE, HANDS_ON, HIGH_ANGLE_REQ), (status, error))

  def test_model_3y_path_is_not_changed_by_code7(self):
    for param in (0, 1):
      self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
      l.init_tests()
      l.set_timer(T0)
      l.safety_rx_hook(epb(1))
      l.safety_rx_hook(epas(0.0, AVAILABLE, RATE_REQ))
      l.safety_rx_hook(di_state(2))
      l.set_controls_allowed(True)
      l.set_desired_angle_last(0)
      self.assertTrue(self.tx(0, 0), param)


# Only the code 7 tests above run from this module.
for _name in list(vars(TestTeslaAp1EpasTmpFault)):
  if _name.startswith("test_") and _name not in vars(TestTeslaAp1EpasRateReq):
    setattr(TestTeslaAp1EpasRateReq, _name, None)
del TestTeslaAp1EpasTmpFault  # do not collect the code 4 suite twice

if __name__ == "__main__":
  unittest.main()
