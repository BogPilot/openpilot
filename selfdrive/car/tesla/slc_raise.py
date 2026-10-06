"""AP1 low-conflict speed-limit raise (no fake stalk, no panda 0x45 loosen).

When FrogPilot's Speed Limit Controller confirms a higher posted limit, lift
openpilot's cruise target to limit+offset so longitudinal accelerates into the
faster zone. The instrument-cluster set digit is updated by writing
DAS_accSpeedLimit on 0x389 (see cluster.py). DI_cruiseSet still seeds the
pcmCruise set; stalk UP/DN injection is intentionally not used.

Not a product. No warranty. The driver remains responsible. Comply with local law.
"""

from openpilot.common.conversions import Conversions as CV


def is_ap1(fingerprint: str | None) -> bool:
  from openpilot.selfdrive.car.tesla.values import CAR
  return fingerprint == CAR.TESLA_AP1_MODELS


def lift_cruise_ms(v_cruise_ms: float, slc_desired_ms: float, slc_target_ms: float,
                   cruising_speed_ms: float) -> float:
  """Raise v_cruise toward a confirmed higher SLC target.

  Caller still min()-caps with curve-speed / other targets afterward.
  No-op when the SLC target is missing or below cruising speed.
  """
  if slc_target_ms < cruising_speed_ms or slc_desired_ms < cruising_speed_ms:
    return v_cruise_ms
  if slc_desired_ms > v_cruise_ms:
    return slc_desired_ms
  return v_cruise_ms


def cluster_display_kph(v_cruise_cluster_kph: float, frogpilot_v_cruise_ms: float) -> float:
  """Comma / HUD set digit follows the SLC-raised planner cruise when higher.

  Never lowers the displayed set for curve-speed slowdowns — only lifts when
  frogpilotPlan.vCruise is above the DI-seeded cluster set.
  """
  fp_kph = float(frogpilot_v_cruise_ms) * CV.MS_TO_KPH
  if fp_kph > float(v_cruise_cluster_kph):
    return fp_kph
  return float(v_cruise_cluster_kph)


def cruise_set_mph(set_speed_ms: float | None) -> float | None:
  """Convert OP set speed (m/s) to mph for DAS_accSpeedLimit, or None to keep stock."""
  if set_speed_ms is None:
    return None
  mph = float(set_speed_ms) * CV.MS_TO_MPH
  if mph <= 0.0:
    return None
  return mph
