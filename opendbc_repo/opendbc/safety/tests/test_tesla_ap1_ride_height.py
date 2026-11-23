#!/usr/bin/env python3
"""Auto Height in Park (was Lower on Park): the AP1 panda rule for the 0x308 ride height request (tesla_ap1.h). Raw wire only.

Allowed only with flag 1024, in Park (DI_torque2 0x118 gear, recent), stopped, never while controls are allowed, byte 0 only
0x41-0x44 (Low, Medium, High, Very High), bytes 1-7 equal to the newest touchscreen 0x308 on bus 0 (recent), at most one frame per 15 ms and at most 150
frames per stay in Park.
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
RH = 1024
SCREEN = bytes.fromhex("4066ad0b3200f500")
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


def low(src=SCREEN):
  return bytes([0x41]) + src[1:]


class TestTeslaAp1RideHeight(unittest.TestCase):
  def init(self, param=8 | RH):
    self.assertEqual(l.set_safety_hooks(10, param), 0)
    l.init_tests()
    self.t = 1_000_000
    l.set_timer(self.t)

  def tick(self, us):
    self.t += us
    l.set_timer(self.t)

  def rx(self, addr, data, bus=0):
    p = packet(addr, data, bus)
    l.safety_rx_hook(p)

  def tx(self, data, bus=0, addr=0x308):
    return bool(l.safety_tx_hook(packet(addr, data, bus)))

  def parked(self, src=SCREEN, gear="P", mph=0.0):
    self.rx(0x118, di_torque2(gear, mph))
    self.rx(0x308, src)

  def test_allowed_in_park_with_flag_low_and_medium(self):
    for param in (8 | RH, 9 | RH, 25 | RH):
      self.init(param)
      self.parked()
      self.assertTrue(self.tx(low()))
      self.tick(20_000); self.parked()
      self.assertTrue(self.tx(bytes([0x42]) + SCREEN[1:]))

  def test_never_without_the_flag(self):
    for param in (8, 9, 25, 8 | 512):
      self.init(param)
      self.parked()
      self.assertFalse(self.tx(low()))

  def test_only_levels_1_to_4(self):
    self.init()
    for b0 in range(256):
      self.tick(20_000); self.parked()
      self.assertEqual(self.tx(bytes([b0]) + SCREEN[1:]), 0x41 <= b0 <= 0x44, hex(b0))

  def test_high_and_very_high_follow_every_park_condition(self):
    for b0 in (0x43, 0x44):
      frame = bytes([b0]) + SCREEN[1:]
      self.init(8); self.parked(); self.assertFalse(self.tx(frame))                  # no flag
      self.init(); self.parked(); self.assertTrue(self.tx(frame))
      self.tick(5_000); self.parked(); self.assertFalse(self.tx(frame))              # 15 ms gap
      self.init(9 | RH); self.parked(); l.set_controls_allowed(True); self.assertFalse(self.tx(frame))
      self.init(); self.parked(); bad = bytearray(frame); bad[5] ^= 1; self.assertFalse(self.tx(bytes(bad)))

  def test_bytes_1_to_7_must_match_the_newest_screen_frame(self):
    self.init()
    self.parked()
    for i in range(1, 8):
      bad = bytearray(low()); bad[i] ^= 0x01
      self.tick(20_000); self.parked()
      self.assertFalse(self.tx(bytes(bad)), i)
    newer = bytes.fromhex("4067b30b3200f400")
    self.tick(20_000); self.parked(src=newer)
    self.assertFalse(self.tx(low(SCREEN)))
    self.assertTrue(self.tx(low(newer)))

  def test_no_screen_frame_or_stale_screen_frame(self):
    self.init()
    self.rx(0x118, di_torque2("P"))
    self.assertFalse(self.tx(bytes([0x41]) + bytes(7)))            # zeros == the never-received buffer, still refused
    self.assertFalse(self.tx(low()))
    self.parked()
    self.tick(600_000); self.rx(0x118, di_torque2("P"))
    self.assertFalse(self.tx(low()))
    self.rx(0x308, SCREEN)
    self.assertTrue(self.tx(low()))

  def test_screen_frame_only_from_bus_0(self):
    self.init()
    self.rx(0x118, di_torque2("P"))
    for bus in (1, 2):
      self.rx(0x308, SCREEN, bus)
    self.assertFalse(self.tx(low()))

  def test_only_in_park_and_gear_must_be_recent(self):
    for gear in ("R", "N", "D", "SNA", "INVALID"):
      self.init()
      self.parked(gear=gear)
      self.assertFalse(self.tx(low()), gear)
    self.init()
    self.rx(0x308, SCREEN)
    self.assertFalse(self.tx(low()))                                 # no gear seen yet
    self.parked()
    self.tick(150_000); self.rx(0x308, SCREEN)
    self.assertFalse(self.tx(low()))                                 # gear older than 100 ms

  def test_not_while_moving(self):
    self.init()
    self.parked(mph=3.0)
    self.assertFalse(self.tx(low()))

  def test_never_while_controls_allowed(self):
    self.init()
    self.parked()
    l.set_controls_allowed(True)
    self.assertFalse(self.tx(low()))
    l.set_controls_allowed(False)
    self.assertTrue(self.tx(low()))

  def test_bus_and_length(self):
    self.init()
    self.parked()
    for bus in (1, 2, 3):
      self.assertFalse(self.tx(low(), bus))
    self.assertFalse(self.tx(low()[:6]))

  def test_rate_cap_15ms(self):
    self.init()
    self.parked()
    self.assertTrue(self.tx(low()))
    self.tick(10_000); self.parked()
    self.assertFalse(self.tx(low()))
    self.tick(6_000); self.parked()
    self.assertTrue(self.tx(low()))

  def test_150_frames_per_park_stay_then_rearm_after_leaving_park(self):
    self.init()
    sent = 0
    for _ in range(400):
      self.tick(20_000); self.parked()
      sent += self.tx(low())
    self.assertEqual(sent, 150)
    self.tick(20_000); self.parked(gear="D")
    self.tick(20_000); self.parked()
    self.assertTrue(self.tx(low()))

  def test_proven_burst_fits_the_rule(self):
    """100 frames at 50 Hz with the screen at 10 Hz and gear at 100 Hz: every frame passes."""
    self.init()
    ok = 0
    for k in range(200):                     # 2 s in 10 ms steps
      self.tick(10_000)
      self.rx(0x118, di_torque2("P"))
      if k % 10 == 0:
        self.rx(0x308, SCREEN)
      if k % 2 == 0:
        ok += self.tx(low())
    self.assertEqual(ok, 100)

  def test_other_ap1_tx_unchanged_by_the_flag(self):
    for param in (8, 8 | RH):
      self.init(param)
      l.set_controls_allowed(False)
      self.assertTrue(bool(l.safety_tx_hook(packet(0x45, [1] + [0] * 7))))
      self.assertFalse(bool(l.safety_tx_hook(packet(0x45, [2] + [0] * 7))))
      self.assertTrue(bool(l.safety_tx_hook(packet(0x349, bytes(8)))))

  def test_preap_mode_never_sends_0x308(self):
    for param in (32, 32 | RH, 96 | RH):
      self.assertEqual(l.set_safety_hooks(10, param), 0)
      l.init_tests(); l.set_timer(1_000_000)
      l.safety_rx_hook(packet(0x118, di_torque2("P")))
      l.safety_rx_hook(packet(0x308, SCREEN))
      self.assertFalse(bool(l.safety_tx_hook(packet(0x308, low()))))

  def test_screen_0x308_does_not_trip_the_relay_check(self):
    self.init()
    self.parked()
    self.assertFalse(l.get_relay_malfunction())


if __name__ == "__main__":
  unittest.main()
