"""Model X AP1 marker detection on top of the AP1 chassis signature.

Bus 0 only. A key is a CAN address and a value is the message length from
Tinkla's capture or from a real Model X capture (modelx_observed_data.py).
The EPS firmware of that real car is a third marker. Mixed or incomplete X
evidence prefers no detection.

AP2 Model X cannot be detected: Tinkla's AP2 Model X fingerprint dict is
byte-identical to the AP1 Model X dict, so CAN data cannot tell them apart.
AP2 Model S has bus-0 markers (ap2_fingerprint.py). A capture with them is not
auto-detected as AP1 Model S. AP2 platforms are manual-select only.
"""

from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.ap2_fingerprint import looks_like_ap2_s
from opendbc.car.tesla_ap1.modelx_fingerprint_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.modelx_observed_data import MODELX_EPS_FW, OBSERVED_AP1_MODELX_BUS0
from opendbc.car.tesla_ap1.values import CANBUS, CAR, match_ap1_chassis

EPS_ADDR = 0x730

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


def fw_says_x(car_fw) -> bool:
  """True when the live EPS (0x730) reports the Model X HW1 software part number.

  This is X evidence only: it never overrides Model S-only frames, and the
  chassis and Mobileye signature is still required. The brand's own FW table is
  not used: the tesla_ap1 brand sends no UDS request of its own, and the upstream
  tesla request already returns this EPS response. Any bad input is False.
  """
  try:
    for fw in car_fw or ():
      if fw.ecu == CarParams.Ecu.eps and fw.address == EPS_ADDR and bytes(fw.fwVersion).rstrip(b"\x00") == MODELX_EPS_FW:
        return True
  except Exception:
    return False
  return False


def _known_x_length(addr, length) -> bool:
  return TINKLA_AP1_MODELX.get(addr) == length or OBSERVED_AP1_MODELX_BUS0.get(addr) == length


def _std_frames_match_x(bus0) -> bool:
  """Every 11-bit bus-0 frame is in Tinkla's or the observed X dict at the same length."""
  try:
    items = list(bus0.items())
  except Exception:
    return False
  for addr, length in items:
    # bool is a subclass of int. Reject it.
    if type(addr) is not int or type(length) is not int:
      return False
    if addr < 0x800 and not _known_x_length(addr, length):
      return False
  return True


def match_ap1_modelx(fp, car_fw=None) -> bool:
  """Clean Model X: AP1 chassis, X evidence (marker or EPS firmware), no S evidence, known lengths."""
  try:
    if not match_ap1_chassis(fp):
      return False
    if not (x_evidence(fp) or fw_says_x(car_fw)) or s_evidence(fp):
      return False
    bus0 = _bus0(fp)
    if bus0 is None:
      return False
    return _std_frames_match_x(bus0)
  except Exception:
    return False


def ap1_sx_ambiguous(fp, car_fw=None) -> bool:
  """X-looking capture that is not a clean Model X. Prefer no detection."""
  try:
    return bool(x_evidence(fp) or fw_says_x(car_fw)) and not match_ap1_modelx(fp, car_fw)
  except Exception:
    return False


def detect_ap1_candidate(fp, car_fw=None):
  """Model X, Model S, or None.

  Empty X evidence (no marker address and no Model X EPS firmware) returns the
  previous result: Model S when match_ap1_chassis is true, otherwise None. X
  evidence that is not a clean Model X returns None. A capture with AP2 Model S
  markers returns None. car_fw is the live CarParams.CarFw list and is optional.
  """
  try:
    if looks_like_ap2_s(fp):
      return None
    if match_ap1_modelx(fp, car_fw):
      return CAR.TESLA_AP1_MODELX
    if ap1_sx_ambiguous(fp, car_fw):
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
