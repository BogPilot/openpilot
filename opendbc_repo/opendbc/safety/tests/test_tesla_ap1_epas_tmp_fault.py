#!/usr/bin/env python3
"""BogPilot AP1 safety (TESLA_FLAG_AP1): a latched EAC_ERROR_TMP_FAULT (4) does not lock lateral out for good.

Like HANDS_ON (3) and HIGH_ANGLE_REQ (6), the EPAS keeps code 4 in EPAS_eacErrorCode until it is commanded again.
The panda lets an active steering frame through with code 4 only while the same EPAS_sysStatus (0x370) frame says
AVAILABLE or ACTIVE and the last EPB_epasControl (0x214, bus 0) said EPB_epasEACAllow == 1 less than 250 ms ago.
Every other gate is unchanged: controls_allowed, the rate table, all other codes and statuses. Raw-wire tests.
"""
import itertools
import unittest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.libsafety import libsafety_py

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
AP1 = 8 | 1          # 1 is LONG_CONTROL
AP1_NO_LONG = 8

INHIBITED, AVAILABLE, ACTIVE, FAULT, SNA = 0, 1, 2, 3, 4
IDLE, HANDS_ON, TMP_FAULT, HIGH_ANGLE_REQ = 0, 3, 4, 6
OK_ERRORS = (IDLE, HANDS_ON, HIGH_ANGLE_REQ)
READY = (AVAILABLE, ACTIVE)
EPB_TIMEOUT_US = 250000
T0 = 1000

# EPB states: None = no 0x214 seen since init; otherwise (EPB_epasEACAllow value, age in us at the TX)
EPB_CASES = (None, (1, 0), (1, EPB_TIMEOUT_US - 1), (1, EPB_TIMEOUT_US), (1, 10 * EPB_TIMEOUT_US),
             (0, 0), (2, 0), (3, 0), (7, 0))


def pkt(addr, dat, bus=0):
  return libsafety_py.make_CANPacket(addr, bus, bytes(dat))


def epas(angle_deg=0.0, eac_status=AVAILABLE, eac_error=IDLE, hands=0):
  raw = int(round(angle_deg * 10)) + 8192
  d = bytearray(8)
  d[2] = (eac_error & 0x0F) << 4
  d[4] = ((hands & 3) << 6) | ((raw >> 8) & 0x3F)
  d[5] = raw & 0xFF
  d[6] = (eac_status & 0x07) << 5
  return pkt(0x370, d)


def epb(allow, bus=0, length=3):
  d = bytearray(length)
  d[0] = allow & 0x07
  return pkt(0x214, d, bus)


def di_state(cruise_state):
  d = bytearray(8)
  d[1] = (cruise_state & 0x0F) << 4
  return pkt(0x368, d)


def di_torque2(speed_mps):
  raw = int(round(((speed_mps / 0.447) + 25) / 0.05))
  d = bytearray(6)
  d[2] = raw & 0xFF
  d[3] = (raw >> 8) & 0x0F
  return pkt(0x118, d)


def steer_cmd(angle_can, control_type=1):
  raw = angle_can + 16384
  d = bytearray(4)
  d[0] = (raw >> 8) & 0x7F
  d[1] = raw & 0xFF
  d[2] = (control_type & 0x03) << 6
  return pkt(0x488, d)


def expected(status, error, epb_case):
  if status not in READY:
    return False
  if error in OK_ERRORS:
    return True
  return error == TMP_FAULT and epb_case is not None and epb_case[0] == 1 and epb_case[1] < EPB_TIMEOUT_US


class TestTeslaAp1EpasTmpFault(unittest.TestCase):
  def init(self, param=AP1, engage=True):
    self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
    l.init_tests()
    l.set_timer(T0)
    for _ in range(6):
      self.assertTrue(l.safety_rx_hook(di_torque2(8.0)))
    self.assertTrue(l.safety_rx_hook(di_state(1)))
    self.wheel()
    if engage:
      self.assertTrue(l.safety_rx_hook(di_state(2)))
      self.assertTrue(l.get_controls_allowed())

  def wheel(self, angle=0.0, status=AVAILABLE, error=IDLE):
    for _ in range(3):
      self.assertTrue(l.safety_rx_hook(epas(angle, status, error)))

  def set_epb(self, epb_case):
    # Leaves the timer at T0 + age, the moment of the TX under test.
    if epb_case is not None:
      allow, age = epb_case
      l.set_timer(T0)
      self.assertTrue(l.safety_rx_hook(epb(allow)))
      l.set_timer(T0 + age)

  def tx(self, angle_can=0, control_type=1):
    return bool(l.safety_tx_hook(steer_cmd(angle_can, control_type)))

  def test_full_matrix_error_status_epb_controls_allowed(self):
    # every EPAS error 0-15 x every 3-bit status x EPB (none / allowed fresh / boundary / stale / not allowed)
    # x controls_allowed, active control types 1 and 2
    n = 0
    for param, status, error, epb_case, allowed, ctype in itertools.product(
        (AP1, AP1_NO_LONG), range(8), range(16), EPB_CASES, (True, False), (1, 2)):
      self.init(param)
      self.wheel(0.0, status, error)
      self.set_epb(epb_case)
      if not allowed:
        l.set_controls_allowed(False)
      want = allowed and expected(status, error, epb_case)
      self.assertEqual(self.tx(0, ctype), want, (param, status, error, epb_case, allowed, ctype))
      n += 1
    self.assertEqual(n, 2 * 8 * 16 * len(EPB_CASES) * 2 * 2)

  def test_never_engaged_tmp_fault_with_epb_allow_is_dropped(self):
    # controls_allowed never set by the car (no cruise engage): the exception cannot open the gate
    for status in READY:
      self.init(engage=False)
      self.wheel(0.0, status, TMP_FAULT)
      self.set_epb((1, 0))
      self.assertFalse(l.get_controls_allowed())
      self.assertFalse(self.tx(0), status)

  def test_codes_0_3_6_are_unchanged_without_any_epb_frame(self):
    for status, error in itertools.product(range(8), OK_ERRORS):
      self.init()
      self.wheel(0.0, status, error)
      self.assertEqual(self.tx(0), status in READY, (status, error))

  def test_other_codes_stay_blocked_even_with_epb_allow(self):
    for status, error in itertools.product(READY, (1, 2, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15)):
      self.init()
      self.wheel(0.0, status, error)
      self.set_epb((1, 0))
      self.assertFalse(self.tx(0), (status, error))

  def test_tmp_fault_with_inhibited_fault_sna_stays_blocked(self):
    for status in (INHIBITED, FAULT, SNA, 5, 6, 7):
      self.init()
      self.wheel(0.0, status, TMP_FAULT)
      self.set_epb((1, 0))
      self.assertFalse(self.tx(0), status)

  def test_type_none_and_disabled_always_pass(self):
    for control_type, status, epb_case in itertools.product((0, 3), range(8), EPB_CASES):
      self.init()
      self.wheel(0.0, status, TMP_FAULT)
      self.set_epb(epb_case)
      self.assertTrue(self.tx(0, control_type), (control_type, status, epb_case))

  def test_rate_table_still_applies_in_recovery(self):
    self.init()
    self.wheel(0.0, AVAILABLE, TMP_FAULT)
    self.set_epb((1, 0))
    self.assertTrue(self.tx(0))
    self.assertFalse(self.tx(400), "rate table still applies")

  def test_epb_revoke_blocks_on_the_next_frame(self):
    self.init()
    self.wheel(0.0, AVAILABLE, TMP_FAULT)
    self.set_epb((1, 0))
    self.assertTrue(self.tx(0))
    self.assertTrue(l.safety_rx_hook(epb(0)))
    self.assertFalse(self.tx(0))
    self.assertTrue(l.safety_rx_hook(epb(1)))
    self.assertTrue(self.tx(0))

  def test_epb_freshness_boundary(self):
    self.init()
    self.wheel(0.0, ACTIVE, TMP_FAULT)
    self.set_epb((1, 0))
    l.set_timer(T0 + EPB_TIMEOUT_US - 1)
    self.assertTrue(self.tx(0))
    l.set_timer(T0 + EPB_TIMEOUT_US)
    self.assertFalse(self.tx(0))
    self.assertTrue(l.safety_rx_hook(epb(1)))
    self.assertTrue(self.tx(0), "a new 0x214 frame restores it")

  def test_epb_on_other_bus_or_length_is_ignored(self):
    for bus, length in ((1, 3), (2, 3), (0, 2), (0, 4), (0, 8)):
      self.init()
      self.wheel(0.0, AVAILABLE, TMP_FAULT)
      l.safety_rx_hook(epb(1, bus, length))
      self.assertFalse(self.tx(0), (bus, length))

  def test_tmp_fault_flag_follows_each_0x370_frame(self):
    self.init()
    self.set_epb((1, 0))
    self.wheel(0.0, AVAILABLE, TMP_FAULT)
    self.assertTrue(self.tx(0))
    self.wheel(0.0, AVAILABLE, 9)
    self.assertFalse(self.tx(0), "a new error replaces the latched code 4")
    self.wheel(0.0, AVAILABLE, TMP_FAULT)
    self.assertTrue(self.tx(0))

  def test_logged_sequence(self):
    # ACTIVE/IDLE -> ACTIVE/TMP_FAULT -> INHIBITED/TMP_FAULT -> AVAILABLE/TMP_FAULT -> ACTIVE/IDLE, EPB allow 1
    self.init()
    self.set_epb((1, 0))
    for status, error, want in ((ACTIVE, IDLE, True), (ACTIVE, TMP_FAULT, True), (INHIBITED, TMP_FAULT, False),
                                (AVAILABLE, TMP_FAULT, True), (ACTIVE, IDLE, True)):
      self.assertTrue(l.safety_rx_hook(epb(1)))
      self.wheel(0.0, status, error)
      self.assertEqual(self.tx(0), want, (status, error))

  def test_init_clears_the_epb_and_tmp_fault_state(self):
    self.init()
    self.wheel(0.0, AVAILABLE, TMP_FAULT)
    self.set_epb((1, 0))
    self.assertTrue(self.tx(0))
    self.init()
    self.assertTrue(self.tx(0), "clean status after re-init")
    self.wheel(0.0, AVAILABLE, TMP_FAULT)
    self.assertFalse(self.tx(0), "no EPB frame since init")

  def feed_chassis(self, with_epb):
    # one frame of every AP1 RX-checked message, engaged and with no pedal pressed
    brake_released = bytearray(8)
    brake_released[0] = 1 << 2
    frames = [pkt(0x2b9, bytearray(8), 2), pkt(0x108, bytearray(8)), di_torque2(8.0), pkt(0x20a, brake_released),
              di_state(2), pkt(0x318, bytearray(8)), epas(0.0, AVAILABLE, IDLE)]
    if with_epb:
      frames.append(epb(1))
    for f in frames:
      self.assertTrue(l.safety_rx_hook(f))

  def test_epb_is_an_rx_check(self):
    # 0x214 is RX-checked like the other AP1 chassis frames: missing for more than 1 s removes controls_allowed
    for with_epb in (True, False):
      self.init()
      for k in range(1, 31):
        l.set_timer(T0 + k * 100000)
        self.feed_chassis(with_epb)
      l.safety_tick()
      self.assertEqual(l.get_controls_allowed(), with_epb, with_epb)
      self.assertEqual(l.safety_config_valid(), with_epb, with_epb)

  def test_model_3y_path_is_not_changed(self):
    for param in (0, 1):
      self.assertEqual(l.set_safety_hooks(SAFETY_TESLA, param), 0)
      l.init_tests()
      l.set_timer(T0)
      l.safety_rx_hook(epb(1))
      l.safety_rx_hook(epas(0.0, INHIBITED, TMP_FAULT))
      l.set_controls_allowed(True)
      l.set_desired_angle_last(0)
      self.assertTrue(self.tx(0, 0), param)


if __name__ == "__main__":
  unittest.main()
