"""AP1 DI_cruiseSet scale correction (file-backed, default ON).

Ported from BogPilot `bogpilot-tesla-cruise-half-fix` (06180370a, 0d7a29610, ec39be533; 0.9.7 layout,
selfdrive/car/tesla/cruise_set.py). tesla_ap1_can.dbc declares DI_state.DI_cruiseSet (0x368, bit 32, 9 bits)
with factor 0.5. On AP1 the raw value is whole display units, so the decoded value is half of the set.
The DBC factor is kept; carstate.py multiplies the decoded value by cruise_set_scale().

  # default ON when the file is missing
  echo 0 > /data/params_bogpilot/TeslaCruiseSetScaleFix   # off: keep the DBC 0.5
  echo 1 > /data/params_bogpilot/TeslaCruiseSetScaleFix   # on: x2 (raw units)

Missing/empty = ON (x2). Explicit 0/false/off/no = OFF. Anything else = OFF (as the BogPilot source).
Read once when CarState is constructed. KPH-mode scaling is unverified on the car.
Under openpilot long on AP1 (S and X), cruiseState.speed is openpilot's own set (op_long_set_speed.py),
so this applies only with openpilot long off (stock AP).
"""
from __future__ import annotations

from pathlib import Path

CRUISE_SET_SCALE_FIX_PATH = Path("/data/params_bogpilot/TeslaCruiseSetScaleFix")
# Tests may override the path via this module attribute.
_cruise_set_scale_fix_path = CRUISE_SET_SCALE_FIX_PATH

# DBC factor is 0.5; the AP1 raw value is whole units, so undo the halving.
DBC_FACTOR_CORRECTION = 2.0


def cruise_set_scale_fix_enabled(stored: str | bytes | None = None) -> bool:
  """Missing/empty file = ON. Explicit 0/false/off/no = OFF. 1/true/on/yes = ON."""
  if stored is None:
    try:
      p = _cruise_set_scale_fix_path
      if not p.is_file():
        return True
      text = p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
      return True
  else:
    text = (stored.decode(errors="replace") if isinstance(stored, bytes) else str(stored)).strip()
  if not text:
    return True
  low = text.lower()
  if low in ("0", "false", "off", "no"):
    return False
  return low in ("1", "true", "on", "yes")


def cruise_set_scale(enabled: bool) -> float:
  """Multiplier applied to the DBC-decoded DI_cruiseSet value."""
  return DBC_FACTOR_CORRECTION if enabled else 1.0
