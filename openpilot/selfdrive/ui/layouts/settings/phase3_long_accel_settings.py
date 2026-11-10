"""Real raylib factories for owned 04d560f3e Gas / Brake settings.

No parent navigation/default edits. Constructing, opening, hiding and changing
units NEVER writes a preference/adoption marker. Only user callbacks configure().
"""
from dataclasses import dataclass
from decimal import Decimal
import math
from openpilot.selfdrive.controls.lib.phase3_long_accel import (
  configure, PROFILE_ACK, ADVANCED_ACK, CEM_ACK,
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
 'StopAccel': '<b>The acceleration openpilot commands to hold a stop.</b> More negative brakes harder; the '
              'current tree default is kept until you change it. Cannot be set above -0.5 m/s^2.',
 'StoppingDecelRate': '<b>How quickly the braking command ramps toward Stop Acceleration</b> while stopping. '
                      'Lower is gentler. Cannot be set below 0.1 m/s^3.',
 'CESpeedLead': '<b>Switch to "Experimental Mode" when driving below this speed with a lead</b> to help openpilot '
                'handle low-speed situations more smoothly.'}


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
GROUPS = {
  "advanced": ("AdvancedLongitudinalTune", "Advanced Longitudinal Tuning", ADVANCED_ACK,
               ("LongitudinalActuatorDelay", "MaxDesiredAcceleration", "StopAccel", "StoppingDecelRate")),
  "profiles": ("LongitudinalTune", "Longitudinal Tuning", PROFILE_ACK,
               ("AccelerationProfile", "DecelerationProfile", "HumanAcceleration")),
  "conditional": ("ConditionalExperimental", "Conditional Experimental Mode", CEM_ACK,
                  tuple(r.key for r in ROWS[7:])),
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

  def active(self):
    return self.store.get_bool(self.ack, False) and self.store.toggle_bool(self.parent)

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

  def value_text(self, key):
    row = BY_KEY[key]
    value = self.display_value(key)
    _, _, step, unit = self.number_contract(row)
    if not math.isfinite(value):
      return "—"
    if key.startswith("CE") and value == 0:
      return "Off"
    if key == "CEModelStopTime":
      return f"{value:g} " + ("second" if value == 1 else "seconds")
    digits = max(0, -Decimal(str(step)).as_tuple().exponent)
    return f"{value:.{digits}f}" + unit


def make_settings(group, store=None, capabilities=Capabilities(), cp=None, can_edit=lambda: True):
  import pyray as rl
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.button import Button
  from openpilot.system.ui.widgets.list_view import ItemAction, ListItem, toggle_item, multiple_button_item, text_item
  from openpilot.system.ui.widgets.label import gui_label
  from openpilot.system.ui.lib.application import FontWeight
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  if store is None:
    from openpilot.common.bogpilot_store import ParamStore
    store = ParamStore()

  class NumberAction(ItemAction):
    def __init__(self, controller, key):
      super().__init__(width=500)
      self.controller, self.key = controller, key
      self.minus = Button("−", click_callback=lambda: self.change(-1), text_padding=0)
      self.plus = Button("+", click_callback=lambda: self.change(1), text_padding=0)

    def change(self, direction):
      if self.enabled:
        self.controller.nudge(self.key, direction)

    def set_touch_valid_callback(self, callback):
      super().set_touch_valid_callback(callback)
      self.minus.set_touch_valid_callback(callback)
      self.plus.set_touch_valid_callback(callback)

    def _render(self, rect):
      y = rect.y + (rect.height - 100) / 2
      self.minus.set_enabled(self.enabled)
      self.plus.set_enabled(self.enabled)
      self.minus.render(rl.Rectangle(rect.x, y, 90, 100))
      self.plus.render(rl.Rectangle(rect.x + rect.width - 90, y, 90, 100))
      gui_label(rl.Rectangle(rect.x + 95, y, rect.width - 190, 100), self.controller.value_text(self.key),
                font_size=34, font_weight=FontWeight.MEDIUM)

  class SettingsPanel(Widget):
    def __init__(self):
      super().__init__()
      self.controller = SettingsController(group, store, capabilities, cp, can_edit)
      self.items = {}
      self._build()

    def _write(self, key, value):
      if self.controller.change(key, value):
        self._build()

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
      for row in c.rows():
        title = ("    " if row.parent or row.key == "CESpeedLead" else "") + row.title
        if row.key == "LongitudinalActuatorDelay" and cp is not None and cp.longitudinalActuatorDelay:
          title += f" (Default: {cp.longitudinalActuatorDelay:.2f})"
        desc = description(row, capabilities)
        enabled = c.enabled(row) and editable
        if row.kind == "toggle":
          item = toggle_item(title, desc, store.get_bool(row.key),
                             callback=lambda value, k=row.key: self._write(k, value), enabled=enabled)
        elif row.kind == "choice":
          item = multiple_button_item(title, desc, list(row.choices), store.get_int(row.key), button_width=140,
                                      callback=lambda value, k=row.key: self._write(k, value))
          item.action_item.set_enabled(enabled)
        else:
          action = NumberAction(c, row.key)
          action.set_enabled(enabled)
          item = ListItem(title=title, description=desc, action_item=action)
        attach_help(item, row.key)
        self.items[row.key] = item
        items.append(item)
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
  for group in ("advanced", "conditional", "profiles"):
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
