"""BogPilot list actions that honour their own lock (D2, option 2: stock list_view.py stays byte-identical).

Stock v0.11.2 `system/ui/widgets/list_view.py` has two gaps the BogPilot settings panels hit while onroad:

* `DualButtonAction` never passes its `enabled` state to its two `Button`s. They are built enabled, and each Button
  gates touches on its own `enabled` (`Widget.render`), so a "locked" dual row still fires and does not look dimmed.
* `MultipleButtonAction` is always built `enabled=True`, and `_handle_mouse_release` moves the highlight before the
  callback runs, so a caller that locks only the `ListItem` (not the action) gets a live, mis-highlighted row.

The classes below subclass the stock actions and change only those two things. Every BogPilot editor still refuses
the write itself while onroad. These classes fix the UI gate (look and touch); they are not the safety check.
The factories mirror the stock `dual_button_item` / `multiple_button_item` signatures and return a stock `ListItem`.
"""
from __future__ import annotations

from collections.abc import Callable

from openpilot.system.ui.widgets.list_view import BUTTON_WIDTH, DualButtonAction, ListItem, MultipleButtonAction

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


__all__ = ["GatedDualButtonAction", "GatedMultipleButtonAction", "gated_dual_button_item", "gated_multiple_button_item"]
