#!/usr/bin/env python3
"""Existing Pre-AP safety checks with Bosch radar flags 256 and 256+128.

Subclasses every PreapCase-based class so the same pedal-brake, gas, engage,
0x551, angle/torque and latch tests run with PREAP|256 and PREAP|256|128
(and with the pedal flag where the base class already has it). No C changes.
The unflagged classes in the original modules still cover flag-off.
"""
import opendbc.safety.tests.test_tesla_preap as preap
import opendbc.safety.tests.test_tesla_preap_brake_steer as brake_steer
import opendbc.safety.tests.test_tesla_preap_gas_threshold as gas
import opendbc.safety.tests.test_tesla_preap_pedal_brake as pedal_brake

RADAR = 256
NOSE = 128

# Base classes that already set PARAM through PreapCase / BrakeSteerCase.
_BASES = (
  preap.TestPreapEngageDisengage,
  preap.TestPreapTakeover,
  preap.TestPreapTx,
  preap.TestPreapPedal,
  preap.TestPreapStockGasWithoutPedal,
  preap.TestPreapPedalBusLatch,
  pedal_brake.TestPreapPedalBrake,
  pedal_brake.TestPreapPedalBrakeWithoutPedalFlag,
  gas.TestPreapStockGasThresholdMismatch,
  brake_steer.TestBrakeKeepsSteering,
  brake_steer.TestDisarm,
)


def _variant(base, flags, suffix):
  return type(f"{base.__name__}{suffix}", (base,), {"PARAM": base.PARAM | flags})


for _cls in _BASES:
  globals()[f"{_cls.__name__}Radar"] = _variant(_cls, RADAR, "Radar")
  globals()[f"{_cls.__name__}RadarNose"] = _variant(_cls, RADAR | NOSE, "RadarNose")
