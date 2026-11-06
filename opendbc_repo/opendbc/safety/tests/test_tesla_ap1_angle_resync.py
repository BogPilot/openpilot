#!/usr/bin/env python3
"""BogPilot AP1 safety: desired_angle_last follows the measured wheel while disengaged.

openpilot sends no 0x488 while disengaged on AP1 (stock Mobileye 0x488 is
forwarded instead), so without a resync the first 0x488 after an engage was
rate checked against the last angle of the previous engagement. With
TESLA_FLAG_AP1, each EPAS_sysStatus (0x370) received while controls are not
allowed sets desired_angle_last to the measured angle.
"""
import unittest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
AP1 = (8 | 1)  # 9


def pkt(addr, dat, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(dat))


def epas_status(angle_deg):
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
  raw = int(round(((speed_mps / 0.447) + 25) / 0.05))
  dat = bytearray(6)
  dat[2] = raw & 0xFF
  dat[3] = (raw >> 8) & 0x0F
  return pkt(0x118, dat)


def steer_cmd(angle_can, control_type=1):
  raw = angle_can + 16384
  dat = bytearray(4)
  dat[0] = (raw >> 8) & 0x7F
  dat[1] = raw & 0xFF
  dat[2] = (control_type & 0x03) << 6
  return pkt(0x488, dat)


SPEED_MPS = 8.0
# At SPEED_MPS=8, decoded speed rounds to 8001 (factor 1000) so fudged_speed=7.001;
# interpolate yields int deltas 40 up / 50 down (not the exact-breakpoint 41/51).
DELTA_UP = 40
DELTA_DOWN = 50
STANDBY = 1
ENABLED = 2


class TestTeslaAp1AngleResync(unittest.TestCase):
  TX_MSGS = [[0x488, 0], [0x45, 0], [0x45, 2], [0x2b9, 0], [0x349, 0], [0x399, 0], [0x389, 0], [0x239, 0]]
  def init(self, param=AP1):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.init_tests()
    l.set_timer(1000)
    for _ in range(6):
      self.assertTrue(l.safety_rx_hook(di_torque2(SPEED_MPS)))
    self.assertTrue(l.safety_rx_hook(di_state(STANDBY)))
    self.assertFalse(l.get_controls_allowed())

  def wheel(self, angle_deg):
    for _ in range(6):
      self.assertTrue(l.safety_rx_hook(epas_status(angle_deg)))

  def engage(self):
    self.assertTrue(l.safety_rx_hook(di_state(ENABLED)))
    self.assertTrue(l.get_controls_allowed())

  def disengage(self):
    self.assertTrue(l.safety_rx_hook(di_state(STANDBY)))
    self.assertFalse(l.get_controls_allowed())

  def tx(self, angle_can, control_type=1):
    return l.safety_tx_hook(steer_cmd(angle_can, control_type))

  def drive_then_reengage(self, wheel_after_deg):
    self.wheel(0)
    self.engage()
    for a in (0, 30, 50):
      self.assertTrue(self.tx(a), a)
    self.assertEqual(l.get_desired_angle_last(), 50)
    self.disengage()
    self.wheel(wheel_after_deg)
    self.engage()

  def test_first_cmd_after_reengage_near_measured_accepted(self):
    for wheel in (-30.0, -4.0, 0.0, 12.5, 90.0):
      self.init()
      self.drive_then_reengage(wheel)
      self.assertEqual(l.get_desired_angle_last(), int(round(wheel * 10)))
      self.assertTrue(self.tx(int(round(wheel * 10))), wheel)

  def test_first_cmd_after_reengage_far_from_measured_rejected(self):
    for wheel in (-30.0, 12.5, 90.0):
      for offset in (-200, -100, 100, 200):
        self.init()
        self.drive_then_reengage(wheel)
        self.assertFalse(self.tx(int(round(wheel * 10)) + offset), (wheel, offset))

  def test_stale_previous_angle_rejected_after_wheel_moved(self):
    self.init()
    self.drive_then_reengage(-30.0)
    self.assertFalse(self.tx(50))

  def test_first_cmd_window_is_the_normal_rate_window(self):
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

  def test_no_resync_while_controls_allowed(self):
    self.init()
    self.wheel(0)
    self.engage()
    self.assertTrue(self.tx(0))
    self.wheel(20.0)
    self.assertEqual(l.get_desired_angle_last(), 0)
    self.assertTrue(self.tx(DELTA_DOWN))
    self.assertFalse(self.tx(200))

  def test_no_resync_without_ap1_flag(self):
    # Without AP1, Model 3/Y path does not resync on 0x370 AP1 packing.
    # Init with LONG only still loads Model 3/Y RX (0x370 is present there too
    # but hands-on / eac fields differ); force desired_angle_last and confirm
    # AP1-style wheel update does not overwrite when flag is clear.
    for param in (0, 1):
      self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
      l.init_tests()
      l.set_desired_angle_last(50)
      # Model 3/Y rx on 0x370 updates angle_meas but does not resync desired_angle_last
      for _ in range(6):
        l.safety_rx_hook(epas_status(-30.0))
      self.assertEqual(l.get_desired_angle_last(), 50, param)

  def test_angle_control_still_rejected_while_disengaged(self):
    self.init()
    self.wheel(-30.0)
    self.assertFalse(self.tx(-300, control_type=1))

  def test_inactive_angle_rule_unchanged(self):
    for control_type in (0, 3):
      self.init()
      self.wheel(-30.0)
      self.assertTrue(self.tx(-300, control_type))
      self.assertTrue(self.tx(-299, control_type))
      self.assertTrue(self.tx(-301, control_type))
      self.assertFalse(self.tx(-298, control_type))
      self.assertFalse(self.tx(-302, control_type))
      self.assertFalse(self.tx(50, control_type))

  def test_rate_limit_after_first_frame_unchanged(self):
    self.init()
    self.drive_then_reengage(-30.0)
    self.assertTrue(self.tx(-300))
    self.assertTrue(self.tx(-300 - DELTA_UP))
    self.assertFalse(self.tx(-300 - DELTA_UP - DELTA_UP - 1))


if __name__ == "__main__":
  unittest.main()
