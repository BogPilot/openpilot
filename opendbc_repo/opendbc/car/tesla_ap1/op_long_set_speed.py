"""AP1 cruiseState.speed under openpilot longitudinal: openpilot's own set speed, never DI_cruiseSet.

Under openpilot long on AP1, DI_cruiseSet follows ego speed (not a driver set) and reads 0 at every
stop. openpilot's VCruiseHelper (pcmCruise branch) turns cruiseState.speed 0 into V_CRUISE_UNSET, the
planner then resets every cycle, and shouldStop stays latched after the lead pulls away.

Set taken on the engage edge (first engaged DI_cruiseState tick). The stalk action that engaged decides it
(a rolling tap latches the current speed and never follows SLC; only a pull engages SLC):
Rolling (not standstill):
1. A fresh stalk PULL (resumeCruise, SpdCtrlLvr_Stat 2, values.py) and a known dashboardSpeedLimit: the limit
   plus the speed-limit offset (Offset1..7 bands), the same limit source (speed_limit.py) and bands
   (phase3_speed_control.offset_for) the planner's SLC uses; BogPilot 0.9.7 SLC (speed_limit_controller.py
   @568fea947). The offset comes from the card (params), never from bogpilotPlan, so there is no feedback loop.
2. Otherwise (a fresh UP/DN tap, a pull with no known limit, or no stalk seen): vEgoRaw at the engage edge,
   rounded half-up to a whole display unit (whole mph; km/h when the car's DI_speedUnits is KPH), the same
   latch a Pre-AP tip gets (v6: tip behaviour identical on AP1 and Pre-AP; before v6 the exact
   vEgoRaw). Rounding never turns the latch into 0 (it then stays exact). Includes below 8 kph. No 8 kph
   clamp-up, no 5 mph rounding. Tinkla ACC_module.py:154-158 @501c7de
   (current-speed latch at engage); BogPilot 0.9.7 slc_raise (tap -> sticky vEgo) @04d560f3e. A known limit
   never wins over a rolling tap. If that vEgo would publish as 0, the standstill rules below apply instead.
Fresh = pressed while engaged with nothing latched, or at most TAP_WINDOW_S before the engage edge (BogPilot
0.9.7 slc_raise RECENT_S); the most recent of tap / pull wins, and a press is used once.
Standstill (a tap never takes SLC here either; only a pull does):
3. A fresh stalk UP/DN tap as the most recent press: the tap-from-stop speed (AP1TapFromZeroMs, m/s; default 15 mph,
   24.14016 kph), even with a known limit. The planner's tap from 0 gives the same set (slc_raise tap_from_zero_ms).
   A tap made while still rolling, then a stop inside the window: the vEgo at the tap (whole display unit, as
   rule 2), the same latch the
   planner takes for that tap (slc_raise engage_vego_ms), never limit plus offset.
4. A known limit (a fresh pull, or no stalk seen): limit plus offset.
5. A fresh tap with no limit (e.g. a pull after the tap): the tap-from-stop speed. An older tap (e.g. at a red
   light before the engage) is dropped, and a tap is used once.
6. No limit, no tap: nothing latched. speed_limit_unknown is raised so selfdrived refuses
   the engage (NO_ENTRY ap1SpeedLimitUnknown). 0 (unset) is published meanwhile: openpilot is not
   enabled, so no set reaches the planner, the HUD or 0x389 (no 8 kph / 5 mph placeholder).
Once latched, a limit or standstill-tap set is clamped to 8-170 kph (Tinkla ACC_module.py:231-232); a
rolling vEgo latch is only capped at 170 kph. The set is held through later stops, including DI_cruiseSet 0,
until cruise disengages. Limit changes after the engage stay in the
planner's SLC; stalk tips after the engage stay in the planner's tip path.

With no sticky, tip or SLC set active in the planner, the car can speed back up to this set after
slowing (as Tinkla's set does).

Not engaged under openpilot long: 0 is published (VCruiseHelper reads it as unset), never DI_cruiseSet,
so vCruise steps straight to the set on the engage edge with no DI seed first.

Applies to every AP1 car with openpilot long on (is_ap1_family: Model S and Model X AP1,
values.py:158-159). With openpilot long off, DI_cruiseSet is published unchanged.
Inputs: DI_cruiseState, ESP_vehicleSpeed, dashboardSpeedLimit, stalk buttons and the card-supplied
offset. Never cruiseState.speed, carState.vCruise / vCruiseCluster, bogpilotPlan or hudControl.
"""
import math
from collections.abc import Callable

from opendbc.car import DT_CTRL
from opendbc.car.common.conversions import Conversions as CV

# DI_cruiseState values with cruise engaged (tesla_ap1_can.dbc VAL_ 872): 2 ENABLED,
# 3 STANDSTILL, 4 OVERRIDE, 6 PRE_FAULT, 7 PRE_CANCEL. The same set drives cruiseState.enabled.
ENGAGED_STATES = ("ENABLED", "STANDSTILL", "OVERRIDE", "PRE_FAULT", "PRE_CANCEL")
# Floor: openpilot V_CRUISE_MIN (selfdrive/car/cruise.py, 8 kph).
SET_MIN_KPH = 8.
# Tinkla ACC_module.py:231-232 @501c7de clips acc_speed_kph to 170 kph.
SET_MAX_KPH = 170.
# Stalk tap from 0 (standstill, nothing latched). Default 15 mph. User setting AP1TapFromZeroMs: stored in
# m/s, shown and stepped in whole mph (5-30) or, with IsMetric, whole km/h (8-48). Before this change it was AP1TapFromZeroMph
# (whole mph 5-30); system/bogpilot/legacy_migration.migrate_tap_from_zero_ms carries a saved mph value over exactly
# (N mph -> N * 0.44704 m/s). Missing, non-numeric, non-finite or out-of-range values fall back to 15 mph (never clamped).
TAP_FROM_ZERO_DEFAULT_MPH = 15
TAP_FROM_ZERO_MIN_MPH = 5
TAP_FROM_ZERO_MAX_MPH = 30
# Metric steps: whole km/h. 8 km/h is openpilot's V_CRUISE_MIN (SET_MIN_KPH, the floor the latch is clamped to anyway)
# and shows as 5 mph; 48 km/h is the last whole km/h inside 30 mph (48.28 km/h). Both edges stay inside the mph range's
# display (8 km/h -> "5 mph", 48 km/h -> "30 mph"; 5 mph -> "8 km/h", 30 mph -> "48 km/h").
TAP_FROM_ZERO_MIN_KPH_DISPLAY = 8
TAP_FROM_ZERO_MAX_KPH_DISPLAY = 48
MPH_TO_MS_EXACT = 0.44704   # international mile: 1609.344 m / 3600 s, exact in decimal
MS_TO_KPH_EXACT = 3.6
TAP_FROM_ZERO_KPH = TAP_FROM_ZERO_DEFAULT_MPH * CV.MPH_TO_KPH
TAP_FROM_ZERO_DEFAULT_MS = TAP_FROM_ZERO_DEFAULT_MPH * MPH_TO_MS_EXACT   # 6.7056
TAP_FROM_ZERO_PARAM = "AP1TapFromZeroMs"
TAP_FROM_ZERO_LEGACY_MPH_PARAM = "AP1TapFromZeroMph"   # previous key, read only by the one-time migration
# Accepted stored range (m/s): the lower of the two unit floors (8 km/h) to the higher of the two ceilings (30 mph).
_MS_EPS = 1e-6
TAP_FROM_ZERO_MIN_MS = TAP_FROM_ZERO_MIN_KPH_DISPLAY / MS_TO_KPH_EXACT
TAP_FROM_ZERO_MAX_MS = TAP_FROM_ZERO_MAX_MPH * MPH_TO_MS_EXACT


def parse_tap_from_zero_mph(raw) -> int:
  """Legacy AP1TapFromZeroMph text: whole mph in 5-30, else the default 15. Does not clamp an invalid value to an edge."""
  if raw is None:
    return TAP_FROM_ZERO_DEFAULT_MPH
  if isinstance(raw, (bytes, bytearray)):
    raw = raw.decode("utf-8", "replace")
  if isinstance(raw, bool):
    return TAP_FROM_ZERO_DEFAULT_MPH
  if isinstance(raw, str):
    text = raw.strip()
    if text == "" or not text.lstrip("-").isdigit():
      return TAP_FROM_ZERO_DEFAULT_MPH
    value = int(text)
  elif isinstance(raw, int):
    value = raw
  elif isinstance(raw, float):
    if not raw.is_integer():
      return TAP_FROM_ZERO_DEFAULT_MPH
    value = int(raw)
  else:
    return TAP_FROM_ZERO_DEFAULT_MPH
  if value < TAP_FROM_ZERO_MIN_MPH or value > TAP_FROM_ZERO_MAX_MPH:
    return TAP_FROM_ZERO_DEFAULT_MPH
  return value


def legacy_mph_valid(raw) -> bool:
  """True when a legacy AP1TapFromZeroMph value is a real saved choice (whole mph 5-30), not the parser's fallback."""
  if raw is None or isinstance(raw, bool):
    return False
  if isinstance(raw, (bytes, bytearray)):
    raw = raw.decode("utf-8", "replace")
  if isinstance(raw, str):
    text = raw.strip()
    if text == "" or not text.lstrip("-").isdigit():
      return False
    value = int(text)
  elif isinstance(raw, int):
    value = raw
  elif isinstance(raw, float) and raw.is_integer():
    value = int(raw)
  else:
    return False
  return TAP_FROM_ZERO_MIN_MPH <= value <= TAP_FROM_ZERO_MAX_MPH


def mph_to_ms(mph: int) -> float:
  """Whole mph as the stored m/s float (N * 0.44704; the migration and the imperial -/+ use this)."""
  return int(mph) * MPH_TO_MS_EXACT


def kph_to_ms(kph: int) -> float:
  """Whole km/h as the stored m/s float (N / 3.6; the metric -/+ use this)."""
  return int(kph) / MS_TO_KPH_EXACT


def format_ms_text(ms: float) -> str:
  """Stored text for a m/s value: repr, so float(text) gives back the exact same float (no %g rounding drift)."""
  return repr(float(ms))


def parse_tap_from_zero_ms(raw) -> float:
  """AP1TapFromZeroMs text/number as m/s: finite and within 8 km/h .. 30 mph, else the default (15 mph). Never clamped."""
  if raw is None or isinstance(raw, bool):
    return TAP_FROM_ZERO_DEFAULT_MS
  if isinstance(raw, (bytes, bytearray)):
    raw = raw.decode("utf-8", "replace")
  try:
    value = float(raw.strip()) if isinstance(raw, str) else float(raw)
  except (TypeError, ValueError):
    return TAP_FROM_ZERO_DEFAULT_MS
  if not math.isfinite(value):
    return TAP_FROM_ZERO_DEFAULT_MS
  if value < TAP_FROM_ZERO_MIN_MS - _MS_EPS or value > TAP_FROM_ZERO_MAX_MS + _MS_EPS:
    return TAP_FROM_ZERO_DEFAULT_MS
  return value


def tap_from_zero_kph_from_ms(ms: float) -> float:
  """m/s setting as kph for the card / planner. A value that is a whole mph (every migrated value, every imperial edit)
  returns N * CV.MPH_TO_KPH, bit-for-bit the kph the previous whole-mph setting produced; a whole km/h (metric edit)
  returns that whole km/h; anything else is ms * 3.6."""
  ms = float(ms)
  mph = math.floor(ms / MPH_TO_MS_EXACT + 0.5)
  if abs(mph * MPH_TO_MS_EXACT - ms) <= _MS_EPS:
    return mph * CV.MPH_TO_KPH
  kph = math.floor(ms * MS_TO_KPH_EXACT + 0.5)
  if abs(kph / MS_TO_KPH_EXACT - ms) <= _MS_EPS:
    return float(kph)
  return ms * MS_TO_KPH_EXACT


def tap_from_zero_kph_from_param(raw) -> float:
  """AP1TapFromZeroMs (m/s) as kph; invalid/missing -> 15 mph (24.14016 kph)."""
  return tap_from_zero_kph_from_ms(parse_tap_from_zero_ms(raw))


def tap_from_zero_display_value(ms: float, is_metric: bool) -> int:
  """Whole display unit (half-up) for a m/s value: km/h with IsMetric, else mph. Display only, never written back."""
  ms = float(ms)
  if is_metric:
    return int(math.floor(ms * MS_TO_KPH_EXACT + 0.5))
  return int(math.floor(ms / MPH_TO_MS_EXACT + 0.5))


def tap_from_zero_display_bounds(is_metric: bool) -> tuple[int, int]:
  if is_metric:
    return TAP_FROM_ZERO_MIN_KPH_DISPLAY, TAP_FROM_ZERO_MAX_KPH_DISPLAY
  return TAP_FROM_ZERO_MIN_MPH, TAP_FROM_ZERO_MAX_MPH


def tap_from_zero_display_to_ms(value: int, is_metric: bool) -> float:
  return kph_to_ms(value) if is_metric else mph_to_ms(value)


def format_tap_from_zero_display(ms: float, is_metric: bool) -> str:
  """Settings value for a m/s setting: '15 mph', or '24 km/h' when the UI is metric (IsMetric)."""
  value = tap_from_zero_display_value(ms, is_metric)
  return f"{value} km/h" if is_metric else f"{value} mph"


# A tap before the engage edge counts only this long: BogPilot 0.9.7 slc_raise.py:183 RECENT_S @568fea947
# (the same stalk-to-enable window the 0.9.7 engage classifier uses).
TAP_WINDOW_S = 0.8


def _clamp_kph(kph: float) -> float:
  return min(max(float(kph), SET_MIN_KPH), SET_MAX_KPH)


def _clamp_max_kph(kph: float) -> float:
  """Rolling vEgo latch: keep the exact speed, including below 8 kph; still cap at 170."""
  return min(float(kph), SET_MAX_KPH)


def round_whole_kph(kph: float, is_metric: bool = False) -> float:
  """v6: a rolling tip latch in whole display units (half-up), returned in kph. Whole mph unless is_metric (whole km/h).
  A result of 0 (a speed under half a unit) keeps the exact value, so a latch never becomes 0 / unset."""
  unit = 1.0 if is_metric else CV.MPH_TO_KPH
  rounded = math.floor(float(kph) / unit + 0.5) * unit
  return rounded if rounded > 0.0 else float(kph)


def _limit_plus_offset_kph(limit_ms: float, offset_fn: Callable[[float], float] | None) -> float:
  """Limit plus offset in kph, clamped to 8-170. 0 (treated as an unknown limit) when the offset or the sum is not finite."""
  offset_ms = float(offset_fn(limit_ms)) if offset_fn is not None else 0.0
  total_ms = limit_ms + offset_ms
  if not math.isfinite(offset_ms) or not math.isfinite(total_ms):
    return 0.0
  return _clamp_kph(total_ms * CV.MS_TO_KPH)


def _would_publish_zero(kph: float) -> bool:
  """True when a rolling vEgo latch would be 0 on the dash/planner (never 0/UNSET while enabled)."""
  if kph <= 0.0 or round(float(kph), 1) == 0.0:
    return True
  # 0x389 DAS_accSpeedLimit factor 0.4 mph, half-up onto the grid.
  mph = float(kph) * CV.KPH_TO_MPH
  return round(mph / 0.4) * 0.4 <= 0.0


class OpLongSetSpeed:
  """Latched openpilot set speed while DI cruise is engaged."""

  def __init__(self):
    self.set_kph = 0.0     # latched set; 0 = nothing latched
    self.tap_kph = 0.0     # fresh stalk tap at a standstill with nothing latched
    self.tap_age_s = 0.0   # time since that tap
    self.stalk_kind = None   # fresh engage stalk action: "tap" (UP/DN) or "pull" (resumeCruise); None = none seen
    self.stalk_age_s = 0.0   # time since that press
    self.tap_vego_kph = 0.0  # vEgoRaw at the latest tap made while rolling (0 = none, or the tap was at a standstill)
    self.speed_limit_unknown = False

  def update(self, cruise_state, v_ego_raw_ms: float, standstill: bool, limit_ms: float = 0.0,
             offset_fn: Callable[[float], float] | None = None, tap: bool = False,
             tap_from_zero_kph: float | None = None, pull: bool = False, is_metric: bool = False) -> float:
    """Returns cruiseState.speed (m/s). Sets self.speed_limit_unknown.

    tap: an UP/DN (accelCruise / decelCruise) press edge this frame. pull: a resumeCruise (SpdCtrlLvr_Stat 2) press edge.
    is_metric: DI_speedUnits is KPH (the rolling latch rounds to whole km/h instead of whole mph).
    """
    # Non-finite inputs never become a set: a non-finite limit (or limit plus offset) is an unknown limit, a non-finite
    # vEgoRaw latches nothing (the engage is refused like an unknown limit at a standstill), a non-finite tap-from-stop
    # setting is the default (as parse_tap_from_zero_ms treats an invalid value).
    v_raw = float(v_ego_raw_ms)
    v_ok = math.isfinite(v_raw)
    v_kph = max(v_raw, 0.0) * CV.MS_TO_KPH if v_ok else 0.0
    tap_zero_kph = TAP_FROM_ZERO_KPH if tap_from_zero_kph is None else float(tap_from_zero_kph)
    if not math.isfinite(tap_zero_kph):
      tap_zero_kph = TAP_FROM_ZERO_KPH
    limit_ms = float(limit_ms) if limit_ms else 0.0
    if not math.isfinite(limit_ms) or limit_ms <= 0.0:
      limit_ms = 0.0
    engaged = cruise_state in ENGAGED_STATES
    # True standstill is CarState.standstill (carstate.py: ret.standstill = ret.vEgo < 0.1 m/s).
    # A rolling vEgo that would publish as 0 also follows the standstill rules.
    use_standstill = bool(standstill) or (v_ok and _would_publish_zero(v_kph))
    refused_nonfinite = engaged and self.set_kph <= 0.0 and not v_ok
    self.tap_age_s += DT_CTRL
    self.stalk_age_s += DT_CTRL
    if pull:
      self.stalk_kind, self.stalk_age_s = "pull", 0.0
    elif tap:
      self.stalk_kind, self.stalk_age_s = "tap", 0.0
      self.tap_vego_kph = v_kph if not use_standstill else 0.0
    if not use_standstill:
      self.tap_kph = 0.0   # rolling: a tap-from-0 does not apply; the exact vEgo latch does
    elif tap and self.set_kph <= 0.0:
      self.tap_kph = tap_zero_kph
      self.tap_age_s = 0.0
    if not engaged:
      self.set_kph = 0.0
      if self.tap_age_s > TAP_WINDOW_S + 1e-6:
        self.tap_kph = 0.0   # stale: too long before any engage edge
      if self.stalk_age_s > TAP_WINDOW_S + 1e-6:
        self.stalk_kind = None   # stale: too long before any engage edge
    elif self.set_kph <= 0.0:
      limit_set_kph = _limit_plus_offset_kph(limit_ms, offset_fn) if limit_ms > 0.0 else 0.0
      if limit_set_kph <= 0.0:
        limit_ms = 0.0   # limit plus offset not finite: an unknown limit
      if not v_ok:
        pass   # vEgoRaw not finite: no latch from it (refused below, speed_limit_unknown)
      elif not use_standstill:
        # Rolling: only a fresh pull takes the limit; a tap or no stalk latches the current speed.
        if self.stalk_kind == "pull" and limit_set_kph > 0.0:
          self.set_kph = limit_set_kph
        else:
          self.set_kph = _clamp_max_kph(round_whole_kph(v_kph, is_metric))
      elif self.stalk_kind == "tap" and self.tap_kph > 0.0:
        # Standstill tap: the tap-from-stop speed even with a known limit; only a pull engages SLC.
        self.set_kph = _clamp_kph(self.tap_kph)
      elif self.stalk_kind == "tap" and self.tap_vego_kph > 0.0 and not _would_publish_zero(self.tap_vego_kph):
        # Tapped while rolling, stopped inside the window: the vEgo latch of that tap (the planner latches the same
        # vEgo for this engage), never limit plus offset.
        self.set_kph = _clamp_max_kph(round_whole_kph(self.tap_vego_kph, is_metric))
      elif limit_set_kph > 0.0:
        self.set_kph = limit_set_kph
      elif self.tap_kph > 0.0:
        self.set_kph = _clamp_kph(self.tap_kph)
      if self.set_kph > 0.0:
        self.tap_kph = 0.0   # used (or overridden by the limit / vEgo latch): never reused on a re-engage
        self.stalk_kind = None
        self.tap_vego_kph = 0.0
    self.speed_limit_unknown = bool(refused_nonfinite or
                                    (use_standstill and self.set_kph <= 0.0 and limit_ms <= 0.0 and self.tap_kph <= 0.0))
    if not engaged:
      return 0.0
    if self.set_kph <= 0.0:
      return 0.0   # engage refused (speed_limit_unknown, NO_ENTRY): openpilot stays disabled, no placeholder set
    if self.set_kph < SET_MIN_KPH:
      self.set_kph = _clamp_max_kph(self.set_kph)  # keep a rolling vEgo latch below 8 kph
    else:
      self.set_kph = _clamp_kph(self.set_kph)
    return self.set_kph * CV.KPH_TO_MS
