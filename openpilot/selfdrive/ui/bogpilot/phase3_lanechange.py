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
  human_lane_changes_default_on,
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
# Display tree: Delay and Minimum Lane Width sit under Automatic Lane Changes; speed and one-per-signal under Lane Changes.
TREE = (
  ("LaneChanges", (
    ("NudgelessLaneChange", (("LaneChangeTime", ()), ("LaneDetectionWidth", ()))),
    ("MinimumLaneChangeSpeed", ()),
    ("OneLaneChange", ()),
  )),
)
HUMAN_ROW = ("HumanLaneChanges", "Human-Like Lane Changes", "toggle", "LongitudinalTune", None, None, None)
DESCRIPTIONS = {
  "LaneChanges": "Allow openpilot to change lanes.",
  "NudgelessLaneChange": "Change lanes on turn signal without a steering-wheel nudge. Off until you change a row here; blindspot SNA/stale/invalid blocks the move.",
  "LaneChangeTime": "Delay between turn signal activation and the start of an automatic lane change.",
  "MinimumLaneChangeSpeed": "Lowest lane-change speed. The runtime retains a minimum safety floor of 20 mph (32.2 km/h).",
  "LaneDetectionWidth": "Prevent automatic lane changes into lanes narrower than the set width. Zero disables this additional width check.",
  "OneLaneChange": "Limit lane changes to one per turn-signal activation.",
  "HumanLaneChanges": "Anticipate and track adjacent vehicles during lane changes. Requires radar and openpilot longitudinal control. On by default on an AP1 Model S; on other cars, off until you change this row.",
}


def display_bool(store, key: str, CP=None) -> bool:
  """Panel display: dormant groups show OFF so saved ON prefs are not implied active. CP: the car, for the
  groups that are on by default on one car type (Human-Like Lane Changes on the AP1 Model S)."""
  if key == "LaneChanges" and not lane_change_adopted(store):
    return True  # stock torque LC remains available
  if key in LANE_CHANGE_KEYS and not lane_change_adopted(store):
    return False
  if key == "HumanLaneChanges" and not (human_lane_changes_adopted(store) or human_lane_changes_default_on(CP)):
    return False
  if key == "TurnDesires" and not turn_desires_adopted(store):
    return False
  # Unset rows show the same default the runtime reads (read_settings: HumanLaneChanges defaults on).
  default = key in ("LaneChanges", "OneLaneChange") or (key == "HumanLaneChanges" and human_lane_changes_default_on(CP))
  return store.get_bool(key, default)


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


# Existing defaults only (never invent a number). Each value cites its already-shipping source.
# LaneChangeTime "1.0": bogpilot_defaults.py / common/bogpilot_params.py BOGPILOT_PARAMS
#   ("PERSISTENT", "FLOAT", "1.0", 1, "0"); consumer fallback number(..., 1.0, ...) at
#   openpilot/selfdrive/controls/lib/phase3_lanechange.py:134.
# LaneDetectionWidth "0": bogpilot_defaults.py / BOGPILOT_PARAMS; FEATURE_SPECS declared_default "0".
# MinimumLaneChangeSpeed "20.0": bogpilot_defaults.py / BOGPILOT_PARAMS; FEATURE_SPECS declared_default "20.0".
STEP_DEFAULTS = {
  "LaneChangeTime": "1.0",
  "LaneDetectionWidth": "0",
  "MinimumLaneChangeSpeed": "20.0",
}
NUDGELESS_STEP_KEYS = ("LaneChangeTime", "LaneDetectionWidth")
SPEED_STEP_KEYS = ("MinimumLaneChangeSpeed",)


def format_step_value(value) -> str:
  return f"{float(value):g}"


def step_is_default(store, key: str) -> bool:
  from openpilot.selfdrive.ui.bogpilot.step_defaults import differs_from_default
  return not differs_from_default(store.get_float(key), STEP_DEFAULTS[key])


class LaneChangeLayout:
  def __new__(cls, store=None, *, runtime_integrated=False, offroad=None):
    if not runtime_integrated:
      raise RuntimeError("Lane-change consumers must be integrated before exposing controls")
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.system.ui.widgets import Widget
    from openpilot.system.ui.widgets.list_view import toggle_item
    from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_value_step_item, reset_section_item, RESET_SECTION_TITLE
    from openpilot.system.ui.widgets.scroller_tici import Scroller
    from openpilot.system.ui.lib.multilang import tr
    from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
    from openpilot.selfdrive.ui.bogpilot.nesting import place, indent_under
    from openpilot.selfdrive.ui.bogpilot import tuning_level

    class _Layout(Widget):
      def __init__(self):
        super().__init__()
        self.store = store if store is not None else ParamStore()
        self._build()

      def _editable(self):
        # No private calibration/capability assumptions: primary supplies offroad.
        return offroad is not None and offroad()

      def _build(self):
        by_key = {}
        self.steps = {}
        self.resets = {}
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
            # Shared value row: [-] [value] [+], grey "default: X" under the value, outlined when changed.
            # Offroad lock, range, and step are unchanged.
            item = gated_value_step_item(
              lambda t=title: tr(t),
              lambda d=desc: tr(d),
              lambda k=key: format_step_value(self.store.get_float(k)),
              lambda r=row: self._step(r, -1),
              lambda r=row: self._step(r, 1),
              enabled=self._editable,
              default_text=lambda k=key: format_step_value(STEP_DEFAULTS[k]),
              is_default=lambda k=key: step_is_default(self.store, k),
              translate=tr,
            )
            self.steps[key] = item
          attach_help(item, key)
          by_key[key] = item
        items = place(by_key, TREE)

        def add_reset(parent_key, keys, toggles=()):
          rows = [by_key[k] for k in keys if k in by_key]
          parent = by_key.get(parent_key)
          if not rows or parent is None:
            return None
          from openpilot.selfdrive.ui.bogpilot.step_defaults import whole_section

          def defaults():
            # The whole section: its value rows back to their existing defaults, its toggle rows and its own switch
            # back to their shipped defaults, then this car's reset profile on top (switch last; the switch takes the
            # profile value when the profile sets one).
            from openpilot.selfdrive.ui.bogpilot.step_defaults import car_type_overrides
            ov_keys = [parent_key, *(k for k in keys if k in by_key), *(k for k in toggles if k in by_key)]
            return whole_section({k: STEP_DEFAULTS[k] for k in keys if k in by_key},
                                 tuple(k for k in toggles if k in by_key), parent=parent_key,
                                 overrides=car_type_overrides(self.store, ov_keys))

          def write(key, value):
            if not self._editable():
              raise PermissionError(f"{key} was not reset")
            # Only this section's keys (no other writes). Switches go through the same path as their toggle rows.
            if isinstance(value, bool):
              configure(self.store, key, value)
            else:
              self.store.put(key, value)
            if hasattr(self.store, "invalidate"):
              self.store.invalidate()

          item = reset_section_item(defaults, write, title=lambda: tr(RESET_SECTION_TITLE),
                                    enabled=self._editable, on_done=self._after_reset)
          item.set_visible(lambda rs=tuple(rows): any(r.is_visible for r in rs))
          item.set_level_gate(lambda: tuning_level.row_visible(parent_key))
          attach_help(item, "section.reset_defaults")
          indent_under(parent, item)
          items.insert(items.index(rows[-1]) + 1, item)
          return item

        self.resets["NudgelessLaneChange"] = add_reset("NudgelessLaneChange", NUDGELESS_STEP_KEYS)
        self.resets["LaneChanges"] = add_reset("LaneChanges", SPEED_STEP_KEYS, toggles=("OneLaneChange",))
        self.scroller = Scroller(items, line_separator=True, spacing=0)

      def _after_reset(self):
        # A reset may switch a section off or on: rebuild like a toggle does, so the rows follow the switch.
        self._build()
        self.scroller.show_event()

      def _toggle(self, key, state):
        if self._editable():
          configure(self.store, key, bool(state))
          self._build()
          self.scroller.show_event()

      def _step(self, row, direction):
        if self._editable():
          low, high, step = numeric_bounds(row, self.store.get_bool("IsMetric", False))
          key = row[0]
          value = self.store.get_float(key)
          configure(self.store, key, str(round(max(low, min(high, value + direction * step)), 1)))

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
    display_bool(store, "HumanLaneChanges", CP),
    callback=write,
    enabled=editable,
  )


TURN_DESIRE_PATH = ("BogPilot", "Driving Controls", "Steering", "Lateral Tuning")
TURN_DESIRE_ROW = ("TurnDesires", "Force Turn Desires Below Lane Change Speed", "toggle", "LateralTune", None, None, None)


def turn_desire_row_available(store, *, runtime_integrated=False):
  level = store.tuning_level()
  return bool(runtime_integrated and store.honoured("LateralTune", level) and store.get_bool("LateralTune", True) and store.honoured("TurnDesires", level))


def turn_desire_item(store, *, runtime_integrated=False, offroad=None):
  """Historical Lateral Tuning child; import into the native tuning group."""
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
      "While driving below minimum lane-change speed with a turn signal, ask the model to turn left/right. "
      "Requires active lateral control; off until you change this row."
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
