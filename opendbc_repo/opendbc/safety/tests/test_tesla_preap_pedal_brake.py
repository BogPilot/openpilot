#!/usr/bin/env python3
"""Pre-AP: a brake press blocks an enabled Comma Pedal command (0x551). Raw-wire, no DBC.

tesla_preap.h tx hook: an enabled GAS_COMMAND (ENABLE, byte 4 bit 7) is rejected while brake_pressed, independent of
controls_allowed; brake_pressed is BrakeMessage (0x20A) driverBrakeStatus != NOT_APPLIED or DI_torque2 (0x118) DI_brakePedal.
Idle frames (ENABLE clear, raw <= 500) are not affected by the brake. A rejected frame is refused by the tx hook, never
rewritten. A brake press also clears controls_allowed (safety.h generic_rx_checks): a rising edge always, a held brake only
while moving. Brake RX is processed before the TX in every case here; no counter or checksum is checked on 0x551 TX.
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_preap import LONG, PEDAL, PREAP, PreapCase, brake_msg, di_torque2, esp_b, pedal_cmd, pedal_sensor, stalk

l = libsafety_py.libsafety
ENABLED_RAW = 1500
PEDAL_BUSES = (0, 2)


class TestPreapPedalBrake(PreapCase):
  PARAM = PREAP | PEDAL | LONG

  def enabled_ok(self):
    return [self.tx(pedal_cmd(ENABLED_RAW, True, bus)) for bus in PEDAL_BUSES]

  def press(self, source):
    if source == "brake_msg":
      self.assertTrue(l.safety_rx_hook(brake_msg(True)))
    else:
      self.assertTrue(l.safety_rx_hook(di_torque2(brake=True)))

  def release(self, source):
    if source == "brake_msg":
      self.assertTrue(l.safety_rx_hook(brake_msg(False)))
    else:
      self.assertTrue(l.safety_rx_hook(di_torque2(brake=False)))

  def test_brake_released_enabled_pedal_is_accepted(self):
    self.engage()
    self.assertEqual(self.enabled_ok(), [True, True])

  def test_brake_press_while_moving_blocks_enabled_but_not_idle(self):
    self.feed_all(speed=12.0)
    self.engage()
    self.press("brake_msg")
    self.assertFalse(l.get_controls_allowed())
    self.assertEqual(self.enabled_ok(), [False, False])
    self.assertTrue(self.tx(pedal_cmd(0, False)))
    self.assertTrue(self.tx(pedal_cmd(500, False)))
    self.assertFalse(self.tx(pedal_cmd(501, False)))

  def test_brake_rule_holds_even_with_controls_allowed(self):
    for source in ("brake_msg", "di_brake"):
      with self.subTest(source=source):
        self.setUp()
        self.press(source)
        l.set_controls_allowed(True)
        self.assertEqual(self.enabled_ok(), [False, False], "brake pressed: enabled pedal rejected")
        self.assertTrue(self.tx(pedal_cmd(0, False)))
        self.release(source)
        self.assertTrue(l.get_controls_allowed())
        self.assertEqual(self.enabled_ok(), [True, True], "brake released: enabled pedal accepted")

  def test_brake_rx_then_enabled_tx_in_the_same_tick(self):
    self.engage()
    self.assertEqual(self.enabled_ok(), [True, True])
    self.press("brake_msg")
    self.assertEqual(self.enabled_ok(), [False, False])

  def test_pull_with_the_brake_already_held_at_a_standstill(self):
    for source in ("brake_msg", "di_brake"):
      with self.subTest(source=source):
        self.setUp()
        self.press(source)
        l.safety_rx_hook(stalk(0))
        self.pull()
        self.assertTrue(l.get_controls_allowed(), "no rising edge at a standstill")
        self.assertEqual(self.enabled_ok(), [False, False])
        self.release(source)
        self.assertEqual(self.enabled_ok(), [True, True])

  def test_release_does_not_bring_the_pedal_back_without_a_new_pull(self):
    self.feed_all(speed=12.0)
    self.engage()
    self.press("brake_msg")
    self.release("brake_msg")
    self.assertTrue(l.safety_rx_hook(esp_b(12.0)))
    self.assertFalse(l.get_controls_allowed())
    self.assertEqual(self.enabled_ok(), [False, False])
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertEqual(self.enabled_ok(), [True, True])

  def test_releasing_one_of_two_sources_still_blocks(self):
    self.press("brake_msg")
    self.press("di_brake")
    l.set_controls_allowed(True)
    self.release("brake_msg")
    self.assertEqual(self.enabled_ok(), [False, False], "DI_brakePedal still pressed")
    self.release("di_brake")
    self.assertEqual(self.enabled_ok(), [True, True])

  def test_controls_not_allowed_blocks_enabled_with_or_without_the_brake(self):
    self.assertFalse(l.get_controls_allowed())
    self.assertEqual(self.enabled_ok(), [False, False])
    self.assertTrue(self.tx(pedal_cmd(0, False)))
    self.press("brake_msg")
    self.assertEqual(self.enabled_ok(), [False, False])
    self.assertTrue(self.tx(pedal_cmd(0, False)))

  def test_bound_still_applies_after_release(self):
    self.press("brake_msg")
    self.release("brake_msg")
    self.engage()
    self.assertTrue(self.tx(pedal_cmd(2500, True)))
    self.assertFalse(self.tx(pedal_cmd(2501, True)))

  def test_idle_frames_while_braking_keep_the_500_cap(self):
    self.engage()
    self.press("brake_msg")
    for bus in PEDAL_BUSES:
      self.assertTrue(self.tx(pedal_cmd(500, False, bus)))
      self.assertFalse(self.tx(pedal_cmd(501, False, bus)))
    self.assertFalse(self.tx(pedal_cmd(2500, True)), "in range but braking")

  def test_other_buses_are_rejected(self):
    self.engage()
    for bus in (1, 3):
      self.assertFalse(self.tx(pedal_cmd(ENABLED_RAW, True, bus)), bus)
      self.assertFalse(self.tx(pedal_cmd(0, False, bus)), bus)

  def test_gas_on_the_latched_pedal_bus_blocks_enabled(self):
    self.engage()
    self.assertTrue(l.safety_rx_hook(pedal_sensor(651)))
    self.assertTrue(l.get_controls_allowed())
    self.assertEqual(self.enabled_ok(), [False, False], "gas_pressed_prev")
    self.assertTrue(l.safety_rx_hook(pedal_sensor(650)))
    self.assertEqual(self.enabled_ok(), [True, True], "650 is not pressed")

  def test_gas_and_brake_together(self):
    self.engage()
    self.assertTrue(l.safety_rx_hook(pedal_sensor(700)))
    self.press("brake_msg")
    self.assertEqual(self.enabled_ok(), [False, False])
    l.set_controls_allowed(True)
    self.assertEqual(self.enabled_ok(), [False, False])
    self.release("brake_msg")
    self.assertEqual(self.enabled_ok(), [False, False], "gas still pressed")
    self.assertTrue(l.safety_rx_hook(pedal_sensor(0)))
    self.assertEqual(self.enabled_ok(), [True, True])

  def test_controls_allowed_by_brake_edge_and_speed(self):
    # rising edge at a standstill clears controls
    self.engage()
    self.press("di_brake")
    self.assertFalse(l.get_controls_allowed())
    # held brake at a standstill: a pull can set controls again and the next frames keep it
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.press("di_brake")
    self.assertTrue(l.get_controls_allowed())
    self.assertEqual(self.enabled_ok(), [False, False])
    # the same held brake once moving clears controls
    self.assertTrue(l.safety_rx_hook(esp_b(12.0)))
    self.press("di_brake")
    self.assertFalse(l.get_controls_allowed())
    self.assertEqual(self.enabled_ok(), [False, False])


class TestPreapPedalBrakeWithoutPedalFlag(PreapCase):
  PARAM = PREAP

  def test_pedal_flag_unset_rejects_every_0x551(self):
    self.engage()
    for bus in PEDAL_BUSES:
      self.assertFalse(self.tx(pedal_cmd(ENABLED_RAW, True, bus)))
      self.assertFalse(self.tx(pedal_cmd(0, False, bus)))

if __name__ == "__main__":
  unittest.main()
