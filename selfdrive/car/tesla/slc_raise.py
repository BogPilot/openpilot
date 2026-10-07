"""AP1 low-conflict speed-limit raise (no fake stalk, no panda 0x45 loosen).

When FrogPilot's Speed Limit Controller confirms a higher posted limit, lift
openpilot's cruise target to limit+offset so longitudinal accelerates into the
faster zone. DI_cruiseSet still seeds the pcmCruise set; stalk UP/DN injection
is intentionally not used.

The IC set digit (DAS_accSpeedLimit on 0x389) tracks the OP raised set via the
cluster pack path. DBC factor is 0.4 so a raised 30 packs as dig 30 (route 21
dig=60 was packing with legacy 0.2 against an IC that scales 0.4). Comma/HUD
also lifts via cluster_display_kph. No Ap1RaiseHoldoff / stalk-DECEL suppress.

Not a product. No warranty. The driver remains responsible. Comply with local law.
"""

from openpilot.common.conversions import Conversions as CV


def is_ap1(fingerprint: str | None) -> bool:
  from openpilot.selfdrive.car.tesla.values import CAR
  return fingerprint == CAR.TESLA_AP1_MODELS


def lift_cruise_ms(v_cruise_ms: float, slc_desired_ms: float, slc_target_ms: float,
                   cruising_speed_ms: float) -> float:
  """Raise v_cruise toward a confirmed higher SLC target.

  Intended to run AFTER the min() merge so a pre-lift DI/csc seed cannot undo
  the raise. Caller re-caps with CSC only when CSC is actively controlling.
  No-op when the SLC target is missing or below cruising speed.
  """
  if slc_target_ms < cruising_speed_ms or slc_desired_ms < cruising_speed_ms:
    return v_cruise_ms
  if slc_desired_ms > v_cruise_ms:
    return slc_desired_ms
  return v_cruise_ms


def apply_slc_raise_after_min(v_cruise_ms: float, slc_desired_ms: float, slc_target_ms: float,
                              cruising_speed_ms: float, csc_controlling_speed: bool,
                              csc_target_ms: float) -> float:
  """AP1 post-min raise: lift, then re-min with CSC only if CSC is active.

  Used by frogpilot_vcruise after min(targets) so DI_cruiseSet sitting in
  csc_target (CSC inactive) cannot collapse a confirmed SLC raise.
  """
  v = lift_cruise_ms(v_cruise_ms, slc_desired_ms, slc_target_ms, cruising_speed_ms)
  if csc_controlling_speed:
    v = min(v, csc_target_ms)
  return v


def merge_vcruise_with_slc(v_cruise_ms: float, csc_target_ms: float, slc_desired_ms: float,
                           slc_target_ms: float, cruising_speed_ms: float,
                           csc_controlling_speed: bool = False) -> float:
  """Full AP1 merge order: min(targets) then apply_slc_raise_after_min.

  Mirrors frogpilot_vcruise.py so unit tests cover the DI≥CRUISING_SPEED
  regression (raise must stick at 30 when DI=11.5, limit 25, offset +5).
  """
  targets = [csc_target_ms, v_cruise_ms, slc_desired_ms]
  v = min(t if t >= cruising_speed_ms else v_cruise_ms for t in targets)
  return apply_slc_raise_after_min(
    v, slc_desired_ms, slc_target_ms, cruising_speed_ms,
    csc_controlling_speed, csc_target_ms)


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
  """Convert OP set speed (m/s) to mph for DAS_accSpeedLimit (DBC factor 0.4)."""
  if set_speed_ms is None:
    return None
  mph = float(set_speed_ms) * CV.MS_TO_MPH
  if mph <= 0.0:
    return None
  return mph
