"""Pre-AP accel envelope helpers (NAP-style personality profiles).

Credit: NAP-style.
"""
from __future__ import annotations

import numpy as np

from openpilot.selfdrive.car.tesla.preap.vdas_constants import (
  ACCEL_PREAP_BP, ACCEL_PREAP_PROFILES, REGEN_MAX,
)


def get_preap_accel_limits(current_speed: float, personality: int = 1) -> tuple[float, float]:
  profile = ACCEL_PREAP_PROFILES.get(int(personality), ACCEL_PREAP_PROFILES[1])
  a_max = float(np.interp(current_speed, ACCEL_PREAP_BP, profile))
  return float(REGEN_MAX), a_max
