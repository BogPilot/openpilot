"""BogPilot list actions that honour their own lock (D2, option 2: stock list_view.py stays byte-identical).

Stock v0.11.2 `system/ui/widgets/list_view.py` has two gaps the BogPilot settings panels hit while onroad:

* `DualButtonAction` never passes its `enabled` state to its two `Button`s. They are built enabled, and each Button
  gates touches on its own `enabled` (`Widget.render`), so a "locked" dual row still fires and does not look dimmed.
* `MultipleButtonAction` is always built `enabled=True`, and `_handle_mouse_release` moves the highlight before the
  callback runs, so a caller that locks only the `ListItem` (not the action) gets a live, mis-highlighted row.

The classes below subclass the stock actions and change only those two things. Every BogPilot editor still refuses
the write itself while onroad. These classes fix the UI gate (look and touch); they are not the safety check.
The factories mirror the stock `dual_button_item` / `multiple_button_item` signatures and return a stock `ListItem`.

`gated_value_step_item` is the shared value row, `[leading...] [-] [value] [+] [trailing...]` on one line (the Alert
Volume layout). It is a GatedMultipleButtonAction underneath, so locked / greyed / hidden behave exactly like the
other gated rows. It can show a small grey "default: X" hint under the value and outline the value when it is not
the default. `reset_section_item` is the one "Reset section to defaults" row per section: it asks first, then writes
only that section's keys back to the defaults the caller passes in (see step_defaults.py).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets.list_view import (BUTTON_HEIGHT, BUTTON_WIDTH, ITEM_DESC_TEXT_COLOR, RIGHT_ITEM_PADDING,
                                                   ButtonAction, DualButtonAction, ListItem, MultipleButtonAction)
from openpilot.selfdrive.ui.bogpilot.step_defaults import default_hint, reset_section

Enabled = bool | Callable[[], bool]


def _gate(action, callback: Callable | None) -> Callable | None:
  if callback is None:
    return None

  def gated(*args):
    if action.enabled:
      return callback(*args)
    return None
  return gated


class GatedDualButtonAction(DualButtonAction):
  """DualButtonAction whose buttons follow the action's `enabled` (look and touch), with gated callbacks."""

  def __init__(self, left_text, right_text, left_callback: Callable | None = None, right_callback: Callable | None = None,
               enabled: Enabled = True):
    super().__init__(left_text, right_text, None, None, enabled)
    self.left_button.set_click_callback(_gate(self, left_callback))
    self.right_button.set_click_callback(_gate(self, right_callback))
    # Resolved each frame by Button.render: dims the button and stops touch processing while locked.
    self.left_button.set_enabled(lambda: self.enabled)
    self.right_button.set_enabled(lambda: self.enabled)


class GatedMultipleButtonAction(MultipleButtonAction):
  """MultipleButtonAction that takes an `enabled` lock, ignores taps while locked, and can show the stored choice.

  `selected_source`, when given, returns the stored index. The highlight is re-read from it every frame and after
  each tap, so a refused or pending write can never leave a choice highlighted that is not stored.
  Without it, an enabled tap behaves exactly like stock (highlight follows the tap)."""

  def __init__(self, buttons, button_width: int, selected_index: int = 0, callback: Callable | None = None,
               enabled: Enabled = True, selected_source: Callable[[], int] | None = None):
    super().__init__(buttons, button_width, selected_index, callback=callback)
    self.set_enabled(enabled)
    self._selected_source = selected_source
    self._sync_selected()

  def _sync_selected(self) -> None:
    if self._selected_source is None:
      return
    try:
      self.set_selected_button(int(self._selected_source()))
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
      pass   # keep the last shown index; never raise from render

  def _render(self, rect):
    self._sync_selected()
    return super()._render(rect)

  def _handle_mouse_release(self, mouse_pos):
    if not self.enabled:
      return
    super()._handle_mouse_release(mouse_pos)
    self._sync_selected()


def gated_dual_button_item(left_text, right_text, left_callback: Callable | None = None, right_callback: Callable | None = None,
                           description=None, enabled: Enabled = True) -> ListItem:
  action = GatedDualButtonAction(left_text, right_text, left_callback, right_callback, enabled)
  return ListItem(title="", description=description, action_item=action)


def gated_multiple_button_item(title, description, buttons, selected_index: int, button_width: int = BUTTON_WIDTH,
                               callback: Callable | None = None, icon: str = "", enabled: Enabled = True,
                               selected_source: Callable[[], int] | None = None) -> ListItem:
  action = GatedMultipleButtonAction(buttons, button_width, selected_index, callback=callback, enabled=enabled,
                                     selected_source=selected_source)
  return ListItem(title=title, description=description, icon=icon, action_item=action)


MINUS = "-"   # ASCII U+002D: the Inter atlas has no U+2212 (it renders as '?')
PLUS = "+"
STEP_BUTTON_WIDTH = 150
HINT_FONT_SIZE = 28
HINT_COLOR = ITEM_DESC_TEXT_COLOR             # the same grey as row descriptions
HIGHLIGHT_COLOR = rl.Color(255, 184, 0, 255)  # value outline while it is not the default
HIGHLIGHT_THICKNESS = 4
RESET_SECTION_TITLE = "Reset section to defaults"
RESET_BUTTON_TEXT = "RESET"
RESET_CONFIRM_TEXT = "Reset every setting in this section to its default?"
RESET_FAILED_TEXT = "Reset did not finish. Some settings in this section may not be at their defaults."


class GatedValueStepAction(GatedMultipleButtonAction):
  """GatedMultipleButtonAction laid out as [leading...] [-] [value] [+] [trailing...].

  Gating is inherited unchanged (locked: dimmed and taps ignored). `hint` (str or callable) is drawn small and grey
  under the value; `highlight` (callable -> bool) outlines the value. With `selected_index=None` no button stays
  green after a tap (a stepper has no "chosen" button); otherwise selection behaves exactly like the parent class."""

  def __init__(self, buttons, button_width: int, value_index: int, selected_index: int | None = None,
               callback: Callable | None = None, enabled: Enabled = True, selected_source: Callable[[], int] | None = None,
               hint=None, highlight: Callable[[], bool] | None = None):
    self._no_selection = selected_index is None
    super().__init__(buttons, button_width, -1 if self._no_selection else selected_index, callback=callback,
                     enabled=enabled, selected_source=selected_source)
    self.value_index = value_index
    self._hint = hint
    self._highlight = highlight
    self._hint_font = None

  @property
  def hint_text(self) -> str:
    try:
      text = self._hint() if callable(self._hint) else self._hint
    except Exception:
      return ""
    return "" if text is None else str(text)

  @property
  def highlighted(self) -> bool:
    if self._highlight is None:
      return False
    try:
      return bool(self._highlight())
    except Exception:
      return False   # never raise from render; an unknown value is not highlighted

  def value_rect(self, rect) -> rl.Rectangle:
    x = rect.x + self.value_index * (self.button_width + RIGHT_ITEM_PADDING)
    return rl.Rectangle(x, rect.y + (rect.height - BUTTON_HEIGHT) / 2, self.button_width, BUTTON_HEIGHT)

  def _render(self, rect):
    ret = super()._render(rect)
    box = self.value_rect(rect)
    if self.highlighted:
      rl.draw_rectangle_rounded_lines_ex(box, 1.0, 20, HIGHLIGHT_THICKNESS, HIGHLIGHT_COLOR)
    text = self.hint_text
    if text:
      if self._hint_font is None:
        self._hint_font = gui_app.font(FontWeight.NORMAL)
      size = measure_text_cached(self._hint_font, text, HINT_FONT_SIZE)
      pos = rl.Vector2(box.x + (box.width - size.x) / 2, box.y + box.height + 2)
      rl.draw_text_ex(self._hint_font, text, pos, HINT_FONT_SIZE, 0, HINT_COLOR)
    return ret

  def _handle_mouse_release(self, mouse_pos):
    super()._handle_mouse_release(mouse_pos)
    if self._no_selection:
      self.selected_button = -1


def gated_value_step_item(title, description, value, on_minus: Callable[[], object] | None = None,
                          on_plus: Callable[[], object] | None = None, *, minus: str = MINUS, plus: str = PLUS,
                          leading: Sequence = (), on_leading: Callable[[int], object] | None = None,
                          trailing: Sequence = (), on_trailing: Callable[[int], object] | None = None,
                          callback: Callable[[int], object] | None = None, selected_index: int | None = None,
                          selected_source: Callable[[], int] | None = None, button_width: int = STEP_BUTTON_WIDTH,
                          icon: str = "", enabled: Enabled = True, default_text=None,
                          is_default: Callable[[], bool] | None = None, translate: Callable[[str], str] | None = None
                          ) -> ListItem:
  """One value row: [leading...] [-] [value] [+] [trailing...], gated like gated_multiple_button_item.

  `value` is the live value text (str or callable); the value button ignores taps. Either pass `callback(index)` (the
  raw button index, as gated_multiple_button_item does) or the per-button `on_minus` / `on_plus` / `on_leading(i)` /
  `on_trailing(i)`. `default_text` shows "default: X" under the value; `is_default()` False outlines the value."""
  leading, trailing = list(leading), list(trailing)
  value_index = len(leading) + 1
  buttons = [*leading, minus, value, plus, *trailing]

  def dispatch(index):
    if index < len(leading):
      return on_leading(index) if on_leading else None
    if index == value_index - 1:
      return on_minus() if on_minus else None
    if index == value_index + 1:
      return on_plus() if on_plus else None
    if index > value_index + 1:
      return on_trailing(index - value_index - 2) if on_trailing else None
    return None   # the value itself

  hint = None if default_text is None else (lambda: default_hint(default_text, translate))
  highlight = None if is_default is None else (lambda: not is_default())
  action = GatedValueStepAction(buttons, button_width, value_index, selected_index,
                                callback=callback if callback is not None else dispatch, enabled=enabled,
                                selected_source=selected_source, hint=hint, highlight=highlight)
  return ListItem(title=title, description=description, icon=icon, action_item=action)


def _confirm_dialog(text, on_yes):
  """Ask through the dialog stack; the reset runs from the callback only, after a yes."""
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import DialogResult
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog

  def on_result(result):
    if result == DialogResult.CONFIRM:
      on_yes()

  gui_app.push_widget(ConfirmDialog(tr(text), tr("Reset"), callback=on_result))


def _alert(text):
  """Tell the user a reset write failed (one OK button)."""
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
  gui_app.push_widget(alert_dialog(tr(text)))


def reset_section_item(defaults: Mapping | Callable[[], Mapping], write: Callable[[str, object], object], *,
                       title=RESET_SECTION_TITLE, description=None, enabled: Enabled = True,
                       confirm_text: str = RESET_CONFIRM_TEXT, request_confirm: Callable | None = None,
                       on_done: Callable[[], object] | None = None,
                       report_failure: Callable[[str], object] | None = None) -> ListItem:
  """"Reset section to defaults" row. A tap asks first; only a yes writes, and only the keys in `defaults`, each
  through `write(key, default)`. Locked like the other gated rows: dimmed, taps ignored, and the lock is checked
  again when the yes arrives (the car may have started while the dialog was up). If a write fails, the reset stops
  there and the user is told (`report_failure`, an OK dialog by default); the row still refreshes."""
  ask = request_confirm if request_confirm is not None else _confirm_dialog
  report = report_failure if report_failure is not None else _alert
  action = ButtonAction(RESET_BUTTON_TEXT, enabled=enabled)

  def locked() -> bool:
    return not action.enabled

  def on_yes():
    if locked():
      return
    try:
      reset_section(defaults, write)
    except Exception:   # a writer refused or the store failed: say so instead of failing silently
      report(RESET_FAILED_TEXT)
    if on_done is not None:
      on_done()

  def on_tap():
    if locked():
      return
    ask(confirm_text, on_yes)

  return ListItem(title=title, description=description, callback=on_tap, action_item=action)


__all__ = ["GatedDualButtonAction", "GatedMultipleButtonAction", "GatedValueStepAction", "gated_dual_button_item",
           "gated_multiple_button_item", "gated_value_step_item", "reset_section_item"]
