"""Lead-aware acceleration cap for the legacy Teslas (AP1 Model S/X, Pre-AP Model S).

Credit: NAP / sunnypilot Tesla Pre-AP "Adaptive Accel Limits" (MIT). The follow-limit table (ACCEL_PREAP_FOLLOW) and the
blend ratio (1.2x to 1.5x of the safe obstacle distance) are NAP's values, unchanged, listed here for review.

Why: the stock-style accel profile limits only the cruise-speed path; once a lead is close the car can still be handed a
large positive request by the cruise path while the lead path settles, which gives gas, overshoot, regen, gas. With the
toggle on, the final planner accel is capped by a speed table, blended in by how close the lead is, so the car stops
lunging at a slower lead. It only ever lowers a POSITIVE request. Braking is never touched.

Off (AdaptiveAccelLead = 0, the default) the planner never calls this module: zero behaviour change.
"""
from __future__ import annotations

import math

import numpy as np

# NAP ACCEL_PREAP_BP / ACCEL_PREAP_FOLLOW (opendbc/car/tesla/preap/constants.py). m/s, m/s^2.
FOLLOW_BP = (0.0, 1.3, 7.5, 15.0, 25.0, 30.0, 40.0)
FOLLOW_ACCEL = (0.3, 0.6, 0.9, 0.8, 0.7, 0.5, 0.45)
# Cap strength is 1 at or below FULL_RATIO and 0 at or above NONE_RATIO, linear between (NAP: 1 - (r - 1.2) / 0.3).
FULL_RATIO = 1.2
NONE_RATIO = 1.5
# Same constants as longitudinal_mpc_lib.long_mpc (a test pins them to the MPC's).
COMFORT_BRAKE = 2.5
STOP_DISTANCE = 6.0


def follow_limit(v_ego: float) -> float:
  return float(np.interp(v_ego, FOLLOW_BP, FOLLOW_ACCEL))


def cap_strength(v_ego: float, lead_distance: float, lead_speed: float, t_follow: float) -> float:
  """0..1: how much of the follow limit applies. Obstacle-equivalent distance over the safe obstacle distance."""
  obstacle = lead_distance + max(lead_speed, 0.0) ** 2 / (2 * COMFORT_BRAKE)
  safe = v_ego ** 2 / (2 * COMFORT_BRAKE) + t_follow * v_ego + STOP_DISTANCE
  ratio = obstacle / max(safe, 1.0)
  return float(np.clip(1.0 - (ratio - FULL_RATIO) / (NONE_RATIO - FULL_RATIO), 0.0, 1.0))


def lead_accel_cap(accel_max: float, v_ego: float, lead_distance: float, lead_speed: float, t_follow: float) -> float | None:
  """The positive accel ceiling for this step, or None when the lead is far enough that nothing is capped.

  accel_max is the ceiling that would otherwise apply (blend start); the result is never above it."""
  values = (accel_max, v_ego, lead_distance, lead_speed, t_follow)
  if not all(math.isfinite(v) for v in values):
    return None   # bad input: leave the plan alone
  strength = cap_strength(v_ego, lead_distance, lead_speed, t_follow)
  if strength <= 0.0:
    return None
  blended = accel_max * (1.0 - strength) + follow_limit(v_ego) * strength
  return float(min(accel_max, blended))
