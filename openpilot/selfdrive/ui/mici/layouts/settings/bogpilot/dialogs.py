"""comma 4 stand-ins for the 3X dialogs the BogPilot pages open.

The 3X pages (and onroad_policy's reboot prompt) open stock tici dialogs with gui_app.push_widget: ConfirmDialog /
alert_dialog, MultiOptionDialog, Keyboard, and the Pre-AP pedal calibration screen. On the comma 4 `install()` makes
push_widget show a mici page instead, and every answer goes back through the 3X dialog's own handler or callback
(the same DialogResult, the same selection / text), so the page code runs unchanged. Small UI only; the 3X never
installs it. Anything else is pushed as is.
"""
from __future__ import annotations

import re

import pyray as rl

from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import InfoCard, LiveCard, chunk_text, TEXT, HINT, GREEN
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.system.ui.widgets.scroller import NavScroller

_TAG = re.compile(r"<[^>]+>")


def _plain(text: str) -> str:
  text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", str(text), flags=re.I)
  return " ".join(_TAG.sub(" ", text).replace("&nbsp;", " ").replace("&amp;", "&").split())


def confirm_text(dialog) -> str:
  if getattr(dialog, "_rich", False):
    html = getattr(dialog, "html", None)
    if html:
      return _plain(html)
    elements = getattr(getattr(dialog, "_html_renderer", None), "elements", [])
    return " ".join(e.content for e in elements if getattr(e, "content", ""))
  return _label_text(getattr(dialog, "_label", None))


def _label_text(label) -> str:
  """Text of a tici Label (its _text, a str or a callable) or a UnifiedLabel (.text)."""
  if label is None:
    return ""
  text = getattr(label, "_text", None)
  if text is None:
    text = getattr(label, "text", "")
  if callable(text):
    text = text()
  return str(text or "")


def _button_text(button) -> str:
  return _label_text(getattr(button, "_label", None))


DESTRUCTIVE = ("reset", "delete", "erase", "remove", "clear", "uninstall", "wipe", "forget", "restore", "discard")


def _destructive(text: str, confirm: str) -> bool:
  """Red slider (stock "slide to forget" / "slide to delete" look) when the 3X button or question names a destructive
  action. Look only: which actions ask, and what they do, is the 3X page's."""
  words = f"{confirm} {text}".lower()
  return any(w in words for w in DESTRUCTIVE)


class ConfirmPage(NavWidget):
  """ConfirmDialog with a Cancel button: the question on top (marquee when long), the stock comma 4 slide-to-confirm
  below. Sliding runs the 3X dialog's own confirm handler; a swipe down is its Cancel.

  The page keeps the lock of the 3X row that opened it (row_model.opening_gate): while that row is locked (the car
  started, a parent switch went off, ...) the slider cannot be dragged or confirmed and the lock note replaces the
  question. A dialog opened outside a row (the reboot prompt) has no lock of its own; its handler keeps the 3X rule
  (Reboot Now refused while engaged).

  alert_dialog (one OK button, no Cancel) is not a confirmation: it stays the text cards + one OK card (AlertPage)."""

  def __init__(self, dialog, gate=None):
    super().__init__()
    from openpilot.system.ui.widgets.label import UnifiedLabel
    from openpilot.system.ui.widgets.slider import BigSlider, RedBigSlider
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import mici_title
    self.dialog = dialog
    self.gate = gate or (lambda: True)
    self.set_rect(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
    confirm = _button_text(getattr(dialog, "_confirm_button", None)) or "OK"
    self.question = confirm_text(dialog)
    self.slider_title = f"slide to {mici_title(confirm)}"
    icon = gui_app.texture("icons_mici/setup/small_slider/slider_arrow.png", 64, 55)
    cls = RedBigSlider if _destructive(self.question, confirm) else BigSlider
    self.red = cls is RedBigSlider
    self.slider = self._child(cls(self.slider_title, icon, confirm_callback=self._confirmed))
    self.slider.set_enabled(lambda: self.unlocked() and not self.is_dismissing)
    self._label = self._child(UnifiedLabel(lambda: self.question if self.unlocked() else self.locked_note(), font_size=30,
                                           font_weight=FontWeight.MEDIUM, text_color=TEXT, wrap_text=False, scroll=True))
    self.confirmed = False
    self.set_back_callback(self._swiped)

  def unlocked(self) -> bool:
    try:
      return bool(self.gate())
    except Exception:
      return False               # fail closed

  @staticmethod
  def locked_note() -> str:
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import LOCKED_WHILE_DRIVING
    from openpilot.system.ui.lib.multilang import tr
    return tr(LOCKED_WHILE_DRIVING)

  def _confirmed(self):
    if not self.unlocked():      # locked between the drag and the end of the slide animation
      self.slider.reset()
      return
    self.confirmed = True
    self.dialog._confirm_button_callback()

  def _swiped(self):
    if self.confirmed:
      return
    callback = getattr(self.dialog, "_callback", None)
    if callback is not None:
      callback(DialogResult.CANCEL)

  def _update_state(self):
    super()._update_state()
    if not self.unlocked() and not self.slider.confirmed:
      self.slider.reset()        # drop a drag in progress the moment the row locks

  def _render(self, rect):
    self._label.render(rl.Rectangle(rect.x + 20, rect.y + 8, rect.width - 40, 44))
    sw, sh = self.slider.rect.width, self.slider.rect.height
    self.slider.render(rl.Rectangle(rect.x + (rect.width - sw) / 2, rect.y + rect.height - sh, sw, sh))


class AlertPage(NavScroller):
  """alert_dialog (one OK button): the text as grey cards, then the OK card (the 3X dialog's own handler). A swipe
  down is OK too."""

  def __init__(self, dialog):
    super().__init__()
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import mici_title
    self.dialog = dialog
    confirm = _button_text(getattr(dialog, "_confirm_button", None)) or "OK"
    cards = [InfoCard(lambda: "", lambda p=p: p) for p in chunk_text(confirm_text(dialog))] or [InfoCard(lambda: "", lambda: "")]
    cards.append(LiveCard(lambda: mici_title(confirm), on_tap=dialog._confirm_button_callback))
    self._scroller.add_widgets(cards)
    self.set_back_callback(lambda: dialog._callback and dialog._callback(DialogResult.CONFIRM))


class OptionsPage(NavScroller):
  """MultiOptionDialog: title, then one card per option (green pill on the current one). A tap selects it and
  confirms through the 3X dialog; a swipe down is Cancel."""

  def __init__(self, dialog):
    super().__init__()
    self.dialog = dialog
    cards = [InfoCard(lambda: str(dialog.title), lambda: "")]
    for option in dialog.options:
      cards.append(LiveCard(lambda o=option: str(o), on_tap=lambda o=option: self._pick(o), pill=lambda o=option: dialog.selection == o))
    self._scroller.add_widgets(cards)
    self.set_back_callback(lambda: dialog._callback and dialog._callback(DialogResult.CANCEL))

  def _pick(self, option):
    self.dialog.selection = option
    self.dialog._set_result(DialogResult.CONFIRM)


def keyboard_page(dialog):
  """Keyboard: the stock mici BigInputDialog; Enter hands the text to the 3X keyboard and confirms it."""
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
  hint = str(getattr(getattr(dialog, "_title", None), "text", "")) or "enter text"

  def done(text):
    dialog.set_text(text)
    if dialog._callback:
      dialog._callback(DialogResult.CONFIRM)

  page = BigInputDialog(hint, default_text=dialog.text, minimum_length=getattr(dialog, "_min_text_size", 0), confirm_callback=done)
  page.set_back_callback(lambda: dialog._callback and dialog._callback(DialogResult.CANCEL))
  return page


class PedalCalPage(NavWidget):
  """Pre-AP pedal calibration screen: the same PedalCalSession and Screen (title, steps, instruction, detail,
  buttons) drawn small; buttons go through the 3X screen's own _press (which closes this page). A swipe down is
  Cancel, as leaving the 3X screen always disarms."""

  def __init__(self, screen):
    super().__init__()
    self.screen = screen
    self.set_rect(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
    self._buttons = [LiveCard(lambda i=i: self._label(i), on_tap=lambda i=i: self._press(i)) for i in range(2)]
    for b in self._buttons:
      b.set_rect(rl.Rectangle(0, 0, 200, 60))
    self.set_back_callback(self._swiped)
    self._scr = None
    self._closed = False

  def _label(self, i):
    return self._scr.buttons[i] if self._scr is not None and i < len(self._scr.buttons) else ""

  def _press(self, i):
    if self._scr is not None and i < len(self._scr.buttons):
      self._closed = self._scr.buttons[i] in ("Cancel", "Close", "Done")
      self.screen._press(self._scr.buttons[i])

  def show_event(self):
    super().show_event()
    self.screen.show_event()     # session.begin()

  def hide_event(self):
    self.screen.hide_event()     # session.close(): leaving always disarms
    super().hide_event()

  def _swiped(self):
    if self._scr is not None and not self._closed and "Cancel" in self._scr.buttons:
      self.screen.session.cancel()

  def _render(self, rect):
    scr = self.screen.session.tick()
    self._scr = scr
    font_b, font = gui_app.font(FontWeight.BOLD), gui_app.font(FontWeight.NORMAL)
    x, y = rect.x + 20, rect.y + 12
    rl.draw_text_ex(font_b, str(scr.title), rl.Vector2(x, y), 30, 0, HINT)
    steps = "   ".join(f"{'[x]' if s == 'done' else ('[!]' if s == 'failed' else ('[>]' if s == 'active' else '[ ]'))} {lab}"
                       for lab, s in scr.steps)
    rl.draw_text_ex(font, steps, rl.Vector2(x, y + 36), 22, 0, TEXT)
    rl.draw_text_ex(font_b, str(scr.instruction), rl.Vector2(x, y + 66), 28, 0, GREEN if scr.phase == "saved" else TEXT)
    for i, line in enumerate(chunk_text(scr.detail, 46)[:3]):
      rl.draw_text_ex(font, line, rl.Vector2(x, y + 100 + i * 26), 22, 0, TEXT)
    n = len(scr.buttons)
    for i in range(min(n, 2)):
      bw = 240 if n == 2 else 300
      bx = rect.x + (rect.width - (n * bw + (n - 1) * 16)) / 2 + i * (bw + 16)
      self._buttons[i].set_rect(rl.Rectangle(bx, rect.y + rect.height - 70, bw, 60))
      self._buttons[i].render(rl.Rectangle(bx, rect.y + rect.height - 70, bw, 60))


class RadarToolPage(NavWidget):
  """Pre-AP Test Radar / Calibrate Radar on the comma 4: the same RadarToolSession and ScreenState as the 3X screen, drawn compact
  (preap_radar_tools.draw_radar_screen). A swipe down closes it, as every comma 4 page; leaving always closes the `can` subscription."""

  def __init__(self, screen):
    super().__init__()
    self.screen = screen
    self.set_rect(rl.Rectangle(0, 0, gui_app.width, gui_app.height))

  def show_event(self):
    super().show_event()
    self.screen.show_event()     # session.begin(): opens the can subscription

  def hide_event(self):
    self.screen.hide_event()     # session.close()
    super().hide_event()

  def _render(self, rect):
    from openpilot.selfdrive.ui.bogpilot.preap_radar_tools import draw_radar_screen
    state = self.screen.session.tick()
    self.screen.state = state
    draw_radar_screen(rect, state, compact=True)


def to_mici(widget):
  """The comma 4 page for a 3X dialog, or None to push `widget` unchanged."""
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.keyboard import Keyboard
  from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
  if isinstance(widget, ConfirmDialog):
    if not getattr(widget, "_cancel_text", ""):
      return AlertPage(widget)
    from openpilot.selfdrive.ui.bogpilot.row_model import opening_gate
    return ConfirmPage(widget, gate=opening_gate())
  if isinstance(widget, MultiOptionDialog):
    return OptionsPage(widget)
  if isinstance(widget, Keyboard):
    return keyboard_page(widget)
  if type(widget).__name__ == "PedalCalibrationScreen" and hasattr(widget, "session") and hasattr(widget, "_press"):
    return PedalCalPage(widget)
  if type(widget).__name__ == "RadarToolScreen" and hasattr(widget, "session") and hasattr(widget, "_press"):
    return RadarToolPage(widget)
  return None


_installed = False


def install(app=None) -> bool:
  """Route 3X dialogs to their comma 4 pages (small UI only). Idempotent. Returns True when installed."""
  global _installed
  app = app or gui_app
  if _installed or app.big_ui():
    return _installed
  original = app.push_widget

  def push_widget(widget):
    try:
      page = to_mici(widget)
    except Exception:
      page = None   # never lose a dialog: show the 3X one if its comma 4 page cannot be built
    return original(page if page is not None else widget)

  app.push_widget = push_widget
  _installed = True
  return True


__all__ = ["ConfirmPage", "AlertPage", "OptionsPage", "PedalCalPage", "RadarToolPage", "keyboard_page", "to_mici", "install", "confirm_text"]
