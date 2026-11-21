"""One model of a 3X settings row, shared by the comma 3X list and the comma 4 (mici) BogPilot menu.

The comma 4 does not re-implement any BogPilot page. It builds the SAME 3X page (layouts/settings/bogpilot.py ->
menu_sections()), draws it off screen every frame so the page keeps running its own refresh / visibility / Tuning
Level / onroad-policy logic, records which rows it drew (ListItem.render_observer) and shows each row as comma 4 cards.
A tap on a card goes through the 3X row's own handler (the stock Toggle / Button release handler, the action's own
MultipleButtonAction release handler at the button's own rectangle, ListItem.callback for a ButtonAction), so param
keys, defaults, ranges, units, locks, reboot prompts and staged writes are exactly the 3X ones: nothing here writes a
setting by itself.

`kind_of(item)` names how a row is shown on the comma 4. UNSUPPORTED must never occur for a BogPilot page row
(tests/test_comma4_menu_parity.py walks every page).
"""
from __future__ import annotations

from collections.abc import Callable

TOGGLE = "toggle"                 # ToggleAction: one card, tap flips the switch
MANAGE_TOGGLE = "manage_toggle"   # switch + MANAGE button (0.9.7 manage control): a switch card and an indented MANAGE card
BUTTON = "button"                 # ButtonAction (OPEN / MANAGE / RESET / SELECT ...): one card, tap presses it
CHOICE = "choice"                 # MultipleButtonAction: card -> list of options
STEPPER = "stepper"               # GatedValueStepAction [leading] [-] [value] [+] [trailing]: card -> adjuster page
DUAL = "dual"                     # DualButtonAction: two cards
INFO = "info"                     # TextAction / no action: read-only card
UNSUPPORTED = "unsupported"
KINDS = (TOGGLE, MANAGE_TOGGLE, BUTTON, CHOICE, STEPPER, DUAL, INFO)

# Characters the font atlas holds besides printable ASCII (system/ui/lib/application.py EXTRA_FONT_CHARS). A comma 4
# label with anything else would draw as '?'. U+2212 (real minus) is NOT in the atlas: values use ASCII '-', the
# adjuster's own minus / plus are drawn as shapes, never as glyphs.
INDENT_MARK = "\u21b3 "           # "↳ ": rows the 3X indents under their parent switch
MANAGE_CHILD_TITLE = "Customize"   # title of the MANAGE card under a switch + MANAGE row (the switch card has the row title)


def _res(value, default=""):
  try:
    value = value() if callable(value) else value
  except Exception:
    return default
  return default if value is None else value


def kind_of(item) -> str:
  from openpilot.system.ui.widgets.list_view import (ButtonAction, DualButtonAction, MultipleButtonAction, TextAction,
                                                     ToggleAction)
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedValueStepAction
  a = getattr(item, "action_item", None)
  if a is None:
    return INFO
  if isinstance(a, GatedValueStepAction):
    return STEPPER
  if isinstance(a, MultipleButtonAction):
    return CHOICE
  if hasattr(a, "toggle") and hasattr(a, "manage"):
    return MANAGE_TOGGLE
  if isinstance(a, ToggleAction):
    return TOGGLE
  if isinstance(a, DualButtonAction):
    return DUAL
  if isinstance(a, ButtonAction):
    return BUTTON
  if isinstance(a, TextAction):
    return INFO
  return UNSUPPORTED


def _button_text(button) -> str:
  label = getattr(button, "_label", None)
  return str(_res(getattr(label, "text", ""), "")) if label is not None else ""


def _ensure_rect(action) -> None:
  """A row drawn at least once has its rectangle; before that (tests, first frame) give it the size the 3X would."""
  import pyray as rl
  from openpilot.system.ui.widgets.list_view import ITEM_BASE_HEIGHT
  r = action.rect
  if r.width <= 0 or r.height <= 0:
    action.set_rect(rl.Rectangle(r.x, r.y, max(1.0, float(action.get_width_hint())), float(ITEM_BASE_HEIGHT)))


_opening: list = []    # rows whose 3X handler is running right now (innermost last)


def _opens(method):
  """Remember which row is acting while its 3X handler runs, so a dialog that handler opens (on the comma 4: a
  slide-to-confirm page) keeps that row's lock: a row that becomes locked cannot be confirmed."""
  def wrapper(self, *args, **kwargs):
    _opening.append(self)
    try:
      return method(self, *args, **kwargs)
    finally:
      _opening.pop()
  wrapper.__name__, wrapper.__doc__ = method.__name__, method.__doc__
  return wrapper


def opening_gate() -> Callable[[], bool] | None:
  """The lock of the row whose handler is running (None outside a row action, e.g. the reboot prompt)."""
  return _opening[-1].enabled if _opening else None


class Row:
  """Read and act on one 3X row. Every action re-checks the row's lock first (fail closed: a row whose ListItem OR
  action is disabled is locked) and then calls the 3X handler, which checks its own gate again before it writes."""

  def __init__(self, item):
    self.item = item
    self.action = getattr(item, "action_item", None)
    self.kind = kind_of(item)

  # ---- read
  def title(self) -> str:
    return str(_res(lambda: self.item.title, ""))

  def description(self) -> str:
    return str(_res(lambda: self.item.description, ""))

  @property
  def help_key(self) -> str:
    return getattr(self.item, "help_key", None) or ""

  def indented(self) -> bool:
    return bool(getattr(self.item, "indent", 0))

  def visible(self) -> bool:
    return bool(_res(lambda: self.item.is_visible, False))

  def enabled(self) -> bool:
    row_on = bool(_res(lambda: self.item.enabled, False))
    act_on = True if self.action is None else bool(_res(lambda: self.action.enabled, False))
    return row_on and act_on

  # toggle / manage
  def state(self) -> bool:
    toggle = getattr(self.action, "toggle", None)
    return bool(_res(toggle.get_state, False)) if toggle is not None else False

  def toggle_enabled(self) -> bool:
    if not self.enabled():
      return False
    if self.kind == MANAGE_TOGGLE:
      return bool(_res(self.action.toggle_enabled, False))
    return True

  def manage_enabled(self) -> bool:
    return self.kind == MANAGE_TOGGLE and self.enabled() and bool(_res(self.action.manage_enabled, False))

  # button
  def button_text(self) -> str:
    return str(_res(lambda: self.action.text, "")) if self.kind == BUTTON else ""

  def value_text(self) -> str:
    if self.kind == BUTTON:
      return str(_res(lambda: self.action.value, ""))
    if self.kind == INFO and self.action is not None:
      return str(_res(lambda: self.action.text, ""))
    if self.kind == CHOICE:
      opts, sel = self.options(), self.selected()
      return opts[sel] if 0 <= sel < len(opts) else ""
    if self.kind == STEPPER:
      return self.value()
    return ""

  # choice / stepper (raw button labels, left to right)
  def options(self) -> list[str]:
    if self.kind not in (CHOICE, STEPPER):
      return []
    return [str(_res(b, "")) for b in self.action.buttons]

  def selected(self) -> int:
    if self.kind != CHOICE:
      return -1
    sync = getattr(self.action, "_sync_selected", None)
    if callable(sync):
      sync()
    return int(_res(self.action.get_selected_button, -1))

  def value(self) -> str:
    if self.kind != STEPPER:
      return ""
    opts = self.options()
    i = self.action.value_index
    return opts[i] if 0 <= i < len(opts) else ""

  def hint(self) -> str:
    return str(_res(lambda: self.action.hint_text, "")) if self.kind == STEPPER else ""

  def highlighted(self) -> bool:
    return bool(_res(lambda: self.action.highlighted, False)) if self.kind == STEPPER else False

  def leading(self) -> list[str]:
    return self.options()[:self.action.value_index - 1] if self.kind == STEPPER else []

  def trailing(self) -> list[str]:
    return self.options()[self.action.value_index + 2:] if self.kind == STEPPER else []

  # dual
  def dual(self) -> list[tuple[str, bool]]:
    if self.kind != DUAL:
      return []
    return [(_button_text(b), bool(_res(lambda b=b: b.is_visible, False))) for b in (self.action.left_button, self.action.right_button)]

  # ---- act (each returns True when the 3X handler was called)
  @_opens
  def toggle(self) -> bool:
    if self.kind not in (TOGGLE, MANAGE_TOGGLE) or not self.toggle_enabled():
      return False
    from openpilot.system.ui.lib.application import MousePos
    t = self.action.toggle
    t.set_enabled(True)            # the 3X action does this every frame from the same lock checked above
    t._handle_mouse_release(MousePos(t.rect.x + 1, t.rect.y + 1))
    return True

  @_opens
  def manage(self) -> bool:
    if not self.manage_enabled():
      return False
    cb = getattr(self.action.manage, "_click_callback", None)
    if cb is None:
      return False
    cb()
    return True

  @_opens
  def press(self) -> bool:
    """ButtonAction: what ListItem._render does when its button reports a press and the action is enabled."""
    if self.kind != BUTTON or not self.enabled() or self.item.callback is None:
      return False
    self.item.callback()
    return True

  @_opens
  def press_index(self, index: int) -> bool:
    """CHOICE option / STEPPER button `index`: a release at that button's own rectangle, so the action's own handler
    (gate, highlight sync, value-step dispatch) runs unchanged."""
    if self.kind not in (CHOICE, STEPPER) or not self.enabled():
      return False
    a = self.action
    if not 0 <= index < len(a.buttons):
      return False
    from openpilot.system.ui.lib.application import MousePos
    from openpilot.system.ui.widgets.list_view import BUTTON_HEIGHT, RIGHT_ITEM_PADDING
    _ensure_rect(a)
    rects = a.button_rects(a.rect) if hasattr(a, "button_rects") else None
    if rects is not None:
      r = rects[index]
      pos = MousePos(r.x + r.width / 2, r.y + r.height / 2)
    else:
      x = a.rect.x + index * (a.button_width + RIGHT_ITEM_PADDING) + a.button_width / 2
      pos = MousePos(x, a.rect.y + (a.rect.height - BUTTON_HEIGHT) / 2 + BUTTON_HEIGHT / 2)
    a._handle_mouse_release(pos)
    return True

  def choose(self, index: int) -> bool:
    return self.press_index(index)

  def minus(self) -> bool:
    return self.kind == STEPPER and self.press_index(self.action.value_index - 1)

  def plus(self) -> bool:
    return self.kind == STEPPER and self.press_index(self.action.value_index + 1)

  def press_leading(self, i: int) -> bool:
    return self.kind == STEPPER and 0 <= i < len(self.leading()) and self.press_index(i)

  def press_trailing(self, i: int) -> bool:
    return self.kind == STEPPER and 0 <= i < len(self.trailing()) and self.press_index(self.action.value_index + 2 + i)

  @_opens
  def press_dual(self, side: int) -> bool:
    if self.kind != DUAL or not self.enabled():
      return False
    b = (self.action.left_button, self.action.right_button)[side]
    cb = getattr(b, "_click_callback", None)
    if cb is None or not bool(_res(lambda: b.enabled, False)):
      return False
    cb()
    return True


def record(widget, rect) -> list:
  """Draw `widget` into `rect` once and return the rows (ListItems) it drew, in order."""
  from openpilot.system.ui.widgets.list_view import ListItem
  rows: list = []
  seen: set[int] = set()

  def observe(item):
    if id(item) not in seen:
      seen.add(id(item))
      rows.append(item)

  previous = ListItem.render_observer
  ListItem.render_observer = observe
  try:
    widget.render(rect)
  finally:
    ListItem.render_observer = previous
  return rows


def static_rows(root) -> list:
  """Every ListItem a page holds right now (scroller order first), without drawing: the parity test's walk, the same
  traversal tools/bogpilot/settings_row_dump.py uses."""
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import ListItem
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  order, scrollers, visited = [], [], set()
  stack = [(root, 0)]
  while stack:
    obj, depth = stack.pop()
    if id(obj) in visited or depth > 8:
      continue
    visited.add(id(obj))
    if isinstance(obj, Scroller):
      scrollers.append(obj)
    if isinstance(obj, ListItem):
      order.append(obj)
      continue
    children: list = []
    if isinstance(obj, Widget) or depth == 0 or (hasattr(obj, "__dict__") and not callable(obj)
                                                 and type(obj).__module__.startswith("openpilot.selfdrive.ui")):
      children = list(vars(obj).values()) if hasattr(obj, "__dict__") else []
      for c in list(children):
        cells = getattr(c, "__closure__", None) if callable(c) else None
        for cell in cells or ():
          try:
            children.append(cell.cell_contents)
          except ValueError:
            pass
    elif isinstance(obj, (list, tuple, set)):
      children = list(obj)
    elif isinstance(obj, dict):
      children = list(obj.values())
    for c in reversed(children):
      if isinstance(c, (Widget, list, tuple, set, dict)) or (
          hasattr(c, "__dict__") and not callable(c) and type(c).__module__.startswith("openpilot.selfdrive.ui")):
        stack.append((c, depth + 1))
  out, seen = [], set()
  for s in scrollers:
    for it in getattr(s, "_items", []):
      if isinstance(it, ListItem) and id(it) not in seen:
        seen.add(id(it))
        out.append(it)
  for it in order:
    if id(it) not in seen:
      seen.add(id(it))
      out.append(it)
  return out


def card_labels(row: Row) -> list[tuple[str, str]]:
  """(title, value) of every comma 4 card this row becomes. Shared by the cards and the parity / glyph tests."""
  title = row.title()
  mark = INDENT_MARK if row.indented() else ""
  if row.kind == MANAGE_TOGGLE:
    # the switch card carries the title; the MANAGE card is its indented child, so the page does not list the title twice
    return [(mark + title, ""), (INDENT_MARK + MANAGE_CHILD_TITLE, "MANAGE")]
  if row.kind == DUAL:
    return [(text, "") for text, _vis in row.dual()]
  if row.kind == BUTTON:
    return [(mark + (title or row.button_text()), row.value_text() or row.button_text())]
  return [(mark + title, row.value_text())]


__all__ = ["TOGGLE", "MANAGE_TOGGLE", "BUTTON", "CHOICE", "STEPPER", "DUAL", "INFO", "UNSUPPORTED", "KINDS",
           "INDENT_MARK", "MANAGE_CHILD_TITLE", "kind_of", "Row", "record", "static_rows", "card_labels"]
