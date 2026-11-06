"""BogPilot: the one shared FrogPilot/BogPilot setting store for 0.11.2 (daemons, car side and UI).

Why it exists: the FrogPilot keys live in openpilot/common/bogpilot_params.py and are compiled into
libparams_c.so (params_keys_bogpilot.h). A device that still runs an older libparams_c.so raises
UnknownKeyName for them, and the 0.9.7 device kept them as plain files under /data/params_bogpilot.
ParamStore hides that: real Params when the key is known, the file store otherwise, and the 367e1fe
default (BOGPILOT_PARAMS column 2) when the key was never written.

Toggle getters (`toggle_*`) add the 367e1fe tuning-level rule from frogpilot_variables.py: a key above
the user's level reads as its default (level = TuningLevel if TuningLevelConfirmed else 3).

The offroad UI's ui/bogpilot/store.py ParamStore subclasses this one, so every process reads and
writes the same values the same way.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_toggles import FILE_CHOICES, FILE_TOGGLES

_ON = ("1", "true", "on")
_OFF = ("0", "false", "off")


def bogpilot_dir() -> Path:
  return Path(os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))


def file_path(key: str) -> Path:
  return bogpilot_dir() / key


def read_text(key: str, default: str | None = None) -> str | None:
  try:
    with open(file_path(key), encoding="utf-8", errors="replace") as f:
      return f.read().strip()
  except OSError:
    return default


def write_text(key: str, value: str) -> bool:
  try:
    d = bogpilot_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{key}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
      f.write(value)
    os.replace(tmp, d / key)
    return True
  except OSError:
    return False


def remove_file(key: str) -> None:
  try:
    file_path(key).unlink()
  except OSError:
    pass


def parse_bool(text: str | bytes | None, default: bool) -> bool:
  if text is None:
    return default
  if isinstance(text, bytes):
    text = text.decode("utf-8", "replace")
  t = text.strip().lower()
  if t in _ON:
    return True
  if t in _OFF:
    return False
  return default


def registry_default(key: str) -> str:
  """367e1fe default text for a key ("" when it has none). File toggles use their own defaults."""
  row = BOGPILOT_PARAMS.get(key)
  if row is not None:
    return row[2] or ""
  if key in FILE_TOGGLES:
    d = FILE_TOGGLES[key][0]
    return "" if d is None else ("1" if d else "0")
  if key in FILE_CHOICES:
    return FILE_CHOICES[key][0]
  return ""


def registry_level(key: str) -> int | None:
  row = BOGPILOT_PARAMS.get(key)
  return None if row is None else row[3]


class ParamStore:
  """Params for keys the params library knows, /data/params_bogpilot files for the rest."""

  def __init__(self, params=None, cache_ttl: float = 0.0):
    if params is None:
      from openpilot.common.params import Params
      params = Params()
    self._params = params
    self._known: dict[str, bool] = {}
    self._cache: dict[str, tuple[float, str | None]] = {}
    self.cache_ttl = cache_ttl

  # ---- raw access ----
  def is_param_key(self, key: str) -> bool:
    known = self._known.get(key)
    if known is None:
      try:
        self._params.check_key(key)
        known = True
      except Exception:
        known = False
      self._known[key] = known
    return known

  def _raw(self, key: str) -> str | None:
    """Stored text, or None when the key was never written."""
    now = time.monotonic()
    if self.cache_ttl > 0:
      hit = self._cache.get(key)
      if hit is not None and now - hit[0] < self.cache_ttl:
        return hit[1]
    val: str | None
    if self.is_param_key(key):
      try:
        v = self._params.get(key)
      except Exception:
        v = None
      if v is None:
        val = None
      elif isinstance(v, bytes):
        val = v.decode("utf-8", "replace")
      elif isinstance(v, bool):
        val = "1" if v else "0"
      elif isinstance(v, (dict, list)):
        val = json.dumps(v)
      else:
        val = str(v)
    else:
      val = read_text(key)
    if self.cache_ttl > 0:
      self._cache[key] = (now, val)
    return val

  def raw(self, key: str) -> str | None:
    return self._raw(key)

  def invalidate(self, key: str | None = None) -> None:
    if key is None:
      self._cache.clear()
    else:
      self._cache.pop(key, None)

  @staticmethod
  def default(key: str) -> str:
    return registry_default(key)

  # ---- ungated getters (stored value, else default) ----
  def get(self, key: str, default: str | None = None) -> str:
    fallback = self.default(key) if default is None else default
    val = self._raw(key)
    return fallback if val is None or val == "" else val

  def get_bool(self, key: str, default: bool | None = None) -> bool:
    if default is None:
      default = parse_bool(self.default(key), False)
    return parse_bool(self._raw(key), default)

  def get_float(self, key: str, default: float | None = None) -> float:
    if default is None:
      try:
        default = float(self.default(key) or 0)
      except ValueError:
        default = 0.0
    try:
      return float(self.get(key, str(default)))
    except ValueError:
      return default

  def get_int(self, key: str, default: int | None = None) -> int:
    return int(self.get_float(key, None if default is None else float(default)))

  # ---- writes ----
  def put_bool(self, key: str, value: bool) -> None:
    self.put(key, "1" if value else "0")

  def put(self, key: str, value) -> None:
    if isinstance(value, bool):
      text = "1" if value else "0"
    elif isinstance(value, float):
      text = f"{value:g}"
    else:
      text = value if isinstance(value, str) else str(value)
    self.invalidate(key)
    if self.is_param_key(key):
      try:
        from openpilot.common.params import ParamKeyType
        t = self._params.get_type(key)
        if t == ParamKeyType.BOOL:
          self._params.put_bool(key, parse_bool(text, False))
        elif t == ParamKeyType.INT:
          self._params.put(key, int(float(text)))
        elif t == ParamKeyType.FLOAT:
          self._params.put(key, float(text))
        else:
          self._params.put(key, text)
        return
      except Exception:
        pass
    write_text(key, text)

  def remove(self, key: str) -> None:
    self.invalidate(key)
    if self.is_param_key(key):
      try:
        self._params.remove(key)
      except Exception:
        pass
    remove_file(key)

  # ---- 367e1fe toggle semantics (tuning-level gated) ----
  def tuning_level(self) -> int:
    if self.get_bool("TuningLevelConfirmed", False):
      return self.get_int("TuningLevel", 0)
    return 3

  def honoured(self, key: str, level: int | None = None) -> bool:
    lvl = registry_level(key)
    if lvl is None:
      return True
    return (self.tuning_level() if level is None else level) >= lvl

  def toggle_bool(self, key: str, level: int | None = None) -> bool:
    if self.honoured(key, level):
      return self.get_bool(key)
    return parse_bool(self.default(key), False)

  def toggle_float(self, key: str, level: int | None = None) -> float:
    if self.honoured(key, level):
      return self.get_float(key)
    try:
      return float(self.default(key) or 0)
    except ValueError:
      return 0.0

  def toggle_int(self, key: str, level: int | None = None) -> int:
    return int(self.toggle_float(key, level))

  def toggle_str(self, key: str, level: int | None = None) -> str:
    return self.get(key) if self.honoured(key, level) else self.default(key)


_store: ParamStore | None = None


def store() -> ParamStore:
  global _store
  if _store is None:
    _store = ParamStore()
  return _store
