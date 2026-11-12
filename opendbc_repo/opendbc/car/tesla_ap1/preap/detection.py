"""Pre-AP Model S detection.

A Pre-AP Model S has the same chassis messages as an AP1 car on bus 0 but no Autopilot ECU: bus 2 carries none of the
Mobileye frames (0x399 / 0x2B9 / 0x488). Chassis-only evidence is therefore ambiguous (an AP1 car with its camera harness
unplugged looks the same), so automatic detection also requires the Comma Pedal to be talking (GAS_SENSOR 0x552, 6 bytes, on bus 0 or 2).
A Pre-AP car without a pedal (lateral only, stock TACC) is not auto-detected: select it with CarModel + ForceFingerprint.

Pure functions of the openpilot fingerprint dict (bus -> {address: length}); no CAN, no params.
"""
from opendbc.car.tesla_ap1.values import AP1_CHASSIS_SIGNATURE, CANBUS, CAR

MOBILEYE_ADDRS = (0x399, 0x2B9, 0x488)
PEDAL_GAS_SENSOR = (0x552, 6)


def _bus(fp, bus):
  if not isinstance(fp, dict):
    return {}
  b = fp.get(bus, {})
  return b if isinstance(b, dict) else {}


def preap_chassis_signature(fp) -> bool:
  bus0 = _bus(fp, CANBUS.chassis)
  return all(bus0.get(addr) == length for addr, length in AP1_CHASSIS_SIGNATURE.items())


def no_mobileye(fp) -> bool:
  """Stock Autopilot camera traffic is absent on bus 2 (and not on the chassis bus either)."""
  return not any(addr in _bus(fp, CANBUS.autopilot_chassis) for addr in MOBILEYE_ADDRS)


def pedal_present(fp) -> bool:
  addr, length = PEDAL_GAS_SENSOR
  return _bus(fp, CANBUS.chassis).get(addr) == length or _bus(fp, CANBUS.autopilot_chassis).get(addr) == length


def match_preap(fp) -> bool:
  try:
    return preap_chassis_signature(fp) and no_mobileye(fp) and pedal_present(fp)
  except Exception:
    return False


def detect_preap_candidate(fp):
  """CAR.TESLA_PREAP_MODELS or None. Never returns an AP1 platform; AP1 detection runs first in car_helpers."""
  return CAR.TESLA_PREAP_MODELS if match_preap(fp) else None
