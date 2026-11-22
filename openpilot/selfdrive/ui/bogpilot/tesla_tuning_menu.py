"""Settings > Vehicle Settings > TESLA TUNING: the adjustable AP1 / Pre-AP comfort tuning values.

Store, model and layout for one page. Rows come from opendbc tesla_ap1/tesla_tuning.py (the table the consumers read), so a row
shows the value the car code really uses, the bounds are the same ones the consumers clamp to, and an edit reaches the consumer
through the file store:

  UI row  ->  set_value()  ->  /data/params_bogpilot/TeslaTuning<Key>  ->  tesla_tuning.get() in the consumer module
                                                                              (long_smooth, actuator_plan, regen_aware, curve brake,
                                                                               comfort_regen, vdas_constants), read when the process starts.

The page is shown only for an AP1 Model S, AP1 Model X or Pre-AP Model S and only at Tuning Level Advanced or higher. A row shows only on
the cars it applies to. The page is locked while the car is on (onroad_policy "tesla_tuning"): the values are read at start.
Value rows use the Alert Volume layout: label, small -, value, +. The minus is ASCII U+002D (the font has no U+2212).
"""
from __future__ import annotations

PAGE_KEY = "tesla_tuning"
PAGE_TITLE = "Tesla Tuning"
PILL_LABEL = "TESLA TUNING"
RESET_TITLE = "Reset to Tesla defaults"
RESET_CONFIRM = "Reset every Tesla Tuning value to its Tesla starting value?"
MINUS = "-"
PLUS = "+"
GROUP_TITLES = (("accel_braking", "Acceleration and Braking"), ("stop_start", "Stopping and Starting"), ("curves_preap", "Curves and Pre-AP"))
LEGACY_TESLAS = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS")


def _tt():
  from opendbc.car.tesla_ap1 import tesla_tuning
  return tesla_tuning


def controls():
  """Control ids of the page (keys of every row), for the menu's Tuning Level and registration."""
  return tuple(_tt().KEYS)


def read_value(key: str) -> float:
  """What the row shows: the saved value (clamped), else the shipped value."""
  tt = _tt()
  saved = tt.stored(key)
  return tt.BY_KEY[key].shipped if saved is None else saved


def is_default(key: str) -> bool:
  return read_value(key) == _tt().BY_KEY[key].shipped


def value_text(key: str) -> str:
  row = _tt().BY_KEY[key]
  return f"{read_value(key):.{row.decimals}f}"


def default_text(key: str) -> str:
  row = _tt().BY_KEY[key]
  return f"{row.shipped:.{row.decimals}f}" + (f" {row.unit}" if row.unit else "")


def set_value(key: str, value) -> float:
  """Clamp to the row's bounds and save. A value equal to the shipped one removes the file (the row is untouched again)."""
  from openpilot.common.bogpilot_store import remove_file, write_text
  tt = _tt()
  row = tt.BY_KEY[key]
  v = round(row.clamp(value), 4)
  if v == row.shipped:
    remove_file(tt.file_key(key))
    return v
  if not write_text(tt.file_key(key), f"{v:g}"):
    raise OSError(f"could not write {key}")
  return v


def nudge(key: str, direction: int) -> float:
  row = _tt().BY_KEY[key]
  return set_value(key, read_value(key) + direction * row.step)


def reset_table() -> dict[str, float]:
  """Every row of the section back to its Tesla starting value."""
  return {r.key: r.shipped for r in _tt().ROWS}


def current_car() -> str:
  try:
    from openpilot.selfdrive.ui.ui_state import ui_state
    return str(ui_state.CP.carFingerprint)
  except Exception:
    return ""


def pill_visible(car_fn=None) -> bool:
  """Only for an AP1 Model S / Model X or a Pre-AP Model S (the Tuning Level is applied by the menu through the page's rows)."""
  return ((car_fn or current_car)() in LEGACY_TESLAS)


def create_tesla_tuning_layout(car_fn=None, editable=None):
  from openpilot.selfdrive.ui.bogpilot import onroad_policy
  from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_value_step_item, reset_section_item
  from openpilot.selfdrive.ui.bogpilot.tesla_start_values import tuning_start_text
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import text_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  car = car_fn or current_car
  can_edit = editable or onroad_policy.editor(PAGE_KEY)
  tt = _tt()

  class TeslaTuningLayout(Widget):
    def __init__(self):
      super().__init__()
      self.rows = {}
      items = []
      for group, title in GROUP_TITLES:
        header = text_item(lambda title=title: tr(title), "")
        group_rows = [r for r in tt.ROWS if r.group == group]
        header.set_visible(lambda rows=group_rows: any(car() in r.cars for r in rows))
        items.append(header)
        for row in group_rows:
          item = gated_value_step_item(
            lambda row=row: tr(row.title),
            lambda row=row: tr(row.what),
            lambda key=row.key: value_text(key),
            on_minus=lambda key=row.key: self.step(key, -1),
            on_plus=lambda key=row.key: self.step(key, 1),
            minus=MINUS, plus=PLUS, button_width=150, enabled=can_edit,
            default_text=lambda key=row.key: default_text(key),
            is_default=lambda key=row.key: is_default(key),
            translate=tr)
          item.set_visible(lambda row=row: car() in row.cars)
          attach_help(item, row.key, extra=lambda key=row.key: tuning_start_text(key, car()))
          self.rows[row.key] = item
          items.append(item)
      self.reset = reset_section_item(reset_table, lambda key, value: set_value(key, value), title=lambda: tr(RESET_TITLE),
                                      confirm_text=RESET_CONFIRM, enabled=can_edit)
      attach_help(self.reset, "section.reset_defaults")
      items.append(self.reset)
      self.scroller = Scroller(items, line_separator=True, spacing=0)

    def step(self, key, direction):
      if can_edit():
        nudge(key, direction)

    def show_event(self):
      super().show_event()
      self.scroller.show_event()

    def _render(self, rect):
      self.scroller.render(rect)

  return TeslaTuningLayout()
