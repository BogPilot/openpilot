#!/usr/bin/env python3
"""Auto Height in Drive: the AP1 panda rule for the 0x308 ride height request in Drive (tesla_ap1.h). Raw wire only, no DBC.

Allowed only with flag 2048, in Drive (DI_torque2 0x118 gear, recent), stopped, gas not pressed, never while controls are allowed,
byte 0 only 0x41-0x44 (Low, Medium, High, Very High; the same levels as in Park), bytes 1-7 equal to the newest touchscreen
0x308 on bus 0 (recent), at most one frame per 15 ms and at most 150 frames per stay in Drive. The Park flag 1024 alone never
allows Drive, and 2048 alone never allows Park.
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
RH = 1024
RHD = 2048
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


def di_torque1(gas):
  b = bytearray(8)
  b[6] = 0x40 if gas else 0x00
  return bytes(b)


def low(src=SCREEN):
  return bytes([0x41]) + src[1:]


def medium(src=SCREEN):
  return bytes([0x42]) + src[1:]


def high(src=SCREEN):
  return bytes([0x43]) + src[1:]


def very_high(src=SCREEN):
  return bytes([0x44]) + src[1:]


LEVELS = (low, medium, high, very_high)


class TestTeslaAp1RideHeightDrive(unittest.TestCase):
  def init(self, param=8 | RHD):
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

  def car(self, gear="D", mph=0.0, src=SCREEN):
    self.rx(0x118, di_torque2(gear, mph))
    self.rx(0x308, src)

  def test_allowed_in_drive_with_flag_every_level(self):
    for param in (8 | RHD, 9 | RHD, 25 | RHD, 8 | RH | RHD, 25 | RH | RHD):
      self.init(param)
      for level in LEVELS:
        self.tick(20_000); self.car()
        self.assertTrue(self.tx(level()), (param, level.__name__))

  def test_never_in_drive_without_its_flag(self):
    for param in (8, 9, 25, 8 | RH, 25 | RH, 8 | 512):
      self.init(param)
      self.car()
      self.assertFalse(self.tx(low()), param)
      self.assertFalse(self.tx(medium()), param)
      self.assertFalse(self.tx(high()), param)
      self.assertFalse(self.tx(very_high()), param)

  def test_drive_flag_alone_never_allows_park(self):
    self.init(8 | RHD)
    for level in LEVELS:
      self.tick(20_000); self.car(gear="P")
      self.assertFalse(self.tx(level()), level.__name__)

  def test_both_flags_keep_park_and_drive(self):
    self.init(8 | RH | RHD)
    self.car(gear="P")
    self.assertTrue(self.tx(low()))
    self.tick(20_000); self.car(gear="D")
    self.assertTrue(self.tx(medium()))

  def test_only_in_drive_and_gear_must_be_recent(self):
    for gear in ("R", "N", "SNA", "INVALID", "P"):
      self.init()
      self.car(gear=gear)
      self.assertFalse(self.tx(low()), gear)
    self.init()
    self.car()
    self.tick(150_000)                       # gear older than 100 ms
    self.rx(0x308, SCREEN)
    self.assertFalse(self.tx(low()))
    self.rx(0x118, di_torque2("D"))
    self.assertTrue(self.tx(low()))

  def test_not_while_moving(self):
    self.init()
    self.car(mph=1.0)
    self.assertFalse(self.tx(low()))
    self.tick(20_000); self.car(mph=0.0)
    self.assertTrue(self.tx(low()))

  def test_not_while_gas_pressed(self):
    self.init()
    self.car()
    self.rx(0x108, di_torque1(True))
    self.assertFalse(self.tx(low()))
    self.rx(0x108, di_torque1(False))
    self.tick(20_000); self.car()
    self.assertTrue(self.tx(low()))

  def test_gas_does_not_affect_park(self):
    self.init(8 | RH | RHD)
    self.car(gear="P")
    self.rx(0x108, di_torque1(True))
    self.assertTrue(self.tx(low()))

  def test_never_while_controls_allowed(self):
    self.init(9 | RHD)
    self.car()
    l.set_controls_allowed(True)
    self.assertFalse(self.tx(low()))
    l.set_controls_allowed(False)
    self.tick(20_000); self.car()
    self.assertTrue(self.tx(low()))

  def test_only_levels_1_to_4(self):
    self.init()
    for b0 in (0x40, 0x45, 0x46, 0x00, 0xFF, 0x01, 0x02, 0x03, 0x04, 0x4F, 0xC3, 0xC4, 0x81, 0x84):
      self.tick(20_000); self.car()
      self.assertFalse(self.tx(bytes([b0]) + SCREEN[1:]), hex(b0))
    for level in LEVELS:
      self.tick(20_000); self.car()
      self.assertTrue(self.tx(level()), level.__name__)

  def test_every_byte0_in_drive_and_park(self):
    for param, gear, allowed in ((8 | RH | RHD, "D", range(0x41, 0x45)), (8 | RH | RHD, "P", range(0x41, 0x45)),
                                 (8 | RHD, "D", range(0x41, 0x45)), (8 | RHD, "P", ()),
                                 (8 | RH, "D", ()), (8 | RH, "P", range(0x41, 0x45)), (8, "D", ()), (8, "P", ())):
      self.init(param)
      for b0 in range(256):
        self.tick(20_000); self.car(gear=gear)
        self.assertEqual(self.tx(bytes([b0]) + SCREEN[1:]), b0 in allowed, (param, gear, hex(b0)))

  def test_high_and_very_high_follow_every_drive_condition(self):
    # Moving, gas, controls allowed, stale gear, stale screen frame, wrong bytes 1-7, other gears, missing flag: refused like Low.
    for level in (high, very_high):
      self.init(); self.car(mph=1.0); self.assertFalse(self.tx(level()))
      self.init(); self.car(); self.rx(0x108, di_torque1(True)); self.assertFalse(self.tx(level()))
      self.init(9 | RHD); self.car(); l.set_controls_allowed(True); self.assertFalse(self.tx(level()))
      self.init(); self.car(); self.tick(150_000); self.rx(0x308, SCREEN); self.assertFalse(self.tx(level()))
      self.init(); self.car(); self.tick(600_000); self.rx(0x118, di_torque2("D")); self.assertFalse(self.tx(level()))
      self.init(); self.car(); bad = bytearray(level()); bad[3] ^= 1; self.assertFalse(self.tx(bytes(bad)))
      for gear in ("R", "N", "SNA", "INVALID"):
        self.init(); self.car(gear=gear); self.assertFalse(self.tx(level()), gear)
      self.init(8 | RH); self.car(); self.assertFalse(self.tx(level()))

  def test_bytes_1_to_7_must_match_the_newest_screen_frame(self):
    self.init()
    self.car()
    for i in range(1, 8):
      bad = bytearray(low())
      bad[i] ^= 0x01
      self.tick(20_000); self.car()
      self.assertFalse(self.tx(bytes(bad)), i)
    newer = bytes.fromhex("4066d20b3200f400")
    self.tick(20_000); self.car(src=newer)
    self.assertFalse(self.tx(low()))
    self.assertTrue(self.tx(low(newer)))

  def test_no_screen_frame_or_stale_screen_frame(self):
    self.init()
    self.rx(0x118, di_torque2("D"))
    self.assertFalse(self.tx(low()))
    self.rx(0x308, SCREEN)
    self.tick(600_000)
    self.rx(0x118, di_torque2("D"))
    self.assertFalse(self.tx(low()))

  def test_screen_frame_only_from_bus_0(self):
    self.init()
    self.rx(0x118, di_torque2("D"))
    self.rx(0x308, SCREEN, bus=2)
    self.assertFalse(self.tx(low()))

  def test_bus_and_length(self):
    self.init()
    self.car()
    self.assertFalse(self.tx(low(), bus=2))
    self.assertFalse(self.tx(low(), bus=1))
    self.assertFalse(bool(l.safety_tx_hook(packet(0x308, low()[:7]))))

  def test_rate_cap_15ms(self):
    self.init()
    self.car()
    self.assertTrue(self.tx(low()))
    self.tick(10_000); self.car()
    self.assertFalse(self.tx(low()))
    self.tick(6_000); self.car()
    self.assertTrue(self.tx(low()))

  def test_150_frames_per_drive_stay_then_rearm_after_leaving_drive(self):
    self.init()
    sent = 0
    for _ in range(400):
      self.tick(20_000); self.car()
      sent += self.tx(low())
    self.assertEqual(sent, 150)
    self.tick(20_000); self.car(gear="P")
    self.tick(20_000); self.car()
    self.assertTrue(self.tx(low()))

  def test_park_and_drive_have_their_own_frame_budget(self):
    self.init(8 | RH | RHD)
    sent = 0
    for _ in range(200):
      self.tick(20_000); self.car(gear="P")
      sent += self.tx(low())
    self.assertEqual(sent, 150)
    sent = 0
    for _ in range(200):
      self.tick(20_000); self.car(gear="D")
      sent += self.tx(low())
    self.assertEqual(sent, 150)

  def test_proven_burst_fits_the_rule_in_drive(self):
    """100 frames at 50 Hz with the screen at 10 Hz and gear at 100 Hz: every frame passes."""
    self.init()
    ok = 0
    for k in range(200):
      self.tick(10_000)
      self.rx(0x118, di_torque2("D"))
      if k % 10 == 0:
        self.rx(0x308, SCREEN)
      if k % 2 == 0:
        ok += self.tx(very_high())
    self.assertEqual(ok, 100)

  def test_flag_cleared_on_reinit(self):
    self.init(8 | RHD)
    self.car()
    self.assertTrue(self.tx(low()))
    self.init(8)
    self.car()
    self.assertFalse(self.tx(low()))

  def test_other_ap1_tx_unchanged_by_the_flag(self):
    for param in (8, 8 | RHD, 8 | RH | RHD):
      self.init(param)
      l.set_controls_allowed(False)
      self.assertTrue(bool(l.safety_tx_hook(packet(0x45, [1] + [0] * 7))))
      self.assertFalse(bool(l.safety_tx_hook(packet(0x45, [2] + [0] * 7))))
      self.assertTrue(bool(l.safety_tx_hook(packet(0x349, bytes(8)))))

  def test_preap_mode_never_sends_0x308(self):
    for param in (32 | RHD, 96 | RHD, 32 | RH | RHD):
      self.assertEqual(l.set_safety_hooks(10, param), 0)
      l.init_tests(); l.set_timer(1_000_000)
      l.safety_rx_hook(packet(0x118, di_torque2("D")))
      l.safety_rx_hook(packet(0x308, SCREEN))
      self.assertFalse(bool(l.safety_tx_hook(packet(0x308, low()))))
      self.assertFalse(bool(l.safety_tx_hook(packet(0x308, high()))))
      self.assertFalse(bool(l.safety_tx_hook(packet(0x308, very_high()))))


if __name__ == "__main__":
  unittest.main()
