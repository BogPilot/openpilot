"""Driving Controls > Steering Tuning: Advanced Lateral Tuning and Quality of Life, functional rows only.

Every row has a real 0.11.2 consumer (see controls/lib/phase3_steering_tuning.py). Omitted on purpose, with no
inert stand-in: SteerKP, ForceTorqueController, NNFF, NNFFLite.

Parent integrator registers `PAGE_KEY/PAGE_TITLE/create_steering_tuning_layout/ACTIVE_CONTROLS` as one Driving
Controls page. Widget enabled callbacks AND writes enforce offroad/capability guards, so a stale confirmation
cannot write onroad or for a car that lacks the row.
"""
import math
from openpilot.selfdrive.controls.lib.phase3_steering_tuning import numeric_rows, valid_number, NATIVE_AUTO_TUNE_BRANDS

PAGE_KEY = "steering_tuning"
PAGE_TITLE = "Steering Tuning"
# Controls that can be shown for at least one supported CP. Torque rows appear only for torque-controlled CPs.
ACTIVE_CONTROLS = ("AdvancedLateralTune", "SteerDelay", "SteerRatio", "SteerFriction", "SteerLatAccel",
                   "ForceAutoTune", "ForceAutoTuneOff", "QOLLateral", "PauseLateralSpeed", "PauseLateralOnSignal")
NUMERIC_ORDER = ("SteerDelay", "SteerFriction", "SteerLatAccel", "SteerRatio")
NUMERIC_STEP = .01
DESCRIPTIONS = {
  "SteerDelay": "Seconds between a steering command and the car's response. Unset keeps the auto-learned value. Takes effect next drive.",
  "SteerRatio": "Steering wheel angle to road wheel angle ratio. Reset keeps the auto-learned value. Takes effect next drive.",
  "SteerFriction": "Torque-controlled cars only. Compensates steering friction. Needs Force Auto-Tune Off where live tuning exists.",
  "SteerLatAccel": "Torque-controlled cars only. Maps steering torque to turning response. Needs Force Auto-Tune Off where live tuning exists.",
}


def _as_callable(cp):
  return cp if callable(cp) else (lambda: cp)


class TuningEditor:
  """cp may be a CarParams or a callable returning the current persisted CarParams (None when unknown)."""
  def __init__(self, cp, store, offroad):
    self._cp, self.store, self.offroad = _as_callable(cp), store, offroad

  @property
  def cp(self):
    return self._cp()

  @property
  def rows(self):
    cp = self.cp
    return {} if cp is None else {r.key: r for r in numeric_rows(cp)}

  @property
  def torque(self):
    cp = self.cp
    return cp is not None and str(cp.steerControlType) == "torque" and cp.lateralTuning.which() == "torque"

  def native_auto(self):
    return self.torque and self.cp.brand in NATIVE_AUTO_TUNE_BRANDS

  def visible(self, key):
    """Row exists for this vehicle. QOL rows need no vehicle; everything else needs a known CarParams."""
    if key in ("QOLLateral", "PauseLateralSpeed", "PauseLateralOnSignal"):
      return True
    if key == "AdvancedLateralTune":
      return bool(self.rows)
    if key in ("ForceAutoTune", "ForceAutoTuneOff"):
      return self.torque and (self.native_auto() if key == "ForceAutoTuneOff" else not self.native_auto())
    return key in self.rows

  def can_edit(self, key):
    if not self.offroad() or not self.store.honoured(key) or not self.visible(key):
      return False
    if key == "AdvancedLateralTune":
      return True
    if key in ("QOLLateral", "PauseLateralSpeed", "PauseLateralOnSignal"):
      return key == "QOLLateral" or self.store.toggle_bool("QOLLateral")
    if not self.store.toggle_bool("AdvancedLateralTune"):
      return False
    if key in ("ForceAutoTune", "ForceAutoTuneOff"):
      return True
    if key in ("SteerFriction", "SteerLatAccel", "SteerRatio"):
      auto = self.native_auto()
      return self.store.toggle_bool("ForceAutoTuneOff") if auto else not self.store.toggle_bool("ForceAutoTune")
    return True  # SteerDelay

  def write(self, key, value):
    if not self.can_edit(key):
      return False
    rows = self.rows
    if key in rows:
      row = rows[key]
      if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not row.minimum <= value <= row.maximum:
        return False
    elif key == "PauseLateralSpeed":
      if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value != int(value):
        return False
      if not 0 <= value <= (150 if self.store.get_bool("IsMetric") else 99):
        return False
    elif key not in ("AdvancedLateralTune", "QOLLateral", "PauseLateralOnSignal", "ForceAutoTune", "ForceAutoTuneOff") or not isinstance(value, bool):
      return False
    self.store.put(key, value)
    self.store.invalidate(key)
    return True

  def reset(self, key):
    if key not in self.rows or not self.can_edit(key):
      return False
    self.store.remove(key)
    return True

  def value(self, key):
    if key == "PauseLateralSpeed":
      value = self.store.get_float(key)
      return value if math.isfinite(value) and 0 <= value <= (150 if self.store.get_bool("IsMetric") else 99) else 0
    row = self.rows[key]
    value = valid_number(self.store, row)
    return value if value is not None else row.default

  def shown(self, key):
    return f"{self.value(key):.2f}" if key in self.rows else ""

  def hint(self, key):
    row = self.rows.get(key)
    return DESCRIPTIONS[key] if row is None else f"Range {row.minimum:.2f}-{row.maximum:.2f}; step 0.01. {DESCRIPTIONS[key]}"

  def step(self, key, direction):
    return self.write(key, round(self.value(key) + direction * NUMERIC_STEP, 2))


def make_layout(cp, store, offroad):
  """cp: CarParams or callable returning it. Items are fixed; vehicle-dependent ones hide via set_visible."""
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import toggle_item, text_item, dual_button_item, button_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

  class SteeringTuningLayout(Widget):
    def __init__(self):
      super().__init__()
      self.editor = TuningEditor(cp, store, offroad)
      self.toggles = {}
      e = self.editor
      items = []

      def add(item, key):
        item.set_visible(lambda k=key: e.visible(k))
        items.append(item)
        return item

      def toggle(key, title, description):
        item = toggle_item(title, description, store.get_bool(key),
                           callback=lambda value, k=key: e.write(k, value), enabled=lambda k=key: e.can_edit(k))
        self.toggles[key] = item
        attach_help(item, key)
        return add(item, key)

      # Offroad only, applies next drive; no reboot. QOL rows need no vehicle; Advanced rows need a detected car.
      toggle("AdvancedLateralTune", "Advanced Lateral Tuning",
             "Fine-tune steering. Needs a previously detected car. Offroad only; applies next drive. Stock safety limits are unchanged.")
      for key in NUMERIC_ORDER:
        title = {"SteerDelay": "Actuator Delay", "SteerRatio": "Steer Ratio", "SteerFriction": "Friction", "SteerLatAccel": "Lateral Acceleration"}[key]
        # text_item resolves its callables at construction, before any car is known: they must never raise.
        add(attach_help(text_item(title, lambda k=key: e.shown(k), lambda k=key: e.hint(k)), key), key)
        add(dual_button_item("-0.01", "+0.01", left_callback=lambda k=key: e.step(k, -1), right_callback=lambda k=key: e.step(k, 1),
                             enabled=lambda k=key: e.can_edit(k)), key)
        add(button_item("Reset " + title, "RESET", callback=lambda k=key: e.reset(k), enabled=lambda k=key: e.can_edit(k)), key)
      toggle("ForceAutoTuneOff", "Force Auto-Tune Off", "Torque cars with live tuning: use the set Friction and Lateral Acceleration instead of live values.")
      toggle("ForceAutoTune", "Force Auto-Tune On", "Torque cars without native live tuning: learn Friction and Lateral Acceleration live (validity gate stays).")
      toggle("QOLLateral", "Quality of Life", "Steering quality-of-life options. Offroad only; applies next drive.")
      add(attach_help(text_item("Pause Steering Below", lambda: f"{e.value('PauseLateralSpeed'):g} " + ("km/h" if store.get_bool("IsMetric") else "mph"),
                                "0 is Off. Steering is suppressed below this speed. Uses the saved speed units; does not rewrite values."),
                      "PauseLateralSpeed"), "PauseLateralSpeed")
      add(dual_button_item("-1", "+1", left_callback=lambda: e.write("PauseLateralSpeed", e.value("PauseLateralSpeed") - 1),
                           right_callback=lambda: e.write("PauseLateralSpeed", e.value("PauseLateralSpeed") + 1),
                           enabled=lambda: e.can_edit("PauseLateralSpeed")), "PauseLateralSpeed")
      toggle("PauseLateralOnSignal", "Turn Signal Only", "Only pause steering below the speed while a turn signal is on.")
      self.scroller = Scroller(items, line_separator=True, spacing=0)

    def show_event(self):
      super().show_event()
      self.scroller.show_event()
      for key, item in self.toggles.items():
        item.action_item.set_state(store.get_bool(key))

    def _render(self, rect):
      self.scroller.render(rect)

  return SteeringTuningLayout()


def create_steering_tuning_layout():
  """Navigation factory (lazy). Uses the persisted UI CarParams, which does not prove an attached car."""
  from openpilot.common.bogpilot_store import ParamStore
  from openpilot.selfdrive.ui.ui_state import ui_state
  return make_layout(lambda: ui_state.CP, ParamStore(), ui_state.is_offroad)
