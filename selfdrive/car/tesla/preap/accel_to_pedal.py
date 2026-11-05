"""Legacy open-loop accel→pedal map (kept for host unit tests).

Live Pre-AP long uses NAP-style VirtualDAS + PedalAuthority in
preap/long_controller.py. This simplified 15+12*a mapping remains so existing
tests (test_preap_pedal_radar) stay stable; do not call it from CarController.
"""
from __future__ import annotations

_DI_ZERO = 0.0
_DI_PRESSED = 2.0


def accel_to_pedal_command(accel_ms2: float, enabled: bool,
                           pedal_zero: float = 0.0,
                           pedal_factor: float = 1.0) -> tuple[float, int]:
  """Return (pedal_command, enable_bit). Legacy path only."""
  if not enabled:
    return 0.0, 0
  cmd = 15.0 + (accel_ms2 * 12.0)
  cmd = max(0.0, min(80.0, cmd))
  factor = pedal_factor if pedal_factor != 0 else 1.0
  if factor != 1.0 or pedal_zero != 0.0:
    di = _DI_ZERO + (_DI_PRESSED - _DI_ZERO) * (cmd / 100.0)
    cmd = pedal_zero + (di - _DI_ZERO) / factor
  return float(cmd), 1
