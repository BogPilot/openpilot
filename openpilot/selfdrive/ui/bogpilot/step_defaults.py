"""Default-value helpers for the value-step rows (no UI imports, so they run anywhere).

* `default_hint` builds the small grey "default: X" text shown under a row's value.
* `differs_from_default` decides when the value is highlighted (stored value is not the default).
* `reset_section` writes a section's own keys back to their existing defaults, and nothing else.

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


__all__ = ["HINT_PREFIX", "default_hint", "differs_from_default", "reset_section"]
