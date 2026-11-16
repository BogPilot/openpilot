#!/usr/bin/env python3
"""Pre-AP Bosch radar donor-VIN config (host 0x560 -> panda, never on the car).

Ported from NAP opendbc/safety/tests/test_tesla_preap_radar_donor.py (9 tests) @ opendbc 5dbe36d37
(openpilot naponsp-alpha-prebuilt 7eb09d2a7), on our raw-wire can_send log instead of NAP debug getters.
VINs here are synthetic: each contains I, O and Q, which no real VIN may contain.
Divergence (docs/tesla/DIVERGENCES.md): 0x560 is ignored without flag 256 and while engaged or armed (stricter than NAP).
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_preap import PREAP, SAFETY_TESLA, pkt
from opendbc.safety.tests.test_tesla_preap_radar import NOSE, RADAR, donor_config, send_donor_config, sent

l = libsafety_py.libsafety

DONOR_4WD = "TESTQQQ4OIQ000001"   # char 8 '4' (dual motor)
DONOR_DM2 = "TESTQQQ2OIQ000002"   # char 8 '2' (dual motor)
DONOR_RWD = "TESTQQQ1OIQ000003"   # char 8 '1' (single motor)


class DonorCase(unittest.TestCase):
  PARAM = PREAP | RADAR

  def setUp(self):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, self.PARAM), 0)
    l.init_tests()
    l.set_timer(1_000_000)
    l.set_controls_allowed(False)
    l.safety_can_send_log_reset()

  def rx(self, addr, data):
    l.safety_can_send_log_reset()
    l.safety_rx_hook(pkt(addr, bytearray(data), 0))
    return sent()

  def car_config(self, src_hex):
    frames = [f for f in self.rx(0x398, bytes.fromhex(src_hex)) if f[0] == 0x2A9]
    return frames[0][3].hex() if frames else None


class TestPreapRadarDonor(DonorCase):
  def test_gtw_silent_until_vin_stream_complete(self):
    self.assertIsNone(self.car_config("0281555300000000"))
    self.assertEqual(self.rx(0x108, bytes(8)), [])
    l.safety_tx_hook(pkt(0x560, donor_config("")[0], 0))
    self.assertIsNone(self.car_config("0281555300000000"))
    send_donor_config("")
    self.assertEqual(self.car_config("0281555300000000"), "4285555300000010")

  def test_use_radar_clear_keeps_gtw_silent(self):
    send_donor_config(DONOR_4WD, use_radar=False)
    self.assertIsNone(self.car_config("0281555300000000"))
    self.assertEqual(self.rx(0x405, bytes((0x11, 0, 0, 0, 0, 0, 0, 0))), [])

  def test_empty_vin_keeps_passthrough(self):
    send_donor_config("")
    self.assertEqual(self.car_config("0281555300000000"), "4285555300000010")
    mux = bytes((0x11, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47))
    self.assertEqual(self.rx(0x405, mux), [(0x2B9, 1, 8, mux)])

  def test_empty_vin_still_applies_position(self):
    send_donor_config("", position=1, epas_type=0)
    self.assertEqual(self.car_config("0281555300000000"), "4285555310000010")

  def test_donor_4wd_vin_sets_4wd_to_match_vin_char(self):
    send_donor_config(DONOR_4WD, position=1, epas_type=3)
    self.assertEqual(self.car_config("0281555300000000"), "4a85555310300010")

  def test_position_3_is_not_a_position(self):
    send_donor_config("", position=3, epas_type=0)
    self.assertEqual(self.car_config("0281555300000000"), "4285555300000010")

  def test_4wd_source_config_remains_four_wheel_drive(self):
    send_donor_config(DONOR_4WD)
    self.assertEqual(self.car_config("0a90555300001700"), "4a95555300001710")

  def test_vin_char8_2_sets_4wd(self):
    send_donor_config(DONOR_DM2)
    self.assertEqual(self.car_config("0290555300001700"), "4a95555300001710")

  def test_single_motor_vin_preserves_chassis_2wd(self):
    send_donor_config(DONOR_RWD)
    self.assertEqual(self.car_config("0290555300001700"), "4295555300001710")

  def test_donor_vin_replaces_mux_records(self):
    send_donor_config(DONOR_4WD)
    v = DONOR_4WD.encode()
    src = bytes((0, 0x51, 0x52, 0x53, 0x54, 0x55, 0x56, 0x57))
    self.assertEqual(self.rx(0x405, bytes((0x10,)) + src[1:]), [(0x2B9, 1, 8, bytes((0x10, 0, 0, 0, 0)) + v[0:3])])
    self.assertEqual(self.rx(0x405, bytes((0x11,)) + src[1:]), [(0x2B9, 1, 8, bytes((0x11,)) + v[3:10])])
    self.assertEqual(self.rx(0x405, bytes((0x12,)) + src[1:]), [(0x2B9, 1, 8, bytes((0x12,)) + v[10:17])])
    # other 0x405 records pass through unchanged
    for rec in (0x00, 0x13, 0x20):
      d = bytes((rec,)) + src[1:]
      self.assertEqual(self.rx(0x405, d), [(0x2B9, 1, 8, d)])


class TestPreapRadarDonorStricter(DonorCase):
  """Stricter than NAP: 0x560 is ignored while engaged, and init clears all donor state."""

  def test_config_ignored_while_controls_allowed(self):
    l.set_controls_allowed(True)
    send_donor_config("")
    l.set_controls_allowed(False)
    self.assertIsNone(self.car_config("0281555300000000"))

  def test_donor_cannot_change_mid_engagement(self):
    send_donor_config("")
    l.set_controls_allowed(True)
    send_donor_config(DONOR_4WD)
    self.assertEqual(self.car_config("0281555300000000"), "4285555300000010")
    mux = bytes((0x11, 1, 2, 3, 4, 5, 6, 7))
    self.assertEqual(self.rx(0x405, mux), [(0x2B9, 1, 8, mux)])

  def test_init_resets_donor_state(self):
    send_donor_config(DONOR_4WD)
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, self.PARAM), 0)
    l.init_tests()
    self.assertIsNone(self.car_config("0281555300000000"))

  def test_config_ignored_without_flag_256(self):
    for param in (PREAP, PREAP | NOSE):
      self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
      l.init_tests()
      send_donor_config(DONOR_4WD)
      self.assertEqual(self.rx(0x405, bytes((0x11, 0, 0, 0, 0, 0, 0, 0))), [])
      self.assertIsNone(self.car_config("0281555300000000"))

  def test_bad_record_ids_ignored(self):
    for rec in (3, 0x10, 0xFF):
      l.safety_tx_hook(pkt(0x560, bytes((rec, 1, 1, 0, 0, 0x41, 0x41, 0x41)), 0))
    self.assertIsNone(self.car_config("0281555300000000"))


if __name__ == "__main__":
  unittest.main()
