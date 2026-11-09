"""BogPilot > Vehicle Settings > Vehicle Info; read-only snapshot.

ui_state.CP comes from CarParamsPersistent: never imply current identification.
No Params writes, controls, VIN, serial, ECU, or firmware reads.

Provenance labels (t994 vehicle lane):
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


def vehicle_info(cp, *, current=False):
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
  return rows


def refresh_info_items(items, cp, *, current=False, translate=lambda s: s):
  """Update existing text_item rows; clear stale values on CP loss."""
  rows = vehicle_info(cp, current=current)
  for key, item in items.items():
    item.set_visible(key in rows)
    item.action_item.set_text(translate(rows.get(key, UNAVAILABLE)))
