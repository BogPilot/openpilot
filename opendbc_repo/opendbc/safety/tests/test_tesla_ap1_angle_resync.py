#!/usr/bin/env python3
"""Tesla AP1 safety (tesla_ap1.h): desired_angle_last follows the measured wheel while disengaged.

Ported from BogPilot panda/tests/safety/test_tesla_ap1_angle_resync.py (BogPilot 1d6669ae, milestone 4).
openpilot sends no 0x488 while disengaged on AP1 (stock Mobileye 0x488 is forwarded instead), so without
a resync the first 0x488 after an engage was rate checked against the last angle of the previous
engagement. Each EPAS_sysStatus (0x370) received while neither controls_allowed nor always-on lateral
is active now sets desired_angle_last to the measured angle. The rate window around that reference is
the same Tinkla table as before; nothing else changes.

Not a driving validation.
"""
import unittest

from opendbc.car.structs import CarParams
from opendbc.car.tesla.values import TeslaAp1SafetyFlags
from opendbc.safety import ALTERNATIVE_EXPERIENCE
from opendbc.safety.tests.libsafety import libsafety_py

AP1 = int(TeslaAp1SafetyFlags.HAS_AP | TeslaAp1SafetyFlags.LONG_CONTROL)
AOL = int(ALTERNATIVE_EXPERIENCE.ALWAYS_ON_LATERAL)

# DI_state cruise states (byte 1 >> 4)
OFF = 0
STANDBY = 1
ENABLED = 2

# 8 m/s gives vehicle_speed.min - 1 = about 7.0 m/s, a Tinkla breakpoint: up 4.0 deg/frame, down
# 5.0 deg/frame. This opendbc's steer_angle_cmd_checks accepts at most 40 / 50 (0.1 deg) per frame there
# (BogPilot's older panda accepted 41 / 51: the DI speed decodes a hair under 8 m/s here). The resync
# test only needs the first-frame window to equal the normal rate window, whatever its width.
SPEED_MPS = 8.0
DELTA_UP = 40
DELTA_DOWN = 50


def pkt(addr, dat, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(dat))


def epas_status(angle_deg):
  # EPAS_internalSAS: (0.1 * raw) - 819.2, 14 bits in byte 4 [5:0] and byte 5.
  raw = int(round(angle_deg * 10)) + 8192
  dat = bytearray(8)
  dat[4] = (raw >> 8) & 0x3F
  dat[5] = raw & 0xFF
  return pkt(0x370, dat)


def di_state(cruise_state):
  dat = bytearray(8)
  dat[1] = (cruise_state & 0x0F) << 4
  return pkt(0x368, dat)


def di_torque2(speed_mps):
  # ((0.05 * raw) - 25) * MPH_TO_MPS, 12 bits in byte 3 [3:0] and byte 2.
  raw = int(round(((speed_mps / 0.447) + 25) / 0.05))
  dat = bytearray(6)
  dat[2] = raw & 0xFF
  dat[3] = (raw >> 8) & 0x0F
  return pkt(0x118, dat)


def steer_cmd(angle_can, control_type=1):
  # DAS_steeringControl in the safety's 1/10 deg unit: raw = angle_can + 16384.
  raw = angle_can + 16384
  dat = bytearray(4)
  dat[0] = (raw >> 8) & 0x7F
  dat[1] = raw & 0xFF
  dat[2] = (control_type & 0x03) << 6
  return pkt(0x488, dat)


class TestTeslaAp1AngleResync(unittest.TestCase):
  # common.PandaSafetyTest.test_tx_hook_on_wrong_safety_mode reads TX_MSGS from every Test* class here.
  TX_MSGS = None

  def setUp(self):
    self.l = libsafety_py.libsafety

  def init(self, param=AP1):
    l = self.l
    self.assertEqual(l.set_safety_hooks(CarParams.SafetyModel.tesla, param), 0)
    l.init_tests()
    l.set_alternative_experience(0)
    l.set_timer(1000)
    for _ in range(6):
      self.assertTrue(l.safety_rx_hook(di_torque2(SPEED_MPS)))
    self.assertAlmostEqual(l.get_vehicle_speed_min(), SPEED_MPS, delta=0.02)
    self.assertTrue(l.safety_rx_hook(di_state(STANDBY)))
    self.assertFalse(l.get_controls_allowed())

  def wheel(self, angle_deg):
    # Six samples so angle_meas min and max both equal the new angle.
    for _ in range(6):
      self.assertTrue(self.l.safety_rx_hook(epas_status(angle_deg)))

  def engage(self):
    self.assertTrue(self.l.safety_rx_hook(di_state(ENABLED)))
    self.assertTrue(self.l.get_controls_allowed())

  def disengage(self):
    self.assertTrue(self.l.safety_rx_hook(di_state(STANDBY)))
    self.assertFalse(self.l.get_controls_allowed())

  def tx(self, angle_can, control_type=1):
    return self.l.safety_tx_hook(steer_cmd(angle_can, control_type))

  def drive_then_reengage(self, wheel_after_deg):
    """Engage at 0, ramp openpilot to +5.0 deg, disengage, move the wheel, re-engage."""
    self.wheel(0)
    self.engage()
    for a in (0, 30, 50):
      self.assertTrue(self.tx(a), a)
    self.assertEqual(self.l.get_desired_angle_last(), 50)
    self.disengage()
    self.wheel(wheel_after_deg)
    self.engage()

  # ---- the change ----
  def test_first_cmd_after_reengage_near_measured_accepted(self):
    for wheel in (-30.0, -4.0, 0.0, 12.5, 90.0):
      self.init()
      self.drive_then_reengage(wheel)
      self.assertEqual(self.l.get_desired_angle_last(), int(round(wheel * 10)))
      self.assertTrue(self.tx(int(round(wheel * 10))), wheel)

  def test_first_cmd_after_reengage_far_from_measured_rejected(self):
    for wheel in (-30.0, 12.5, 90.0):
      for offset in (-200, -100, 100, 200):  # 10 and 20 deg from the wheel
        self.init()
        self.drive_then_reengage(wheel)
        self.assertFalse(self.tx(int(round(wheel * 10)) + offset), (wheel, offset))

  def test_stale_previous_angle_rejected_after_wheel_moved(self):
    # Before the resync this was the only command accepted after re-engage.
    self.init()
    self.drive_then_reengage(-30.0)
    self.assertFalse(self.tx(50))

  def test_first_cmd_window_is_the_normal_rate_window(self):
    # Window around the measured wheel is exactly the Tinkla rate step at 8 m/s.
    # Positive reference: away from zero is "up", toward zero is "down".
    cases = (
      (+DELTA_UP, True), (+DELTA_UP + 1, False),
      (-DELTA_DOWN, True), (-DELTA_DOWN - 1, False),
    )
    for wheel_can in (300, -300):
      for step, ok in cases:
        signed = step if wheel_can > 0 else -step
        self.init()
        self.drive_then_reengage(wheel_can / 10)
        self.assertEqual(self.tx(wheel_can + signed), ok, (wheel_can, step))

  # ---- what must not change ----
  def test_no_resync_while_controls_allowed(self):
    self.init()
    self.wheel(0)
    self.engage()
    self.assertTrue(self.tx(0))
    self.wheel(20.0)
    self.assertEqual(self.l.get_desired_angle_last(), 0)
    # Rate is still checked against the last command, not the wheel.
    self.assertTrue(self.tx(DELTA_DOWN))
    self.assertFalse(self.tx(200))

  def test_no_resync_with_always_on_lateral(self):
    self.init()
    self.l.set_alternative_experience(AOL)
    self.assertTrue(self.l.get_acc_main_on())
    self.l.set_desired_angle_last(50)
    self.wheel(-30.0)
    self.assertEqual(self.l.get_desired_angle_last(), 50)

  def test_resync_with_aol_flag_but_main_off(self):
    # AOL only gates the rate check when acc main (or lkas) is on; same gate here.
    self.init()
    self.l.set_alternative_experience(AOL)
    self.assertTrue(self.l.safety_rx_hook(di_state(OFF)))
    self.assertFalse(self.l.get_acc_main_on())
    self.l.set_desired_angle_last(50)
    self.wheel(-30.0)
    self.assertEqual(self.l.get_desired_angle_last(), -300)

  def test_angle_control_still_rejected_while_disengaged(self):
    self.init()
    self.wheel(-30.0)
    self.assertFalse(self.tx(-300, control_type=1))

  def test_inactive_angle_rule_unchanged(self):
    # Type NONE (0) must be within 0.1 deg of the measured wheel. (BogStar's tesla_ap1.h only allows
    # control types 0 and 1, so the BogPilot DISABLED (3) case is rejected outright here.)
    self.init()
    self.wheel(-30.0)
    self.assertTrue(self.tx(-300, 0))
    self.assertTrue(self.tx(-299, 0))
    self.assertTrue(self.tx(-301, 0))
    self.assertFalse(self.tx(-298, 0))
    self.assertFalse(self.tx(-302, 0))
    self.assertFalse(self.tx(50, 0))
    self.assertFalse(self.tx(-300, 3))

  def test_rate_limit_after_first_frame_unchanged(self):
    self.init()
    self.drive_then_reengage(-30.0)
    self.assertTrue(self.tx(-300))
    # From -30.0 (negative side): away from zero uses up (41), toward zero down (51).
    self.assertTrue(self.tx(-300 - DELTA_UP))
    self.assertFalse(self.tx(-300 - DELTA_UP - DELTA_UP - 1))


if __name__ == "__main__":
  unittest.main()
