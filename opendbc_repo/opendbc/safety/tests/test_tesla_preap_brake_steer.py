#!/usr/bin/env python3
"""Pre-AP: steering keeps its own permission through a brake press; the pedal does not. Raw-wire, no DBC.

Design (tesla_preap.h): a stalk pull arms a steering latch. A brake press still drops controls_allowed (that is what blocks the pedal), but
if the session was armed by a pull and a brake press happened since, steering is still allowed. It never opens longitudinal, and an
enabled 0x551 is blocked whenever the brake is pressed. Disarmed by cancel, an EPAS fault, leaving D, a door, a stale monitored
stream and any safety-mode (re)init; only a new pull arms again. A gas press does NOT disarm it. Steering still obeys the angle rate limits and the 360 deg cap.
"""
import unittest

from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_preap import (AP1, LONG, PEDAL, PREAP, SAFETY_TESLA, PreapCase, brake_msg, di_state, di_torque1, di_torque2,
                                                   doors, eac, epas, esp_b, pedal_cmd, pedal_sensor, stalk, steer)

l = libsafety_py.libsafety
MPH = 0.44704


class BrakeSteerCase(PreapCase):
  PARAM = PREAP | PEDAL | LONG

  def setUp(self):
    super().setUp()
    self.feed_all(speed=12.0)

  def feed_held(self, speed=12.0, angle=0.0, gear=4, brake=True, gas=0, pedal=True, ms=6):
    """Keep every monitored stream fresh while the brake is held (or released with brake=False)."""
    for _ in range(ms):
      for m in (epas(angle), esp_b(speed), di_torque2(gear=gear, brake=brake), di_torque1(gas=gas), brake_msg(brake), doors(), di_state(), stalk(0)):
        self.assertTrue(l.safety_rx_hook(m))
      if pedal:
        self.assertTrue(l.safety_rx_hook(pedal_sensor(0)))

  def press_brake(self):
    self.assertTrue(l.safety_rx_hook(brake_msg(True)))
    self.assertFalse(l.get_controls_allowed(), "a brake press drops controls_allowed (it blocks the pedal)")

  def engaged_then_braked(self):
    self.engage()
    self.assertTrue(self.tx(steer(0)))
    self.press_brake()


class TestBrakeKeepsSteering(BrakeSteerCase):
  def test_brake_press_keeps_steering_and_blocks_the_pedal(self):
    self.engaged_then_braked()
    self.assertTrue(self.tx(steer(0)), "steering carries on through the press")
    self.assertTrue(self.tx(steer(20)))
    self.assertFalse(self.tx(pedal_cmd(1500, True)), "enabled pedal blocked")
    self.assertTrue(self.tx(pedal_cmd(0, False)), "disabled (idle) pedal frames still go out")
    self.assertTrue(self.tx(pedal_cmd(400, False)))
    self.assertFalse(l.get_controls_allowed(), "this never sets controls_allowed")

  def test_held_brake_for_seconds_keeps_steering_while_streams_stay_fresh(self):
    self.engaged_then_braked()
    for _ in range(5):
      self.advance(500_000)
      self.feed_held()
      self.assertTrue(self.tx(steer(0)))
    self.assertFalse(self.tx(pedal_cmd(1500, True)))

  def test_brake_released_steering_stays_pedal_waits_for_a_new_pull(self):
    self.engaged_then_braked()
    self.feed_held(brake=False)
    self.assertFalse(l.get_controls_allowed())
    self.assertTrue(self.tx(steer(0)), "steering continues after the brake is released")
    self.assertFalse(self.tx(pedal_cmd(1500, True)), "the pedal needs a new pull")
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed())
    self.assertTrue(self.tx(pedal_cmd(1500, True)), "a new pull with the brake free brings the pedal back")

  def test_rate_limits_and_angle_cap_still_apply_through_the_press(self):
    self.engaged_then_braked()
    self.assertTrue(self.tx(steer(0)))
    self.assertTrue(self.tx(steer(30)))
    self.assertFalse(self.tx(steer(600)), "a 60 deg jump in one command is a rate violation")
    self.assertFalse(self.tx(steer(3601)), "past the 360 deg cap")

  def test_second_brake_press_after_release_still_steers(self):
    self.engaged_then_braked()
    self.feed_held(brake=False)
    self.assertTrue(self.tx(steer(0)))
    self.assertTrue(l.safety_rx_hook(brake_msg(True)))
    self.assertTrue(self.tx(steer(0)))

  def test_no_pull_means_no_permission_even_with_a_brake_press(self):
    self.assertFalse(l.get_controls_allowed())
    self.assertTrue(l.safety_rx_hook(brake_msg(True)))
    self.assertFalse(self.tx(steer(0, ctype=1)))
    self.feed_held()
    self.assertFalse(self.tx(steer(0, ctype=1)))

  def test_controls_dropped_without_a_brake_press_gives_no_extra_permission(self):
    self.engage()
    self.assertTrue(self.tx(steer(0)))
    l.set_controls_allowed(False)                    # dropped some other way: the latch alone grants nothing
    self.assertFalse(self.tx(steer(0)))
    self.feed_held(brake=False)
    self.assertFalse(self.tx(steer(0)))

  def test_pull_with_the_brake_already_held_blocks_the_pedal_even_at_a_standstill(self):
    self.feed_all(speed=0.0)
    l.safety_rx_hook(brake_msg(True))
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed(), "at a standstill only a rising edge drops controls")
    self.assertFalse(self.tx(pedal_cmd(1500, True)), "but the brake rule blocks the pedal")
    l.safety_rx_hook(brake_msg(False))
    self.assertTrue(self.tx(pedal_cmd(1500, True)))


class TestDisarm(BrakeSteerCase):
  def check_off_until_repull(self, restore):
    self.assertFalse(self.tx(steer(0)))
    restore()
    self.feed_held(brake=False)
    self.assertFalse(self.tx(steer(0)), "the prerequisite is back but nobody pulled: still off")
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed())
    self.assertTrue(self.tx(steer(0)), "a new pull arms again")
    self.press_brake()
    self.assertTrue(self.tx(steer(0)), "and steering survives the next press")

  def test_cancel_disarms(self):
    self.engaged_then_braked()
    self.advance(700_000)
    self.feed_held()
    l.safety_rx_hook(stalk(1))
    self.check_off_until_repull(lambda: l.safety_rx_hook(stalk(0)))

  def test_cancel_echo_inside_600ms_does_not_disarm(self):
    self.engaged_then_braked()
    self.advance(100_000)
    l.safety_rx_hook(stalk(1))
    self.assertTrue(self.tx(steer(0)))

  def test_hands_on_disarms_the_brake_latch(self):
    self.engaged_then_braked()
    l.safety_rx_hook(epas(0.0, hands=3))
    self.assertFalse(self.tx(steer(0)))
    l.safety_rx_hook(epas(0.0, hands=0))
    self.assertFalse(self.tx(steer(0)), "G1: a takeover ends the brake-interrupted session, a new pull is needed")

  def test_epas_refusing_disarms_the_brake_latch(self):
    self.engaged_then_braked()
    l.safety_rx_hook(epas(0.0, eac_status=0, err=7))
    self.assertFalse(self.tx(steer(0)))
    l.safety_rx_hook(epas(0.0, eac_status=1, err=0))
    self.assertFalse(self.tx(steer(0)), "G1: a new pull is needed")

  def test_epas_fault_disarms(self):
    self.engaged_then_braked()
    l.safety_rx_hook(epas(0.0, eac_status=3))
    self.check_off_until_repull(lambda: l.safety_rx_hook(epas(0.0, eac_status=1, err=0)))

  def test_leaving_drive_disarms(self):
    self.engaged_then_braked()
    self.feed_held(gear=3)
    self.check_off_until_repull(lambda: self.feed_held(gear=4))

  def test_door_open_disarms(self):
    self.engaged_then_braked()
    l.safety_rx_hook(doors(open_fl=True))
    self.check_off_until_repull(lambda: l.safety_rx_hook(doors()))

  def test_stale_stream_disarms(self):
    self.engaged_then_braked()
    self.advance(1_200_000)                          # nothing received for 1.2 s
    self.check_off_until_repull(lambda: None)

  def test_lost_pedal_stream_disarms(self):
    self.engaged_then_braked()
    self.advance(600_000)
    self.feed_held(pedal=False)                      # everything else is fresh, the Comma Pedal is silent
    self.advance(600_000)
    self.feed_held(pedal=False)
    self.assertFalse(self.tx(steer(0)))

  def test_gas_press_does_not_disarm(self):
    # the driver braked, then got back on the accelerator. Steering must carry on (openpilot still shows engaged), pedal stays blocked.
    self.engaged_then_braked()
    self.assertTrue(l.safety_rx_hook(pedal_sensor(1500)))   # interceptor gas > 650: the driver is on the accelerator
    self.assertTrue(self.tx(steer(0)))
    self.assertFalse(self.tx(pedal_cmd(1500, True)), "the pedal stays blocked")
    self.assertTrue(l.safety_rx_hook(pedal_sensor(0)))
    self.assertTrue(self.tx(steer(0)))

  def test_brake_release_then_repeated_gas_edges_keep_steering(self):
    # brake tap, release, then a string of gas rising edges (the tester logged 15 in 35 s) with every stream fresh
    self.engaged_then_braked()
    for _ in range(3):
      self.advance(300_000)
      self.feed_held(brake=False)
      self.assertTrue(self.tx(steer(0)))
    for _ in range(15):
      self.assertTrue(l.safety_rx_hook(pedal_sensor(1500)))
      self.advance(40_000)
      self.feed_held(brake=False, ms=1)
      self.assertTrue(self.tx(steer(0)), "steering after a gas rising edge")
      self.assertTrue(l.safety_rx_hook(pedal_sensor(0)))
      self.advance(40_000)
      self.feed_held(brake=False, ms=1)
      self.assertTrue(self.tx(steer(0)))
    self.assertFalse(self.tx(pedal_cmd(1500, True)), "the pedal is never opened by the latch")
    self.assertFalse(l.get_controls_allowed())

  def test_gas_before_the_brake_does_not_stop_the_latch_arming(self):
    # second hit: a gas edge just before the brake press must not leave the later brake without steering
    self.engage()
    self.assertTrue(l.safety_rx_hook(pedal_sensor(1500)))
    self.assertTrue(l.safety_rx_hook(pedal_sensor(0)))
    self.press_brake()
    self.assertTrue(self.tx(steer(0)))

  def test_cancel_still_disarms_after_gas(self):
    self.engaged_then_braked()
    self.assertTrue(l.safety_rx_hook(pedal_sensor(1500)))
    self.advance(700_000)
    l.safety_rx_hook(stalk(1))
    self.assertFalse(self.tx(steer(0)))

  def test_safety_mode_change_removes_the_permission(self):
    self.engaged_then_braked()
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, PREAP | PEDAL), 0)
    l.init_tests()
    self.assertFalse(self.tx(steer(0, ctype=1)))


class TestOtherModesUnchanged(unittest.TestCase):
  def test_model_3_y_and_ap1_still_lose_steering_on_a_brake_press(self):
    for param in (0, AP1, AP1 | 1):
      self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
      l.init_tests()
      l.set_timer(1_000_000)
      l.safety_rx_hook(stalk(2))                       # a Pre-AP pull byte means nothing here
      self.assertFalse(l.safety_tx_hook(steer(0, ctype=1)), param)

  def test_pre_ap_without_the_pedal_flag_has_the_same_steering_rule(self):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, PREAP), 0)
    l.init_tests()
    l.set_timer(1_000_000)
    for _ in range(6):
      for m in (epas(), esp_b(12.0), di_torque2(), di_torque1(), brake_msg(False), doors(), di_state(), stalk(0)):
        l.safety_rx_hook(m)
    l.safety_rx_hook(stalk(2))
    self.assertTrue(l.get_controls_allowed())
    self.assertTrue(l.safety_tx_hook(steer(0)))
    l.safety_rx_hook(brake_msg(True))
    self.assertFalse(l.get_controls_allowed())
    self.assertTrue(l.safety_tx_hook(steer(0)))


if __name__ == "__main__":
  unittest.main()
