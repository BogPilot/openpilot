"""BogPilot speed row LIMIT tile and SLC offset badge (t913u), daily bogpilot-tesla semantics on real C3X sources.

Pure Python (no pyray, cereal or Params at import) so it is testable headless.

Daily 04d560f3e (annotated_camera.cc updateState / drawRedesignHud):
  shown     = (show_speed_limits || speed_limit_controller) and (not hide_speed_limit or plan.speedLimitChanged)
              MUTCD tile, or a Vienna roundel with UseVienna
  number    = the POSTED limit (frogpilotPlan.slcSpeedLimit); an SLC override shows the overridden speed at 25 % opacity
  badge     = frogpilotPlan.slcSpeedLimitOffset as a separate green "+N" badge, hidden when 0
  set speed = engaged and a limit: colour white -> orange -> red at limit + 5 / 15 / 25 (display units); not set: grey
Daily FrogPilot only publishes a non-zero offset when the Speed Limit Controller actually drives the cruise target
(frogpilot_vcruise.py: show-only mode publishes offset 0).

C3X sources (verified, no invented values):
  posted limit  frogpilotCarState.dashboardSpeedLimit, m/s, 0 = none. AP1 opendbc tesla_ap1/speed_limit.py:
                DAS_fusedSpeedLimit (bus 2) -> UI_mapSpeedLimit enum -> UI_mppSpeedLimit, units UI_mapSpeedLimitUnits.
                Must be valid, alive, from the current drive and at most LIMIT_STALE_S old.
  SLC fields    frogpilotPlan.slcSpeedLimit / slcSpeedLimitOffset / slcOverriddenSpeed / speedLimitChanged, from the
                validated plan reader (cluster_layout.read_csc_status). C3X has NO Speed Limit Controller yet, so they
                are 0 and the badge stays hidden; they are honoured as soon as a real SLC publishes them.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

LIMIT_STALE_S = 0.5          # frogpilotCarState publishes at 100 Hz
MIN_LIMIT_MS = 1.0           # speed_limit_controller.update_limits: limits below 1 m/s are "no limit"
MAX_LIMIT_MS = 100.0         # sanity bound (360 km/h); anything above is treated as invalid, not displayed
NO_LIMIT = "–"

WHITE = (255, 255, 255, 255)
ORANGE = (0xFF, 0x95, 0x00, 255)
RED = (0xFF, 0x00, 0x00, 255)
GREY = (0x72, 0x72, 0x72, 0xFF)


@dataclass(frozen=True)
class LimitPolicy:
  show_speed_limits: bool = False
  speed_limit_controller: bool = False
  vienna: bool = False
  hide_speed_limit: bool = False
  show_speed_limit_offset: bool = False

  @property
  def slc_limits(self) -> bool:
    return self.show_speed_limits or self.speed_limit_controller


CLOSED_POLICY = LimitPolicy()


def policy_from_store(store, CP=None) -> LimitPolicy:
  """367e1fe frogpilot_variables.py :773 / :1056 / :1057 / :1127 / :1132 through the shared onroad_toggles."""
  from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
  t = onroad_toggles(store, CP)
  level = t.tuning_level
  vienna = bool(t.navigation_ui and store.toggle_bool("UseVienna", level))
  hide = bool(store.toggle_bool("AdvancedCustomUI", level) and store.toggle_bool("HideSpeedLimit", level) and not t.debug_mode)
  return LimitPolicy(show_speed_limits=bool(t.show_speed_limits), speed_limit_controller=bool(t.speed_limit_controller),
                     vienna=vienna, hide_speed_limit=hide, show_speed_limit_offset=bool(t.show_speed_limit_offset))


class LimitPolicyReader:
  """Cached (2 s) policy. Any read failure fails closed: no LIMIT tile."""

  def __init__(self, store=None, cp_fn=None, clock=time.monotonic, ttl=2.0):
    self._store, self._cp_fn, self.clock, self.ttl = store, cp_fn, clock, ttl
    self._next = -1.0
    self._value = CLOSED_POLICY

  def get(self) -> LimitPolicy:
    now = self.clock()
    if now >= self._next:
      self._next = now + self.ttl
      try:
        if self._store is None:
          from openpilot.common.bogpilot_store import ParamStore
          self._store = ParamStore()
        cp = self._cp_fn() if self._cp_fn is not None else None
        self._value = policy_from_store(self._store, cp)
      except Exception:
        self._value = CLOSED_POLICY
    return self._value


def read_dashboard_limit(sm, now: float, drive_start: float) -> float | None:
  """frogpilotCarState.dashboardSpeedLimit in m/s; 0.0 = valid "no limit"; None = absent, stale, invalid or bogus."""
  name = "frogpilotCarState"
  try:
    if sm is None or name not in sm.data:
      return None
    t = sm.recv_time[name]
    if not (sm.alive[name] and sm.valid[name] and t >= drive_start and 0.0 <= now - t <= LIMIT_STALE_S):
      return None
    v = float(sm[name].dashboardSpeedLimit)
  except (AttributeError, KeyError, TypeError, ValueError):
    return None
  if not math.isfinite(v) or v < 0.0 or v > MAX_LIMIT_MS:
    return None
  return v if v >= MIN_LIMIT_MS else 0.0


def format_offset(offset_display: float) -> str:
  """Daily speedLimitOffsetStr, with one sign: "+5" / "-5"; "" when it rounds to 0."""
  n = int(round(offset_display))
  if n == 0:
    return ""
  return f"+{n}" if n > 0 else f"-{abs(n)}"


@dataclass(frozen=True)
class SpeedLimitView:
  show_limit: bool = False
  vienna: bool = False
  limit: str = NO_LIMIT
  offset: str = ""
  limit_opacity: float = 1.0
  color_limit: float = 0.0       # display units; the limit the set-speed colour compares against (0 = none)
  source: str = "none"           # "slc" (real frogpilotPlan SLC), "dashboard" (frogpilotCarState), "none"

  def fields(self) -> dict:
    """Keyword arguments for redesign.SpeedRowInputs."""
    return {"show_limit": self.show_limit, "vienna": self.vienna, "limit": self.limit, "offset": self.offset,
            "limit_opacity": self.limit_opacity}


HIDDEN = SpeedLimitView()


def speed_limit_view(policy: LimitPolicy, dashboard_ms: float | None, plan, display_conv: float) -> SpeedLimitView:
  """`plan` is a cluster_layout.CscStatus (valid=False when absent/stale). `display_conv` m/s -> display units."""
  if not policy.slc_limits or not math.isfinite(display_conv) or display_conv <= 0:
    return HIDDEN   # daily falls back to the navigation limit here; C3X has no navigation source
  plan_ok = bool(getattr(plan, "valid", False))
  changed = plan_ok and bool(plan.speed_limit_changed)
  if policy.hide_speed_limit and not changed:
    return HIDDEN
  overridden_ms = float(plan.slc_overridden_speed) if plan_ok else 0.0
  slc_ms = float(plan.slc_speed_limit) if plan_ok else 0.0
  offset_ms = float(plan.slc_speed_limit_offset) if plan_ok else 0.0
  if not all(math.isfinite(x) for x in (overridden_ms, slc_ms, offset_ms)):
    overridden_ms = slc_ms = offset_ms = 0.0
  if slc_ms >= MIN_LIMIT_MS:
    posted_ms, source = slc_ms, "slc"
  elif dashboard_ms is not None and dashboard_ms >= MIN_LIMIT_MS:
    posted_ms, source, offset_ms = dashboard_ms, "dashboard", 0.0   # no SLC: nothing is added to the posted limit
  else:
    posted_ms, source, offset_ms = 0.0, "none", 0.0

  overridden = overridden_ms != 0.0
  if overridden:
    shown = overridden_ms * display_conv
    limit = str(int(round(shown))) if shown > 1 else NO_LIMIT
    offset = ""
    color_limit = shown
  else:
    posted = posted_ms * display_conv
    limit = str(int(round(posted))) if posted > 1 else NO_LIMIT
    offset = format_offset(offset_ms * display_conv) if (posted > 1 and source == "slc") else ""
    # annotated_camera.cc:129-131: the offset is added to the comparison limit unless ShowSLCOffset is on
    color_limit = posted + (0.0 if policy.show_speed_limit_offset else offset_ms * display_conv) if posted > 1 else 0.0
  return SpeedLimitView(show_limit=True, vienna=policy.vienna, limit=limit, offset=offset,
                        limit_opacity=0.25 if overridden else 1.0, color_limit=color_limit, source=source)


def _lerp(a, b, t):
  return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(4))


def interp_color(x: float, xs: tuple[float, float, float], cs) -> tuple[int, int, int, int]:
  """Qt interpColor: clamp below the first / above the last stop, linear in between."""
  if x <= xs[0]:
    return cs[0]
  for i in range(1, len(xs)):
    if x <= xs[i]:
      return _lerp(cs[i - 1], cs[i], (x - xs[i - 1]) / (xs[i] - xs[i - 1]))
  return cs[-1]


def set_speed_rgba(cruise_set: bool, engaged_not_override: bool, set_speed_display: float, color_limit: float):
  """Daily redesign set-speed colour (annotated_camera.cc:253-260)."""
  if not cruise_set:
    return GREY
  if engaged_not_override and color_limit > 0 and math.isfinite(set_speed_display):
    L = color_limit
    return interp_color(set_speed_display, (L + 5, L + 15, L + 25), (WHITE, ORANGE, RED))
  return WHITE
