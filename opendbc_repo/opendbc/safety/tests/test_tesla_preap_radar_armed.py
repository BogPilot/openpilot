#!/usr/bin/env python3
"""Pre-AP radar: the steering latch alone (controls_allowed False) blocks the 0x560 donor config and the 0x641 F190 frames.

tesla_preap.h tesla_preap_radar_apply_vin_msg and tesla_preap_radar_f190_tx_ok both require !tesla_preap_steer_armed, so
neither can change or read the radar contract while a pull-armed session still steers through a brake press.
Each test checks the latch is really armed (steering accepted, controls_allowed False), then that a cancel which disarms
it lets the same frames through. Synthetic VIN only (it contains I, O and Q, which no real VIN may contain).
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_preap import pkt, stalk, steer
from opendbc.safety.tests.test_tesla_preap_brake_steer import BrakeSteerCase
from opendbc.safety.tests.test_tesla_preap_radar import RADAR, donor_config, sent

l = libsafety_py.libsafety

DONOR_4WD = "TESTQQQ4OIQ000001"
F190_READ = bytes((0x03, 0x22, 0xF1, 0x90, 0, 0, 0, 0))
TESTER_PRESENT = bytes((0x02, 0x3E, 0x00, 0, 0, 0, 0, 0))


class ArmedCase(BrakeSteerCase):
  PARAM = BrakeSteerCase.PARAM | RADAR

  def arm_without_controls(self):
    self.engaged_then_braked()
    self.assertFalse(l.get_controls_allowed())
    self.assertTrue(self.tx(steer(0)), "the latch is armed: steering is still accepted")

  def disarm(self):
    self.advance(700_000)
    self.feed_held()
    l.safety_rx_hook(stalk(1))
    self.assertFalse(self.tx(steer(0)), "the cancel disarmed the latch")
    self.assertFalse(l.get_controls_allowed())

  def send_config(self, vin):
    self.assertEqual([self.tx(pkt(0x560, d, 0)) for d in donor_config(vin, position=1)], [False, False, False])

  def car_config(self):
    l.safety_can_send_log_reset()
    l.safety_rx_hook(pkt(0x398, bytearray(bytes.fromhex("0281555300000000")), 0))
    return [f for f in sent() if f[0] == 0x2A9]


class TestArmedLatchBlocksRadarContract(ArmedCase):
  def test_donor_config_ignored_while_only_the_latch_is_armed(self):
    self.arm_without_controls()
    self.send_config(DONOR_4WD)
    self.assertEqual(self.car_config(), [], "0x560 ignored: the radar gateway stays closed")
    self.disarm()
    self.send_config(DONOR_4WD)
    frames = self.car_config()
    self.assertEqual(len(frames), 1, "the same 0x560 records apply once the latch is disarmed")
    self.assertEqual(frames[0][3][0] & 0x08, 0x08, "the donor 4WD bit is set")

  def test_f190_frames_refused_while_only_the_latch_is_armed(self):
    self.arm_without_controls()
    for d in (F190_READ, TESTER_PRESENT):
      self.assertFalse(self.tx(pkt(0x641, d, 1)), d.hex())
    self.disarm()
    for d in (F190_READ, TESTER_PRESENT):
      self.assertTrue(self.tx(pkt(0x641, d, 1)), d.hex())


if __name__ == "__main__":
  unittest.main()
