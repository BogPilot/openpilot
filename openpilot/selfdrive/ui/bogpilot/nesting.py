"""Parent / child rows for the BogPilot menu.

One helper, used by every page that has a parent switch with rows that only matter while it is on: the children are indented
under the parent and shown only while the parent row is showing AND switched on. Turning the parent off never writes the
children, so their saved choices come back when it is turned on again (they simply stop being offered, and the consumers
already ignore them).

  nest(parent_item, child_item, ...)          one level
  indent_under(parent_item, child_item, ...)  indent only, for pages that already hide the children from the saved value
  place(items_by_key, TREE)                   a whole page: TREE is ((key, (child, ...)), ...), children nest recursively
"""
from collections.abc import Callable

INDENT = 40   # pixels per nesting level


def is_on(item) -> bool:
  """True while the parent row is offered and its switch is on. A row without a switch counts as on."""
  try:
    if not item.is_visible:
      return False
    action = getattr(item, "action_item", None)
    getter = getattr(action, "get_state", None)
    return True if getter is None else bool(getter())
  except Exception:
    return False


def _and_visible(child, predicate: Callable[[], bool]) -> None:
  """Keep whatever visibility the child already had (car gates, Tuning Level, ...) and add the parent condition."""
  previous = child._is_visible
  child.set_visible(lambda: bool(previous() if callable(previous) else previous) and predicate())


def indent_under(parent, *children) -> None:
  """Indent only. For a page whose children already hide themselves from the saved value of the parent (so the switch cannot
  disagree with the store)."""
  for child in children:
    child.indent = getattr(parent, "indent", 0) + INDENT


def nest(parent, *children) -> None:
  indent_under(parent, *children)
  for child in children:
    _and_visible(child, lambda p=parent: is_on(p))


def place(items_by_key: dict, tree) -> list:
  """Return the page's rows in display order and nest the children. Keys that are not in items_by_key (a page that shows only
  some of the rows) are skipped, and a child whose parent is not on the page is dropped from the nesting but still listed."""
  ordered: list = []
  placed: set = set()

  def walk(entries, parent=None):
    for key, children in entries:
      item = items_by_key.get(key)
      if item is None:
        walk(children, parent)
        continue
      if key in placed:
        raise ValueError(f"{key} is placed twice")
      placed.add(key)
      ordered.append(item)
      if parent is not None:
        nest(parent, item)
      walk(children, item)

  walk(tree)
  return ordered
