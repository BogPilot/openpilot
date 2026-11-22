"""Log the longitudinal mode the car started in, once per drive (card starts once per onroad session).

One cloudlog event "bogpilot_long_mode" in the drive's rlog/qlog (logMessage): openpilot or stock longitudinal, the safety
flags, and on the AP1 Model X the AP1XOpenpilotLong setting it was read with, so a log shows at a glance whether an X drive
ran openpilot long (X long on) or stock TACC (X long off). Legacy Tesla (tesla_ap1) only; nothing is logged for other cars.
"""
from __future__ import annotations

AP1_X = "TESLA_AP1_MODELX"
EVENT = "bogpilot_long_mode"


def long_mode_fields(CP) -> dict | None:
  """The event fields for this CarParams, or None for a car that is not tesla_ap1. Never raises."""
  try:
    if str(getattr(CP, "brand", "")) != "tesla_ap1":
      return None
    fp = str(CP.carFingerprint)
    op_long = bool(CP.openpilotLongitudinalControl)
    configs = list(getattr(CP, "safetyConfigs", []) or [])
    out = {
      "fingerprint": fp,
      "mode": "openpilot" if op_long else "stock",
      "openpilotLongitudinalControl": op_long,
      "dashcamOnly": bool(getattr(CP, "dashcamOnly", False)),
      "safetyParam": int(configs[-1].safetyParam) if configs else 0,
    }
    if fp == AP1_X:
      from opendbc.car.tesla_ap1 import toggles
      out["xLong"] = "on" if op_long else "off"
      out["xLongSetting"] = bool(toggles.ap1x_op_long(fp))
    return out
  except Exception:
    return None


def log_long_mode(CP, event=None) -> dict | None:
  """Emit the event once (the caller runs it once per card start). Returns the fields logged, or None."""
  fields = long_mode_fields(CP)
  if fields is None:
    return None
  if event is None:
    from openpilot.common.swaglog import cloudlog
    event = cloudlog.event
  try:
    event(EVENT, **fields)
  except Exception:
    return None
  return fields
