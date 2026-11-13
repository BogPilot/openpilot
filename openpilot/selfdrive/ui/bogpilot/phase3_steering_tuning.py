"""Driving Controls > Steering Tuning: Advanced Lateral Tuning and Quality of Life, functional rows only.

Every row has a real 0.11.2 consumer (see controls/lib/phase3_steering_tuning.py). Omitted on purpose, with no
inert stand-in: SteerKP, ForceTorqueController, NNFF, NNFFLite.

Parent integrator registers `PAGE_KEY/PAGE_TITLE/create_steering_tuning_layout/ACTIVE_CONTROLS` as one Driving
Controls page. Widget enabled callbacks AND writes enforce offroad/capability guards, so a stale confirmation
cannot write onroad or for a car that lacks the row.
"""
import math
from opendbc.car.tesla_ap1.override import SENSITIVITY_DEFAULT, SENSITIVITY_LEVELS, sanitize_level
from openpilot.selfdrive.controls.lib.phase3_steering_tuning import numeric_rows, valid_number, NATIVE_AUTO_TUNE_BRANDS

PAGE_KEY = "steering_tuning"
PAGE_TITLE = "Steering Tuning"
# Controls that can be shown for at least one supported CP. Torque rows appear only for torque-controlled CPs.
ACTIVE_CONTROLS = ("AdvancedLateralTune", "SteerDelay", "SteerRatio", "SteerFriction", "SteerLatAccel",
                   "ForceAutoTune", "ForceAutoTuneOff", "QOLLateral", "PauseLateralSpeed", "PauseLateralOnSignal", "OverrideSensitivity")
# File-backed (not a compiled Params key): the Tesla AP1 and Pre-AP car code reads it once per drive. Levels 1 to 5, default 3.
OVERRIDE_SENSITIVITY = "OverrideSensitivity"
LEGACY_TESLA_BRAND = "tesla_ap1"
NUMERIC_ORDER = ("SteerDelay", "SteerFriction", "SteerLatAccel", "SteerRatio")
NUMERIC_STEP = .01
DESCRIPTIONS = {
  "SteerDelay": "Seconds between a steering command and the car's response. Unset keeps the auto-learned value. Takes effect next drive.",
  "SteerRatio": "Steering wheel angle to road wheel angle ratio. Unset keeps the auto-learned value. Takes effect next drive.",
  "SteerFriction": "Torque-controlled cars only. Compensates steering friction. Needs Force Auto-Tune Off where live tuning exists.",
  "SteerLatAccel": "Torque-controlled cars only. Maps steering torque to turning response. Needs Force Auto-Tune Off where live tuning exists.",
  OVERRIDE_SENSITIVITY: "How hard you must push the wheel to take over steering. 1 needs the hardest push, 5 the lightest. 3 is the standard feel. Offroad only; applies next drive.",
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

  @property
  def legacy_tesla(self):
    """Override Sensitivity only exists for the legacy Teslas (Model S AP1, Model X AP1, Model S Pre-AP)."""
    cp = self.cp
    return cp is not None and cp.brand == LEGACY_TESLA_BRAND

  def native_auto(self):
    return self.torque and self.cp.brand in NATIVE_AUTO_TUNE_BRANDS

  def visible(self, key):
    """Row exists for this vehicle and its parent toggle is on (as in 0.9.7, a child row shows once its parent is switched on).
    QOL rows need no vehicle; everything else needs a known CarParams."""
    if key == "QOLLateral":
      return True
    if key == OVERRIDE_SENSITIVITY:
      return self.legacy_tesla
    if key in ("PauseLateralSpeed", "PauseLateralOnSignal"):
      return self.store.toggle_bool("QOLLateral")
    if key == "AdvancedLateralTune":
      return bool(self.rows)
    if not self.store.toggle_bool("AdvancedLateralTune"):
      return False
    if key in ("ForceAutoTune", "ForceAutoTuneOff"):
      return self.torque and (self.native_auto() if key == "ForceAutoTuneOff" else not self.native_auto())
    return key in self.rows

  def can_edit(self, key):
    if not self.offroad() or not self.store.honoured(key) or not self.visible(key):
      return False
    if key in ("AdvancedLateralTune", OVERRIDE_SENSITIVITY):
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
    rows = {} if key == OVERRIDE_SENSITIVITY else self.rows   # this row needs no CarParams numbers
    if key in rows:
      row = rows[key]
      if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not row.minimum <= value <= row.maximum:
        return False
    elif key == OVERRIDE_SENSITIVITY:
      if isinstance(value, bool) or not isinstance(value, int) or value not in SENSITIVITY_LEVELS:
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
    if (key != OVERRIDE_SENSITIVITY and key not in self.rows) or not self.can_edit(key):
      return False
    self.store.remove(key)
    return True

  def level(self):
    """The saved Override Sensitivity as the car code reads it: a missing or bad value is the default."""
    return sanitize_level(self.store.raw(OVERRIDE_SENSITIVITY))

  def value(self, key):
    if key == OVERRIDE_SENSITIVITY:
      return self.level()
    if key == "PauseLateralSpeed":
      value = self.store.get_float(key)
      return value if math.isfinite(value) and 0 <= value <= (150 if self.store.get_bool("IsMetric") else 99) else 0
    row = self.rows[key]
    value = valid_number(self.store, row)
    return value if value is not None else row.default

  def shown(self, key):
    if key == OVERRIDE_SENSITIVITY:
      level = self.level()
      # "3 of 5 (default)" (~289 px) overran the 150 px value pill; the grey "default: 3" hint and the outline
      # (shown when not at the default) already say whether it is the default.
      return f"{level} of {len(SENSITIVITY_LEVELS)}"
    return f"{self.value(key):.2f}" if key in self.rows else ""

  def hint(self, key):
    row = self.rows.get(key)
    return DESCRIPTIONS[key] if row is None else f"Range {row.minimum:.2f}-{row.maximum:.2f}; step 0.01. {DESCRIPTIONS[key]}"

  def default(self, key):
    """The existing default a row shows as "default: X", or None when there is none to show (no car yet).
    Numeric rows: NumericRow.default from controls/lib/phase3_steering_tuning.py numeric_rows (the car's own value, or
    lagd's initial delay). Override Sensitivity: SENSITIVITY_DEFAULT (opendbc tesla_ap1/override.py). Pause Steering
    Below: the registry default (bogpilot_params.py / bogpilot_defaults.py, read through ParamStore.default)."""
    if key == OVERRIDE_SENSITIVITY:
      return SENSITIVITY_DEFAULT
    if key == "PauseLateralSpeed":
      try:
        value = float(self.store.default(key))
      except (AttributeError, TypeError, ValueError, KeyError):
        return None
      return value if math.isfinite(value) else None
    row = self.rows.get(key)
    return None if row is None else row.default

  def default_shown(self, key):
    d = self.default(key)
    if d is None:
      return None
    if key == OVERRIDE_SENSITIVITY:
      return str(d)
    if key == "PauseLateralSpeed":
      return f"{d:g} " + ("km/h" if self.store.get_bool("IsMetric") else "mph")
    return f"{d:.2f}"

  def at_default(self, key):
    """True unless the value in effect differs from the default (an unknown default is never highlighted)."""
    from openpilot.selfdrive.ui.bogpilot.step_defaults import differs_from_default
    d = self.default(key)
    if d is None:
      return True
    try:
      v = self.value(key)
    except (KeyError, TypeError, ValueError):
      return True
    if key in self.rows:
      v, d = round(float(v), 2), round(float(d), 2)
    return not differs_from_default(v, d)

  def section_defaults(self, keys):
    """Reset table for a section: each of its keys that exists for this car and can be edited right now, with its
    existing default. A key locked at this moment (onroad, Tuning Level, parent off, auto-tune exclusivity) is left
    alone, exactly as its own value row is."""
    return {k: self.default(k) for k in keys if self.default(k) is not None and self.can_edit(k)}

  def step(self, key, direction):
    if key == OVERRIDE_SENSITIVITY:
      return self.write(key, self.level() + int(direction))   # a step past 1 or 5 is refused by write
    return self.write(key, round(self.value(key) + direction * NUMERIC_STEP, 2))


def make_layout(cp, store, offroad):
  """cp: CarParams or callable returning it. Items are fixed; vehicle-dependent ones hide via set_visible."""
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import toggle_item
  from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_value_step_item, reset_section_item, RESET_SECTION_TITLE, MINUS, PLUS
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help, override_sensitivity_help_key
  from openpilot.selfdrive.ui.bogpilot.nesting import indent_under
  from openpilot.selfdrive.ui.bogpilot import tuning_level

  PARENT_KEYS = ("AdvancedLateralTune", "QOLLateral")
  QOL_KEYS = ("PauseLateralSpeed", "PauseLateralOnSignal")

  class SteeringTuningLayout(Widget):
    def __init__(self):
      super().__init__()
      self.editor = TuningEditor(cp, store, offroad)
      self.toggles = {}
      e = self.editor
      items = []

      placed = []

      def add(item, key):
        item.set_visible(lambda k=key: e.visible(k))
        items.append(item)
        placed.append((item, key))
        return item

      def toggle(key, title, description):
        # Section switches (Advanced Lateral Tuning, Quality of Life) carry their 0.9.7 icon; rows inside do not.
        from openpilot.selfdrive.ui.bogpilot.section_icons import STEERING_SECTIONS, resolve_icon
        item = toggle_item(title, description, store.get_bool(key),
                           callback=lambda value, k=key: e.write(k, value), enabled=lambda k=key: e.can_edit(k),
                           icon=resolve_icon(key) if key in STEERING_SECTIONS else None)
        self.toggles[key] = item
        attach_help(item, key)
        return add(item, key)

      # Offroad only, applies next drive; no reboot. QOL rows need no vehicle; Advanced rows need a detected car.
      toggle("AdvancedLateralTune", "Advanced Lateral Tuning",
             "Fine-tune steering. Needs a previously detected car. Offroad only; applies next drive. Stock safety limits are unchanged.")
      def stepper(key, title, description, minus, plus, on_minus, on_plus):
        # One row: [minus] [value] [plus], value between the buttons, grey "default: X" under it, outlined when changed.
        # Its callables run before any car is known: they must never raise.
        shown = pause_text if key == "PauseLateralSpeed" else (lambda k=key: e.shown(k))
        item = gated_value_step_item(title, description, shown, on_minus, on_plus, minus=minus, plus=plus, enabled=lambda k=key: e.can_edit(k),
                                     default_text=lambda k=key: e.default_shown(k), is_default=lambda k=key: e.at_default(k),
                                     translate=tr)
        return item

      def pause_text():
        # Number only: "150 km/h" (~177 px at 40 px Inter Medium) overran the 150 px value pill. The grey hint keeps
        # the unit ("default: 0 mph" / "default: 0 km/h", default_shown).
        return f"{e.value('PauseLateralSpeed'):g}"

      def must(ok, key):
        # A refused write raises, so the shared reset row stops and tells the user instead of failing silently.
        if not ok:
          raise PermissionError(f"{key} was not reset")

      def section_reset(parent, keys, write, rows, toggles=()):
        # One "Reset section to defaults" row: asks first, then writes the whole section back: its value keys to their
        # existing defaults, its toggle rows and its own switch (parent) to their shipped defaults, the switch last
        # (step_defaults.whole_section). Shown only while one of its value rows is shown (their visibility and Tuning
        # Level gates), and also behind the parent toggle's own Tuning Level, so it is hidden whenever the rows it
        # resets are hidden. Enabled only while one of those keys can be edited.
        from openpilot.selfdrive.ui.bogpilot.step_defaults import whole_section

        def table():
          from openpilot.selfdrive.ui.bogpilot.step_defaults import car_type_overrides
          ov_keys = (parent,) + tuple(keys) + tuple(toggles)
          return whole_section(e.section_defaults(keys), toggles, parent=parent, can_edit=e.can_edit,
                               overrides=car_type_overrides(e.store, ov_keys))

        def write_any(k, value):
          if isinstance(value, bool):   # a toggle row or the switch: the same guarded write as its toggle
            return must(e.write(k, value), k)
          return write(k, value)
        item = reset_section_item(table, write_any, title=lambda: tr(RESET_SECTION_TITLE),
                                  enabled=lambda: any(e.can_edit(k) for k in keys),
                                  on_done=self._after_reset)
        item.set_visible(lambda: any(r.is_visible for r in rows))
        item.set_level_gate(lambda: tuning_level.row_visible(parent))
        attach_help(item, "section.reset_defaults")
        items.append(item)
        return item

      numeric_rows_shown = []
      for key in NUMERIC_ORDER:
        title = {"SteerDelay": "Actuator Delay", "SteerRatio": "Steer Ratio", "SteerFriction": "Friction", "SteerLatAccel": "Lateral Acceleration"}[key]
        numeric_rows_shown.append(add(attach_help(stepper(key, title, lambda k=key: e.hint(k), MINUS, PLUS,
                                                          lambda k=key: e.step(k, -1), lambda k=key: e.step(k, 1)), key), key))
      toggle("ForceAutoTuneOff", "Force Auto-Tune Off", "Torque cars with live tuning: use the set Friction and Lateral Acceleration instead of live values.")
      toggle("ForceAutoTune", "Force Auto-Tune On", "Torque cars without native live tuning: learn Friction and Lateral Acceleration live (validity gate stays).")
      # Removing a numeric key is its existing reset: the value goes back to the default shown in its hint.
      self.advanced_reset = section_reset("AdvancedLateralTune", NUMERIC_ORDER, lambda k, _default: must(e.reset(k), k),
                                          numeric_rows_shown, toggles=("ForceAutoTuneOff", "ForceAutoTune"))
      toggle("QOLLateral", "Quality of Life", "Steering quality-of-life options. Offroad only; applies next drive.")
      pause_row = add(attach_help(stepper("PauseLateralSpeed", "Pause Steering Below",
                                          "0 is Off. Steering is suppressed below this speed. Uses the saved speed units; does not rewrite values.",
                                          MINUS, PLUS, lambda: e.write("PauseLateralSpeed", e.value("PauseLateralSpeed") - 1),
                                          lambda: e.write("PauseLateralSpeed", e.value("PauseLateralSpeed") + 1)),
                                  "PauseLateralSpeed"), "PauseLateralSpeed")
      toggle("PauseLateralOnSignal", "Turn Signal Only", "Only pause steering below the speed while a turn signal is on.")
      self.qol_reset = section_reset("QOLLateral", ("PauseLateralSpeed",), lambda k, default: must(e.write(k, int(default)), k),
                                     [pause_row], toggles=("PauseLateralOnSignal",))
      add(attach_help(stepper(OVERRIDE_SENSITIVITY, "Override Sensitivity", lambda: e.hint(OVERRIDE_SENSITIVITY), "-", "+",
                              lambda: e.step(OVERRIDE_SENSITIVITY, -1), lambda: e.step(OVERRIDE_SENSITIVITY, 1)),
                      OVERRIDE_SENSITIVITY,
                      key_fn=lambda: override_sensitivity_help_key(None if e.cp is None else e.cp.carFingerprint)), OVERRIDE_SENSITIVITY)
      # Visibility already follows the saved parent value (TuningEditor.visible), so the children are only indented.
      indent_under(self.toggles["AdvancedLateralTune"], *(i for i, k in placed if k not in PARENT_KEYS + (OVERRIDE_SENSITIVITY,)
                                                           and k not in QOL_KEYS), self.advanced_reset)
      indent_under(self.toggles["QOLLateral"], *(i for i, k in placed if k in QOL_KEYS), self.qol_reset)
      self.scroller = Scroller(items, line_separator=True, spacing=0)

    def show_event(self):
      super().show_event()
      self.scroller.show_event()
      for key, item in self.toggles.items():
        item.action_item.set_state(store.get_bool(key))

    def _after_reset(self):
      # A reset may switch toggles (and the section's own switch): show the stored states, as show_event does.
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
