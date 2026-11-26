"""Inline accordion for BogPilot settings rows.

A row's help text is the row's own description: tap the text area to expand it under the row, tap again to collapse it, and
opening another row collapses the one that was open. Nothing is pushed onto the screen stack, so a screen timeout still
returns to the driving view, and leaving or re-showing a page collapses the text (ListItem.show_event / hide_event).

No raylib import: the rows are ListItems, this module only keeps track of which one is open.
"""
from __future__ import annotations

import weakref

_open: weakref.ref | None = None


def row_opened(item) -> None:
  """A row just expanded: collapse the row that was open before it."""
  global _open
  previous = _open() if _open is not None else None
  if previous is not None and previous is not item and getattr(previous, "description_visible", False):
    previous._set_description_visible(False)
  _open = weakref.ref(item)


def open_row():
  """The row currently expanded, or None."""
  row = _open() if _open is not None else None
  return row if row is not None and getattr(row, "description_visible", False) else None


def attach(item) -> None:
  """Make `item` part of the one-open-at-a-time group."""
  ref = weakref.ref(item)
  item.set_description_opened_callback(lambda: row_opened(ref()))
