"""BogPilot cluster layout: top-left stack order, accel graph and the CSC MAX slot.

Pure Python (no pyray, cereal or Params) so it is testable headless. Mirrors the C3 Qt bogpilot_cluster.h contract.

Stack (shared footprint y 24..468, design coordinates):
  LowerSpeedLimitsBox OFF (shipping default): speed capsule y 24..200; if the accel graph is on, it sits at y 228..468.
  LowerSpeedLimitsBox ON:                     speed capsule y 292..468 (the old slot below the accel graph, for a
                                              rear-view mirror that covers the top of the screen); if the graph is on,
                                              it sits at y 24..264.
  ShowAccelGraph OFF (shipping default): the graph is not painted. The capsule follows LowerSpeedLimitsBox only.
  ShowAccelGraph ON: the graph occupies the slot the capsule is not using.

CSC: with the redesign on, CSC status lives in the capsule's MAX slot. Status must come from a validated, fresh
planner message (bogpilotPlan). Nothing here infers CSC from stock fields such as curvature.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

EDGE = 30
SPEED_ROW_TOP = 24
SPEED_ROW_HEIGHT = 176
SPEED_ROW_MIN_RIGHT = 740
GRAPH_TOP = 228
GRAPH_WIDTH = 560
GRAPH_HEIGHT = 240
STACK_BOTTOM = GRAPH_TOP + GRAPH_HEIGHT              # 468
SWAP_GRAPH_TOP = SPEED_ROW_TOP                        # 24
SWAP_SPEED_ROW_TOP = STACK_BOTTOM - SPEED_ROW_HEIGHT  # 292

SHOW_ACCEL_GRAPH_KEY = "ShowAccelGraph"
LOWER_SPEED_LIMITS_BOX_KEY = "LowerSpeedLimitsBox"
DEFAULTS = {SHOW_ACCEL_GRAPH_KEY: False, LOWER_SPEED_LIMITS_BOX_KEY: False}

# Settings copy. Lower Speed Limits Box is a Minimal (0) Appearance row; Show Accel Graph is a Developer (3) row.
TOGGLE_METADATA = {
  SHOW_ACCEL_GRAPH_KEY: {
    "title": "Show Accel Graph", "default": False, "tuning_level": 3,
    "description": "Show the acceleration request graph on the driving screen. It can slow UI draw time, so it lives "
                   "under Developer and is off by default. Display only. Takes effect on the driving screen within 2 seconds.",
  },
  LOWER_SPEED_LIMITS_BOX_KEY: {
    "title": "Lower Speed Limits Box", "default": False, "tuning_level": 0,
    "description": "Lower speed limits box (if obstructed by rear view mirror). Moves the top-left speed row "
                   "(MAX, speed, and the LIMIT tile) down to the slot below where the accel graph sits. Display only. "
                   "Takes effect within 2 seconds.",
  },
}

CSC_STALE_S = 0.5   # bogpilotPlan publishes at 20 Hz


@dataclass(frozen=True)
class ClusterLayout:
  show_accel: bool = False
  lower_speed_box: bool = False
  graph_suppressed: bool = False   # e.g. full-screen map; the capsule does not move

  @property
  def capsule_lower(self) -> bool:
    return self.lower_speed_box

  @property
  def graph_visible(self) -> bool:
    return self.show_accel and not self.graph_suppressed

  @property
  def capsule_top(self) -> int:
    return SWAP_SPEED_ROW_TOP if self.capsule_lower else SPEED_ROW_TOP

  @property
  def graph_top(self) -> int:
    return SWAP_GRAPH_TOP if self.capsule_lower else GRAPH_TOP

  @property
  def swap(self) -> bool:
    """True when the capsule is in the lower slot (graph, if shown, sits on top). Used by accel_graph_rect."""
    return self.capsule_lower

  def graph_rect(self) -> tuple[float, float, float, float] | None:
    """(x, y, w, h), or None when the graph is not painted (never a keepout or anchor then)."""
    return (EDGE, self.graph_top, GRAPH_WIDTH, GRAPH_HEIGHT) if self.graph_visible else None

  def capsule_band(self) -> tuple[float, float, float, float]:
    return (EDGE, self.capsule_top, SPEED_ROW_MIN_RIGHT - EDGE, SPEED_ROW_HEIGHT)

  @property
  def redesign_swap(self) -> bool:
    """Value for redesign.SpeedRowInputs.swap / max_slot_rect(swap): True puts the capsule in the lower slot."""
    return self.capsule_lower

  def keepouts(self) -> list[tuple[float, float, float, float]]:
    out = [self.capsule_band()]
    g = self.graph_rect()
    if g is not None:
      out.append(g)
    return out


def layout_from_toggles(get, graph_suppressed: bool = False) -> ClusterLayout:
  return ClusterLayout(show_accel=bool(get(SHOW_ACCEL_GRAPH_KEY)),
                       lower_speed_box=bool(get(LOWER_SPEED_LIMITS_BOX_KEY)),
                       graph_suppressed=graph_suppressed)


# ---- CSC MAX slot ----
@dataclass(frozen=True)
class CscStatus:
  """Validated planner CSC report in m/s. valid=False when absent, stale, invalid, previous-drive or non-finite."""
  valid: bool = False
  training: bool = False
  controlling: bool = False
  csc_speed: float = 0.0
  road_curvature: float = 0.0
  slc_overridden_speed: float = 0.0
  slc_speed_limit: float = 0.0
  slc_speed_limit_offset: float = 0.0
  speed_limit_changed: bool = False


INVALID_CSC = CscStatus()
_NUMERIC = ("csc_speed", "road_curvature", "slc_overridden_speed", "slc_speed_limit", "slc_speed_limit_offset")


def _finite(s: CscStatus) -> bool:
  return all(isinstance(getattr(s, f), (int, float)) and math.isfinite(getattr(s, f)) for f in _NUMERIC)


def csc_status_from_plan(plan) -> CscStatus:
  """Read a bogpilotPlan reader (or any object with the same attribute names). Missing fields fail closed.

  The message valid bit is also set for speed limit control, CEM and force stop, so CSC itself must report cscActive."""
  try:
    if not bool(plan.cscActive):
      return INVALID_CSC
    s = CscStatus(valid=True, training=bool(plan.cscTraining), controlling=bool(plan.cscControllingSpeed),
                  csc_speed=float(plan.cscSpeed), road_curvature=float(plan.roadCurvature),
                  slc_overridden_speed=float(plan.slcOverriddenSpeed), slc_speed_limit=float(plan.slcSpeedLimit),
                  slc_speed_limit_offset=float(plan.slcSpeedLimitOffset), speed_limit_changed=bool(plan.speedLimitChanged))
  except (AttributeError, TypeError, ValueError):
    return INVALID_CSC
  return s if _finite(s) else INVALID_CSC


def read_csc_status(sm, now: float, drive_start: float) -> CscStatus:
  """Fresh (<= CSC_STALE_S), valid, current-drive bogpilotPlan only, from a SubMaster that subscribes it.

  Stock release-tizi has no such service, so callers never build that SubMaster and this stays invalid.
  `now` / `drive_start` use the SubMaster's clock (time.monotonic)."""
  try:
    if "bogpilotPlan" not in sm.data:
      return INVALID_CSC
    t = sm.recv_time["bogpilotPlan"]
    if not (sm.alive["bogpilotPlan"] and sm.valid["bogpilotPlan"] and t >= drive_start and now - t <= CSC_STALE_S):
      return INVALID_CSC
    return csc_status_from_plan(sm["bogpilotPlan"])
  except (AttributeError, KeyError, TypeError):
    return INVALID_CSC


@dataclass(frozen=True)
class CscContext:
  redesign: bool = True
  show_status: bool = True          # ShowCSCStatus gate (its tuning-level visibility is set in the shipping defaults)
  map_open: bool = False
  static_left_signal: bool = False
  cruise_set: bool = False
  slc_limits: bool = False
  set_speed_display: float = 0.0
  display_conv: float = 2.23694     # m/s -> display units
  t: float = 0.0                    # monotonic seconds, for the training pulse


@dataclass(frozen=True)
class CscSlot:
  active: bool = False
  training: bool = False
  left: bool = True
  speed: str = ""
  from_speed: int | None = None     # "from N"; None = hidden
  pulse: float = 0.0


def csc_slot(s: CscStatus, c: CscContext) -> CscSlot:
  if (not s.valid or not _finite(s) or not c.redesign or not c.show_status or c.map_open or s.speed_limit_changed
      or c.static_left_signal or not math.isfinite(c.set_speed_display)):
    return CscSlot()
  left = s.road_curvature < 0
  if s.training:
    pulse = 0.5 + 0.5 * math.sin(math.fmod(c.t, 2.0) / 2.0 * 2 * math.pi)
    return CscSlot(training=True, left=left, pulse=pulse)
  if not c.cruise_set or not s.controlling or s.csc_speed < 0:
    return CscSlot(left=left)
  n = c.set_speed_display
  if s.slc_overridden_speed > 0:
    n = s.slc_overridden_speed * c.display_conv
  elif c.slc_limits and s.slc_speed_limit > 0:
    n = (s.slc_speed_limit + s.slc_speed_limit_offset) * c.display_conv
  n_shown = round(n)
  target = round(min(n, s.csc_speed * c.display_conv))
  return CscSlot(active=True, left=left, speed=str(target), from_speed=None if target == n_shown else n_shown)


def csc_fields(slot: CscSlot, tr=lambda s: s) -> dict:
  """Keyword arguments for the existing redesign.SpeedRowInputs MAX-slot fields."""
  if slot.training:
    label = tr("training")
  elif slot.from_speed is not None:
    label = tr("from {}").format(slot.from_speed)
  else:
    label = ""
  return {"csc_active": slot.active, "csc_training": slot.training, "csc_left": slot.left,
          "csc_speed": slot.speed, "csc_label": label, "csc_pulse": slot.pulse}
