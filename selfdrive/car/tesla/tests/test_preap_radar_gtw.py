"""Pre-AP radar GTW helper TX / packing tests (radar branch).

Avoids napcal-owned test_preap_pedal_radar.py. Focus: radar off sends nothing,
dummy VIN refuse, GTW_carConfig matches NAP bitfields, TX whitelist addrs.
"""
from __future__ import annotations

import unittest

from openpilot.selfdrive.car.tesla.preap import radar_tx


class TestPreapRadarGtw(unittest.TestCase):
  def test_radar_off_sends_nothing(self):
    self.assertEqual(radar_tx.radar_tx_frames(enabled=False), [])

  def test_radar_on_sends_vin_and_carconfig(self):
    frames = radar_tx.radar_tx_frames(enabled=True, bus=1)
    self.assertEqual(len(frames), 2)
    addrs = {f[0] for f in frames}
    self.assertEqual(addrs, {radar_tx.ADDR_VIN_VIP, radar_tx.ADDR_GTW_CAR_CONFIG})
    for addr, _ext, dat, bus in frames:
      self.assertEqual(bus, 1)
      self.assertEqual(len(dat), 8)
      self.assertIn(addr, radar_tx.RADAR_TX_ADDRS)

  def test_dummy_vin_refuse_real_looking(self):
    # NOTAREAL/TEST/DUMMY markers are allowed; refuse a real-looking 17-char.
    with self.assertRaises(ValueError):
      radar_tx.pack_dummy_vin("ABCDEFGHIJKLMNOPQ")
    dat = radar_tx.pack_dummy_vin()
    self.assertEqual(len(dat), 8)
    self.assertTrue(dat.startswith(b"TESTDUMM"))

  def test_gtw_car_config_nap_bits(self):
    dat = radar_tx.pack_gtw_car_config(behind_nosecone=False)
    lo = int.from_bytes(dat[0:4], "little")
    hi = int.from_bytes(dat[4:8], "little")
    # NAP: lo = (0 & 0xFFFFF33F) | 0x100 | 0x440. 0x440 occupies mask-cleared bits.
    self.assertEqual(lo, 0x100 | 0x440)
    self.assertEqual(lo & 0xFFFFF33F, 0x100)  # after mask, only 0x100 of the forced pair remains
    self.assertEqual(lo & 0x100, 0x100)
    self.assertEqual(lo & 0x440, 0x440)
    self.assertEqual((lo >> 6) & 0x03, 1)  # fwd_radar_hw
    # DBC: GTW_autopilot in byte7; BO_681 has no checksum (do not clobber)
    self.assertEqual((hi >> 28) & 0x03, 1)  # autopilot
    self.assertEqual(dat[7], 0x10)
    self.assertEqual((hi >> 4) & 0x0F, 0)   # radar_position flush

  def test_gtw_car_config_nosecone(self):
    dat = radar_tx.pack_gtw_car_config(behind_nosecone=True)
    hi = int.from_bytes(dat[4:8], "little")
    self.assertEqual((hi >> 4) & 0x0F, 1)
    self.assertEqual((hi >> 28) & 0x03, 1)  # autopilot still set
    self.assertEqual(dat[7], 0x10)

  def test_safety_header_has_rx_all_gtw(self):
    from pathlib import Path
    # Repo-relative: openpilot lives under selfdrive/...; panda is sibling of selfdrive
    root = Path(__file__).resolve().parents[4]  # .../selfdrive/car/tesla/tests -> repo?
    # parents: 0=tests 1=tesla 2=car 3=selfdrive 4=repo root (BogPilot openpilot root)
    preap = root / "panda" / "board" / "safety" / "safety_tesla_preap.h"
    text = preap.read_text()
    self.assertIn("tesla_preap_gtw_emulation", text)
    self.assertIn(".rx_all = tesla_preap_gtw_emulation", text)
    self.assertIn("preap_radar_readdr", text)
    self.assertIn("0x169", text)  # synthetic wheel speeds
    self.assertIn("0x2A9", text)


if __name__ == "__main__":
  unittest.main()
