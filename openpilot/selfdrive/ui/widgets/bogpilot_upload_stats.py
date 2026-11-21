"""Offroad home card for Custom Log Upload Stats (right column, under the Experimental Mode button).

Shown only while the toggle is on and a manually installed uploader is writing fresh status
(selfdrive/ui/bogpilot/upload_stats.py). Otherwise it reports itself hidden and the home screen keeps its default layout.
"""
import pyray as rl

from openpilot.selfdrive.ui.bogpilot import upload_stats as US
from openpilot.selfdrive.ui.onroad.bogpilot.style import C, W, draw_text
from openpilot.system.ui.widgets import Widget

CARD_BG = rl.Color(51, 51, 51, 255)
DIM = C(170, 170, 170, 255)
WHITE = C(255, 255, 255, 255)
GOOD = C(61, 220, 151, 255)
WARN = C(255, 196, 60, 255)
PAD_X, PAD_Y = 50, 36


def card_lines(v: US.View) -> list[tuple[str, int, object, rl.Color, int]]:
  """(text, px, weight, colour, advance): advance is the baseline step down to this line."""
  out = [("Up to date" if v.caught_up else "Uploading", 56, W.DEMI, WHITE, 56),
         ("UPLOAD RATE", 30, W.DEMI, DIM, 56),
         (v.rate + " \u2191", 76, W.BOLD, WHITE, 78)]
  if v.workers:
    out.append((v.workers, 30, W.DEMI, DIM, 42))
  if v.backlog_size is not None:
    out += [("PENDING", 30, W.DEMI, DIM, 60),
            (v.backlog_size, 76, W.BOLD, WHITE, 78),
            (v.backlog_segments, 38, W.DEMI, WHITE, 50)]
    if v.backlog_note:
      tone = GOOD if v.note_tone == US.TONE_GOOD else WARN if v.note_tone == US.TONE_WARN else DIM
      out.append((v.backlog_note, 38, W.DEMI, tone, 48))
  return out


class UploadStatsCard(Widget):
  def __init__(self, reader: US.UploadStatsReader | None = None):
    super().__init__()
    self.reader = reader if reader is not None else US.UploadStatsReader()
    self.view: US.View | None = None

  def refresh(self) -> bool:
    """Read (only while the toggle is on). True when the card should be drawn."""
    self.view = self.reader.update()
    return self.view is not None

  def height(self) -> int:
    if self.view is None:
      return 0
    return int(sum(a for *_, a in card_lines(self.view)) + 2 * PAD_Y)

  def _render(self, rect: rl.Rectangle):
    if self.view is None:
      return
    rl.draw_rectangle_rounded(rect, 0.04, 10, CARD_BG)
    x, y = rect.x + PAD_X, rect.y + PAD_Y
    for text, px, weight, color, advance in card_lines(self.view):
      y += advance
      draw_text(text, x, y - px * 0.15, px, color, weight)
