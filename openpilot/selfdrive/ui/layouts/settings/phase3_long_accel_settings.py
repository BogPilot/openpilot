"""Real raylib factories for owned 04d560f3e Gas / Brake settings.

No parent navigation/default edits. Constructing, opening, hiding and changing
units NEVER writes a preference/adoption marker. Only user callbacks configure().
"""
from dataclasses import dataclass
from decimal import Decimal
import math
from openpilot.selfdrive.controls.lib.phase3_long_accel import (
  configure, PROFILE_ACK, ADVANCED_ACK, CEM_ACK, profiles_default_on,
)

HISTORICAL_DESCRIPTIONS = {'AdvancedLongitudinalTune': '<b>Advanced acceleration and braking control changes</b> to fine-tune how openpilot '
                             'drives.',
 'LongitudinalActuatorDelay': "<b>The time between openpilot's throttle or brake command and the vehicle's "
                              'response.</b> Increase if the vehicle feels slow to react; decrease if it feels too '
                              'eager or overshoots.',
 'MaxDesiredAcceleration': '<b>Limit the strongest acceleration</b> openpilot can command.',
 'ConditionalExperimental': '<b>Automatically switch to "Experimental Mode" when set conditions are met.</b> Allows '
                            'the model to handle challenging situations with smarter decision making.',
 'CESpeed': '<b>Switch to "Experimental Mode" when driving below this speed without a lead</b> to help openpilot '
            'handle low-speed situations more smoothly.',
 'CECurves': '<b>Switch to "Experimental Mode" when a curve is detected</b> to allow the model to set an appropriate '
             'speed for the curve.',
 'CEStopLights': '<b>Switch to "Experimental Mode" whenever the driving model "detects" a red light or stop '
                 'sign.</b><br><br><i><b>Disclaimer</b>: openpilot does not explicitly detect traffic lights or stop '
                 'signs. In "Experimental Mode", openpilot makes end-to-end driving decisions from camera input, '
                 "which means it may stop even when there's no clear reason!</i>",
 'CELead': '<b>Switch to "Experimental Mode" when a slower or stopped vehicle is detected.</b> Can make braking '
           'smoother and more reliable on some vehicles.',
 'CENavigation': '<b>Switch to "Experimental Mode" when approaching intersections or turns on the active route</b> '
                 'while using "Navigate on openpilot" (NOO) to allow the model to set an appropriate speed for '
                 'upcoming maneuvers.',
 'CEModelStopTime': '<b>Switch to "Experimental Mode" when openpilot predicts a stop within the set time.</b> This '
                    'is usually triggered when the model "sees" a red light or stop sign '
                    'ahead.<br><br><i><b>Disclaimer</b>: openpilot does not explicitly detect traffic lights or stop '
                    'signs. In "Experimental Mode", openpilot makes end-to-end driving decisions from camera input, '
                    "which means it may stop even when there's no clear reason!</i>",
 'CESignalSpeed': '<b>Switch to "Experimental Mode" when using a turn signal below the set speed</b> to allow the '
                  'model to choose an appropriate speed for smoother left and right turns.',
 'ShowCEMStatus': '<b>Show which condition triggered "Experimental Mode"</b> on the driving screen.',
 'LongitudinalTune': '<b>Acceleration and braking control changes</b> to fine-tune how openpilot drives.',
 'AccelerationProfile': '<b>How quickly openpilot speeds up.</b> "Eco" is gentle and efficient, "Sport" is firmer '
                        'and more responsive, and "Sport+" accelerates at the maximum rate allowed.',
 'DecelerationProfile': '<b>How gently openpilot slows down.</b> "Eco" favors coasting, "Eco+" coasts even more and '
                        'brakes as softly as possible.',
 'HumanAcceleration': '<b>Acceleration that mimics human behavior</b> by easing the throttle at low speeds and '
                      'adding extra power when taking off from a stop.',
 'AdaptiveAccelLead': '<b>Gentler acceleration when close behind a lead car</b> to stop the car lunging at a slower vehicle '
                      'and then braking. Only limits acceleration; braking is not affected.',
 'StopAccel': '<b>The acceleration openpilot commands to hold a stop.</b> More negative brakes harder; the '
              'current tree default is kept until you change it. Cannot be set above -0.5 m/s^2.',
 'StoppingDecelRate': '<b>How quickly the braking command ramps toward Stop Acceleration</b> while stopping. '
                      'Lower is gentler. Cannot be set below 0.1 m/s^3.',
 'CESpeedLead': '<b>Switch to "Experimental Mode" when driving below this speed with a lead</b> to help openpilot '
                'handle low-speed situations more smoothly.'}


# Selector pills (Acceleration / Deceleration Profile). "Standard" is ~176 px at 40 px Inter Medium and spilled out of
# the old 140 px pill; 190 px fits the full word (4 x 190 + 3 x 20 = 820 px, under the 880 px value rows).
CHOICE_PILL_WIDTH = 190


@dataclass(frozen=True)
class Row:
  key: str
  title: str
  kind: str = "toggle"
  parent: str | None = None
  low: float = 0
  high: float = 1
  step: float = 1
  unit: str = ""
  choices: tuple = ()
  capability: str = ""


ROWS = (
  Row("LongitudinalActuatorDelay", "Actuator Delay", "number", low=0, high=1, step=.01, unit=" seconds"),
  Row("MaxDesiredAcceleration", "Maximum Acceleration", "number", low=.1, high=4, step=.1, unit=" m/s^2"),
  Row("StopAccel", "Stop Acceleration", "number", low=-4, high=-.5, step=.01, unit=" m/s^2"),
  Row("StoppingDecelRate", "Stopping Rate", "number", low=.1, high=1, step=.01, unit=" m/s^3"),
  Row("AccelerationProfile", "Acceleration Profile", "choice", choices=("Standard", "Eco", "Sport", "Sport+")),
  Row("DecelerationProfile", "Deceleration Profile", "choice", choices=("Standard", "Eco", "Eco+")),
  Row("HumanAcceleration", "Human-Like Acceleration"),
  Row("AdaptiveAccelLead", "Adaptive Accel Near Lead"),
  Row("CESpeed", "Below", "number", low=0, high=99, unit=" mph"),
  Row("CESpeedLead", "With Lead", "number", low=0, high=99, unit=" mph"),
  Row("CECurves", "Curve Detected Ahead"),
  Row("CECurvesLead", "With Lead", parent="CECurves"),
  Row("CEStopLights", '"Detected" Stop Lights/Signs'),
  Row("CELead", "Lead Detected Ahead"),
  Row("CESlowerLead", "Slower Lead", parent="CELead"),
  Row("CEStoppedLead", "Stopped Lead", parent="CELead"),
  Row("CENavigation", "Navigation-Based", capability="navigation"),
  Row("CENavigationIntersections", "Intersections", parent="CENavigation", capability="navigation"),
  Row("CENavigationTurns", "Turns", parent="CENavigation", capability="navigation"),
  Row("CENavigationLead", "With Lead", parent="CENavigation", capability="navigation"),
  Row("CEModelStopTime", "Predicted Stop In", "number", low=0, high=9, unit=" seconds"),
  Row("CESignalSpeed", "Turn Signal Below", "number", low=0, high=99, unit=" mph"),
  Row("CESignalLaneDetection", "Not For Detected Lanes", parent="CESignalSpeed"),
  Row("ShowCEMStatus", "Status Widget"),
)
BY_KEY = {r.key: r for r in ROWS}
# Toggle rows other rows hang under (written before their rows when they turn on, after when they turn off).
SUB_PARENTS = tuple(sorted({r.parent for r in ROWS if r.parent and BY_KEY[r.parent].kind == "toggle"}))
GROUPS = {
  "advanced": ("AdvancedLongitudinalTune", "Advanced Longitudinal Tuning", ADVANCED_ACK,
               ("LongitudinalActuatorDelay", "MaxDesiredAcceleration", "StopAccel", "StoppingDecelRate")),
  "profiles": ("LongitudinalTune", "Longitudinal Tuning", PROFILE_ACK,
               ("AccelerationProfile", "DecelerationProfile", "HumanAcceleration", "AdaptiveAccelLead")),
  "conditional": ("ConditionalExperimental", "Conditional Experimental Mode", CEM_ACK,
                  tuple(r.key for r in ROWS[[r.key for r in ROWS].index("CESpeed"):])),
}


@dataclass(frozen=True)
class Capabilities:
  navigation: bool = False
  # Engines exist; no real external producers are assumed by these settings.
  slc: bool = False
  v9_prediction: bool = False
  gears: bool = False
  weather: bool = False


def _cp_value(cp, name, fallback):
  try:
    value = float(getattr(cp, name))
  except (AttributeError, TypeError, ValueError):
    return fallback
  return value if math.isfinite(value) else fallback


# Unwritten Advanced rows show (and the consumers use) the current stock values.
STOCK_DISPLAY = {
  "LongitudinalActuatorDelay": lambda cp, store: _cp_value(cp, "longitudinalActuatorDelay", 0.0),
  "StopAccel": lambda cp, store: _cp_value(cp, "stopAccel", -2.0),
  "StoppingDecelRate": lambda cp, store: 1.0,
}


def description(row, capabilities):
  text = HISTORICAL_DESCRIPTIONS.get(row.key, "")
  if not text and row.parent:
    text = HISTORICAL_DESCRIPTIONS.get(row.parent, "")
  if row.capability and not getattr(capabilities, row.capability):
    text += "<br><br><b>Pending:</b> the real navigation producer is not connected in this build. Saved preference is retained."
  if row.key == "CELead" and not capabilities.v9_prediction:
    text += "<br><br>Radar slower/stopped-lead conditions work. The old v9-only predictive-lead path awaits verified model-version input."
  return text


class SettingsController:
  """Same callback target used by the real raylib actions; testable without a renderer.

  can_edit is re-evaluated on EVERY write (offroad guard); cp may be a live proxy.
  """
  def __init__(self, group, store, capabilities=Capabilities(), cp=None, can_edit=lambda: True):
    self.group, self.store, self.capabilities = group, store, capabilities
    self.cp, self.can_edit = cp, can_edit
    self.parent, self.title, self.ack, self.keys = GROUPS[group]

  def platform(self):
    try:
      return getattr(self.cp, "carFingerprint", None)
    except Exception:  # LiveCP without CarParams raises AttributeError
      return None

  def adopted(self):
    # Profiles are live by default on the legacy Tesla platforms (no ACK needed); other groups and cars need the ACK.
    return self.store.get_bool(self.ack, False) or (self.ack == PROFILE_ACK and profiles_default_on(self.platform()))

  def active(self):
    return self.adopted() and self.store.toggle_bool(self.parent)

  def parent_on(self, key):
    return self.store.get_float(key) > 0 if key == "CESignalSpeed" else self.store.get_bool(key)

  def rows(self):
    if not self.active():
      return []
    out = []
    for key in self.keys:
      row = BY_KEY[key]
      if not self.store.honoured(key):
        continue
      if key == "CEStopLights" and self.store.honoured("CEModelStopTime"):
        continue  # old UI only presents the simple stop-light switch below the time control's level
      if row.parent and not self.parent_on(row.parent):
        continue
      if key == "AdaptiveAccelLead" and not profiles_default_on(self.platform()):
        continue  # only the legacy Teslas have a consumer: no inert row on any other car (or before the car is known)
      if row.capability and not self.enabled(row):
        continue  # no consumer-less rows: hidden until its real producer is connected (saved value kept)
      out.append(row)
    return out

  def enabled(self, row):
    return not row.capability or bool(getattr(self.capabilities, row.capability))

  def long_available(self):
    return self.cp is None or bool(self.cp.openpilotLongitudinalControl)

  def change(self, key, value):
    # Live guards: a stale callback must not write while driving or without openpilot longitudinal.
    if not self.can_edit() or not self.long_available() or not self.store.honoured(key):
      return False
    if key != self.parent:
      row = BY_KEY[key]
      if key not in self.keys or not self.active() or not self.enabled(row):
        return False
      if row.parent and not self.parent_on(row.parent):
        return False
      if row.kind == "choice":
        value = max(0, min(len(row.choices) - 1, int(value)))
      elif row.kind == "number":
        low, high, _, _ = self.number_contract(row)
        if not math.isfinite(float(value)):
          return False
        value = max(low, min(high, float(value)))
    configure(self.store, key, value)
    return True

  def number_contract(self, row):
    if row.unit == " mph" and self.store.get_bool("IsMetric", False):
      return row.low, 150, row.step, " km/h"
    return row.low, row.high, row.step, row.unit

  def display_value(self, key):
    row = BY_KEY[key]
    if self.store.raw(key) in (None, "") and key in STOCK_DISPLAY:
      return STOCK_DISPLAY[key](self.cp, self.store)
    if key in ("StopAccel", "StoppingDecelRate"):
      # A stale saved value outside the safety floor is shown (and nudged from) as the clamped value the consumer uses.
      value = self.store.get_float(key)
      return max(row.low, min(row.high, value)) if math.isfinite(value) else STOCK_DISPLAY[key](self.cp, self.store)
    if row.unit == " mph" and self.store.raw(key) is None:
      default_mph = float(self.store.default(key) or 0)
      return int(default_mph * 1.609344) if self.store.get_bool("IsMetric", False) else default_mph
    return self.store.get_float(key)

  def nudge(self, key, direction):
    row = BY_KEY[key]
    _, _, step, _ = self.number_contract(row)
    # Decimal avoids cumulative 0.01-step binary rounding in saved preferences.
    current = self.display_value(key)
    if not math.isfinite(current):
      current = row.low
    value = float(Decimal(str(current)) + Decimal(str(step)) * direction)
    return self.change(key, value)

  # ---- defaults for the value rows: exactly what display_value() shows while the key is unsaved (no new number) ----
  #   MaxDesiredAcceleration "4.0"   openpilot/common/bogpilot_params.py:242 (UI catalog bogpilot_defaults.py:181)
  #   CESpeed "0", CESpeedLead "0"   bogpilot_params.py:91-92 (bogpilot_defaults.py:60-61)
  #   CESignalSpeed "55"             bogpilot_params.py:89 (bogpilot_defaults.py:58)
  #   CEModelStopTime "8.0"          bogpilot_params.py:83 (bogpilot_defaults.py:52)
  # The mph rows in metric show the same int(mph * 1.609344) display_value() already shows for an unsaved key.
  # No default, so no hint and no reset: LongitudinalActuatorDelay, StopAccel, StoppingDecelRate (registry default ""
  # at bogpilot_params.py:225,406,409 and bogpilot_defaults.py:168,313,316; STOCK_DISPLAY shows the car's stock value).
  def unsaved_value(self, key):
    """The value a number row shows while its key is unsaved, or None when the key has no default (never invented)."""
    row = BY_KEY.get(key)
    if row is None or row.kind != "number" or key in STOCK_DISPLAY:
      return None
    getter = getattr(self.store, "default", None)
    try:
      value = float(getter(key)) if getter is not None else None
    except (TypeError, ValueError):
      return None
    if value is None or not math.isfinite(value):
      return None
    if row.unit == " mph" and self.store.get_bool("IsMetric", False):
      return int(value * 1.609344)
    return value

  def default_text(self, key):
    value = self.unsaved_value(key)
    return None if value is None else self.format_value(key, value)

  def at_default(self, key):
    from openpilot.selfdrive.ui.bogpilot.step_defaults import differs_from_default
    return not differs_from_default(self.display_value(key), self.unsaved_value(key))

  def section_defaults(self, keys):
    """Reset table for this group: each of its number keys that has a default and can be edited right now (offroad,
    openpilot longitudinal, row shown for the Tuning Level and parent), with that default. Locked keys are left alone."""
    if not self.can_edit() or not self.long_available():
      return {}
    shown = {r.key for r in self.rows()}
    return {k: self.unsaved_value(k) for k in keys if k in shown and self.unsaved_value(k) is not None}

  def reset_write(self, key, value):
    """Section-reset writer: the same guarded change() as the -/+ buttons; a refused write raises (the row reports it)."""
    if not self.change(key, value):
      raise PermissionError(f"{key} was not reset")

  def value_text(self, key):
    return self.format_value(key, self.display_value(key))

  def format_value(self, key, value):
    row = BY_KEY[key]
    _, _, step, unit = self.number_contract(row)
    if not math.isfinite(value):
      return "—"
    if key.startswith("CE") and value == 0:
      return "Off"
    if key == "CEModelStopTime":
      return f"{value:g} " + ("second" if value == 1 else "seconds")
    digits = max(0, -Decimal(str(step)).as_tuple().exponent)
    return f"{value:.{digits}f}" + unit


def make_settings(group, store=None, capabilities=Capabilities(), cp=None, can_edit=lambda: True, extra_items=None):
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import toggle_item, text_item
  from openpilot.selfdrive.ui.bogpilot.gated_actions import (RESET_SECTION_TITLE, gated_multiple_button_item,
                                                             gated_value_step_item, reset_section_item)
  from openpilot.selfdrive.ui.bogpilot import tuning_level
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  from openpilot.selfdrive.ui.bogpilot.tesla_start_values import start_text
  from openpilot.selfdrive.ui.bogpilot.nesting import indent_under
  if store is None:
    from openpilot.common.bogpilot_store import ParamStore
    store = ParamStore()

  class SettingsPanel(Widget):
    def __init__(self):
      super().__init__()
      self.controller = SettingsController(group, store, capabilities, cp, can_edit)
      self.items = {}
      self._build()

    def _write(self, key, value):
      if self.controller.change(key, value):
        self._build()

    def _section_table(self, reset_keys):
      """The whole group (step_defaults.whole_section): its number rows back to their existing defaults
      (section_defaults), its toggle and choice rows and the group switch itself back to their shipped defaults, then
      this car's reset profile on top (the switch takes the profile value when the profile sets one). Only rows shown
      right now, and only while the group can be edited."""
      from openpilot.selfdrive.ui.bogpilot.step_defaults import car_type_overrides, whole_section
      c = self.controller
      if not bool(can_edit()) or not c.long_available():
        return {}
      rows = c.rows()
      shown = {r.key for r in rows}
      keys = (c.parent,) + tuple(r.key for r in rows)
      return whole_section(c.section_defaults(reset_keys),
                           toggles=tuple(r.key for r in rows if r.kind == "toggle"),
                           choices=tuple(r.key for r in rows if r.kind == "choice"),
                           parent=c.parent, sub_parents=SUB_PARENTS,
                           can_edit=lambda k: k == c.parent or k in shown,
                           overrides=car_type_overrides(store, keys))

    def _build(self):
      c = self.controller
      editable = bool(can_edit()) and c.long_available()
      self._editable = editable
      parent_enabled = store.honoured(c.parent) and editable
      self.items = {}
      root = toggle_item(c.title, HISTORICAL_DESCRIPTIONS.get(c.parent, ""), c.active(),
                         callback=lambda value: self._write(c.parent, value), enabled=parent_enabled)
      attach_help(root, c.parent)
      self.items[c.parent] = root
      items = [root]
      rows = c.rows()
      for row in rows:
        title = row.title
        if row.key == "LongitudinalActuatorDelay" and cp is not None and cp.longitudinalActuatorDelay:
          title += f" (Default: {cp.longitudinalActuatorDelay:.2f})"
        desc = description(row, capabilities)
        enabled = c.enabled(row) and editable
        if row.kind == "toggle":
          item = toggle_item(title, desc, store.get_bool(row.key),
                             callback=lambda value, k=row.key: self._write(k, value), enabled=enabled)
        elif row.kind == "choice":
          item = gated_multiple_button_item(title, desc, list(row.choices), store.get_int(row.key), button_width=CHOICE_PILL_WIDTH,
                                            callback=lambda value, k=row.key: self._write(k, value))
          item.action_item.set_enabled(enabled)
        else:
          # The shared value row [-] [value] [+] (was a custom inline action with U+2212). Same step, same guards: the
          # lock is re-read every frame and change() still refuses a stale tap. Hint and outline only with a default.
          has_default = c.unsaved_value(row.key) is not None
          item = gated_value_step_item(title, desc, lambda k=row.key: c.value_text(k),
                                       on_minus=lambda k=row.key: c.nudge(k, -1), on_plus=lambda k=row.key: c.nudge(k, 1),
                                       button_width=280,
                                       enabled=lambda r=row: c.enabled(r) and bool(can_edit()) and c.long_available(),
                                       default_text=(lambda k=row.key: c.default_text(k)) if has_default else None,
                                       is_default=(lambda k=row.key: c.at_default(k)) if has_default else None,
                                       translate=tr)
        # Tesla starting values for this car (the delay shown above is the live CarParams value; the others are the code defaults).
        attach_help(item, row.key, extra=lambda k=row.key: start_text(k, c.platform()))
        self.items[row.key] = item
        items.append(item)
      self.reset = None
      reset_keys = tuple(r.key for r in rows if c.unsaved_value(r.key) is not None)
      if reset_keys:
        # One reset row for the group, after its own rows: asks first, then writes the whole group back
        # (_section_table: number rows to their existing defaults, toggle / choice rows and the group switch to the
        # shipped defaults, the switch last). Locked like the rows; shown only while one of its number rows is shown,
        # and behind the group switch's own Tuning Level.
        rows_of_reset = tuple(self.items[k] for k in reset_keys)
        self.reset = reset_section_item(lambda: self._section_table(reset_keys), c.reset_write,
                                        title=lambda: tr(RESET_SECTION_TITLE),
                                        enabled=lambda: bool(can_edit()) and c.long_available(), on_done=self._build)
        attach_help(self.reset, "section.reset_defaults")
        self.reset.set_visible(lambda: any(i.is_visible for i in rows_of_reset))
        self.reset.set_level_gate(lambda: tuning_level.row_visible(c.parent))
        items.append(self.reset)
      extra = list(extra_items()) if extra_items is not None and c.active() else []
      items.extend(extra)   # rows another module owns (Longitudinal Tuning: following rows), after this group's own
      # Every row belongs to the group switch at the top; a row with its own parent (and With Lead under Below) goes one level
      # deeper. Visibility already follows the saved values (SettingsController.rows), so the helper only indents.
      indent_under(root, *(self.items[r.key] for r in rows), *((self.reset,) if self.reset is not None else ()), *extra)
      for row in rows:
        parent = row.parent or ("CESpeed" if row.key == "CESpeedLead" else None)
        if parent in self.items and parent != row.key:
          indent_under(self.items[parent], self.items[row.key])
      if not c.active():
        items.append(text_item("Saved preferences", "Unchanged", "Enable this section explicitly to adopt its stored settings."))
      self.scroller = Scroller(items, spacing=0, line_separator=True)
      self._shown = tuple(self.items)

    def show_event(self):
      super().show_event()
      store.invalidate()
      self._build()
      self.scroller.show_event()

    def hide_event(self):
      super().hide_event()
      self.scroller.hide_event()

    def _render(self, rect):
      expected = (self.controller.parent, *(r.key for r in self.controller.rows()))
      if expected != self._shown or self._editable != (bool(can_edit()) and self.controller.long_available()):
        self._build()
      self.scroller.render(rect)

  return SettingsPanel()


def AdvancedLongitudinalSettings(store=None, capabilities=Capabilities(), cp=None, can_edit=lambda: True):
  return make_settings("advanced", store, capabilities, cp, can_edit)


def LongitudinalProfilesSettings(store=None, capabilities=Capabilities(), cp=None, can_edit=lambda: True):
  return make_settings("profiles", store, capabilities, cp, can_edit)


def ConditionalExperimentalSettings(store=None, capabilities=Capabilities(), cp=None, can_edit=lambda: True):
  return make_settings("conditional", store, capabilities, cp, can_edit)


def gas_accel_entries(open_panel, store=None, capabilities=Capabilities(), cp=None, can_edit=lambda: True):
  """Optional PRIMARY navigation wiring: open_panel(widget, exact_historical_title).

  Returns actual list-view items, not metadata. Does not edit or own parent nav.
  """
  from openpilot.system.ui.widgets.list_view import button_item
  if store is None:
    from openpilot.common.bogpilot_store import ParamStore
    store = ParamStore()
  items = []
  for group in ("advanced", "profiles"):   # no "conditional": Conditional Experimental Mode is removed
    parent, title, _ack, keys = GROUPS[group]
    if not any(store.honoured(key) for key in keys):
      continue
    items.append(button_item(title, "MANAGE", HISTORICAL_DESCRIPTIONS.get(parent, ""),
                             callback=lambda g=group, t=title: open_panel(make_settings(g, store, capabilities, cp, can_edit), t),
                             enabled=cp is None or cp.openpilotLongitudinalControl))
  return items


def convert_cem_speed_units(store, old_metric, new_metric):
  """PRIMARY units-action hook, never a show_event/startup migration.

  Match old Qt integer conversion exactly once, for real saved preferences only.
  No configure()/adoption marker: changing display units must not enable CEM.
  """
  if bool(old_metric) == bool(new_metric):
    return False
  factor = 1.609344 if new_metric else 1 / 1.609344
  for key in ("CESpeed", "CESpeedLead", "CESignalSpeed"):
    if store.raw(key) is not None:
      store.put(key, int(store.get_int(key) * factor), block=True)
  store.invalidate()
  return True
