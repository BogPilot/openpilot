"""What modeld should load this start: the selected model if it validates, else the exact stock model."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, STOCK_NAME
from openpilot.common.bogpilot_models import registry, selection


@dataclass
class Resolution:
  kind: str  # "stock" | "alternate"
  entry: registry.Entry | None = None
  selection: selection.Selection | None = None
  paths: dict = field(default_factory=dict)  # role -> verified Path (alternate only)
  fallback: bool = False  # a selection existed but could not be used
  reason: str = ""

  @property
  def is_alternate(self) -> bool:
    return self.kind == "alternate"


@dataclass(frozen=True)
class DriveContext:
  """One drive: `token` is stable for every modeld start in it, `started` is its wall start time."""
  token: str
  started: float


BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"


def drive_context(offroad_param_path=None, boot_id_path: str = BOOT_ID_PATH) -> DriveContext | None:
  """The current drive, from the kernel boot id and the IsOffroad param, which the manager writes ("0") exactly at
  the onroad transition (system/manager/manager.py). None when not onroad or unreadable. Never raises."""
  try:
    if offroad_param_path is None:
      from openpilot.common.params import Params
      offroad_param_path = Params().get_param_path("IsOffroad")
    with open(offroad_param_path, encoding="utf-8") as f:
      if f.read().strip() != "0":
        return None
    st = os.stat(offroad_param_path)
    with open(boot_id_path, encoding="utf-8") as f:
      boot = f.read().strip()
    if not boot:
      return None
    return DriveContext(f"{boot}:{st.st_mtime_ns}", st.st_mtime)
  except Exception:
    return None


def _stock(reason: str = "", fallback: bool = False, sel=None) -> Resolution:
  return Resolution("stock", registry.stock_entry(), sel, {}, fallback, reason)


def resolve_for_modeld(store=None, root=None, cache: dict | None = None, drive: DriveContext | None = None) -> Resolution:
  """Never raises. Any problem yields stock plus a recorded fallback (which the offroad alert reports).

  With a drive context, the first start of a drive latches the choice and later starts in the same drive reuse it;
  a choice recorded after the drive started is deferred to the next drive (stock until then, no alert)."""
  store = selection.default_store() if store is None else store
  sel = None
  try:
    sel, corrupt = selection.read_selection(store)
    if drive is not None:
      latched, found = selection.read_latch(store, drive.token)
      if found and latched is None:
        return _fail(store, None, "unknown", "the model choice saved for this drive is unreadable", "select")
      if found:
        sel, corrupt = latched, False
      elif not corrupt and sel is not None and sel.id != STOCK_ID:
        if sel.t > drive.started:
          return _stock("chosen during this drive; it applies from the next drive", False, sel)
        selection.write_latch(store, drive.token, sel)
    if corrupt:
      selection.record_fallback(store, None, "unknown", "the saved model choice is unreadable", "select")
      return _stock("the saved model choice is unreadable", True)
    if sel is None or sel.id == STOCK_ID:
      return _stock()
    fb = selection.read_state(store).get("fallback") or {}
    if (fb.get("requested_id"), fb.get("pin_model"), fb.get("pin_manifest")) == (sel.id, sel.pin_model, sel.pin_manifest):
      return _stock(str(fb.get("reason", "previous start failed")), True, sel)  # blocked until selected again
    entry = registry.get_entry(sel.id, root)
    if entry is None:
      return _fail(store, sel, sel.id, "the model is no longer installed", "validate")
    v = registry.validate_entry(entry, cache)
    if not v.ok:
      return _fail(store, sel, entry.name, v.reason, "validate")
    if (v.model_sha256, v.manifest_sha256) != (sel.pin_model, sel.pin_manifest):
      return _fail(store, sel, entry.name, "the model files changed after they were selected; select it again", "validate")
    return Resolution("alternate", entry, sel, dict(v.paths))
  except Exception as e:  # last resort: stock, never a crash in front of modeld
    try:
      return _fail(store, sel, sel.id if sel else "unknown", f"selector error ({type(e).__name__})", "validate")
    except Exception:
      return _stock(f"selector error ({type(e).__name__})", True, sel)


def _fail(store, sel, name, reason, phase) -> Resolution:
  try:
    selection.record_fallback(store, sel, name, reason, phase)
  except Exception:
    pass
  return _stock(reason, True, sel)


def note_started(store, res: Resolution) -> None:
  """After modeld finished loading: remember what is active. Never raises."""
  try:
    if res.is_alternate:
      selection.record_active(store, res.entry.id, res.entry.name, res.selection.pin_model)
    elif not res.fallback:
      selection.record_active(store, STOCK_ID, STOCK_NAME, "")
  except Exception:
    pass


def note_failed(store, res: Resolution, reason: str, phase: str) -> None:
  """Load / warmup / inference failure of the alternate: block it until the user selects it again."""
  try:
    selection.record_fallback(store, res.selection, res.entry.name if res.entry else "unknown", reason, phase)
  except Exception:
    pass
