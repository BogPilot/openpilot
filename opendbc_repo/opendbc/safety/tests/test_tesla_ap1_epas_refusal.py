#!/usr/bin/env python3
"""BogPilot AP1 safety (Model S and Model X, TESLA_FLAG_AP1): no active steering command into a refusing EPAS.

The EPAS is refusing when the last EPAS_sysStatus (0x370) says EAC INHIBITED, FAULT or SNA, or carries an
error other than IDLE, HANDS_ON (3) or HIGH_ANGLE_REQ (6). The panda cannot see openpilot's latActive, so
it checks what it can see: controls_allowed (existing) and the EPAS state (new). Type NONE and DISABLED
frames are never affected. Raw-wire tests, no DBC.
"""
import unittest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
AP1 = 8 | 1          # Model S and Model X share the flag; 1 is LONG_CONTROL
AP1_NO_LONG = 8

INHIBITED, AVAILABLE, ACTIVE, FAULT, SNA = 0, 1, 2, 3, 4
IDLE, HANDS_ON, HIGH_ANGLE_REQ = 0, 3, 6
OK_ERRORS = (IDLE, HANDS_ON, HIGH_ANGLE_REQ)


def pkt(addr, dat, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(dat))


def epas(angle_deg=0.0, eac_status=AVAILABLE, eac_error=IDLE, hands=0):
  raw = int(round(angle_deg * 10)) + 8192
  d = bytearray(8)
  d[2] = (eac_error & 0x0F) << 4
  d[4] = ((hands & 3) << 6) | ((raw >> 8) & 0x3F)
  d[5] = raw & 0xFF
  d[6] = (eac_status & 0x07) << 5
  return pkt(0x370, d)


def di_state(cruise_state):
  d = bytearray(8)
  d[1] = (cruise_state & 0x0F) << 4
  return pkt(0x368, d)


def di_torque2(speed_mps):
  raw = int(round(((speed_mps / 0.447) + 25) / 0.05))
  d = bytearray(6)
  d[2] = raw & 0xFF
  d[3] = (raw >> 8) & 0x0F
  return pkt(0x118, d)


def steer_cmd(angle_can, control_type=1):
  raw = angle_can + 16384
  d = bytearray(4)
  d[0] = (raw >> 8) & 0x7F
  d[1] = raw & 0xFF
  d[2] = (control_type & 0x03) << 6
  return pkt(0x488, d)


class TestTeslaAp1EpasRefusal(unittest.TestCase):
  def init(self, param=AP1):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.init_tests()
    l.set_timer(1000)
    for _ in range(6):
      self.assertTrue(l.safety_rx_hook(di_torque2(8.0)))
    self.assertTrue(l.safety_rx_hook(di_state(1)))
    self.wheel()
    self.assertTrue(l.safety_rx_hook(di_state(2)))
    self.assertTrue(l.get_controls_allowed())

  def wheel(self, angle=0.0, status=AVAILABLE, error=IDLE):
    for _ in range(3):
      self.assertTrue(l.safety_rx_hook(epas(angle, status, error)))

  def tx(self, angle_can=0, control_type=1):
    return bool(l.safety_tx_hook(steer_cmd(angle_can, control_type)))

  def test_angle_passes_when_the_epas_is_ready(self):
    for param in (AP1, AP1_NO_LONG):
      for status in (AVAILABLE, ACTIVE):
        for error in OK_ERRORS:
          self.init(param)
          self.wheel(0.0, status, error)
          self.assertTrue(self.tx(0), (param, status, error))

  def test_angle_is_dropped_for_every_refusing_status_whatever_the_error(self):
    for status in (INHIBITED, FAULT, SNA, 5, 6, 7):
      for error in range(16):
        self.init()
        self.wheel(0.0, status, error)
        self.assertFalse(self.tx(0), (status, error))

  def test_angle_is_dropped_for_every_error_outside_the_latched_pair(self):
    for status in (AVAILABLE, ACTIVE):
      for error in range(16):
        self.init()
        self.wheel(0.0, status, error)
        self.assertEqual(self.tx(0), error in OK_ERRORS, (status, error))

  def test_the_logged_cases(self):
    # INHIBITED + HIGH_ANGLE_RATE_SAFETY (9), and INHIBITED + HANDS_ON (3) with hands on
    for error, hands in ((9, 0), (3, 3)):
      self.init()
      self.assertTrue(self.tx(0))
      self.assertTrue(l.safety_rx_hook(epas(0.0, INHIBITED, error, hands)))
      self.assertFalse(self.tx(0), "angle at the measured wheel is dropped too")
      self.assertFalse(self.tx(0))

  def test_type_none_and_disabled_always_pass(self):
    for control_type in (0, 3):
      for status in (INHIBITED, AVAILABLE, ACTIVE, FAULT, SNA):
        for error in (IDLE, 9, 15):
          self.init()
          self.wheel(0.0, status, error)
          self.assertTrue(self.tx(0, control_type), (control_type, status, error))

  def test_recovers_on_the_next_clean_status(self):
    self.init()
    self.wheel(0.0, INHIBITED, 9)
    self.assertFalse(self.tx(0))
    self.wheel(0.0, AVAILABLE, HANDS_ON)
    self.assertTrue(self.tx(0))
    self.wheel(0.0, ACTIVE, IDLE)
    self.assertTrue(self.tx(0))

  def test_still_needs_controls_allowed_and_the_rate_table(self):
    self.init()
    self.assertFalse(self.tx(400), "rate table still applies")
    self.assertTrue(l.safety_rx_hook(di_state(1)))
    self.assertFalse(l.get_controls_allowed())
    self.assertFalse(self.tx(0), "angle with controls not allowed is still dropped")

  def test_model_3y_path_is_not_changed(self):
    # Without TESLA_FLAG_AP1 this layout is not the AP1 one: a Model 3/Y init must not pick up the rule.
    for param in (0, 1):
      self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
      l.init_tests()
      l.set_timer(1000)
      l.safety_rx_hook(epas(0.0, INHIBITED, 9))
      l.set_controls_allowed(True)
      l.set_desired_angle_last(0)
      self.assertTrue(self.tx(0, 0), param)


if __name__ == "__main__":
  unittest.main()
