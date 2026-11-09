"""Model X AP1 marker detection on top of the AP1 chassis signature.

Bus 0 only. A key is a CAN address and a value is the message length from
Tinkla's capture. Mixed or incomplete X evidence prefers no detection.

AP2 Model X is intentionally not a platform. Tinkla's AP2 Model X fingerprint
dict is byte-identical to the AP1 Model X dict, so CAN data cannot tell them
apart. AP2 also needs the powertrain bus (4/6), a second panda, and a
different safety path. The signed safety mode
(opendbc/safety/modes/tesla_ap1.h) implements the AP1 chassis path only.
"""

from opendbc.car.tesla_ap1.modelx_fingerprint_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.values import CANBUS, CAR, match_ap1_chassis

# Present on Tinkla's Model X capture and absent from Model S.
X_ONLY = {0x2F1: 8, 0x371: 8, 0x37B: 8, 0x588: 8, 0x598: 8, 0x5A8: 8}
# 0x303 is 8 bytes on X and 2 bytes on S.
X_LENGTH_AT = {0x303: 8}

# Present on Tinkla's Model S captures and absent from Model X.
# 0x201 is SDM1. Model X carries the driver seatbelt on RCM_status (0x211).
S_ONLY = {0x165: 8, 0x201: 5, 0x379: 8, 0x37E: 8}
S_LENGTH_AT = {0x303: 2}


def _bus0(fp):
  if not isinstance(fp, dict):
    return None
  bus0 = fp.get(CANBUS.chassis)
  if not isinstance(bus0, dict):
    return None
  return bus0


def _evidence(fp, fixed, length_at) -> frozenset:
  bus0 = _bus0(fp)
  if bus0 is None:
    return frozenset()
  found = set()
  for table in (fixed, length_at):
    for addr, length in table.items():
      try:
        if bus0.get(addr) == length:
          found.add(addr)
      except Exception:
        return frozenset()
  return frozenset(found)


def x_evidence(fp) -> frozenset:
  """X marker addresses on bus 0 whose observed length matches Tinkla."""
  return _evidence(fp, X_ONLY, X_LENGTH_AT)


def s_evidence(fp) -> frozenset:
  """S marker addresses on bus 0 whose observed length matches Tinkla."""
  return _evidence(fp, S_ONLY, S_LENGTH_AT)


def _std_frames_match_x(bus0) -> bool:
  """Every 11-bit bus-0 frame is in Tinkla's X dict at the same length."""
  try:
    items = list(bus0.items())
  except Exception:
    return False
  for addr, length in items:
    # bool is a subclass of int. Reject it.
    if type(addr) is not int or type(length) is not int:
      return False
    if addr < 0x800 and TINKLA_AP1_MODELX.get(addr) != length:
      return False
  return True


def match_ap1_modelx(fp) -> bool:
  """Clean Model X: AP1 chassis, some X evidence, no S evidence, Tinkla lengths."""
  try:
    if not match_ap1_chassis(fp):
      return False
    if not x_evidence(fp) or s_evidence(fp):
      return False
    bus0 = _bus0(fp)
    if bus0 is None:
      return False
    return _std_frames_match_x(bus0)
  except Exception:
    return False


def ap1_sx_ambiguous(fp) -> bool:
  """X-looking capture that is not a clean Model X. Prefer no detection."""
  try:
    return bool(x_evidence(fp)) and not match_ap1_modelx(fp)
  except Exception:
    return False


def detect_ap1_candidate(fp):
  """Model X, Model S, or None.

  Empty X evidence returns the previous result: Model S when match_ap1_chassis
  is true, otherwise None. X evidence that is not a clean Model X returns None.
  """
  try:
    if match_ap1_modelx(fp):
      return CAR.TESLA_AP1_MODELX
    if ap1_sx_ambiguous(fp):
      return None
    if match_ap1_chassis(fp):
      return CAR.TESLA_AP1_MODELS
  except Exception:
    return None
  return None


def s_contradicts_x(fp) -> bool:
  """True when bus 0 shows a Model S-only message. Manual Model X then stays dashcam."""
  try:
    return bool(s_evidence(fp))
  except Exception:
    return False
