#!/usr/bin/env python3
"""BogPilot Pre-AP Model S safety (SAFETY_TESLA + flag 32, optional pedal flag 64). Raw-wire tests, no DBC.

Engage: stalk pull (SpdCtrlLvr_Stat 2) with gear D and doors closed. Disengage: cancel (outside the 600 ms echo window), brake,
an EPAS fault, gear out of D, door open. Hands on and an EPAS refusal only reject ANGLE while they last (steering resumes by itself). TX: steering 0x488 (rate checked, NONE/ANGLE only), 0x214 EACAllow 0/1, 0x45 cancel only,
0x551 Comma Pedal only with the pedal flag, enabled only while longitudinal is allowed and bounded.
"""
import unittest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
PREAP = 32
PEDAL = 64
AP1 = 8
LONG = 1


def pkt(addr, dat, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(dat))


def epas(angle_deg=0.0, hands=0, eac_status=1, err=0):
  raw = int(round(angle_deg * 10)) + 8192
  d = bytearray(8)
  d[2] = (err & 0x0F) << 4
  d[4] = ((hands & 3) << 6) | ((raw >> 8) & 0x3F)
  d[5] = raw & 0xFF
  d[6] = (eac_status & 7) << 5
  return pkt(0x370, d)


def esp_b(speed_mps):
  raw = int(round(speed_mps / 0.277778 / 0.01))
  d = bytearray(8)
  d[5] = (raw >> 8) & 0xFF
  d[6] = raw & 0xFF
  return pkt(0x155, d)


def di_torque2(gear=4, brake=False):
  d = bytearray(6)
  d[1] = ((gear & 7) << 4) | (0x80 if brake else 0)
  return pkt(0x118, d)


def di_torque1(gas=0):
  d = bytearray(8)
  d[6] = gas
  return pkt(0x108, d)


def brake_msg(pressed):
  d = bytearray(8)
  d[0] = (2 if pressed else 1) << 2
  return pkt(0x20a, d)


def doors(open_fl=False):
  d = bytearray(8)
  d[1] = (1 << 4) if open_fl else 0
  return pkt(0x318, d)


def stalk(lever):
  d = bytearray(8)
  d[0] = lever
  return pkt(0x45, d)


def di_state():
  return pkt(0x368, bytearray(8))


def pedal_sensor(val, bus=0):
  d = bytearray(6)
  d[0] = (val >> 8) & 0xFF
  d[1] = val & 0xFF
  return pkt(0x552, d, bus)


def steer(angle_can, ctype=1):
  raw = angle_can + 16384
  d = bytearray(4)
  d[0] = (raw >> 8) & 0x7F
  d[1] = raw & 0xFF
  d[2] = (ctype & 3) << 6
  return pkt(0x488, d)


def eac(mode):
  return pkt(0x214, bytes([mode & 7, 0, 0]))


def pedal_cmd(raw, enable, bus=0):
  d = bytearray(6)
  d[0] = (raw >> 8) & 0xFF
  d[1] = raw & 0xFF
  d[4] = 0x80 if enable else 0
  return pkt(0x551, d, bus)


class PreapCase(unittest.TestCase):
  PARAM = PREAP

  def setUp(self):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, self.PARAM), 0)
    l.init_tests()
    l.set_timer(1_000_000)
    self.t = 1_000_000
    self.feed_all()
    self.assertFalse(l.get_controls_allowed())

  def advance(self, us):
    self.t += us
    l.set_timer(self.t)

  def feed_all(self, speed=0.0, angle=0.0):
    for _ in range(6):
      for m in (epas(angle), esp_b(speed), di_torque2(), di_torque1(), brake_msg(False), doors(), di_state(), stalk(0)):
        self.assertTrue(l.safety_rx_hook(m))
      if self.PARAM & PEDAL:
        self.assertTrue(l.safety_rx_hook(pedal_sensor(0)))

  def pull(self):
    self.assertTrue(l.safety_rx_hook(stalk(2)))

  def engage(self):
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed())

  def tx(self, m):
    return bool(l.safety_tx_hook(m))


class TestPreapEngageDisengage(PreapCase):
  def test_pull_engages_in_gear_d_with_doors_closed(self):
    self.engage()

  def test_pull_does_nothing_in_other_gears_or_with_a_door_open(self):
    for _ in range(6):
      l.safety_rx_hook(di_torque2(gear=3))
    self.pull()
    self.assertFalse(l.get_controls_allowed())
    for _ in range(6):
      l.safety_rx_hook(di_torque2(gear=4))
    l.safety_rx_hook(stalk(0))
    l.safety_rx_hook(doors(open_fl=True))
    self.pull()
    self.assertFalse(l.get_controls_allowed())

  def test_cancel_disengages_but_the_echo_right_after_our_pull_is_ignored(self):
    self.engage()
    self.advance(100_000)
    l.safety_rx_hook(stalk(1))
    self.assertTrue(l.get_controls_allowed(), "echo inside 600 ms")
    self.advance(700_000)
    l.safety_rx_hook(stalk(1))
    self.assertFalse(l.get_controls_allowed())

  def test_repull_after_cancel_rearms(self):
    self.engage()
    self.advance(700_000)
    l.safety_rx_hook(stalk(1))
    self.assertFalse(l.get_controls_allowed())
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed())

  def test_repull_after_a_non_cancel_drop_rearms(self):
    self.engage()
    l.safety_rx_hook(epas(0.0, eac_status=3))   # an EPAS fault drops controls without any cancel
    self.assertFalse(l.get_controls_allowed())
    l.safety_rx_hook(epas(0.0, eac_status=1))
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed())

  def test_brake_message_drops_controls(self):
    self.engage()
    l.safety_rx_hook(brake_msg(True))
    self.assertFalse(l.get_controls_allowed())

  def test_di_brake_pedal_drops_controls(self):
    self.engage()
    l.safety_rx_hook(di_torque2(brake=True))
    self.assertFalse(l.get_controls_allowed())

  def test_brake_from_one_source_is_not_cleared_by_the_other(self):
    self.feed_all(speed=10.0)                    # moving: a held brake blocks engagement
    self.engage()
    l.safety_rx_hook(di_torque2(brake=True))
    self.assertFalse(l.get_controls_allowed())
    l.safety_rx_hook(brake_msg(False))           # BrakeMessage says released, DI still says pressed
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertFalse(l.get_controls_allowed())
    l.safety_rx_hook(di_torque2(brake=False))    # both released now
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed())

  def test_epas_fault_drops_controls(self):
    self.engage()
    l.safety_rx_hook(epas(0.0, eac_status=3))
    self.assertFalse(l.get_controls_allowed())

  def test_leaving_drive_drops_controls(self):
    self.engage()
    l.safety_rx_hook(di_torque2(gear=3))
    self.assertFalse(l.get_controls_allowed())

  def test_door_opening_drops_controls(self):
    self.engage()
    l.safety_rx_hook(doors(open_fl=True))
    self.assertFalse(l.get_controls_allowed())


class TestPreapTakeover(PreapCase):
  """Hands on and an EPAS refusal only reject ANGLE. controls_allowed stays, so steering resumes without a new pull."""

  def check_blocks_then_resumes(self, block, free):
    self.engage()
    self.assertTrue(self.tx(steer(0)))
    l.safety_rx_hook(block)
    self.assertFalse(l.get_controls_allowed(), "G1: a takeover or an EPAS refusal disengages")
    self.assertFalse(self.tx(steer(0, ctype=1)), "no ANGLE while the driver or the EPAS blocks it")
    self.assertTrue(self.tx(steer(0, ctype=0)), "NONE is always fine, the host releases with it")
    l.safety_rx_hook(free)
    self.assertFalse(l.get_controls_allowed(), "G1: no resume on its own")
    self.assertFalse(self.tx(steer(0, ctype=1)))
    self.advance(1_000_000)
    self.engage()
    self.assertTrue(self.tx(steer(0, ctype=1)), "a new stalk pull re-engages")

  def test_hands_level_3(self):
    self.check_blocks_then_resumes(epas(0.0, hands=3), epas(0.0, hands=0))

  def test_epas_refusing_6_to_9(self):
    for err in (6, 7, 8, 9):
      self.setUp()
      self.check_blocks_then_resumes(epas(0.0, eac_status=0, err=err), epas(0.0, eac_status=1, err=0))

  def test_other_inhibited_errors_and_lower_hands_levels_do_not_block(self):
    self.engage()
    for m in (epas(0.0, hands=2), epas(0.0, eac_status=0, err=3), epas(0.0, eac_status=0, err=4), epas(0.0, eac_status=0, err=10)):
      l.safety_rx_hook(m)
      self.assertTrue(self.tx(steer(0, ctype=1)))

  def test_blocked_state_keeps_the_rate_reference_on_the_wheel(self):
    self.engage()
    self.assertTrue(self.tx(steer(0)))
    l.safety_rx_hook(epas(20.0, hands=3))        # the driver turned the wheel 20 deg
    self.assertFalse(self.tx(steer(200, ctype=1)))
    l.safety_rx_hook(epas(20.0, hands=0))
    self.advance(1_000_000)
    self.engage()
    self.assertTrue(self.tx(steer(200, ctype=1)), "the first ANGLE after the hand-back is rate checked from the wheel, not from 0")

  def test_the_panda_limits_still_apply_after_the_resume(self):
    self.engage()
    l.safety_rx_hook(epas(0.0, hands=3))
    l.safety_rx_hook(epas(0.0, hands=0))
    self.advance(1_000_000)
    self.engage()
    self.assertFalse(self.tx(steer(600, ctype=1)), "a 60 deg jump is still a rate violation")
    self.assertFalse(self.tx(steer(3601, ctype=1)))

  def test_fault_still_drops_even_with_hands_on(self):
    self.engage()
    l.safety_rx_hook(epas(0.0, hands=3, eac_status=3))
    self.assertFalse(l.get_controls_allowed())

  def test_stalk_cancel_still_disengages_during_a_takeover(self):
    self.engage()
    self.advance(700_000)
    l.safety_rx_hook(epas(0.0, hands=3))
    l.safety_rx_hook(stalk(1))
    self.assertFalse(l.get_controls_allowed())
    l.safety_rx_hook(epas(0.0, hands=0))
    self.assertFalse(self.tx(steer(0, ctype=1)), "cancelled stays off")

  def test_a_new_pull_is_required(self):
    self.engage()
    l.safety_rx_hook(epas(0.0, hands=3))
    l.safety_rx_hook(epas(0.0, hands=0))
    self.assertFalse(l.get_controls_allowed())
    self.advance(1_000_000)
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed())

  def test_a_pull_held_through_the_drop_does_not_re_engage(self):
    self.engage()                                  # leaves the lever held at PULL
    l.safety_rx_hook(epas(0.0, hands=3))
    l.safety_rx_hook(epas(0.0, hands=0))
    self.advance(1_000_000)
    for _ in range(5):
      l.safety_rx_hook(stalk(2))                   # still held, no release
    self.assertFalse(l.get_controls_allowed(), "a held pull is not a fresh pull")
    self.assertFalse(self.tx(steer(0, ctype=1)))
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed(), "release then pull re-engages")

  def test_a_held_pull_also_cannot_survive_an_eac_fault(self):
    self.engage()
    l.safety_rx_hook(epas(0.0, eac_status=3))
    l.safety_rx_hook(epas(0.0, eac_status=1))
    self.advance(1_000_000)
    l.safety_rx_hook(stalk(2))
    self.assertFalse(l.get_controls_allowed())

  def test_pull_while_hands_on_does_not_survive(self):
    self.engage()
    l.safety_rx_hook(epas(0.0, hands=3))
    self.advance(1_000_000)
    l.safety_rx_hook(stalk(0))
    l.safety_rx_hook(stalk(2))
    l.safety_rx_hook(epas(0.0, hands=3))
    self.assertFalse(l.get_controls_allowed(), "the next EPAS frame with hands on drops it again")


class TestPreapTx(PreapCase):
  def test_tx_whitelist_without_the_pedal_flag(self):
    allowed = {(0x488, 0), (0x214, 0), (0x45, 0)}
    for addr in (0x488, 0x214, 0x45, 0x551, 0x2b9, 0x399, 0x349, 0x389, 0x239, 0x560, 0x641, 0x553):
      for bus in range(4):
        d = bytearray(8)
        if addr == 0x45:
          d[0] = 1
        l.set_controls_allowed(False)
        ok = self.tx(pkt(addr, d, bus))
        if (addr, bus) not in allowed:
          self.assertFalse(ok, (hex(addr), bus))

  def test_steering_none_ok_and_enabled_needs_controls(self):
    self.assertTrue(self.tx(steer(0, ctype=0)))
    self.assertFalse(self.tx(steer(0, ctype=1)))
    self.engage()
    self.assertTrue(self.tx(steer(0, ctype=1)))

  def test_steering_control_types_2_and_3_never_allowed(self):
    self.engage()
    for ctype in (2, 3):
      self.assertFalse(self.tx(steer(0, ctype=ctype)), ctype)

  def test_steering_rate_limit(self):
    self.engage()
    self.assertTrue(self.tx(steer(0)))
    self.assertTrue(self.tx(steer(30)))
    self.assertFalse(self.tx(steer(600)))       # 60 deg jump in one command

  def test_idle_steering_must_track_the_measured_wheel(self):
    self.feed_all(angle=10.0)
    self.assertTrue(self.tx(steer(100, ctype=0)))
    self.assertFalse(self.tx(steer(800, ctype=0)))

  def test_angle_limit_is_360_deg(self):
    self.engage()
    self.assertFalse(self.tx(steer(3601)))

  def test_first_command_after_engage_is_checked_against_the_wheel_not_the_last_engagement(self):
    self.feed_all(angle=0.0)
    self.engage()
    self.assertTrue(self.tx(steer(1000 - 960)))
    l.safety_rx_hook(stalk(0))
    self.advance(700_000)
    l.safety_rx_hook(stalk(1))
    self.assertFalse(l.get_controls_allowed())
    self.feed_all(angle=-20.0)
    self.pull()
    self.assertTrue(self.tx(steer(-200)))

  def test_epas_control_allow_0_and_1_only(self):
    for mode in range(8):
      self.assertEqual(self.tx(eac(mode)), mode <= 1, mode)

  def test_stalk_is_cancel_only(self):
    for bus in (0, 1, 2, 3):
      for lever in range(64):
        d = bytearray(8)
        d[0] = lever
        self.assertEqual(self.tx(pkt(0x45, d, bus)), bus == 0 and lever == 1, (bus, lever))

  def test_pedal_command_is_blocked_without_the_pedal_flag(self):
    self.engage()
    for bus in range(4):
      for enable in (False, True):
        self.assertFalse(self.tx(pedal_cmd(0, enable, bus)))

  def test_fwd_blocks_everything(self):
    for bus in (0, 1, 2):
      for addr in (0x488, 0x214, 0x2b9, 0x45, 0x551, 0x118):
        self.assertEqual(l.safety_fwd_hook(bus, addr), -1)


class TestPreapPedal(PreapCase):
  PARAM = PREAP | PEDAL | LONG

  def test_pedal_buses_0_and_2_only(self):
    for bus in range(4):
      self.assertEqual(self.tx(pedal_cmd(0, False, bus)), bus in (0, 2), bus)

  def test_enabled_pedal_needs_controls(self):
    self.assertFalse(self.tx(pedal_cmd(300, True)))
    self.engage()
    self.assertTrue(self.tx(pedal_cmd(300, True)))

  def test_enabled_pedal_is_bounded(self):
    self.engage()
    self.assertTrue(self.tx(pedal_cmd(2500, True)))
    self.assertFalse(self.tx(pedal_cmd(2501, True)))
    self.assertFalse(self.tx(pedal_cmd(65535, True)))

  def test_disabled_pedal_must_send_idle(self):
    self.assertTrue(self.tx(pedal_cmd(0, False)))
    self.assertTrue(self.tx(pedal_cmd(500, False)))
    self.assertFalse(self.tx(pedal_cmd(501, False)))

  def test_driver_on_the_pedal_blocks_enabled_commands(self):
    self.engage()
    self.assertTrue(l.safety_rx_hook(pedal_sensor(700)))      # > 650: gas pressed
    l.safety_rx_hook(pedal_sensor(700))
    self.assertTrue(l.get_controls_allowed())
    self.assertFalse(self.tx(pedal_cmd(300, True)))
    self.assertTrue(self.tx(pedal_cmd(0, False)))
    l.safety_rx_hook(pedal_sensor(0))
    l.safety_rx_hook(pedal_sensor(0))
    self.assertTrue(self.tx(pedal_cmd(300, True)))

  def test_stock_pedal_message_is_ignored_for_gas_when_the_interceptor_is_the_source(self):
    self.engage()
    for _ in range(3):
      l.safety_rx_hook(di_torque1(gas=80))
    self.assertTrue(self.tx(pedal_cmd(300, True)))

  def test_sensor_on_bus_2_is_accepted(self):
    self.setUp_with_sensor_on_bus(2)

  def setUp_with_sensor_on_bus(self, bus):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, self.PARAM), 0)
    l.init_tests()
    l.set_timer(1_000_000)
    for _ in range(6):
      for m in (epas(), esp_b(0), di_torque2(), di_torque1(), brake_msg(False), doors(), di_state(), stalk(0)):
        self.assertTrue(l.safety_rx_hook(m))
      self.assertTrue(l.safety_rx_hook(pedal_sensor(0, bus)))
    l.safety_rx_hook(stalk(0))
    self.pull()
    self.assertTrue(l.get_controls_allowed())
    l.safety_rx_hook(pedal_sensor(700, bus))
    l.safety_rx_hook(pedal_sensor(700, bus))
    self.assertFalse(self.tx(pedal_cmd(300, True)))


class TestPreapStockGasWithoutPedal(PreapCase):
  def test_stock_gas_drops_longitudinal_allowed_but_not_steering(self):
    self.engage()
    for _ in range(2):
      l.safety_rx_hook(di_torque1(gas=50))
    self.assertTrue(l.get_controls_allowed())
    self.assertTrue(self.tx(steer(0)))


class TestPreapIsolation(unittest.TestCase):
  def init(self, param):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.init_tests()
    l.set_timer(1000)

  def test_ap1_flag_wins_over_the_preap_flag(self):
    for param in (AP1 | PREAP, AP1 | PREAP | PEDAL | LONG):
      self.init(param)
      l.set_controls_allowed(True)
      self.assertFalse(bool(l.safety_tx_hook(pedal_cmd(0, False))), param)
      self.assertFalse(bool(l.safety_tx_hook(eac(1))), param)
      self.assertTrue(bool(l.safety_tx_hook(stalk(1))), param)

  def test_stock_model_3_y_and_ap1_do_not_whitelist_preap_messages(self):
    for param in (0, 1, AP1, AP1 | LONG):
      self.init(param)
      l.set_controls_allowed(True)
      for addr in (0x214, 0x551):
        for bus in range(4):
          self.assertFalse(bool(l.safety_tx_hook(pkt(addr, bytes(8), bus))), (param, hex(addr), bus))

  def test_preap_flags_do_not_collide_with_ap1_or_long(self):
    self.assertEqual(PREAP & (AP1 | 16 | LONG | 2), 0)
    self.assertEqual(PEDAL & (AP1 | 16 | LONG | 2 | PREAP), 0)


class TestPreapPedalBusLatch(PreapCase):
  # G3: feed_all() sends the pedal sensor on bus 0 first, so bus 0 is latched
  PARAM = PREAP | PEDAL | LONG

  def test_pedal_on_the_other_bus_never_drives_gas_pressed(self):
    self.engage()
    for _ in range(3):
      l.safety_rx_hook(pedal_sensor(700, bus=2))
    self.assertTrue(self.tx(pedal_cmd(300, True)), "bus 2 is not the latched pedal bus")
    l.safety_rx_hook(pedal_sensor(700, bus=0))
    l.safety_rx_hook(pedal_sensor(700, bus=0))
    self.assertFalse(self.tx(pedal_cmd(300, True)), "the latched bus still blocks on gas")

  def test_latch_resets_on_init(self):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, self.PARAM), 0)
    l.init_tests()
    l.set_timer(self.t)
    for _ in range(6):
      l.safety_rx_hook(pedal_sensor(0, bus=2))
    self.feed_all()
    self.engage()
    l.safety_rx_hook(pedal_sensor(700, bus=2))
    l.safety_rx_hook(pedal_sensor(700, bus=2))
    self.assertFalse(self.tx(pedal_cmd(300, True)), "after a re-init the first bus seen (2) is the latched one")


if __name__ == "__main__":
  unittest.main()
