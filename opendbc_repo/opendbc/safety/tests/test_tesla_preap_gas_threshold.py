#!/usr/bin/env python3
"""Host vs panda DI_pedalPos threshold: pack raw values with the real DBC packer.

At raw 1-5 the Pre-AP stock host (see tesla_ap1/tests/test_preap_gas_threshold.py)
says not pressed. The panda still treats data[6] != 0 as pressed and blocks gas /
longitudinal TX. That stricter panda side is intentional and is unchanged here.
"""
import unittest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.values import CAR, DBC
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_preap import PreapCase, steer

l = libsafety_py.libsafety
SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
PREAP = 32
DI_PEDAL_FACTOR = 0.4
DBC_NAME = DBC[CAR.TESLA_PREAP_MODELS][Bus.chassis]


def packed_di_torque1(raw):
  packer = CANPacker(DBC_NAME)
  addr, dat, _bus = packer.make_can_msg("DI_torque1", 0, {"DI_pedalPos": raw * DI_PEDAL_FACTOR})
  assert dat[6] == raw, (raw, dat[6])
  return libsafety_py.make_CANPacket(addr, 0, bytes(dat))


class TestPreapStockGasThresholdMismatch(PreapCase):
  PARAM = PREAP

  def test_panda_blocks_gas_tx_at_raw_1_through_5(self):
    self.engage()
    self.assertTrue(l.get_controls_allowed())
    self.assertTrue(l.get_longitudinal_allowed())
    for raw in (1, 2, 3, 4, 5):
      pkt = packed_di_torque1(raw)
      for _ in range(2):
        self.assertTrue(l.safety_rx_hook(pkt))
      self.assertTrue(l.get_controls_allowed())
      # get_longitudinal_allowed is the gas/long TX gate (controls_allowed && !gas_pressed_prev).
      self.assertFalse(l.get_longitudinal_allowed(), raw)
      self.assertTrue(self.tx(steer(0)))
    # Raw 0 is not pressed on either side; longitudinal is allowed again.
    pkt0 = packed_di_torque1(0)
    for _ in range(2):
      self.assertTrue(l.safety_rx_hook(pkt0))
    self.assertTrue(l.get_longitudinal_allowed())
    self.assertTrue(self.tx(steer(0)))
