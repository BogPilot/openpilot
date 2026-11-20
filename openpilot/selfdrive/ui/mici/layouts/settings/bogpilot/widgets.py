"""comma 4 cards for BogPilot settings rows, and the two pages a card can open (option list, value adjuster).

Cards are the stock mici BigButton (402x180, swipe-scrolled). Each card reads and acts through a
selfdrive/ui/bogpilot/row_model.Row, i.e. through the 3X row itself; nothing here knows a param key.
"""
from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.bogpilot import row_model as rm
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, GreyBigButton
from openpilot.system.ui.lib.application import FontWeight, MousePos, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.system.ui.widgets.scroller import NavScroller

GREEN = rl.Color(51, 171, 76, 255)
GREY = rl.Color(57, 57, 57, 255)
PRESSED = rl.Color(80, 80, 80, 255)
TEXT = rl.Color(255, 255, 255, int(255 * 0.9))
TEXT_DIM = rl.Color(255, 255, 255, int(255 * 0.35))
HINT = rl.Color(0xAA, 0xAA, 0xAA, 255)
AMBER = rl.Color(255, 184, 0, 255)      # value outline while it is not the default (3X HIGHLIGHT_COLOR)
INFO_CHARS = 88                          # one grey info card holds about this many characters at 36 px


def chunk_text(text: str, size: int = INFO_CHARS) -> list[str]:
  """Split a long text into card-sized pieces at word boundaries (stock mici shows long text as several grey cards)."""
  words, out, cur = " ".join(str(text).split()).split(" "), [], ""
  for w in words:
    if not w:
      continue
    if cur and len(cur) + 1 + len(w) > size:
      out.append(cur)
      cur = w
    else:
      cur = f"{cur} {w}" if cur else w
  if cur:
    out.append(cur)
  return out


class LiveCard(BigButton):
  """BigButton whose title / value / enabled follow callables, with an optional switch pill (BigToggle look)."""

  def __init__(self, title: Callable[[], str], value: Callable[[], str] = lambda: "", on_tap: Callable[[], object] | None = None,
               enabled: Callable[[], bool] = lambda: True, pill: Callable[[], bool] | None = None, icon=None):
    self._pill = pill
    super().__init__("", "", icon)
    self._title_src, self._value_src = title, value
    self.set_enabled(enabled)
    if on_tap is not None:
      self.set_click_callback(on_tap)
    self._sync_text()

  def _load_images(self):
    super()._load_images()
    if self._pill is not None:
      self._txt_pill_on = gui_app.texture("icons_mici/buttons/toggle_pill_enabled.png", 84, 66)
      self._txt_pill_off = gui_app.texture("icons_mici/buttons/toggle_pill_disabled.png", 84, 66)

  def _sync_text(self):
    try:
      title, value = str(self._title_src()), str(self._value_src())
    except Exception:
      return
    if title != self.text:
      self.set_text(title)
    if value != self.value:
      self.set_value(value)

  def _update_state(self):
    super()._update_state()
    self._sync_text()

  def _draw_content(self, btn_y: float):
    super()._draw_content(btn_y)
    if self._pill is not None:
      try:
        on = bool(self._pill())
      except Exception:
        on = False
      tex = self._txt_pill_on if on else self._txt_pill_off
      rl.draw_texture_ex(tex, (self._rect.x + self._rect.width - tex.width, btn_y), 0, 1.0, rl.WHITE)


class InfoCard(GreyBigButton):
  """Read-only grey card with live text."""

  def __init__(self, title: Callable[[], str], value: Callable[[], str] = lambda: ""):
    super().__init__("", "")
    self._title_src, self._value_src = title, value
    self._sync()

  def _sync(self):
    try:
      title, value = str(self._title_src()), str(self._value_src())
    except Exception:
      return
    if title != self.text:
      self.set_text(title)
    if value != self.value:
      self.set_value(value)

  def _update_state(self):
    super()._update_state()
    self._sync()


def cards_for(row: rm.Row, open_choice: Callable, open_stepper: Callable) -> list[Widget]:
  """The comma 4 cards for one 3X row (see row_model.card_labels for their texts)."""
  labels = rm.card_labels(row)

  def text(i, part):
    return lambda: rm.card_labels(row)[i][part] if i < len(rm.card_labels(row)) else ""

  if row.kind == rm.TOGGLE:
    return [LiveCard(text(0, 0), on_tap=row.toggle, enabled=row.toggle_enabled, pill=row.state)]
  if row.kind == rm.MANAGE_TOGGLE:
    return [LiveCard(text(0, 0), on_tap=row.toggle, enabled=row.toggle_enabled, pill=row.state),
            LiveCard(text(1, 0), text(1, 1), on_tap=row.manage, enabled=row.manage_enabled)]
  if row.kind == rm.BUTTON:
    return [LiveCard(text(0, 0), text(0, 1), on_tap=row.press, enabled=row.enabled)]
  if row.kind == rm.CHOICE:
    return [LiveCard(text(0, 0), text(0, 1), on_tap=lambda: open_choice(RowChoice(row)), enabled=row.enabled)]
  if row.kind == rm.STEPPER:
    return [LiveCard(text(0, 0), text(0, 1), on_tap=lambda: open_stepper(row), enabled=row.enabled)]
  if row.kind == rm.DUAL:
    out = []
    for side in range(len(labels)):
      card = LiveCard(text(side, 0), on_tap=lambda side=side: row.press_dual(side), enabled=row.enabled)
      card.set_visible(lambda side=side: side < len(row.dual()) and row.dual()[side][1])
      out.append(card)
    return out
  # INFO (and, defensively, anything unknown): read only
  return [InfoCard(text(0, 0), text(0, 1))]


class RowChoice:
  """Option-list adapter over a CHOICE row."""

  def __init__(self, row: rm.Row):
    self.row = row

  def title(self):
    return self.row.title()

  def description(self):
    return self.row.description()

  def options(self):
    return self.row.options()

  def selected(self):
    return self.row.selected()

  def enabled(self):
    return self.row.enabled()

  def choose(self, i):
    return self.row.choose(i)


class ChoicePage(NavScroller):
  """One card per option; the stored one shows the green pill. A tap chooses it (through the 3X row) and closes."""

  def __init__(self, source):
    super().__init__()
    self._source = source
    cards: list[Widget] = [InfoCard(source.title, lambda: "")]
    for i, _ in enumerate(source.options()):
      cards.append(LiveCard(lambda i=i: self._label(i), on_tap=lambda i=i: self._choose(i), enabled=source.enabled,
                            pill=lambda i=i: source.selected() == i))
    for piece in chunk_text(source.description())[:6]:
      cards.append(InfoCard(lambda: "", lambda piece=piece: piece))
    self._scroller.add_widgets(cards)

  def _label(self, i):
    opts = self._source.options()
    return opts[i] if i < len(opts) else ""

  def _choose(self, i):
    if not self._source.enabled():
      return
    self.dismiss(lambda: self._source.choose(i))


class StepButton(Widget):
  """Round [-] / [+] or a pill (Mute / Min / Reset ...). The minus and plus are drawn shapes, never font glyphs."""

  def __init__(self, glyph: str, on_tap: Callable[[], object], enabled: Callable[[], bool], label: Callable[[], str] = lambda: ""):
    super().__init__()
    self.glyph, self._label = glyph, label
    self.set_click_callback(on_tap)
    self.set_enabled(enabled)
    self._font = None

  def _render(self, rect):
    color = (PRESSED if self.is_pressed else GREY)
    fg = TEXT if self.enabled else TEXT_DIM
    if not self.enabled:
      color = rl.Color(color.r, color.g, color.b, 150)
    if self.glyph in ("minus", "plus"):
      cx, cy, r = rect.x + rect.width / 2, rect.y + rect.height / 2, min(rect.width, rect.height) / 2
      rl.draw_circle(int(cx), int(cy), r, color)
      bar = r * 0.9
      rl.draw_rectangle_rounded(rl.Rectangle(cx - bar / 2, cy - 4, bar, 8), 1.0, 6, fg)
      if self.glyph == "plus":
        rl.draw_rectangle_rounded(rl.Rectangle(cx - 4, cy - bar / 2, 8, bar), 1.0, 6, fg)
      return
    rl.draw_rectangle_rounded(rect, 1.0, 10, color)
    if self._font is None:
      self._font = gui_app.font(FontWeight.MEDIUM)
    text = str(self._label())
    size = measure_text_cached(self._font, text, 30)
    rl.draw_text_ex(self._font, text, rl.Vector2(rect.x + (rect.width - size.x) / 2, rect.y + (rect.height - size.y) / 2), 30, 0, fg)


class StepperPage(NavWidget):
  """The Alert Volume Controller row, adapted to the 536x240 comma 4 screen:

      title                                   (page note when locked)
      [ - ]        value        [ + ]
                 default: X
      [leading ...]   [trailing ...]

  Each button presses the same button of the 3X row (row_model.Row), so ranges, floors, units and locks are the 3X
  ones. Swipe down to close."""

  def __init__(self, row: rm.Row, note: Callable[[], str] = lambda: ""):
    super().__init__()
    self.row, self._note = row, note
    self.set_rect(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
    self._minus = self._child(StepButton("minus", row.minus, row.enabled))
    self._plus = self._child(StepButton("plus", row.plus, row.enabled))
    self._extras: list[StepButton] = []
    for i in range(len(row.leading())):
      self._extras.append(self._child(StepButton("pill", lambda i=i: row.press_leading(i), row.enabled,
                                                 lambda i=i: self._safe(row.leading, i))))
    for i in range(len(row.trailing())):
      self._extras.append(self._child(StepButton("pill", lambda i=i: row.press_trailing(i), row.enabled,
                                                 lambda i=i: self._safe(row.trailing, i))))
    self._fonts: dict = {}

  @staticmethod
  def _safe(source, i):
    items = source()
    return items[i] if i < len(items) else ""

  def _font(self, weight):
    if weight not in self._fonts:
      self._fonts[weight] = gui_app.font(weight)
    return self._fonts[weight]

  def _text(self, text, x, y, size, color, weight=FontWeight.NORMAL, center=False, max_w=None):
    font = self._font(weight)
    while max_w is not None and size > 20 and measure_text_cached(font, text, size).x > max_w:
      size -= 2
    w = measure_text_cached(font, text, size)
    if center:
      x -= w.x / 2
    rl.draw_text_ex(font, text, rl.Vector2(x, y), size, 0, color)
    return w

  def _render(self, rect):
    pad = 20
    x0, y0, w = rect.x + pad, rect.y + 14, rect.width - 2 * pad
    self._text(self.row.title(), x0, y0, 34, TEXT, FontWeight.BOLD, max_w=w)
    note = self._note() if not self.row.enabled() else ""
    if note:
      self._text(note, x0, y0 + 38, 24, AMBER, max_w=w)
    cy = rect.y + 112
    size = 84
    self._minus.render(rl.Rectangle(x0, cy - size / 2, size, size))
    self._plus.render(rl.Rectangle(x0 + w - size, cy - size / 2, size, size))
    value = self.row.value()
    vw = self._text(value, rect.x + rect.width / 2, cy - 30, 60, TEXT if self.row.enabled() else TEXT_DIM, FontWeight.BOLD,
                    center=True, max_w=w - 2 * size - 40)
    if self.row.highlighted():
      box = rl.Rectangle(rect.x + rect.width / 2 - vw.x / 2 - 14, cy - 36, vw.x + 28, 72)
      rl.draw_rectangle_rounded_lines_ex(box, 1.0, 12, 3, AMBER)
    hint = self.row.hint()
    if hint:
      self._text(hint, rect.x + rect.width / 2, cy + 40, 24, HINT, center=True, max_w=w)
    if self._extras:
      bw, bh, gap = 130, 44, 14
      total = len(self._extras) * bw + (len(self._extras) - 1) * gap
      bx = rect.x + (rect.width - total) / 2
      for b in self._extras:
        b.render(rl.Rectangle(bx, rect.y + rect.height - bh - 14, bw, bh))
        bx += bw + gap


__all__ = ["LiveCard", "InfoCard", "cards_for", "RowChoice", "ChoicePage", "StepButton", "StepperPage", "chunk_text"]
