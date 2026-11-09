"""Native raylib Lane Changes leaf; no central menu is registered by importing.

Primary must install the runtime patches before opting in with runtime_integrated.
HumanLaneChanges remains in its authentic Gas / Brake > Longitudinal Tuning path;
it is exported for that lane, not silently moved into Steering.

Panel writes go through configure() so Phase3*Enabled adoption markers are set;
saved preferences are never rewritten by reads. Until adopted, toggles display OFF
(except LaneChanges shows stock-available ON) so the UI never lies about runtime.
"""

from __future__ import annotations

from openpilot.selfdrive.controls.lib.phase3_lanechange import (
  HUMAN_LANE_CHANGES_ACK,
  LANE_CHANGE_ACK,
  LANE_CHANGE_KEYS,
  TURN_DESIRES_ACK,
  configure,
  human_lane_changes_adopted,
  lane_change_adopted,
  read_settings,
  turn_desires_adopted,
)

PANEL_PATH = ("BogPilot", "Driving Controls", "Steering", "Lane Changes")
HUMAN_PATH = ("BogPilot", "Driving Controls", "Gas / Brake", "Longitudinal Tuning")
# key, title, kind, parent, min, max, step. Numeric units follow IsMetric.
ROWS = (
  ("LaneChanges", "Lane Changes", "toggle", None, None, None, None),
  ("NudgelessLaneChange", "Automatic Lane Changes", "toggle", "LaneChanges", None, None, None),
  ("LaneChangeTime", "Lane Change Delay", "number", "NudgelessLaneChange", 0, 5, 0.1),
  ("MinimumLaneChangeSpeed", "Minimum Lane Change Speed", "number", "LaneChanges", 0, 99, 1),
  ("LaneDetectionWidth", "Minimum Lane Width", "number", "NudgelessLaneChange", 0, 15, 0.1),
  ("OneLaneChange", "One Lane Change Per Signal", "toggle", "LaneChanges", None, None, None),
)
HUMAN_ROW = ("HumanLaneChanges", "Human-Like Lane Changes", "toggle", "LongitudinalTune", None, None, None)
DESCRIPTIONS = {
  "LaneChanges": "Allow openpilot to change lanes.",
  "NudgelessLaneChange": "Change lanes on turn signal without a steering-wheel nudge. Off until you change a row here; blindspot SNA/stale/invalid blocks the move.",
  "LaneChangeTime": "Delay between turn signal activation and the start of an automatic lane change.",
  "MinimumLaneChangeSpeed": "Lowest lane-change speed. The runtime retains a minimum safety floor of 20 mph (32.2 km/h).",
  "LaneDetectionWidth": "Prevent automatic lane changes into lanes narrower than the set width. Zero disables this additional width check.",
  "OneLaneChange": "Limit lane changes to one per turn-signal activation.",
  "HumanLaneChanges": "Anticipate and track adjacent vehicles during lane changes. Requires radar and openpilot longitudinal control. Off until you change this row.",
}


def display_bool(store, key: str) -> bool:
  """Panel display: dormant groups show OFF so saved ON prefs are not implied active."""
  if key == "LaneChanges" and not lane_change_adopted(store):
    return True  # stock torque LC remains available
  if key in LANE_CHANGE_KEYS and not lane_change_adopted(store):
    return False
  if key == "HumanLaneChanges" and not human_lane_changes_adopted(store):
    return False
  if key == "TurnDesires" and not turn_desires_adopted(store):
    return False
  return store.get_bool(key, key in ("LaneChanges", "OneLaneChange"))


def visible_rows(store, *, runtime_integrated=False):
  if not runtime_integrated:
    return ()
  cfg = read_settings(store)
  out = []
  for row in ROWS:
    key, _, _, parent, *_ = row
    if not store.honoured(key, store.tuning_level()):
      continue
    if parent and not cfg.enabled:
      continue
    if parent == "NudgelessLaneChange" and not cfg.nudgeless:
      continue
    out.append(row)
  return tuple(out)


def numeric_bounds(row, metric):
  key, _, _, _, low, high, step = row
  if metric:
    high = {"MinimumLaneChangeSpeed": 150, "LaneDetectionWidth": 5}.get(key, high)
  return low, high, step


class LaneChangeLayout:
  def __new__(cls, store=None, *, runtime_integrated=False, offroad=None):
    if not runtime_integrated:
      raise RuntimeError("Lane-change consumers must be integrated before exposing controls")
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.system.ui.widgets import Widget
    from openpilot.system.ui.widgets.list_view import toggle_item, multiple_button_item
    from openpilot.system.ui.widgets.scroller_tici import Scroller
    from openpilot.system.ui.lib.multilang import tr

    class _Layout(Widget):
      def __init__(self):
        super().__init__()
        self.store = store if store is not None else ParamStore()
        self._build()

      def _editable(self):
        # No private calibration/capability assumptions: primary supplies offroad.
        return offroad is not None and offroad()

      def _build(self):
        items = []
        for row in visible_rows(self.store, runtime_integrated=True):
          key, title, kind, *_ = row
          desc = DESCRIPTIONS[key]
          if kind == "toggle":
            item = toggle_item(
              lambda t=title: tr(t),
              lambda d=desc: tr(d),
              display_bool(self.store, key),
              callback=lambda state, k=key: self._toggle(k, state),
              enabled=self._editable,
            )
          else:
            item = multiple_button_item(
              lambda t=title, k=key: tr(t) + f" ({self.store.get_float(k):g})",
              lambda d=desc: tr(d),
              ["-", "+"],
              0,
              callback=lambda index, r=row: self._step(r, index),
            )
          items.append(item)
        self.scroller = Scroller(items, line_separator=True, spacing=0)

      def _toggle(self, key, state):
        if self._editable():
          configure(self.store, key, bool(state))
          self._build()
          self.scroller.show_event()

      def _step(self, row, index):
        if self._editable():
          low, high, step = numeric_bounds(row, self.store.get_bool("IsMetric", False))
          key = row[0]
          value = self.store.get_float(key)
          configure(self.store, key, str(round(max(low, min(high, value + (-step if index == 0 else step))), 1)))

      def show_event(self):
        super().show_event()
        self.store.invalidate()
        self._build()
        self.scroller.show_event()

      def _render(self, rect):
        self.scroller.render(rect)

    return _Layout()


def human_row_available(store, CP=None, *, runtime_integrated=False):
  """Hardware/parent eligibility, independent of the current child ON/OFF value."""
  if not runtime_integrated or CP is None:
    return False
  level = store.tuning_level()
  return bool(
    not CP.radarUnavailable
    and CP.openpilotLongitudinalControl
    and not store.get_bool("DisableOpenpilotLongitudinal", False)
    and store.honoured("HumanLaneChanges", level)
    and store.honoured("LongitudinalTune", level)
    and store.get_bool("LongitudinalTune", True)
  )


def human_lane_change_item(store, CP=None, *, runtime_integrated=False, offroad=None):
  """Native Gas/Brake child, never registered or offered before its consumer exists."""
  if not human_row_available(store, CP, runtime_integrated=runtime_integrated):
    return None
  from openpilot.system.ui.widgets.list_view import toggle_item
  from openpilot.system.ui.lib.multilang import tr

  def editable():
    return offroad is not None and offroad()

  def write(state):
    if editable():
      configure(store, "HumanLaneChanges", bool(state))

  return toggle_item(
    lambda: tr(HUMAN_ROW[1]),
    lambda: tr(DESCRIPTIONS["HumanLaneChanges"]),
    display_bool(store, "HumanLaneChanges"),
    callback=write,
    enabled=editable,
  )


TURN_DESIRE_PATH = ("BogPilot", "Driving Controls", "Steering", "Lateral Tuning")
TURN_DESIRE_ROW = ("TurnDesires", "Force Turn Desires Below Lane Change Speed", "toggle", "LateralTune", None, None, None)


def turn_desire_row_available(store, *, runtime_integrated=False):
  level = store.tuning_level()
  return bool(runtime_integrated and store.honoured("LateralTune", level) and store.get_bool("LateralTune", True) and store.honoured("TurnDesires", level))


def turn_desire_item(store, *, runtime_integrated=False, offroad=None):
  """Historical Lateral Tuning child; import into lane10's native tuning group."""
  if not turn_desire_row_available(store, runtime_integrated=runtime_integrated):
    return None
  from openpilot.system.ui.widgets.list_view import toggle_item
  from openpilot.system.ui.lib.multilang import tr

  def editable():
    return offroad is not None and offroad()

  def write(state):
    if editable():
      configure(store, "TurnDesires", bool(state))

  return toggle_item(
    lambda: tr(TURN_DESIRE_ROW[1]),
    lambda: tr(
      "While driving below minimum lane-change speed with a turn signal, ask the model to turn left/right. Requires active lateral control; off until you change this row."
    ),
    display_bool(store, "TurnDesires"),
    callback=write,
    enabled=editable,
  )


# Re-export marker names for INT / sysUtilities reset docs.
__all__ = [
  "PANEL_PATH", "HUMAN_PATH", "ROWS", "HUMAN_ROW", "DESCRIPTIONS",
  "visible_rows", "numeric_bounds", "LaneChangeLayout",
  "human_row_available", "human_lane_change_item",
  "TURN_DESIRE_PATH", "TURN_DESIRE_ROW", "turn_desire_row_available", "turn_desire_item",
  "display_bool", "LANE_CHANGE_ACK", "HUMAN_LANE_CHANGES_ACK", "TURN_DESIRES_ACK",
]
