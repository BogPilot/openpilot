"""BogPilot cluster layout (stream 8): top-left stack order, hide-accel and the CSC MAX slot.

Pure Python (no pyray, cereal or Params) so it is testable headless. Mirrors the C3 Qt bogpilot_cluster.h contract.

Stack (shared footprint y 24..468, design coordinates):
  SwapSpeedGraph ON  (shipping default): accel graph y 24..264, speed capsule y 292..468.
  SwapSpeedGraph OFF:                     speed capsule y 24..200, accel graph y 228..468.
  HideAccelGraph ON: the graph is not painted and the capsule always sits in the LOWER slot (y 292..468), so a
  high-mounted comma or a mirror covering the top of the screen still leaves the speed row readable.

CSC: with the redesign on, CSC status lives in the capsule's MAX slot. Status must come from a validated, fresh
planner message (frogpilotPlan, stream-6 schema). Nothing here infers CSC from stock fields such as curvature.
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

SWAP_SPEED_GRAPH_KEY = "SwapSpeedGraph"
HIDE_ACCEL_GRAPH_KEY = "HideAccelGraph"
DEFAULTS = {SWAP_SPEED_GRAPH_KEY: True, HIDE_ACCEL_GRAPH_KEY: False}

# Settings copy for streams 5/6 (approved accel layout toggles are visible from the Minimal tuning level = 0).
TOGGLE_METADATA = {
  SWAP_SPEED_GRAPH_KEY: {
    "title": "Accel Graph on Top", "default": True, "tuning_level": 0,
    "description": "Swap the top-left stack: the acceleration request graph sits on top and the speed row "
                   "(MAX, speed, limit) sits below it. Display only. Takes effect on the driving screen within 2 seconds.",
  },
  HIDE_ACCEL_GRAPH_KEY: {
    "title": "Hide Accel Graph", "default": False, "tuning_level": 0,
    "description": "Hide the acceleration graph and keep the speed row in the lower slot, for a high-mounted comma or "
                   "when the mirror covers the top of the screen. Display only. Takes effect within 2 seconds.",
  },
}

CSC_STALE_S = 0.5   # frogpilotPlan publishes at 20 Hz


@dataclass(frozen=True)
class ClusterLayout:
  swap: bool = True
  hide_accel: bool = False
  graph_suppressed: bool = False   # e.g. full-screen map; the capsule does not move

  @property
  def capsule_lower(self) -> bool:
    return self.swap or self.hide_accel

  @property
  def graph_visible(self) -> bool:
    return not self.hide_accel and not self.graph_suppressed

  @property
  def capsule_top(self) -> int:
    return SWAP_SPEED_ROW_TOP if self.capsule_lower else SPEED_ROW_TOP

  @property
  def graph_top(self) -> int:
    return SWAP_GRAPH_TOP if self.swap else GRAPH_TOP

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
  return ClusterLayout(swap=bool(get(SWAP_SPEED_GRAPH_KEY)), hide_accel=bool(get(HIDE_ACCEL_GRAPH_KEY)),
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
  """Read a frogpilotPlan reader (or any object with the same attribute names). Missing fields fail closed."""
  try:
    s = CscStatus(valid=True, training=bool(plan.cscTraining), controlling=bool(plan.cscControllingSpeed),
                  csc_speed=float(plan.cscSpeed), road_curvature=float(plan.roadCurvature),
                  slc_overridden_speed=float(plan.slcOverriddenSpeed), slc_speed_limit=float(plan.slcSpeedLimit),
                  slc_speed_limit_offset=float(plan.slcSpeedLimitOffset), speed_limit_changed=bool(plan.speedLimitChanged))
  except (AttributeError, TypeError, ValueError):
    return INVALID_CSC
  return s if _finite(s) else INVALID_CSC


def read_csc_status(sm, now: float, drive_start: float) -> CscStatus:
  """Fresh (<= CSC_STALE_S), valid, current-drive frogpilotPlan only, from a SubMaster that subscribes it.

  Stock release-tizi has no such service, so callers never build that SubMaster and this stays invalid.
  `now` / `drive_start` use the SubMaster's clock (time.monotonic)."""
  try:
    if "frogpilotPlan" not in sm.data:
      return INVALID_CSC
    t = sm.recv_time["frogpilotPlan"]
    if not (sm.alive["frogpilotPlan"] and sm.valid["frogpilotPlan"] and t >= drive_start and now - t <= CSC_STALE_S):
      return INVALID_CSC
    return csc_status_from_plan(sm["frogpilotPlan"])
  except (AttributeError, KeyError, TypeError):
    return INVALID_CSC


@dataclass(frozen=True)
class CscContext:
  redesign: bool = True
  show_status: bool = True          # ShowCSCStatus gate (stream 5 owns its tuning-level visibility)
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
