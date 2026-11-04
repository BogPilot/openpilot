"""Map planner accel (m/s^2) to Comma Pedal command units.

Simplified from NotAutopilot Pre-AP virtual DAS / pedal feedback. Full zero-torque
learning and engage-grace ramps are left out of this cut — see PREAP_NA.md.
"""
from __future__ import annotations


def accel_to_pedal_command(accel_ms2: float, enabled: bool) -> tuple[float, int]:
  """Return (pedal_command, enable_bit).

  Neutral / disabled sends enable=0 with near-zero command (passthrough).
  Enabled maps a conservative regen/accel band into pedal percent units.
  """
  if not enabled:
    return 0.0, 0
  # Rough mapping: 0 m/s^2 → ~15% (creep/hold band), +1 → higher, -1 → lower.
  # Clamped; NotAutopilot's learned feedforward is more accurate — TBD.
  cmd = 15.0 + (accel_ms2 * 12.0)
  cmd = max(0.0, min(80.0, cmd))
  return cmd, 1
