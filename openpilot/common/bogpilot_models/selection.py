"""Selected-model record, runtime state, and the offroad-only select operation.

Both records live in the shared BogPilot setting store (Params when the key is compiled in, else the
/data/params_bogpilot file store), so the UI and modeld read and write the same place. The store only
needs raw(key) -> str | None, put(key, text) and remove(key).

Selection is applied by modeld exactly once per start (modeld only runs onroad), so a change can never take
effect mid-drive; select() additionally refuses to write unless the device is offroad.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from openpilot.common.bogpilot_models import STOCK_ID
from openpilot.common.bogpilot_models import registry

KEY_SELECTION = "BogPilotDrivingModel"
KEY_STATE = "BogPilotDrivingModelState"


@dataclass(frozen=True)
class Selection:
  id: str
  pin_model: str
  pin_manifest: str


@dataclass(frozen=True)
class SelectResult:
  ok: bool
  message: str


def default_store():
  from openpilot.common.bogpilot_store import store
  return store()


def _clean(text: str, limit: int = 220) -> str:
  return " ".join(str(text).split())[:limit]


def parse_selection(raw: str | None) -> Selection | None:
  """None for unreadable text. Callers treat unset ("" / None) as Default before calling this."""
  try:
    d = json.loads(raw or "")
    if (d.get("v") == 1 and isinstance(d.get("id"), str) and d["id"] and isinstance(d.get("pin_model"), str)
            and isinstance(d.get("pin_manifest"), str)):
      return Selection(d["id"], d["pin_model"], d["pin_manifest"])
  except (ValueError, AttributeError, TypeError):
    pass
  return None


def read_selection(store=None) -> tuple[Selection | None, bool]:
  """(selection, corrupt). selection None + corrupt False means nothing is selected (Default)."""
  store = default_store() if store is None else store
  raw = store.raw(KEY_SELECTION)
  if raw is None or not raw.strip():
    return None, False
  sel = parse_selection(raw)
  return sel, sel is None


def read_state(store=None) -> dict:
  store = default_store() if store is None else store
  try:
    d = json.loads(store.raw(KEY_STATE) or "")
    return d if isinstance(d, dict) else {}
  except (ValueError, TypeError):
    return {}


def _write_state(store, state: dict) -> None:
  if state:
    store.put(KEY_STATE, json.dumps(state, sort_keys=True))
  else:
    store.remove(KEY_STATE)


def record_active(store, model_id: str, name: str, model_sha256: str) -> None:
  """modeld calls this after the chosen model loaded. Default only rewrites state if something else was active."""
  st = read_state(store)
  act = st.get("active") or {}
  if model_id == STOCK_ID and act.get("id", STOCK_ID) == STOCK_ID:
    return
  st["active"] = {"id": model_id, "name": _clean(name, 60), "model_sha256": model_sha256, "ts": int(time.time())}
  if model_id != STOCK_ID:
    st.pop("fallback", None)
  _write_state(store, st)


def record_fallback(store, requested: Selection | None, name: str, reason: str, phase: str) -> None:
  st = read_state(store)
  st["fallback"] = {"requested_id": requested.id if requested else "", "requested_name": _clean(name, 60),
                    "pin_model": requested.pin_model if requested else "",
                    "pin_manifest": requested.pin_manifest if requested else "",
                    "reason": _clean(reason), "phase": phase, "ts": int(time.time())}
  st["active"] = {"id": STOCK_ID, "name": "Default (stock)", "model_sha256": "", "ts": int(time.time())}
  _write_state(store, st)


def clear_fallback(store) -> None:
  st = read_state(store)
  if st.pop("fallback", None) is not None:
    _write_state(store, st)


def select(model_id: str, is_offroad: Callable[[], bool], store=None, root=None, cache: dict | None = None) -> SelectResult:
  """Record the user's choice for the NEXT drive. Offroad only; the model must validate (hash + compatibility)."""
  store = default_store() if store is None else store
  try:
    if is_offroad() is not True:
      return SelectResult(False, "Driving model can only be changed while the car is off (offroad).")
  except Exception:
    return SelectResult(False, "Cannot confirm the car is off, so the driving model was not changed.")
  if model_id == STOCK_ID:
    store.remove(KEY_SELECTION)
    clear_fallback(store)
    return SelectResult(True, "Default (stock) model selected. It applies at the next drive start.")
  entry = registry.get_entry(model_id, root)
  if entry is None or entry.builtin:
    return SelectResult(False, "That model is not installed.")
  v = registry.validate_entry(entry)  # always fresh (never cached): the pins written below must describe the files as they are now
  if not v.ok:
    return SelectResult(False, f"{entry.name} cannot be used: {v.reason}")
  store.put(KEY_SELECTION, json.dumps({"v": 1, "id": entry.id, "pin_model": v.model_sha256,
                                        "pin_manifest": v.manifest_sha256}, sort_keys=True))
  clear_fallback(store)
  return SelectResult(True, f"{entry.name} selected. It applies at the next drive start; "
                            "if it fails validation or loading the Default (stock) model is used instead.")
