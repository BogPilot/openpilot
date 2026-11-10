"""Tuning Level for the BogPilot settings panel (the 0.9.7 "Minimal / Standard / Advanced / Developer" selector).

This reuses what already exists in this tree; it adds no new setting:
  * the saved choice is the registered `TuningLevel` param (0 Minimal .. 3 Developer) plus `TuningLevelConfirmed`;
  * a level that was never confirmed reads as 3 (Developer), so a fresh install keeps today's full visible set;
  * every row has the level the 0.9.7 table gave it (`BOGPILOT_PARAMS`, column 3, exposed by `registry_level`), and the
    shared `ParamStore.honoured()` already makes the runtime consumers read a key above the level as its default.
The panel uses the same table: a row shows only when the chosen level is at or above the row's level.

Rows that are not in the shared table get a level here (`UI_ROW_LEVELS`) so the menu can place them. Rows with no level at
all (read-only pages, actions, car-specific rows) are basics and always show.

Nothing here writes on import, on open or on read. Only `set_level()` writes, and only when the user taps a level.
"""
from __future__ import annotations

import time

LEVEL_NAMES = ("Minimal", "Standard", "Advanced", "Developer")
MINIMAL, STANDARD, ADVANCED, DEVELOPER = range(4)
LEVEL_KEY = "TuningLevel"
CONFIRMED_KEY = "TuningLevelConfirmed"

# Rows that are not in BOGPILOT_PARAMS (file-only UI keys). Everything else comes from the shared registry.
UI_ROW_LEVELS: dict[str, int] = {
  "BSMFlameTracks": STANDARD,   # "Bog to the Future": cosmetic, needs the blind-spot lane fill (Standard)
  "SwapSpeedGraph": ADVANCED,   # layout preference for the driving screen
}

_CACHE_S = 0.5
_store = None
_cache: tuple[float, int] | None = None


def get_store():
  global _store
  if _store is None:
    from openpilot.common.bogpilot_store import ParamStore
    _store = ParamStore()
  return _store


def set_store(store) -> None:
  """Tests and embedding: use this store for every level read and write."""
  global _store, _cache
  _store, _cache = store, None


def invalidate() -> None:
  global _cache
  _cache = None


def clamp(level) -> int:
  try:
    return max(MINIMAL, min(DEVELOPER, int(level)))
  except (TypeError, ValueError):
    return DEVELOPER


def effective_level(store=None) -> int:
  """The level in force: the saved level if the user confirmed one, else Developer (3). Never writes."""
  global _cache
  now = time.monotonic()
  if store is None and _cache is not None and now - _cache[0] < _CACHE_S:
    return _cache[1]
  s = store if store is not None else get_store()
  try:
    level = clamp(s.tuning_level())
  except Exception:
    level = DEVELOPER   # unreadable setting: show everything, as today
  if store is None:
    _cache = (now, level)
  return level


def is_confirmed(store=None) -> bool:
  s = store if store is not None else get_store()
  try:
    return bool(s.get_bool(CONFIRMED_KEY, False))
  except Exception:
    return False


def set_level(level: int, store=None) -> bool:
  """Save the user's choice (TuningLevel + TuningLevelConfirmed). Returns True when it reads back."""
  level = clamp(level)
  s = store if store is not None else get_store()
  try:
    s.put(LEVEL_KEY, level, block=True)
    s.put_bool(CONFIRMED_KEY, True, block=True)
    s.invalidate()
    ok = s.tuning_level() == level
  except Exception:
    ok = False
  invalidate()
  return ok


def _param_for(key: str) -> str:
  from openpilot.selfdrive.ui.bogpilot.toggle_help import ALIASES
  return ALIASES.get(key, key)


def row_level(key: str) -> int | None:
  """The level a row needs, or None when it has none (always shown)."""
  if key in UI_ROW_LEVELS:
    return UI_ROW_LEVELS[key]
  param = _param_for(key)
  if param in UI_ROW_LEVELS:
    return UI_ROW_LEVELS[param]
  from openpilot.common.bogpilot_store import registry_level
  return registry_level(param)


def row_visible(key: str, level: int | None = None) -> bool:
  need = row_level(key)
  if need is None:
    return True
  return (effective_level() if level is None else clamp(level)) >= need


def page_level(controls) -> int:
  """A page shows from the lowest level of any row inside it; a page with an unleveled control is basic (0)."""
  levels = []
  for key in controls:
    need = row_level(key)
    if need is None:
      return MINIMAL
    levels.append(need)
  return min(levels) if levels else MINIMAL
