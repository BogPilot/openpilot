"""Pedal and motor inputs for the onroad 3-bar pedal gauge (display only; nothing in controls or safety reads these).

All three come from 0x108 DI_torque1 on the chassis bus (tesla_ap1_can.dbc BO_ 264, the same frame on AP1 and Pre-AP):
  DI_pedalPos     48|8@1+ (0.4,0) "%", VAL_ 255 "SNA" (decodes to 102 %)
  DI_torqueMotor  16|13@1- (0.25,0) "Nm", VAL_ -4096 "SNA" (decodes to -1024 Nm)
  DI_motorRPM     32|16@1- (1,0) "RPM", VAL_ -32768 "SNA"
"""
import math

PEDAL_MISSING = -1.0          # published in CarState.deprecated.gas when DI_pedalPos is SNA / out of range
DI_PEDAL_POS_MAX_PCT = 100.0  # DBC range [0|100]; SNA 255 decodes to 102 % and must never read as a full bar


def pedal_position(pct) -> float:
  """DI_pedalPos (%) -> 0..1, or PEDAL_MISSING for SNA, out-of-range, NaN or junk (never clamped to a full bar)."""
  try:
    x = float(pct)
  except (TypeError, ValueError):
    return PEDAL_MISSING
  if not math.isfinite(x) or x < 0.0 or x > DI_PEDAL_POS_MAX_PCT:
    return PEDAL_MISSING
  return x / 100.0
