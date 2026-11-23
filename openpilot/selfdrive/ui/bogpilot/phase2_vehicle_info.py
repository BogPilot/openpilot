"""BogPilot > Vehicle Settings > Vehicle Info; read-only snapshot.

ui_state.CP comes from CarParamsPersistent: never imply current identification.
No Params writes, controls, VIN, serial, ECU, or firmware reads.

Provenance labels:
  - no CarParams  -> "not detected"
  - persisted CP  -> "LAST-DETECTED / UNVERIFIED"
  - current=True  -> "CURRENT" (only for a caller with live-session CP)
"""
from __future__ import annotations

UNAVAILABLE = "Unavailable"
NOT_DETECTED = "not detected"
LAST_UNVERIFIED = "LAST-DETECTED / UNVERIFIED"
CURRENT = "CURRENT"
INFO_KEYS = ("Vehicle Info", "Detected Make", "Detected Model / Fingerprint",
             "openpilot Longitudinal Support", "Radar Support", "Stop-and-Go Support")

# AP1 Model S / Model X only: the air suspension flag card last read from 0x398 GTW_carConfig (opendbc tesla_ap1/ride_height.py,
# file AirSuspensionDetected). Like the rows above it is the last reported value, not proof of the car attached now.
AIR_SUSPENSION = "Air Suspension"
AP1_INFO_KEYS = (AIR_SUSPENSION,)
ALL_INFO_KEYS = INFO_KEYS + AP1_INFO_KEYS
AIR_DETECTED = "Detected"
AIR_NOT_DETECTED = "Not Detected"
AIR_UNKNOWN = "Unknown (not reported yet)"
AIR_SUSPENSION_FINGERPRINTS = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX")


def _field(cp, name):
  try:
    return getattr(cp, name, None)
  except (AttributeError, RuntimeError):
    return None


def _identity(value):
  # Never stringify arbitrary structured objects.
  return value.strip() if isinstance(value, str) and value.strip() else UNAVAILABLE


def _support(cp, name, *, inverted=False):
  value = _field(cp, name)
  if not isinstance(value, bool):
    return UNAVAILABLE
  return "Yes" if (not value if inverted else value) else "No"


def air_suspension_text(state):
  """state: True / False / None from ride_height.read_air_suspension_detected()."""
  return AIR_DETECTED if state is True else AIR_NOT_DETECTED if state is False else AIR_UNKNOWN


def read_air_suspension(path=None):
  """Read-only; any import or read problem shows as Unknown, never as a guess."""
  try:
    from opendbc.car.tesla_ap1 import ride_height
    return ride_height.read_air_suspension_detected(path)
  except Exception:
    return None


def vehicle_info(cp, *, current=False, air_suspension=read_air_suspension):
  """Snapshot of supplied CarParams, not a vehicle picker.

  carFingerprint is the platform identifier, not a VIN-decoded retail model.
  Radar Support retains the historical label for not radarUnavailable; it is
  not hardware detection. Longitudinal is configured support, not engagement.
  Only callers with current-session CarParams may explicitly set current=True;
  ui_state.CP is persisted and must use the default False.
  """
  rows = dict.fromkeys(INFO_KEYS, UNAVAILABLE)
  if cp is None:
    rows["Vehicle Info"] = NOT_DETECTED
    return rows
  fp = _identity(_field(cp, "carFingerprint"))
  brand = _identity(_field(cp, "brand"))
  if brand == UNAVAILABLE:  # older schema
    brand = _identity(_field(cp, "carName"))
  if _field(cp, "notCar") is True or brand.lower() == "mock" or fp.lower() == "mock":
    rows["Vehicle Info"] = "Unavailable - non-vehicle / mock CarParams"
    return rows
  if fp == UNAVAILABLE:
    rows["Vehicle Info"] = NOT_DETECTED
    return rows
  rows["Vehicle Info"] = CURRENT if current else LAST_UNVERIFIED
  rows["Detected Make"] = brand
  rows["Detected Model / Fingerprint"] = fp
  rows["openpilot Longitudinal Support"] = _support(cp, "openpilotLongitudinalControl")
  rows["Radar Support"] = _support(cp, "radarUnavailable", inverted=True)
  rows["Stop-and-Go Support"] = _support(cp, "autoResumeSng")
  if fp in AIR_SUSPENSION_FINGERPRINTS:
    rows[AIR_SUSPENSION] = air_suspension_text(air_suspension() if callable(air_suspension) else air_suspension)
  return rows


def refresh_info_items(items, cp, *, current=False, translate=lambda s: s, air_suspension=read_air_suspension):
  """Update existing text_item rows; clear stale values on CP loss. Rows a car does not have (Air Suspension) are hidden."""
  rows = vehicle_info(cp, current=current, air_suspension=air_suspension)
  for key, item in items.items():
    item.set_visible(key in rows)
    item.action_item.set_text(translate(rows.get(key, UNAVAILABLE)))
