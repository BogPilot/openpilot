"""Lateral limits shared by AP1 and Pre-AP (stage 1), host side. Mirrors the panda in safety/lateral.h and modes/tesla_ap1.h.

Lateral-accel bound: stock opendbc ISO bound (car/lateral.py MAX_LATERAL_ACCEL, ~3.6 m/s^2) through the same vehicle model the panda uses
(steer_angle_lat_accel_check), here with the legacy Model S numbers. Same speed floor as get_max_angle_vm (v_raw >= 1 m/s).
The panda evaluates its bound at 1 m/s below the slowest recent speed, so the host bound is never above the panda one.

Rate ceiling: the host up/down tables are capped at the panda tables evaluated 1 m/s lower, minus a margin for the 0.1 deg CAN step.
Only ever lowers a rate limit.
"""
import math

import numpy as np

from opendbc.car.lateral import MAX_LATERAL_ACCEL

# Keep equal to TESLA_LEGACY_LAT_ACCEL_PARAMS in safety/modes/tesla_ap1.h.
LEGACY_S_STEER_RATIO = 15.0
LEGACY_S_WHEELBASE = 2.959
LEGACY_S_SLIP_FACTOR = -0.0005666
MAX_STEER_ANGLE_DEG = 360.0
MEASURED_WHEEL_CLIP_DEG = 20.0  # Tinkla's "to not fault the EPS" clip; AP1 has it inline in actuator_plan._ap1_limited_angle

# Keep equal to the AP1 / Pre-AP angle_rate_up/down_lookup tables in safety/modes/tesla_ap1.h and tesla_preap.h (deg per command frame).
PANDA_RATE_SPEED_BP = (2.0, 7.0, 17.0)
PANDA_RATE_UP = (8.0, 4.0, 2.5)
PANDA_RATE_DOWN = (9.0, 5.0, 4.5)
PANDA_SPEED_FUDGE = 1.0     # m/s, VEHICLE_SPEED_FACTOR fudge in steer_angle_cmd_checks_with_lateral_permission
HOST_RATE_MARGIN_DEG = 0.15  # panda adds 1 CAN count (0.1 deg) and truncates; host steps are quantized to 0.1 deg


def max_lat_accel_angle_deg(v_ego_raw):
  """Largest steering wheel angle (deg) the lateral-accel bound allows at this speed, capped at +-360."""
  v = max(float(v_ego_raw), 1.0)
  curvature_factor = 1. / (1. - LEGACY_S_SLIP_FACTOR * v * v) / LEGACY_S_WHEELBASE
  max_curvature = MAX_LATERAL_ACCEL / (v * v)
  angle = math.degrees(max_curvature * LEGACY_S_STEER_RATIO / curvature_factor)
  return min(angle, MAX_STEER_ANGLE_DEG)


def limit_lat_accel_angle(apply_angle, v_ego_raw):
  bound = max_lat_accel_angle_deg(v_ego_raw)
  return float(np.clip(apply_angle, -bound, bound))


def panda_rate_ceiling(v_ego, steer_up):
  """Host-side ceiling (deg per frame) that keeps the host rate limit below the panda table with margin."""
  table = PANDA_RATE_UP if steer_up else PANDA_RATE_DOWN
  return max(0.0, float(np.interp(v_ego - PANDA_SPEED_FUDGE, PANDA_RATE_SPEED_BP, table)) - HOST_RATE_MARGIN_DEG)


def clip_to_measured_wheel(apply_angle, measured_angle_deg):
  return float(np.clip(apply_angle, measured_angle_deg - MEASURED_WHEEL_CLIP_DEG, measured_angle_deg + MEASURED_WHEEL_CLIP_DEG))
