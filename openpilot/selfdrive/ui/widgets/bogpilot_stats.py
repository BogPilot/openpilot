"""The existing three-row BogPilot stats card, using read-only on-device data.

Unavailable placeholder uses EN DASH (U+2013) because the frozen font atlas
loads EXTRA_FONT_CHARS with U+2013 but not EM DASH U+2014 (which rendered as "?").
"""
import time
import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.bogpilot.offroad_stats import read_rows
from openpilot.system.ui.lib.application import FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import gui_label


class BogPilotStatsWidget(Widget):
  def __init__(self, params=None):
    super().__init__()
    self.params = params if params is not None else Params()
    self._last_refresh = 0.0
    self._rows = None

  def _render(self, rect: rl.Rectangle):
    if self._rows is None or time.monotonic() - self._last_refresh >= 10:
      self._rows = read_rows(self.params)
      self._last_refresh = time.monotonic()
    rl.draw_rectangle_rounded(rect, 0.025, 10, rl.Color(51, 51, 51, 255))
    row_height = rect.height / 3
    scale = min(1.0, max(0.5, (rect.width - 100) / 665), max(0.5, row_height / 265))
    pad = 50 * scale
    width = rect.width - 2 * pad
    column = width / 3
    unit = tr("KM") if self.params.get_bool("IsMetric") else tr("Miles")
    titles = (tr("ALL TIME (ON DEVICE)"), tr("PAST WEEK (ON DEVICE)"), tr("BOGPILOT"))
    for index, (title, row) in enumerate(zip(titles, self._rows, strict=True)):
      x, y = rect.x + pad, rect.y + index * row_height + 15 * scale
      gui_label(rl.Rectangle(x, y, width, 55 * scale), title, int(44 * scale), font_weight=FontWeight.MEDIUM)
      values = (row.drives, row.distance, row.hours)
      for col, (value, label) in enumerate(zip(values, (tr("Drives"), unit, tr("Hours")), strict=True)):
        value_text = str(value) if row.available else "–"  # EN DASH U+2013 (in EXTRA_FONT_CHARS); EM DASH U+2014 missing from atlas -> "?"
        gui_label(rl.Rectangle(x + col * column, y + 65 * scale, column, 75 * scale), value_text, int(65 * scale))
        gui_label(rl.Rectangle(x + col * column, y + 140 * scale, column, 50 * scale), label, int(38 * scale), color=rl.Color(160, 160, 160, 255))
      if not row.available:
        gui_label(rl.Rectangle(x, y + 195 * scale, width, 40 * scale), tr(row.status), int(30 * scale), color=rl.Color(160, 160, 160, 255))
