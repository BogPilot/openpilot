#!/usr/bin/env python3
"""BogPilot AP1 / Pre-AP safety, lateral stage 1: lateral-accel bound and +-360 deg on ANGLE commands. Raw-wire tests, no DBC.

The bound is the stock ISO bound (3.0 m/s^2 + 9.81 * 0.06) through the legacy Model S vehicle model (steer ratio 15, wheelbase 2.959,
slip factor -0.0005666), at 1 m/s below the slowest recent speed, floored at 1 m/s (same fudge as steer_angle_cmd_checks_vm). The expected
values below are computed here, independently of the C code. The rate tables are unchanged by stage 1 and are not tested here.
"""
import math
import unittest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
AP1 = 9       # AP1 + LONG
PREAP = 32
MPH = 0.44704
MAX_LAT_ACCEL = 3.0 + 9.81 * 0.06
SLIP, RATIO, WB = -0.0005666, 15.0, 2.959


def pkt(addr, dat, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(dat))


def epas(angle_deg, eac_status=1):
  raw = int(round(angle_deg * 10)) + 8192
  d = bytearray(8)
  d[4] = (raw >> 8) & 0x3F
  d[5] = raw & 0xFF
  d[6] = (eac_status & 7) << 5
  return pkt(0x370, d)


def steer(angle_can, ctype=1):
  raw = angle_can + 16384
  d = bytearray(4)
  d[0] = (raw >> 8) & 0x7F
  d[1] = raw & 0xFF
  d[2] = (ctype & 3) << 6
  return pkt(0x488, d)


# AP1 speed: DI_torque2 (0x118). Pre-AP speed: ESP_B (0x155) 0.01 kph.
def ap1_speed(v):
  raw = int(round(((v / 0.447) + 25) / 0.05))
  d = bytearray(6)
  d[2] = raw & 0xFF
  d[3] = (raw >> 8) & 0x0F
  return pkt(0x118, d), (((raw * 0.05) - 25) * 0.447)


def preap_speed(v):
  raw = int(round(v / 0.277778 / 0.01))
  d = bytearray(8)
  d[5] = (raw >> 8) & 0xFF
  d[6] = raw & 0xFF
  return pkt(0x155, d), (raw * 0.01) * 0.277778


def expected_bound_can(speed):
  """Largest ANGLE command (1/10 deg) the panda accepts at this decoded speed."""
  fs = max(speed - 1.0, 1.0)
  curvature_factor = 1. / (1. - SLIP * fs * fs) / WB
  angle = math.degrees(MAX_LAT_ACCEL / (fs * fs) * RATIO / curvature_factor)
  return int(angle * 10 + 1.)


class Base(unittest.TestCase):
  PARAM = AP1

  def setup_car(self, v, wheel_deg):
    """Fresh safety, speed v (m/s) and measured wheel, controls allowed. Returns the decoded speed the panda sees."""
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, self.PARAM), 0)
    l.init_tests()
    l.set_timer(1_000_000)
    if self.PARAM == AP1:
      speed_msg, seen = ap1_speed(v)
      for _ in range(6):
        self.assertTrue(l.safety_rx_hook(speed_msg))
        self.assertTrue(l.safety_rx_hook(epas(wheel_deg)))
      d = bytearray(8)
      d[1] = 0x20                      # DI_cruiseState ENABLED
      self.assertTrue(l.safety_rx_hook(pkt(0x368, d)))
    else:
      speed_msg, seen = preap_speed(v)
      d118 = bytearray(6)
      d118[1] = 4 << 4                 # gear D
      brake = bytearray(8)
      brake[0] = 1 << 2
      for _ in range(6):
        for m in (epas(wheel_deg), speed_msg, pkt(0x118, d118), pkt(0x108, bytearray(8)), pkt(0x20a, brake),
                  pkt(0x318, bytearray(8)), pkt(0x368, bytearray(8)), pkt(0x45, bytearray(8))):
          self.assertTrue(l.safety_rx_hook(m))
      self.assertTrue(l.safety_rx_hook(pkt(0x45, bytes([2] + [0] * 7))))   # stalk pull
    self.assertTrue(l.get_controls_allowed())
    return seen

  def tx(self, can, ctype=1):
    return bool(l.safety_tx_hook(steer(can, ctype)))


class LateralStage1Mixin:
  def test_bound_is_enforced_at_each_speed_and_side(self):
    for mph in (20, 30, 45, 60, 75):
      for sign in (1, -1):
        speed = self.setup_car(mph * MPH, 0.0)
        bound = expected_bound_can(speed)
        self.assertLess(bound, 3600)
        # measured wheel one degree inside the bound so the rate window is never the reason for a result
        for cmd, ok in ((bound - 3, True), (bound + 3, False)):
          self.setup_car(mph * MPH, sign * (bound - 10) / 10.0)
          self.assertEqual(self.tx(sign * cmd), ok, (mph, sign, cmd, bound))

  def test_a_violation_puts_the_rate_reference_back_on_the_wheel(self):
    speed = self.setup_car(45 * MPH, 0.0)
    bound = expected_bound_can(speed)
    self.setup_car(45 * MPH, (bound - 10) / 10.0)
    self.assertFalse(self.tx(bound + 3))
    self.assertEqual(l.get_desired_angle_last(), bound - 10)

  def test_bound_does_not_bind_at_low_speed(self):
    for mph in (5, 8, 10):
      self.setup_car(mph * MPH, 100.0)
      self.assertTrue(self.tx(1000), mph)
      self.setup_car(mph * MPH, -100.0)
      self.assertTrue(self.tx(-1000), mph)

  def test_360_deg_cap_on_angle_commands(self):
    for sign in (1, -1):
      self.setup_car(5 * MPH, sign * 360.0)
      self.assertTrue(self.tx(sign * 3600))
      self.setup_car(5 * MPH, sign * 360.0)
      self.assertFalse(self.tx(sign * 3601))

  def test_idle_none_frames_are_not_held_to_the_bound(self):
    # NONE (type 0) at the measured wheel is how the host idles; the new check only looks at ANGLE commands.
    self.setup_car(60 * MPH, 80.0)
    self.assertTrue(self.tx(800, ctype=0))

  def test_no_angle_command_without_controls(self):
    self.setup_car(30 * MPH, 0.0)
    l.set_controls_allowed(False)
    self.assertFalse(self.tx(0))


class TestTeslaAp1LateralStage1(Base, LateralStage1Mixin):
  PARAM = AP1


class TestTeslaPreapLateralStage1(Base, LateralStage1Mixin):
  PARAM = PREAP


if __name__ == "__main__":
  unittest.main()
