"""AP1 low-conflict speed-limit raise (no fake stalk, no panda 0x45 loosen).

When FrogPilot's Speed Limit Controller confirms a higher posted limit, lift
openpilot's cruise target to limit+offset so longitudinal accelerates into the
faster zone. DI_cruiseSet still seeds the pcmCruise set; stalk UP/DN injection
is intentionally not used.

The IC set digit (DAS_accSpeedLimit on 0x389) stays stock. Overlaying the OP
raised set while DI_cruiseSet stayed low locked DI_digitalSpeed at 60 on AP1
(route 21 @ bd26defe; dig==60 == 2x raised set). Comma/HUD set may still lift
via cluster_display_kph.

Engaged stalk DECEL holdoff: once cruise is already enabled, a driver DECEL
suppresses the raise until RES/accel or a higher SLC target (route 21: stalk
DOWN was immediately undone by re-lift to limit+offset while dig showed 60).
Engage-via-SET (DECEL while previously disengaged) still allows raise.

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
                           csc_controlling_speed: bool = False,
                           raise_holdoff: bool = False) -> float:
  """Full AP1 merge order: min(targets) then apply_slc_raise_after_min.

  Mirrors frogpilot_vcruise.py so unit tests cover the DI≥CRUISING_SPEED
  regression (raise must stick at 30 when DI=11.5, limit 25, offset +5).
  When raise_holdoff is True (engaged stalk DECEL), skip the lift so DI set wins.
  """
  targets = [csc_target_ms, v_cruise_ms, slc_desired_ms]
  v = min(t if t >= cruising_speed_ms else v_cruise_ms for t in targets)
  if raise_holdoff:
    return v
  return apply_slc_raise_after_min(
    v, slc_desired_ms, slc_target_ms, cruising_speed_ms,
    csc_controlling_speed, csc_target_ms)


class Ap1RaiseHoldoff:
  """Suppress AP1 SLC raise after engaged stalk DECEL until RES or limit rise.

  Route 21 correction: driver manually pulled set DOWN; OP immediately re-lifted
  frogpilotPlan.vCruise to limit+offset and accelerated while dig locked at 60.
  Nothing was "holding 10" — DI≈10 was the stalked-down set OP was fighting.

  Engage-via-SET (DECEL while previously disengaged) must still allow raise.
  """

  # ~1 mph — clear holdoff when posted limit steps up into a faster zone
  LIMIT_RISE_MS = 0.5

  def __init__(self):
    self.holdoff = False
    self._prev_enabled = False
    self._prev_slc_target = 0.0

  def update(self, enabled: bool, decel_pressed: bool, accel_pressed: bool,
             slc_target_ms: float) -> bool:
    """Update state. Returns True if raise should run this frame."""
    if float(slc_target_ms) > self._prev_slc_target + self.LIMIT_RISE_MS:
      self.holdoff = False
    if accel_pressed:
      self.holdoff = False
    if enabled and self._prev_enabled and decel_pressed:
      self.holdoff = True
    if not enabled:
      self.holdoff = False

    self._prev_enabled = bool(enabled)
    self._prev_slc_target = float(slc_target_ms)
    return not self.holdoff


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
  """Convert OP set speed (m/s) to mph. Unused on CAN: DAS_accSpeedLimit stays stock."""
  if set_speed_ms is None:
    return None
  mph = float(set_speed_ms) * CV.MS_TO_MPH
  if mph <= 0.0:
    return None
  return mph
