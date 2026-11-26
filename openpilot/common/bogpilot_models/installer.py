"""Download, verify and install a hosted driving model, offroad only. Never touches the stock models.

A catalog item (source.CATALOG) looks like the installed manifest plus a `url` per file:

  {"id": "my-model", "name": "My Model", "version": "1.0", "openpilot": "0.11.2", "license": "MIT",
   "onnx_sha256": "<64 hex>", "abi_digest": "<64 hex, optional>", "description": "optional",
   "url": "<first file url>",   # used by source.catalog_entries to screen the item
   "files": [{"role": "driving_model", "name": "driving_tinygrad.pkl", "sha256": "...", "size": 70491206,
              "url": "https://github.com/BogPilot/<repo>/releases/download/<tag>/driving_tinygrad.pkl"}, ...]}

Steps, all of which must pass before anything appears in the models directory:
  1. offroad (`is_offroad()` must return exactly True), license redistributable, every URL on our GitHub releases;
  2. each file is fetched through source.fetch_bytes (allowlist on every hop, sha256 checked) and its size checked;
  3. files and a manifest.json are written to a hidden staging directory (`.staging-<id>-<pid>`) under the models
     directory, then the staged model goes through registry.validate_entry (hashes + fits the 0.11.2 driving code);
  4. only a model that validates is moved into place with a rename. A previous install of the same id is moved
     aside first and deleted only after the new one is in place; on any failure the old one is restored.
Every failure removes the staging directory and returns a reason; nothing here raises.

The stock model directory (selfdrive/modeld/models) is never written. The saved choice is not changed by an
install: the user still picks the model on the Driving Model page, and modeld re-validates it at the next drive.
Removing the model that is currently chosen resets the choice to Default (stock).
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, registry, selection, source

MANIFEST_KEYS = ("id", "name", "version", "openpilot", "license", "onnx_sha256", "abi_digest", "description")
FILE_KEYS = ("role", "name", "sha256", "size")
MAX_DOWNLOAD_BYTES = registry.MAX_FILE_BYTES
_TIMEOUT_S = 60


@dataclass(frozen=True)
class InstallResult:
  ok: bool
  message: str
  model_id: str = ""


def _offroad(is_offroad) -> bool:
  try:
    return is_offroad() is True
  except Exception:
    return False


def manifest_for(item: dict) -> dict:
  """The manifest.json written next to the files: the catalog item without URLs (schema 1)."""
  m = {"schema": 1}
  for k in MANIFEST_KEYS:
    if k in item and item[k] is not None:
      m[k] = item[k]
  m["files"] = [{k: f[k] for k in FILE_KEYS if k in f} for f in item.get("files") or ()]
  return m


def screen(item) -> str:
  """'' if the catalog item may be fetched at all, else why not. No network."""
  if not isinstance(item, dict):
    return "not a catalog entry"
  if item.get("published", True) is not True:
    return "not published on our GitHub releases yet"
  if not source.license_is_redistributable(item.get("license")):
    return "license is missing or not cleared for redistribution"
  files = item.get("files")
  if not isinstance(files, list) or not files:
    return "no files listed"
  for f in files:
    if not isinstance(f, dict) or not source.allowed_source_url(f.get("url") or ""):
      return "a file is not hosted on our GitHub releases"
  try:
    registry.parse_manifest(json.dumps(manifest_for(item)).encode())
  except registry.ManifestError as e:
    return f"catalog entry is invalid: {e}"
  return ""


def install(item: dict, is_offroad, transport=None, root: Path | None = None, cache: dict | None = None,
            progress=None) -> InstallResult:
  """Fetch, verify and install one catalog item. `transport` defaults to https_transport (tests inject one)."""
  mid = item.get("id", "") if isinstance(item, dict) else ""
  staging = None
  try:
    if not _offroad(is_offroad):
      return InstallResult(False, "Driving models can only be downloaded while the car is off (offroad).", mid)
    why = screen(item)
    if why:
      return InstallResult(False, f"Not downloaded: {why}.", mid)
    root = registry.models_dir() if root is None else Path(root)
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{mid}-{os.getpid()}"
    if staging.exists():
      shutil.rmtree(staging)
    staging.mkdir()
    transport = https_transport if transport is None else transport
    files = item["files"]
    for i, f in enumerate(files):
      if not _offroad(is_offroad):
        return InstallResult(False, "Download stopped: the car is no longer off.", mid)
      data = source.fetch_bytes(f["url"], f["sha256"], transport)
      if len(data) != f["size"]:
        return InstallResult(False, f"Not installed: {f['name']} has the wrong size.", mid)
      with open(staging / f["name"], "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
      if progress is not None:
        try:
          progress(i + 1, len(files))
        except Exception:
          pass
    (staging / registry.MANIFEST_NAME).write_text(json.dumps(manifest_for(item), sort_keys=True))
    m = registry.parse_manifest((staging / registry.MANIFEST_NAME).read_bytes())
    entry = registry.Entry(m.id, m.name, m.version, m.license, False, staging, m,
                           tuple((x.role, x.name, x.sha256) for x in m.files))
    v = registry.validate_entry(entry, None)  # never the shared cache: the staged path is about to be renamed
    if not v.ok:
      return InstallResult(False, f"Not installed: {v.reason}.", mid)
    if not _offroad(is_offroad):
      return InstallResult(False, "Not installed: the car is no longer off.", mid)
    final, old = root / mid, root / f".old-{mid}-{os.getpid()}"
    if old.exists():
      shutil.rmtree(old)
    if final.exists() or final.is_symlink():
      os.rename(final, old)
    try:
      os.rename(staging, final)
    except OSError:
      if old.exists():
        os.rename(old, final)
      raise
    staging = None
    if old.exists():
      shutil.rmtree(old, ignore_errors=True)
    if cache is not None:
      cache.clear()
    return InstallResult(True, f"{m.name} is installed. Select it to use it from the next drive.", mid)
  except source.SourceError as e:
    return InstallResult(False, f"Not downloaded: {e}.", mid)
  except Exception as e:
    return InstallResult(False, f"Not installed ({type(e).__name__}).", mid)
  finally:
    if staging is not None:
      shutil.rmtree(staging, ignore_errors=True)


def remove(model_id: str, is_offroad, store=None, root: Path | None = None) -> InstallResult:
  """Delete an installed (non-stock) model, offroad only. If it is the saved choice, the choice returns to Default."""
  try:
    if model_id == STOCK_ID or not registry.ID_RE.match(model_id or ""):
      return InstallResult(False, "The Default (stock) model cannot be removed.", model_id or "")
    if not _offroad(is_offroad):
      return InstallResult(False, "Driving models can only be removed while the car is off (offroad).", model_id)
    root = registry.models_dir() if root is None else Path(root)
    d = root / model_id
    if d.is_symlink() or not d.is_dir():
      return InstallResult(False, "That model is not installed.", model_id)
    store = selection.default_store() if store is None else store
    chosen, _ = selection.read_selection(store)
    if chosen is not None and chosen.id == model_id:
      r = selection.select(STOCK_ID, is_offroad, store, root)
      if not r.ok:
        return InstallResult(False, r.message, model_id)
    shutil.rmtree(d)
    return InstallResult(True, "Removed. The Default (stock) model is used unless you select another.", model_id)
  except Exception as e:
    return InstallResult(False, f"Not removed ({type(e).__name__}).", model_id)


class _Response:
  def __init__(self, content=None, location=None):
    self.content, self.location = content, location


def https_transport(url: str):
  """One request, no automatic redirects (source.fetch_bytes checks and follows each hop), size-capped."""
  import urllib.request

  class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
      return None

  opener = urllib.request.build_opener(_NoRedirect)
  req = urllib.request.Request(url, headers={"User-Agent": "BogPilot-model-installer", "Accept": "application/octet-stream"})
  try:
    resp = opener.open(req, timeout=_TIMEOUT_S)
  except urllib.error.HTTPError as e:
    if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
      return _Response(location=e.headers["Location"])
    raise source.SourceError(f"download failed (HTTP {e.code})") from None
  with resp:
    length = resp.headers.get("Content-Length")
    if length is not None and length.isdigit() and int(length) > MAX_DOWNLOAD_BYTES:
      raise source.SourceError("file is too large")
    data = resp.read(MAX_DOWNLOAD_BYTES + 1)
  if len(data) > MAX_DOWNLOAD_BYTES:
    raise source.SourceError("file is too large")
  return _Response(content=data)
