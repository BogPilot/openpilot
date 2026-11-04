"""Map planner accel (m/s^2) to Comma Pedal command units.

Simplified from NotAutopilot Pre-AP virtual DAS / pedal feedback. Full zero-torque
learning and engage-grace ramps are left out of this cut — see PREAP_NA.md.

When PedalCalibFactor / PedalCalibZero are set, the percent command is scaled
through the NAP-style DI→pedal transform.
"""
from __future__ import annotations

_DI_ZERO = 0.0
_DI_PRESSED = 2.0


def accel_to_pedal_command(accel_ms2: float, enabled: bool,
                           pedal_zero: float = 0.0,
                           pedal_factor: float = 1.0) -> tuple[float, int]:
  """Return (pedal_command, enable_bit).

  Neutral / disabled sends enable=0 with near-zero command (passthrough).
  Enabled maps a conservative regen/accel band into pedal percent units, then
  applies calib (identity when factor=1, zero=0).
  """
  if not enabled:
    return 0.0, 0
  # Rough mapping: 0 m/s^2 → ~15% (creep/hold band), +1 → higher, -1 → lower.
  cmd = 15.0 + (accel_ms2 * 12.0)
  cmd = max(0.0, min(80.0, cmd))
  # Optional calib: treat cmd as DI-ish percent and map with factor/zero.
  # Default factor=1, zero=0 → unchanged (keeps prior host tests stable).
  factor = pedal_factor if pedal_factor != 0 else 1.0
  if factor != 1.0 or pedal_zero != 0.0:
    # Map cmd 0..100 into DI 0..2 then to pedal units (NAP transform_di_to_pedal).
    di = _DI_ZERO + (_DI_PRESSED - _DI_ZERO) * (cmd / 100.0)
    cmd = pedal_zero + (di - _DI_ZERO) / factor
  return float(cmd), 1
