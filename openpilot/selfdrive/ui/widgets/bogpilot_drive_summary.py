"""Drive Summary card: drawn over the left home column after a drive, closes on tap or screen timeout.

Same four boxes as the 0.9.7 card. Values come from DriveSummaryController (selfdrive/ui/bogpilot/drive_summary.py).
Missing values use EN DASH (U+2013): EM DASH is not in the font atlas.
"""
import time
import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.bogpilot.drive_summary import DriveSummary, DriveSummaryController, Phase, distance_value, time_parts
from openpilot.system.ui.lib.application import FontWeight, TextAlignment
from openpilot.system.ui.lib.multilang import tr, trn
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import gui_label

CARD_COLOR = rl.Color(51, 51, 51, 255)
TITLE_COLOR = rl.Color(68, 68, 68, 255)
LABEL_COLOR = rl.Color(170, 170, 170, 255)
HINT_COLOR = rl.Color(160, 160, 160, 255)
MISSING = "–"


def format_distance(meters: float, metric: bool) -> str:
  value = distance_value(meters, metric)
  if metric:
    return trn("{} kilometer", "{} kilometers", value).format(value)
  return trn("{} mile", "{} miles", value).format(value)


def format_drive_time(seconds: float) -> str:
  days, hours, minutes = time_parts(seconds)
  parts = []
  if days > 0:
    parts.append(trn("{} day", "{} days", days).format(days))
  if hours > 0 or days > 0:
    parts.append(trn("{} hour", "{} hours", hours).format(hours))
  parts.append(trn("{} minute", "{} minutes", minutes).format(minutes))
  return " ".join(parts)


def stat_rows(summary: DriveSummary | None, metric: bool) -> list[tuple[str, str]]:
  titles = (tr("% of Drive With openpilot Engaged"), tr("Drive Distance"), tr("Drive Time"),
            tr('% of Drive In "Experimental Mode"'))
  if summary is None or not summary.recorded:
    return [(title, MISSING) for title in titles]
  values = (f"{summary.engaged_pct}%", format_distance(summary.meters, metric), format_drive_time(summary.tracked_s),
            f"{summary.experimental_pct}%")
  return list(zip(titles, values, strict=True))


def footer_text(phase: Phase) -> str:
  if phase == Phase.WAITING:
    return tr("Saving drive stats...")
  if phase == Phase.NO_DRIVE:
    return tr("No drive recorded. Drives count once openpilot engages.")
  return tr("Tap to close")


class DriveSummaryCard(Widget):
  def __init__(self, controller: DriveSummaryController, params=None):
    super().__init__()
    self.controller = controller
    self.params = params if params is not None else Params()
    self.set_click_callback(controller.dismiss)

  def _render(self, rect: rl.Rectangle):
    self.controller.poll(time.monotonic())
    scale = min(1.0, max(0.5, rect.height / 895), max(0.5, rect.width / 1005))
    pad = 30 * scale
    rl.draw_rectangle_rounded(rect, 0.025, 10, CARD_COLOR)

    title_rect = rl.Rectangle(rect.x + pad, rect.y + pad, rect.width - 2 * pad, 100 * scale)
    rl.draw_rectangle_rounded(title_rect, 0.2, 10, TITLE_COLOR)
    gui_label(title_rect, tr("Drive Summary"), int(55 * scale), font_weight=FontWeight.BOLD, alignment=TextAlignment.CENTER)

    footer_h = 55 * scale
    top = title_rect.y + title_rect.height + 20 * scale
    bottom = rect.y + rect.height - pad - footer_h
    rows = stat_rows(self.controller.summary, self.params.get_bool("IsMetric"))
    row_h = max(0.0, (bottom - top) / len(rows))
    width = rect.width - 2 * pad
    for index, (title, value) in enumerate(rows):
      y = top + index * row_h
      gui_label(rl.Rectangle(rect.x + pad, y + row_h * 0.08, width, row_h * 0.34), title, int(40 * scale),
                color=LABEL_COLOR, font_weight=FontWeight.BOLD, alignment=TextAlignment.CENTER)
      gui_label(rl.Rectangle(rect.x + pad, y + row_h * 0.42, width, row_h * 0.52), value, int(75 * scale),
                font_weight=FontWeight.BOLD, alignment=TextAlignment.CENTER)

    gui_label(rl.Rectangle(rect.x + pad, bottom, width, footer_h), footer_text(self.controller.phase), int(32 * scale),
              color=HINT_COLOR, alignment=TextAlignment.CENTER)
