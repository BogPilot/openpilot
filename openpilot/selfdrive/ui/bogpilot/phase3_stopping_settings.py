"""BogPilot Gas/Brake stopping/QoL pages, backed by the shared effective store.

Historical keys/bounds: 04d560f3e longitudinal_settings.cc. Manual weather source
is an explicit offline compatibility adapter, not a claimed historical service.
No unsupported starting-state, Toyota-CAN or credential entry rows are shown.
"""
from dataclasses import dataclass
import math

from openpilot.selfdrive.controls.lib.phase3_long_stopping import (
  MANUAL_WEATHER_KEY, MANUAL_WEATHER, read_options,
  DISTANCE_ACK, FORCE_ACK, WEATHER_ACK,
)


# Pill labels for Manual Weather Condition, in MANUAL_WEATHER order. Display only: the stored values are unchanged.
# "Low visibility" (~253 px at 40 px Inter Medium) overran its pill, so the pill says "Low Vis" (~150 px); the pill is
# 160 px so it fits (5 x 160 + 4 x 20 = 880 px, the same row width as the 280 px value rows).
WEATHER_PILL_LABELS = ("Clear", "Low Vis", "Rain", "Storm", "Snow")
WEATHER_PILL_WIDTH = 160


@dataclass(frozen=True)
class StoppingCapabilities:
  # Stop Acceleration / Stopping Rate live in the single Advanced Longitudinal Tuning panel
  # (phase3_long_accel_settings), which owns the shared AdvancedLongitudinalTune parent.
  stopped_distance: bool = False
  force_stop_inputs: bool = False
  human_acceleration: bool = False
  weather_following: bool = False
  weather_acceleration: bool = False
  weather_curves: bool = False


@dataclass(frozen=True)
class Row:
  key: str
  title: str
  kind: str
  low: float = 0
  high: float = 0
  step: float = 1
  unit: str = ""
  description: str = ""


class StoppingSettingsModel:
  def __init__(self, store, CP, capabilities, can_edit=lambda: False):
    self.store, self.CP, self.capabilities, self.can_edit = store, CP, capabilities, can_edit

  def rows(self, page="root"):
    s, c = self.store, self.capabilities
    if not self.CP.openpilotLongitudinalControl or s.toggle_bool("DisableOpenpilotLongitudinal", s.tuning_level()):
      return []
    options = read_options(s, self.CP, is_metric=s.get_bool("IsMetric"))
    metric = s.get_bool("IsMetric")
    distance = (0, 3, 1, " m") if metric else (0, 10, 1, " feet")
    weather_available = c.stopped_distance or c.weather_following or c.weather_acceleration or c.weather_curves
    rows = []
    if page == "root":
      if c.human_acceleration:
        rows.append(Row("longitudinal", "Longitudinal Tuning", "page"))
      if c.stopped_distance or c.force_stop_inputs or weather_available:
        rows.append(Row("qol", "Quality of Life", "page"))
    elif page == "longitudinal" and c.human_acceleration:
      rows.append(Row("LongitudinalTune", "Longitudinal Tuning", "toggle"))
      if s.toggle_bool("LongitudinalTune", s.tuning_level()):
        rows.append(Row("HumanAcceleration", "Human-Like Acceleration", "toggle"))
    elif page == "qol":
      rows.append(Row("QOLLongitudinal", "Quality of Life", "toggle"))
      if s.toggle_bool("QOLLongitudinal", s.tuning_level()):
        if c.force_stop_inputs:
          rows.append(Row("ForceStops", 'Force Stop at "Detected" Stop Lights/Signs', "toggle",
                          description="The driving model does not explicitly detect traffic lights or stop signs. "
                                      "It may stop without a clear reason. Accelerator or acceleration-button input overrides the request."))
        if c.stopped_distance:
          rows.append(Row("IncreasedStoppedDistance", "Increase Stopped Distance by:", "number", *distance))
        if weather_available:
          rows.append(Row("WeatherPresets", "Weather Condition Offsets", "toggle",
                          description="Manual, local condition selection only. No automatic weather, location upload or API key."))
          if options.weather_presets:
            rows.append(Row("weather", "Weather Condition Offsets", "page"))
    elif page == "weather" and options.weather_presets and weather_available:
      rows.append(Row(MANUAL_WEATHER_KEY, "Manual Weather Condition", "condition",
                      description="Clear disables offsets. This selection stays local until you change it."))
      rows.extend(Row(suffix, title, "page") for suffix, title in
                  (("LowVisibility", "Low Visibility"), ("Rain", "Rain"), ("RainStorm", "Rainstorms"), ("Snow", "Snow")))
    elif page in ("LowVisibility", "Rain", "RainStorm", "Snow") and options.weather_presets:
      if c.weather_following:
        rows.append(Row("IncreaseFollowing" + page, "Increase Following Distance by:", "number", 0, 3, .01, " seconds"))
      if c.stopped_distance:
        rows.append(Row("IncreasedStoppedDistance" + page, "Increase Stopped Distance by:", "number", *distance))
      if c.weather_acceleration:
        rows.append(Row("ReduceAcceleration" + page, "Reduce Acceleration by:", "number", 0, 99, 1, "%"))
      if c.weather_curves:
        rows.append(Row("ReduceLateralAcceleration" + page, "Reduce Speed in Curves by:", "number", 0, 99, 1, "%"))
    return [row for row in rows if row.kind in ("page", "condition") or s.honoured(row.key, s.tuning_level())]

  def value(self, row):
    return self.store.get_float(row.key)

  # ---- default for the Quality of Life value row: what value() shows while the key is unsaved (no new number) ----
  #   IncreasedStoppedDistance "0"   openpilot/common/bogpilot_params.py:196 (UI catalog bogpilot_defaults.py:141)
  # Only the Quality of Life page gets a hint and a reset; the latent weather rows stay without one until their
  # capabilities turn on (they are hidden on this build).
  DEFAULT_PAGES = ("qol",)

  def default(self, page, row):
    """The value a number row shows while its key is unsaved, or None when there is no default (never invented)."""
    if page not in self.DEFAULT_PAGES or row.kind != "number":
      return None
    getter = getattr(self.store, "default", None)
    try:
      value = float(getter(row.key)) if getter is not None else None
    except (TypeError, ValueError):
      return None
    return value if value is not None and math.isfinite(value) else None

  def value_text(self, row, value):
    return f"{value:g}{row.unit}"

  def at_default(self, page, row):
    from openpilot.selfdrive.ui.bogpilot.step_defaults import differs_from_default
    return not differs_from_default(self.value(row), self.default(page, row))

  # The switch each reset page belongs to (written back to its shipped default too, last).
  PAGE_PARENTS = {"qol": "QOLLongitudinal"}

  def section_defaults(self, page):
    """Reset table for one whole page (step_defaults.whole_section): each number row on it now that has a default,
    with that default, plus its toggle rows and the page's own switch at their shipped defaults, then this car's
    reset profile on top (the switch takes the profile value when the profile sets one). Nothing else."""
    from openpilot.selfdrive.ui.bogpilot.step_defaults import car_type_overrides, whole_section
    if not self.can_edit():
      return {}
    values = {}
    rows = self.rows(page)
    for row in rows:
      d = self.default(page, row)
      if d is not None:
        values[row.key] = d
    if page not in self.DEFAULT_PAGES:
      return values
    toggles = tuple(r.key for r in rows if r.kind == "toggle")
    parent = self.PAGE_PARENTS.get(page)
    ov_keys = ((parent,) if parent else ()) + tuple(values) + toggles
    return whole_section(values, toggles, parent=parent, sub_parents=("WeatherPresets",),
                         overrides=car_type_overrides(self.store, ov_keys))

  def reset_write(self, page, key, value):
    """Section-reset writer: the same guarded change() as the -/+ buttons; a refused write raises (the row reports it)."""
    if not self.change(page, key, value=value):
      raise PermissionError(f"{key} was not reset")

  def _commit(self, key, value):
    """Blocking write, then read back through a cleared cache.

    Params.put is asynchronous by default: without block=True an immediate panel rebuild or the
    adoption marker (a plain file) can become visible while the compiled Params still hold the
    OLD preference. A failed read-back returns False and the adoption marker is NOT written.
    """
    if isinstance(value, bool):
      self.store.put_bool(key, value, block=True)
    else:
      self.store.put(key, value, block=True)
    self.store.invalidate()
    if isinstance(value, bool):
      return self.store.get_bool(key) == value
    if isinstance(value, (int, float)):
      return math.isclose(self.store.get_float(key), float(value), rel_tol=0, abs_tol=1e-6)
    return self.store.get(key) == value

  def change(self, page, key, value=None, delta=None):
    row = next((r for r in self.rows(page) if r.key == key), None)
    if row is None or row.kind == "page" or not self.can_edit():
      return False
    if not self.CP.openpilotLongitudinalControl:
      return False
    if row.kind == "toggle":
      if key in ("LongitudinalTune", "HumanAcceleration"):
        # Lane4 is the sole acceleration consumer/adoption owner.
        from openpilot.selfdrive.controls.lib.phase3_long_accel import configure
        configure(self.store, key, bool(value))
        self.store.invalidate()
        return True
      if not self._commit(key, bool(value)):
        return False
    elif row.kind == "condition":
      if value not in MANUAL_WEATHER:
        return False
      if not self._commit(key, value):
        return False
    elif row.kind == "number":
      number = self.value(row) + delta * row.step if delta is not None else float(value)
      if not math.isfinite(number):
        return False
      if not self._commit(key, round(max(row.low, min(row.high, number)), 3)):
        return False
    # Explicit UI action is the only adoption path; deployment never enables
    # dormant saved child tuning. Markers are internal, not invented UI rows.
    ack = None
    if key == "ForceStops":
      ack = FORCE_ACK
    elif key == "IncreasedStoppedDistance":
      ack = DISTANCE_ACK
    elif key == "WeatherPresets" or key == MANUAL_WEATHER_KEY or page in ("LowVisibility", "Rain", "RainStorm", "Snow"):
      ack = WEATHER_ACK
    if ack is not None:
      if not self._commit(ack, True):
        return False
    self.store.invalidate()
    return True


class StoppingSettingsLayout:
  """Embeddable raylib page. Parent provides genuine installed capabilities + offroad edit guard."""
  def __new__(cls, store, CP, capabilities, can_edit=lambda: False, start_page="root"):
    from openpilot.system.ui.widgets import Widget
    from openpilot.system.ui.widgets.list_view import toggle_item, button_item
    from openpilot.selfdrive.ui.bogpilot.gated_actions import (RESET_SECTION_TITLE, gated_multiple_button_item,
                                                               gated_value_step_item, reset_section_item)
    from openpilot.selfdrive.ui.bogpilot import tuning_level
    from openpilot.selfdrive.ui.bogpilot.nesting import indent_under
    from openpilot.system.ui.lib.multilang import tr
    from openpilot.system.ui.widgets.scroller_tici import Scroller
    from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

    class _Layout(Widget):
      def __init__(self):
        super().__init__()
        self.model = StoppingSettingsModel(store, CP, capabilities, can_edit)
        self.page = start_page
        self.history = []
        self._build()

      def _open(self, page):
        self.history.append(self.page)
        self.page = page
        self._build()
        self.scroller.show_event()

      def _back(self):
        self.page = self.history.pop() if self.history else "root"
        self._build()
        self.scroller.show_event()

      def navigation_back(self):
        """Back is the top-left item of the settings sidebar: step up one inner page, True when it moved."""
        if not self.history:
          return False
        self._back()
        return True

      def _change(self, key, value=None, delta=None):
        self.model.change(self.page, key, value, delta)
        self._build()
        self.scroller.show_event()

      def _build(self):
        items = []
        values = []   # this page's value rows, for its one reset row
        parent = None
        page = self.page
        for row in self.model.rows(self.page):
          if row.kind == "page":
            item = button_item(row.title, "MANAGE", callback=lambda k=row.key: self._open(k))
          elif row.kind == "toggle":
            item = toggle_item(row.title, row.description, store.get_bool(row.key),
                               callback=lambda state, k=row.key: self._change(k, state), enabled=can_edit)
          elif row.kind == "condition":
            choices = list(MANUAL_WEATHER)
            selected = store.get(MANUAL_WEATHER_KEY, "clear")
            item = gated_multiple_button_item(row.title, row.description, list(WEATHER_PILL_LABELS),
                                        choices.index(selected) if selected in choices else 0, button_width=WEATHER_PILL_WIDTH, enabled=can_edit,
                                        callback=lambda index: self._change(MANUAL_WEATHER_KEY, choices[index]),
                                        selected_source=lambda: choices.index(store.get(MANUAL_WEATHER_KEY, "clear")))
            item.action_item.set_enabled(can_edit)
          else:
            # The shared value row: title, then [-] [value] [+] (the value moved from the title to between the buttons,
            # ASCII "-" instead of U+2212). Same step, same lock, same writes.
            has_default = self.model.default(page, row) is not None
            item = gated_value_step_item(row.title.rstrip(":"), row.description or None,
                                         lambda r=row: self.model.value_text(r, self.model.value(r)),
                                         on_minus=lambda k=row.key: self._change(k, delta=-1),
                                         on_plus=lambda k=row.key: self._change(k, delta=1), button_width=200, enabled=can_edit,
                                         default_text=(lambda r=row: self.model.value_text(r, self.model.default(page, r)))
                                         if has_default else None,
                                         is_default=(lambda r=row: self.model.at_default(page, r)) if has_default else None,
                                         translate=tr)
            if has_default:
              values.append(item)
          if row.kind == "toggle" and row.key == "QOLLongitudinal":
            parent = item
          if row.kind == "page":
            attach_help(item, "weather." + row.key if row.key in ("LowVisibility", "Rain", "RainStorm", "Snow") else row.key)
          else:
            attach_help(item, row.key)
          items.append(item)
        self.reset = None
        if values:
          # One reset row for the page, after its rows: asks first, then writes the whole page back (value rows to their
          # existing defaults, toggle rows and the Quality of Life switch to their shipped defaults; see
          # StoppingSettingsModel.section_defaults). Locked like those rows; shown only while one of its value rows is
          # shown, and behind the Quality of Life switch's own Tuning Level.
          rows_of_reset = tuple(values)
          self.reset = reset_section_item(lambda: self.model.section_defaults(page),
                                          lambda k, v: self.model.reset_write(page, k, v),
                                          title=lambda: tr(RESET_SECTION_TITLE), enabled=can_edit, on_done=self._after_reset)
          attach_help(self.reset, "section.reset_defaults")
          self.reset.set_visible(lambda: any(i.is_visible for i in rows_of_reset))
          self.reset.set_level_gate(lambda: tuning_level.row_visible("QOLLongitudinal"))
          items.append(self.reset)
        if parent is not None:
          # Everything on the page belongs to the Quality of Life switch: one level in (Appearance style). Visibility
          # already follows the saved switch (rows()), so this only indents; the MANAGE row keeps its behavior.
          indent_under(parent, *(i for i in items if i is not parent))
        self.scroller = Scroller(items, line_separator=True, spacing=0)

      def _after_reset(self):
        store.invalidate()
        self._build()
        self.scroller.show_event()

      def show_event(self):
        super().show_event()
        store.invalidate()
        self._build()
        self.scroller.show_event()

      def _render(self, rect):
        self.scroller.render(rect)
    return _Layout()
