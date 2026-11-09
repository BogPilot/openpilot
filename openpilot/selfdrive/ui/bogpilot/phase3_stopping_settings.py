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
    import pyray as rl
    from openpilot.system.ui.widgets import Widget
    from openpilot.system.ui.widgets.list_view import ListItem, DualButtonAction, toggle_item, button_item, multiple_button_item
    from openpilot.system.ui.widgets.scroller_tici import Scroller

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

      def _change(self, key, value=None, delta=None):
        self.model.change(self.page, key, value, delta)
        self._build()
        self.scroller.show_event()

      def _build(self):
        items = []
        if self.history:
          items.append(button_item("Back", "BACK", callback=self._back))
        for row in self.model.rows(self.page):
          if row.kind == "page":
            item = button_item(row.title, "MANAGE", callback=lambda k=row.key: self._open(k))
          elif row.kind == "toggle":
            item = toggle_item(row.title, row.description, store.get_bool(row.key),
                               callback=lambda state, k=row.key: self._change(k, state), enabled=can_edit)
          elif row.kind == "condition":
            choices = list(MANUAL_WEATHER)
            selected = store.get(MANUAL_WEATHER_KEY, "clear")
            item = multiple_button_item(row.title, row.description, ["Clear", "Low visibility", "Rain", "Storm", "Snow"],
                                        choices.index(selected) if selected in choices else 0, button_width=135,
                                        callback=lambda index: self._change(MANUAL_WEATHER_KEY, choices[index]))
            item.action_item.set_enabled(can_edit)
          else:
            action = DualButtonAction("−", "+", lambda k=row.key: self._change(k, delta=-1),
                                      lambda k=row.key: self._change(k, delta=1), enabled=can_edit)
            # DualButtonAction normally reserves the full row. A bounded action
            # width preserves the historical label, effective number and unit.
            action.set_rect(rl.Rectangle(0, 0, 300, 0))
            item = ListItem(title=lambda r=row: f"{r.title} {self.model.value(r):g}{r.unit}", action_item=action)
          items.append(item)
        self.scroller = Scroller(items, line_separator=True, spacing=0)

      def show_event(self):
        super().show_event()
        store.invalidate()
        self._build()
        self.scroller.show_event()

      def _render(self, rect):
        self.scroller.render(rect)
    return _Layout()
