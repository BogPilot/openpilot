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
2. Otherwise (a fresh UP/DN tap, a pull with no known limit, or no stalk seen): exact vEgoRaw at the engage
   edge, including below 8 kph. No 8 kph clamp-up, no 5 mph rounding. Tinkla ACC_module.py:154-158 @501c7de
   (current-speed latch at engage); BogPilot 0.9.7 slc_raise (tap -> sticky vEgo) @04d560f3e. A known limit
   never wins over a rolling tap. If that vEgo would publish as 0, the standstill rules below apply instead.
Fresh = pressed while engaged with nothing latched, or at most TAP_WINDOW_S before the engage edge (BogPilot
0.9.7 slc_raise RECENT_S); the most recent of tap / pull wins, and a press is used once.
Standstill (a tap never takes SLC here either; only a pull does):
3. A fresh stalk UP/DN tap as the most recent press: the tap-from-stop speed (AP1TapFromZeroMph, default 15 mph,
   24.14016 kph), even with a known limit. The planner's tap from 0 gives the same set (slc_raise tap_from_zero_ms).
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
# Stalk tap from 0 (standstill, nothing latched). Default 15 mph, user setting AP1TapFromZeroMph (whole mph 5-30).
# Missing, non-integer, or out-of-range values fall back to 15 (they are not clamped to 5 or 30).
TAP_FROM_ZERO_DEFAULT_MPH = 15
TAP_FROM_ZERO_MIN_MPH = 5
TAP_FROM_ZERO_MAX_MPH = 30
TAP_FROM_ZERO_KPH = TAP_FROM_ZERO_DEFAULT_MPH * CV.MPH_TO_KPH
TAP_FROM_ZERO_PARAM = "AP1TapFromZeroMph"
# A tap before the engage edge counts only this long: BogPilot 0.9.7 slc_raise.py:183 RECENT_S @568fea947
# (the same stalk-to-enable window the 0.9.7 engage classifier uses).
TAP_WINDOW_S = 0.8


def parse_tap_from_zero_mph(raw) -> int:
  """Whole mph in 5-30, else the default 15. Does not clamp an invalid value to an edge."""
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


def tap_from_zero_kph_from_param(raw) -> float:
  return parse_tap_from_zero_mph(raw) * CV.MPH_TO_KPH


def format_tap_from_zero_display(mph: int, is_metric: bool) -> str:
  """Settings value: '15 mph', or '15 mph (24 km/h)' when the UI is metric."""
  mph = int(mph)
  if is_metric:
    return f"{mph} mph ({int(round(mph * CV.MPH_TO_KPH))} km/h)"
  return f"{mph} mph"


def _clamp_kph(kph: float) -> float:
  return min(max(float(kph), SET_MIN_KPH), SET_MAX_KPH)


def _clamp_max_kph(kph: float) -> float:
  """Rolling vEgo latch: keep the exact speed, including below 8 kph; still cap at 170."""
  return min(float(kph), SET_MAX_KPH)


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
    self.speed_limit_unknown = False

  def update(self, cruise_state, v_ego_raw_ms: float, standstill: bool, limit_ms: float = 0.0,
             offset_fn: Callable[[float], float] | None = None, tap: bool = False,
             tap_from_zero_kph: float | None = None, pull: bool = False) -> float:
    """Returns cruiseState.speed (m/s). Sets self.speed_limit_unknown.

    tap: an UP/DN (accelCruise / decelCruise) press edge this frame. pull: a resumeCruise (SpdCtrlLvr_Stat 2) press edge.
    """
    v_kph = max(float(v_ego_raw_ms), 0.0) * CV.MS_TO_KPH
    tap_zero_kph = TAP_FROM_ZERO_KPH if tap_from_zero_kph is None else float(tap_from_zero_kph)
    limit_ms = float(limit_ms) if limit_ms and limit_ms > 0.0 else 0.0
    engaged = cruise_state in ENGAGED_STATES
    # True standstill is CarState.standstill (carstate.py: ret.standstill = ret.vEgo < 0.1 m/s).
    # A rolling vEgo that would publish as 0 also follows the standstill rules.
    use_standstill = bool(standstill) or _would_publish_zero(v_kph)
    self.tap_age_s += DT_CTRL
    self.stalk_age_s += DT_CTRL
    if pull:
      self.stalk_kind, self.stalk_age_s = "pull", 0.0
    elif tap:
      self.stalk_kind, self.stalk_age_s = "tap", 0.0
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
      if not use_standstill:
        # Rolling: only a fresh pull takes the limit; a tap or no stalk latches the current speed.
        if self.stalk_kind == "pull" and limit_ms > 0.0:
          offset_ms = float(offset_fn(limit_ms)) if offset_fn is not None else 0.0
          self.set_kph = _clamp_kph((limit_ms + offset_ms) * CV.MS_TO_KPH)
        else:
          self.set_kph = _clamp_max_kph(v_kph)
      elif self.stalk_kind == "tap" and self.tap_kph > 0.0:
        # Standstill tap: the tap-from-stop speed even with a known limit; only a pull engages SLC.
        self.set_kph = _clamp_kph(self.tap_kph)
      elif limit_ms > 0.0:
        offset_ms = float(offset_fn(limit_ms)) if offset_fn is not None else 0.0
        self.set_kph = _clamp_kph((limit_ms + offset_ms) * CV.MS_TO_KPH)
      elif self.tap_kph > 0.0:
        self.set_kph = _clamp_kph(self.tap_kph)
      if self.set_kph > 0.0:
        self.tap_kph = 0.0   # used (or overridden by the limit / vEgo latch): never reused on a re-engage
        self.stalk_kind = None
    self.speed_limit_unknown = bool(use_standstill and self.set_kph <= 0.0 and limit_ms <= 0.0 and self.tap_kph <= 0.0)
    if not engaged:
      return 0.0
    if self.set_kph <= 0.0:
      return 0.0   # engage refused (speed_limit_unknown, NO_ENTRY): openpilot stays disabled, no placeholder set
    if self.set_kph < SET_MIN_KPH:
      self.set_kph = _clamp_max_kph(self.set_kph)  # keep a rolling vEgo latch below 8 kph
    else:
      self.set_kph = _clamp_kph(self.set_kph)
    return self.set_kph * CV.KPH_TO_MS
