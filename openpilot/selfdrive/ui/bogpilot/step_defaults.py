"""Default-value helpers for the value-step rows (no UI imports, so they run anywhere).

* `default_hint` builds the small grey "default: X" text shown under a row's value.
* `differs_from_default` decides when the value is highlighted (stored value is not the default).
* `reset_section` writes a section's own keys back to their existing defaults, and nothing else.
* `whole_section` builds a section's reset table: its value rows as the panel already resets them, plus its toggle
  and choice rows and its own parent switch at their shipped BogPilot defaults (`shipped_default`).

Callers pass the defaults from where the panel already reads them (for example the Alert Volume defaults in
alert_volumes.BOGPILOT_VOLUME_DEFAULTS); nothing here defines a default or a param.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

HINT_PREFIX = "default"


def _resolve(value: Any) -> Any:
  return value() if callable(value) else value


def default_hint(default_text: Any, translate: Callable[[str], str] | None = None) -> str:
  """'default: X' for a shown default X; empty when there is no default to show."""
  text = _resolve(default_text)
  if text is None or str(text) == "":
    return ""
  prefix = translate(HINT_PREFIX) if translate is not None else HINT_PREFIX
  return f"{prefix}: {text}"


def differs_from_default(current: Any, default: Any) -> bool:
  """True when the current value is not the default. Numbers compare by value ("101" == 101 == 101.0); anything that is
  not a number compares as text. An unknown current or default is never highlighted."""
  if current is None or default is None:
    return False
  try:
    a, b = float(current), float(default)
  except (TypeError, ValueError):
    return str(current) != str(default)
  if math.isnan(a) or math.isnan(b):
    return False   # NaN is an unknown value: not highlighted, as documented above
  return a != b


def reset_section(defaults: Mapping[str, Any] | Callable[[], Mapping[str, Any]],
                  write: Callable[[str, Any], Any]) -> list[str]:
  """Write each listed key back to its default through the section's own writer. Returns the keys written, in order.
  Only the listed keys are written; a writer that raises stops the reset at that key (later keys are left alone)."""
  table = _resolve(defaults)
  written = []
  for key, value in table.items():
    write(key, value)
    written.append(key)
  return written


_SHIPPED: dict[str, str | None] | None = None


def shipped_default(key: str) -> str | None:
  """The shipped BogPilot default of `key` as stored text: what "Reset BogPilot Settings to Defaults" writes
  (toggle_reset.shipping_defaults, the registry default column plus the shipping overlays). None without one."""
  global _SHIPPED
  if _SHIPPED is None:
    try:
      from openpilot.system.bogpilot.toggle_reset import shipping_defaults
      _SHIPPED = dict(shipping_defaults())
    except Exception:
      return None
  value = _SHIPPED.get(key)
  return None if value in (None, "") else str(value)


def shipped_toggle(key: str) -> bool | None:
  text = shipped_default(key)
  return None if text is None else text == "1"


def shipped_choice(key: str) -> int | None:
  text = shipped_default(key)
  try:
    return None if text is None else int(float(text))
  except (TypeError, ValueError):
    return None


def whole_section(values: Mapping[str, Any], toggles=(), choices=(), parent: str | None = None, sub_parents=(),
                  can_edit: Callable[[str], bool] | None = None, overrides: Mapping[str, Any] | None = None) -> dict:
  """Reset table for a whole section, in write order.

  values: the section's value rows with the defaults the panel already uses (kept as they are). toggles / choices:
  the section's other rows, reset to their shipped defaults (a row without one is left alone). parent: the section's
  own on/off switch, also back to its shipped default. overrides: per-car-type values that replace the shipped ones
  (the SLC reset profiles). Only keys `can_edit` allows right now are listed.
  Order: sub-parent switches that turn on, then the rows, then sub-parent switches that turn off, and the section's own
  parent last, so no row is refused because a switch above it was turned off first."""
  can = can_edit if can_edit is not None else (lambda _k: True)
  first, rows, last = {}, dict(values), {}
  for k in choices:
    if k not in rows and k != parent and can(k):
      v = shipped_choice(k)
      if v is not None:
        rows[k] = v
  for k in toggles:
    if k in rows or k == parent or not can(k):
      continue
    v = shipped_toggle(k)
    if v is None:
      continue
    if k in sub_parents:
      (first if v else last)[k] = v
    else:
      rows[k] = v
  out = {**first, **rows, **last}
  for k, v in (overrides or {}).items():
    if k != parent and (k in out or can(k)):
      out[k] = v
  if parent is not None and can(parent):
    v = shipped_toggle(parent)
    if v is not None:
      out.pop(parent, None)
      out[parent] = v
  return out


__all__ = ["HINT_PREFIX", "default_hint", "differs_from_default", "reset_section", "shipped_choice", "shipped_default",
           "shipped_toggle", "whole_section"]
