"""Pre-AP brake level for the onroad pedal gauge's left bar (display only; controls and the panda never read it).

Default (no iBooster swap): binary. 1.0 while the brake is pressed (BrakeMessage or DI_brakePedal, the same brakePressed
the car state publishes), else 0.0. The stock Pre-AP vacuum booster has no stroke signal on the chassis bus.

With the iBooster swap toggle on (PreApParamKeys.HAS_IBOOSTER, default off): proportional, from 0x554 ECU_BrakeStatus
BrakePedalPosition on bus 0. Sources:
  Tinkla / BogGyver openpilot 501c7de selfdrive/car/tesla/carstate.py:115,212-215,653-662 (TinklaHasIBooster subscribes
    ECU_BrakeStatus on bus 0 with frequency 0; ret.brake stayed 0 there, so the analog level was never shown).
  BogGyver opendbc 9c0b6fe tesla_can.dbc BO_ 1364: BrakePedalPosition 20|12@1+ (0.015625,-5) [0|47] "mm", BrakeOK,
    Status (0 NO_FAULT), DriverBrakeApplied, BrakeApplied.
NotAutopilot e99f4dc75 nap_params.py:31 defines NAPiBoosterEnabled but nothing reads it; it is not used here.
Missing, stale, BrakeOK = 0 or a Status fault is BRAKE_LEVEL_MISSING, so the bar stays empty (fail closed).
"""
import math

from opendbc.car.tesla_ap1.brake_level import BRAKE_LEVEL_MISSING

MSG = "ECU_BrakeStatus"
ADDR = 0x554
# Frame age that still counts as live. The frame rate is not documented in the references; 0.5 s matches the AP1 brake
# level (brake_level.BRAKE_LEVEL_MAX_AGE_S). Provisional until a capture from a swapped car.
IBOOSTER_MAX_AGE_S = 0.5
# Pedal travel (mm) that fills the bar. PROVISIONAL: this is the DBC maximum of BrakePedalPosition ([0|47] mm), NOT a
# measured full-pedal travel; no capture from a swapped Pre-AP car exists yet, so the bar can never over-read. Tune from
# rlogs of a swapped car.
IBOOSTER_PEDAL_FULL_MM = 47.0
STATUS_NO_FAULT = 0


def binary_brake_level(pressed) -> float:
  return 1.0 if bool(pressed) else 0.0


def ibooster_brake_level(values, fresh: bool) -> float:
  """clamp(BrakePedalPosition / IBOOSTER_PEDAL_FULL_MM, 0, 1) for a fresh, healthy frame, else BRAKE_LEVEL_MISSING."""
  if not fresh or not values:
    return BRAKE_LEVEL_MISSING
  try:
    pos, ok, status = float(values["BrakePedalPosition"]), float(values["BrakeOK"]), float(values["Status"])
  except (KeyError, TypeError, ValueError):
    return BRAKE_LEVEL_MISSING
  if not all(math.isfinite(v) for v in (pos, ok, status)) or ok != 1 or status != STATUS_NO_FAULT:
    return BRAKE_LEVEL_MISSING
  return min(max(pos / IBOOSTER_PEDAL_FULL_MM, 0.0), 1.0)
