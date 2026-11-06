"""Target-base AP1 safety params: stock tesla model, AP1=8, LONG=1, STANDSTILL=16.

Matches stream 2 on release-tici and release-tizi. No new safety enum ordinal.
The AP1 bit selects the isolated AP1 implementation; stock Tesla stays unchanged.
"""

from opendbc.car.tesla_ap1.values import CAR, TeslaAp1SafetyFlags

FLAG_TESLA_AP1 = int(TeslaAp1SafetyFlags.AP1)
FLAG_TESLA_LONG_CONTROL = int(TeslaAp1SafetyFlags.LONG_CONTROL)
FLAG_TESLA_AP1_STANDSTILL = int(TeslaAp1SafetyFlags.STANDSTILL)


def flags_for_candidate(candidate, fingerprint=None, standstill=False):
  """Safety params tuple (one config) for the teslaAp1 safety model."""
  if FLAG_TESLA_AP1 != 8:
    raise RuntimeError("TESLA_FLAG_AP1 must be 8")
  flags = 0
  if candidate == CAR.TESLA_AP1_MODELS:
    flags |= FLAG_TESLA_AP1 | FLAG_TESLA_LONG_CONTROL
    if standstill:
      flags |= FLAG_TESLA_AP1_STANDSTILL
  return (flags,)


def dashcam_only_for_candidate(candidate):
  """False only for CAR.TESLA_AP1_MODELS."""
  return candidate != CAR.TESLA_AP1_MODELS
