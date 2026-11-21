"""Target-base AP1 safety params: stock tesla model, AP1=8, LONG=1, STANDSTILL=16.

Matches the panda safety enum on release-tici and release-tizi. No new safety enum ordinal.
The AP1 bit selects the isolated AP1 implementation; stock Tesla stays unchanged.
"""

from opendbc.car.tesla_ap1.values import CAR, TeslaAp1SafetyFlags

FLAG_TESLA_AP1 = int(TeslaAp1SafetyFlags.AP1)
FLAG_TESLA_LONG_CONTROL = int(TeslaAp1SafetyFlags.LONG_CONTROL)
FLAG_TESLA_AP1_STANDSTILL = int(TeslaAp1SafetyFlags.STANDSTILL)


def flags_for_candidate(candidate, fingerprint=None, standstill=False, x_long=False):
  """Safety params tuple (one config) for the teslaAp1 safety model.

  x_long is the opt-in AP1 Model X openpilot longitudinal (AP1XOpenpilotLong, experimental). It adds LONG_CONTROL only; the X never
  gets standstill. Default False keeps the Model X lateral-only (flag 8), identical to before.
  """
  if FLAG_TESLA_AP1 != 8:
    raise RuntimeError("TESLA_FLAG_AP1 must be 8")
  flags = 0
  if candidate == CAR.TESLA_AP1_MODELS:
    flags |= FLAG_TESLA_AP1 | FLAG_TESLA_LONG_CONTROL
    if standstill:
      flags |= FLAG_TESLA_AP1_STANDSTILL
  elif candidate == CAR.TESLA_AP1_MODELX:
    # Model X is lateral only unless the opt-in x_long is passed: AP1 chassis safety, LONG_CONTROL only on opt-in, never standstill.
    flags |= FLAG_TESLA_AP1
    if x_long:
      flags |= FLAG_TESLA_LONG_CONTROL
  return (flags,)


FLAG_TESLA_PREAP = int(TeslaAp1SafetyFlags.PREAP)
FLAG_TESLA_PREAP_PEDAL = int(TeslaAp1SafetyFlags.PREAP_PEDAL)
FLAG_TESLA_PREAP_RADAR_BEHIND_NOSECONE = int(TeslaAp1SafetyFlags.PREAP_RADAR_BEHIND_NOSECONE)
FLAG_TESLA_PREAP_RADAR_EMULATION = int(TeslaAp1SafetyFlags.PREAP_RADAR_EMULATION)


def flags_for_preap(pedal: bool, radar: bool = False, behind_nosecone: bool = False) -> int:
  """Safety param for the Pre-AP Model S (SAFETY_TESLA + PREAP, never with the AP1 bit).

  pedal = Comma Pedal longitudinal. radar / behind_nosecone set flags 256 and 128
  (128 only when both are on). Defaults keep the param identical to PREAP / PREAP|PEDAL.
  """
  flags = FLAG_TESLA_PREAP
  if pedal:
    flags |= FLAG_TESLA_PREAP_PEDAL
  if radar:
    flags |= FLAG_TESLA_PREAP_RADAR_EMULATION
    if behind_nosecone:
      flags |= FLAG_TESLA_PREAP_RADAR_BEHIND_NOSECONE
  return flags


def dashcam_only_for_candidate(candidate):
  """False for Model S AP1, Model X AP1 and the Pre-AP Model S. True for every other candidate."""
  return candidate not in (CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX, CAR.TESLA_PREAP_MODELS)
