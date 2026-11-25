#!/usr/bin/env python3
"""Auto Height Very Low: the AP1 panda rule for 0x308 byte 0 = 0x47 (tesla_ap1.h). Raw wire only, no DBC.

0x47 is allowed only with flag 4096 (set at car start only for an AP1 Model X with Auto Height on) and only together with the
Park bit 1024 in Park or the Drive bit 2048 in Drive at standstill, under every other condition of those rules. 4096 never widens
anything else, and without it 0x47 is refused as before.
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
RH = 1024
RHD = 2048
VL = 4096
SCREEN = bytes.fromhex("407f9ab616010600")
GEAR = {"P": 1, "R": 2, "N": 3, "D": 4, "SNA": 7, "INVALID": 0}


def packet(addr, data, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(data))


def di_torque2(gear, mph=0.0):
  raw_speed = int(round((mph + 25) / 0.05))
  b = bytearray(6)
  b[1] = (GEAR[gear] & 0x7) << 4
  b[2] = raw_speed & 0xFF
  b[3] = (raw_speed >> 8) & 0x0F
  return bytes(b)


def di_torque1(gas):
  b = bytearray(8)
  b[6] = 0x40 if gas else 0x00
  return bytes(b)


def very_low(src=SCREEN):
  return bytes([0x47]) + src[1:]


class TestTeslaAp1RideHeightVeryLow(unittest.TestCase):
  def init(self, param=8 | RH | VL):
    self.assertEqual(l.set_safety_hooks(10, param), 0)
    l.init_tests()
    self.t = 1_000_000
    l.set_timer(self.t)

  def tick(self, us):
    self.t += us
    l.set_timer(self.t)

  def rx(self, addr, data, bus=0):
    l.safety_rx_hook(packet(addr, data, bus))

  def tx(self, data, bus=0, addr=0x308):
    return bool(l.safety_tx_hook(packet(addr, data, bus)))

  def car(self, gear="P", mph=0.0, src=SCREEN):
    self.rx(0x118, di_torque2(gear, mph))
    self.rx(0x308, src)

  def test_every_byte0_by_flags_and_gear(self):
    base = set(range(0x41, 0x45))
    cases = (
      (8 | RH | VL, "P", base | {0x47}), (8 | RH | VL, "D", set()),
      (8 | RHD | VL, "D", base | {0x47}), (8 | RHD | VL, "P", set()),
      (8 | RH | RHD | VL, "P", base | {0x47}), (8 | RH | RHD | VL, "D", base | {0x47}),
      (8 | RH, "P", base), (8 | RHD, "D", base), (8 | RH | RHD, "D", base),
      (8 | VL, "P", set()), (8 | VL, "D", set()), (9 | VL, "P", set()),
    )
    for param, gear, allowed in cases:
      self.init(param)
      for b0 in range(256):
        self.tick(20_000); self.car(gear=gear)
        self.assertEqual(self.tx(bytes([b0]) + SCREEN[1:]), b0 in allowed, (param, gear, hex(b0)))

  def test_very_low_follows_every_park_condition(self):
    self.init(); self.car(); self.assertTrue(self.tx(very_low()))
    self.init(); self.car(mph=3.0); self.assertFalse(self.tx(very_low()))                  # moving
    self.init(); self.car(); l.set_controls_allowed(True); self.assertFalse(self.tx(very_low()))
    self.init(); self.car(); self.tick(200_000); self.assertFalse(self.tx(very_low()))     # gear stale
    self.init(); self.rx(0x118, di_torque2("P")); self.assertFalse(self.tx(very_low()))    # no screen frame
    self.init(); self.car(); self.assertFalse(self.tx(bytes([0x47]) + bytes(7)))           # bytes 1-7 must match
    self.init(); self.car(); self.assertFalse(self.tx(very_low(), bus=2))                  # bus 0 only
    self.init(); self.car(); self.assertTrue(self.tx(very_low())); self.assertFalse(self.tx(very_low()))  # 15 ms gap

  def test_very_low_follows_every_drive_condition(self):
    p = 8 | RHD | VL
    self.init(p); self.car("D"); self.assertTrue(self.tx(very_low()))
    self.init(p); self.car("D"); self.rx(0x108, di_torque1(True)); self.assertFalse(self.tx(very_low()))  # gas
    self.init(p); self.car("D", mph=3.0); self.assertFalse(self.tx(very_low()))
    self.init(p); self.car("D"); l.set_controls_allowed(True); self.assertFalse(self.tx(very_low()))
    self.init(p); self.car("R"); self.assertFalse(self.tx(very_low()))

  def test_frame_budget_is_shared_with_the_other_levels(self):
    self.init()
    sent = 0
    for k in range(400):
      self.tick(20_000); self.car()
      sent += self.tx(very_low() if k % 2 else bytes([0x41]) + SCREEN[1:])
    self.assertEqual(sent, 150)

  def test_burst_fits_the_rule(self):
    """100 frames at 50 Hz with the screen at 10 Hz and gear at 100 Hz: every frame passes."""
    self.init()
    ok = 0
    for k in range(200):
      self.tick(10_000)
      self.rx(0x118, di_torque2("P"))
      if k % 10 == 0:
        self.rx(0x308, SCREEN)
      if k % 2 == 0:
        ok += self.tx(very_low())
    self.assertEqual(ok, 100)

  def test_flag_cleared_on_reinit(self):
    self.init(); self.car(); self.assertTrue(self.tx(very_low()))
    self.init(8 | RH); self.car(); self.assertFalse(self.tx(very_low()))

  def test_preap_mode_never_sends_0x308(self):
    for param in (32 | RH | VL, 96 | RH | RHD | VL):
      self.assertEqual(l.set_safety_hooks(10, param), 0)
      l.init_tests(); l.set_timer(1_000_000)
      self.car()
      self.assertFalse(self.tx(very_low()))


if __name__ == "__main__":
  unittest.main()
