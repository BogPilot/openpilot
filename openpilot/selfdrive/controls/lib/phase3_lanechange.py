"""Native lane-change policies ported from own 0.9.7 bogpilot-tesla 04d560f3.

No CAN commands, steering gains, panda flags, or persistent writes here. Integration
is explicit: DesireHelper consumes LaneChangePolicy; RadarD consumes the existing
adjacent-radar producer through human_lane_change_track BEFORE its AP1 filter.

Activation (same rule as gasFollowSpeed Phase3*Enabled): Lane Changes / Human /
TurnDesires consumers stay stock-equivalent until the user changes a row in the
matching panel (configure() writes an adoption marker). Saved bench prefs such as
NudgelessLaneChange=1 / HumanLaneChanges=1 never wake on first boot. Markers are
never rewritten by reads; sysUtilities reset must clear them (see ACK constants).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time

import numpy as np

MPH_TO_MS = 0.44704
STOCK_MIN_SPEED = 20 * MPH_TO_MS

# Adoption markers — report these to INT/sysUtilities for reset clearing.
LANE_CHANGE_ACK = "Phase3LaneChangeEnabled"
HUMAN_LANE_CHANGES_ACK = "Phase3HumanLaneChangesEnabled"
TURN_DESIRES_ACK = "Phase3TurnDesiresEnabled"
LANE_CHANGE_KEYS = (
  "LaneChanges", "NudgelessLaneChange", "LaneChangeTime",
  "MinimumLaneChangeSpeed", "LaneDetectionWidth", "OneLaneChange",
)
HUMAN_LANE_CHANGES_KEYS = ("HumanLaneChanges",)
TURN_DESIRES_KEYS = ("TurnDesires",)
ADOPTION_MARKERS = (LANE_CHANGE_ACK, HUMAN_LANE_CHANGES_ACK, TURN_DESIRES_ACK)


def _ack_for(key: str) -> str:
  if key in LANE_CHANGE_KEYS:
    return LANE_CHANGE_ACK
  if key in HUMAN_LANE_CHANGES_KEYS:
    return HUMAN_LANE_CHANGES_ACK
  if key in TURN_DESIRES_KEYS:
    return TURN_DESIRES_ACK
  raise ValueError(key)


def _adopted(store, ack: str) -> bool:
  """Fail closed (False) on any read problem."""
  try:
    return bool(store.get_bool(ack, False))
  except Exception:
    return False


def lane_change_adopted(store) -> bool:
  return _adopted(store, LANE_CHANGE_ACK)


def human_lane_changes_adopted(store) -> bool:
  return _adopted(store, HUMAN_LANE_CHANGES_ACK)


def turn_desires_adopted(store) -> bool:
  return _adopted(store, TURN_DESIRES_ACK)


def configure(store, key, value) -> None:
  """Only from an explicit panel action: write the user's value and adopt its group.

  Never rewrites other saved preferences. Does not seed defaults.
  """
  ack = _ack_for(key)
  if isinstance(value, bool):
    store.put_bool(key, value)
  else:
    store.put(key, value)
  store.put_bool(ack, True)
  if hasattr(store, "invalidate"):
    store.invalidate()


@dataclass(frozen=True)
class LaneChangeSettings:
  enabled: bool = True
  nudgeless: bool = False
  delay: float = 1.0
  minimum_speed: float = STOCK_MIN_SPEED
  minimum_width: float = 0.0
  one_per_signal: bool = False  # stock-equivalent until adopted (registry OneLaneChange=1 stays dormant)
  human: bool = False
  turn_desires: bool = False


def read_settings(store, CP=None) -> LaneChangeSettings:
  """Read only; never seed defaults or rewrite a saved preference.

  Without the matching Phase3*Enabled marker, saved ON prefs stay dormant and the
  runtime keeps the stock-equivalent path (manual torque LC, no nudgeless, no
  Human lead substitution, no TurnDesires). Runtime keeps the stock 20mph floor.
  """
  level = store.tuning_level()
  invalid_number = False

  def val(key, default, fallback=None):
    if not store.honoured(key, level):
      return default if fallback is None else fallback
    raw = store.raw(key)
    return default if raw is None or raw == "" else raw

  def boolean(key, default, fallback=False):
    return str(val(key, int(default), int(fallback))).strip().lower() in ("1", "true", "yes", "on")

  def number(key, default, low, high, fallback):
    nonlocal invalid_number
    try:
      x = float(val(key, default, fallback))
      if math.isfinite(x) and low <= x <= high:
        return x
      invalid_number = True
      return default
    except (ValueError, TypeError):
      invalid_number = True
      return default

  metric = store.get_bool("IsMetric", False)
  speed_unit, width_unit = (1 / 3.6, 1.0) if metric else (MPH_TO_MS, 0.3048)
  has_radar = CP is not None and not CP.radarUnavailable
  has_long = CP is not None and CP.openpilotLongitudinalControl and not store.get_bool("DisableOpenpilotLongitudinal", False)

  if lane_change_adopted(store):
    enabled = boolean("LaneChanges", True, True)
    minimum = number("MinimumLaneChangeSpeed", STOCK_MIN_SPEED / speed_unit, 0, 150 if metric else 99, STOCK_MIN_SPEED / speed_unit) * speed_unit
    delay = number("LaneChangeTime", 1.0, 0, 5, 0)
    width = number("LaneDetectionWidth", 0.0, 0, 5 if metric else 15, 0) * width_unit
    nudgeless = enabled and not invalid_number and boolean("NudgelessLaneChange", False)
    one_per_signal = enabled and boolean("OneLaneChange", True)
  else:
    # Dormant panel: stock torque LC remains available; nudgeless/one-per-signal stay OFF.
    enabled, nudgeless, one_per_signal = True, False, False
    delay, width, minimum = 1.0, 0.0, STOCK_MIN_SPEED

  human = False
  if human_lane_changes_adopted(store):
    human = bool(has_radar and has_long and boolean("LongitudinalTune", True) and boolean("HumanLaneChanges", True))

  turn_desires = False
  if turn_desires_adopted(store):
    turn_desires = not invalid_number and boolean("LateralTune", True) and boolean("TurnDesires", False)

  return LaneChangeSettings(
    enabled=enabled,
    turn_desires=turn_desires,
    nudgeless=nudgeless,
    delay=delay,
    minimum_speed=max(STOCK_MIN_SPEED, minimum),
    minimum_width=width,
    one_per_signal=one_per_signal,
    human=human,
  )


class LaneChangeSettingsReader:
  """At most 2 seconds between refreshes, stock-equivalent fallback on read failure."""

  def __init__(self, store=None, CP=None):
    self.store, self.CP = store, CP
    self.settings = LaneChangeSettings()
    self.last_refresh = -math.inf

  def read(self, now=None):
    now = time.monotonic() if now is None else now
    if now - self.last_refresh >= 2.0:
      self.last_refresh = now
      try:
        if self.store is None:
          from openpilot.common.bogpilot_store import ParamStore

          self.store = ParamStore()
        self.store.invalidate()
        self.settings = read_settings(self.store, self.CP)
      except Exception:
        # Do not retain an enabled automatic/human policy after an unreadable store.
        self.settings = LaneChangeSettings()
    return self.settings


def bsm_side_occupied(cs, left: bool) -> bool:
  """True when the target side must block a lane change.

  Occupied OR unknown. Prefer explicit *BlindspotValid attrs when present; if
  validity is absent, treat as unknown → occupied (fail closed). carstate that
  uses Ap1Blindspot already encodes SNA/stale/invalid as left/rightBlindspot=True.
  """
  flag = bool(cs.leftBlindspot if left else cs.rightBlindspot)
  valid_attr = "leftBlindspotValid" if left else "rightBlindspotValid"
  if hasattr(cs, valid_attr):
    try:
      valid = bool(getattr(cs, valid_attr))
    except Exception:
      valid = False
    return flag or not valid
  # No validity publisher: Blindspot flag alone. Ap1Blindspot fail-closed encoding
  # makes False mean "recent clear NO_WARNING only".
  return flag


def _line(line):
  x, y = np.asarray(line.x), np.asarray(line.y)
  if len(x) < 2 or len(x) != len(y) or not np.isfinite(x).all() or not np.isfinite(y).all() or not (np.diff(x) > 0).all():
    raise ValueError("invalid model geometry")
  return x, y


def adjacent_lane_width(model, left):
  """04d560f3 calculate_lane_width: median line distance; closer road edge veto.

  Invalid/empty/nonfinite geometry is unavailable, never interpreted as a wide lane.
  """
  try:
    outer, inner = (0, 1) if left else (3, 2)
    x, y = _line(model.laneLines[inner])
    ox, oy = _line(model.laneLines[outer])
    ex, ey = _line(model.roadEdges[0 if left else 1])
    lane = float(np.median(np.abs(y - np.interp(x, ox, oy))))
    edge = float(np.median(np.abs(y - np.interp(x, ex, ey))))
    return lane if edge >= lane else 0.0
  except (AttributeError, IndexError, TypeError, ValueError):
    return None


class LaneChangePolicy:
  """Extra intent gates; leaves the stock DesireHelper state/timing in charge."""

  def __init__(self):
    self.wait = 0.0
    self.completed = False
    self.previous_signal = 0
    self.armed = False

  def observe(self, cs, lateral_active, pre_lane_change, settings, model=None, model_valid=False, dt=0.05):
    signal = (1 if cs.leftBlinker else 0) - (1 if cs.rightBlinker else 0)
    one = cs.leftBlinker != cs.rightBlinker
    if not cs.leftBlinker and not cs.rightBlinker:
      self.completed = False
    if not lateral_active or not settings.enabled or not one:
      self.armed = False
      self.wait = 0.0
    elif signal != self.previous_signal:
      # Requires a new explicit signal after disengagement/hazards or direction change.
      self.armed = self.previous_signal == 0
      self.wait = 0.0
    if signal != self.previous_signal:
      self.wait = 0.0
    self.previous_signal = signal if one else (2 if cs.leftBlinker else 0)
    blocked = bsm_side_occupied(cs, left=(signal == 1)) if signal != 0 else True
    torque = cs.steeringTorque
    opposed = cs.steeringPressed and (not math.isfinite(torque) or torque * signal <= 0)
    width = adjacent_lane_width(model, signal == 1) if settings.minimum_width > 0 else 0.0
    lane_available = settings.minimum_width == 0 or (width is not None and width >= settings.minimum_width)
    safe = (
      lateral_active
      and settings.enabled
      and one
      and not cs.standstill
      and math.isfinite(cs.vEgo)
      and cs.vEgo >= settings.minimum_speed
      and not blocked
      and not opposed
      and model_valid
      and lane_available
    )
    if not pre_lane_change or not safe or not self.armed:
      self.wait = 0.0
    else:
      self.wait += dt
    return bool(safe and pre_lane_change and self.armed and settings.nudgeless and not self.completed and self.wait + 1e-9 >= settings.delay)

  def started(self, settings):
    self.completed = settings.one_per_signal
    self.wait = 0.0


def human_lane_change_track(tracks, model, exclude_ids=(), *, enabled=False, valid=False):
  """Real adjacent producer -> RadarD lead-matching consumer, not a UI-box toggle.

  04d560f3 preferred nearest target-lane track during laneChangeStarting. This
  adapter does not grant lane-change permission or use radar as blindspot-clear.
  On invalid data/absence/disabled it returns None: caller retains normal matching.
  The caller must retain its >.5 vision gate, low-speed override and AP1 filter,
  and must NOT substitute leadOne unless adoption+valid already set enabled=True.
  """
  if not enabled or not valid:
    return None
  from openpilot.cereal import log
  from openpilot.selfdrive.controls.lib.bogpilot_radar import get_adjacent_lead

  try:
    if model.meta.laneChangeState != log.LaneChangeState.laneChangeStarting:
      return None
    direction = model.meta.laneChangeDirection
    if direction not in (log.LaneChangeDirection.left, log.LaneChangeDirection.right):
      return None
    # The display producer is not itself a safety validation boundary.
    if len(model.laneLines) != 4 or len(model.position.x) < 2 or not np.isfinite(model.position.x).all():
      return None
    for line in model.laneLines:
      _line(line)
    candidate = get_adjacent_lead(tracks, model, direction == log.LaneChangeDirection.left, exclude_ids)
    if not candidate.get("status", False):
      return None
    tid = candidate.get("radarTrackId", -1)
    if tid not in tracks:
      return None
    values = [candidate.get(k, math.nan) for k in ("dRel", "yRel", "vRel", "vLead", "vLeadK", "aLeadK", "aLeadTau")]
    if not all(math.isfinite(v) for v in values) or values[0] <= 0 or values[4] < 1 or values[6] <= 0:
      return None
    return tracks[tid]
  except (AttributeError, IndexError, TypeError, ValueError, KeyError):
    return None


def valid_vision_lead(lead):
  """Never invent target tracking from an absent/malformed/low-confidence lead."""
  try:
    if not math.isfinite(lead.prob) or lead.prob <= 0.5:
      return False
    return all(len(getattr(lead, name)) and np.isfinite(getattr(lead, name)).all() for name in ("x", "y", "v", "xStd", "yStd", "vStd"))
  except (AttributeError, TypeError, ValueError):
    return False
