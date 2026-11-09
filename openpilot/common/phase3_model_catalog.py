"""Fail-closed 0.11.2 QCOM model catalog and stock-bundle staging.

Downloads are explicit, public and content-pinned. Nothing here selects a model,
loads pickle code, changes Params, or writes into the running model directory.
The old 0.9.7 split vision/policy and thneed models are NOT compatible entries.
"""
from __future__ import annotations

from dataclasses import dataclass
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
from typing import Callable
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

STOCK_COMMIT = "f7db927c728bab57bb1263e05465766a8f28fc9d"
MANIFEST_SHA256 = "933974835b4d6aa7617a128e18ce8aa60aff6b73099c2f31801e687566d09b57"
STOCK_ID = "stock-0.11.2-qcom"
MANIFEST = "tools/bogpilot/c3x_stock_models_f7db927.json"
MODEL_DIR = "openpilot/selfdrive/modeld/models"
FORMAT = "tinygrad-oob-monolithic-0.11.2"
STOCK_NAME = "Default (stock)"
SUPPLEMENT = "tools/bogpilot/c3x_runtime_lock_supplement.json"
# Pinned in code (not in the supplement itself) so editing the supplement alone cannot widen the gate.
SUPPLEMENT_SHA256 = "fa59890ae4e52c07e7993c07930c739e68ead4cdb2794afb3c66be4479da2c3a"
ATTESTABLE = ("pyproject.toml", "uv.lock", "openpilot/selfdrive/modeld/modeld.py")
BLOCKER = (
  "No verified alternate 0.11.2 QCOM bundle is available (surveyed Nov 9 2026: FrogPilot 0.9.7/0.10.3 models are "
  "thneed or split vision/policy; sunnypilot catalog models use its own plain-artifact container and a different "
  "input/state/output ABI). A complete 0.11.2 bundle with per-artifact license, pinned SHA256/size and matching "
  "compiler/runtime/ABI evidence is required before selection."
)
# Sizes measured from the six stock Git blobs; hashes come from the pinned manifest.
SIZES = {
  "driving_tinygrad.pkl": 70491206,
  "dmonitoring_model_tinygrad.pkl": 16419617,
  "driving_warp_1344x760_tinygrad.pkl": 844693,
  "driving_warp_1928x1208_tinygrad.pkl": 844502,
  "dm_warp_1344x760_tinygrad.pkl": 1401865,
  "dm_warp_1928x1208_tinygrad.pkl": 1401817,
}


class CatalogError(ValueError):
  pass


class DownloadCancelled(CatalogError):
  pass


@dataclass(frozen=True)
class ModelAsset:
  name: str
  sha256: str
  size: int
  url: str


@dataclass(frozen=True)
class ModelEntry:
  id: str
  name: str
  version: str
  architecture: str
  backend: str
  format: str
  stock_commit: str
  assets: tuple[ModelAsset, ...]


@dataclass(frozen=True)
class Catalog:
  entries: tuple[ModelEntry, ...]
  blockers: tuple[str, ...]


@dataclass(frozen=True)
class ModelInspection:
  """Catalog-side facts for lane3 Model; NEVER a running-inference acknowledgement."""
  id: str
  name: str
  available: bool
  downloaded: bool
  compatible: bool
  reason: str
  protected: bool
  revision: str  # lane2 must combine with runtime/action/offroad revision


def _root(root: Path | None) -> Path:
  return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[2]


def _manifest(root: Path) -> dict:
  p = root / MANIFEST
  try:
    if p.is_symlink():
      raise CatalogError("model manifest must not be a symlink")
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
      raise CatalogError("stock manifest integrity failure")
    manifest = json.loads(raw)
    if manifest["stock_commit"] != STOCK_COMMIT or manifest["backend"] != "QCOM" or manifest["schema"] != 1:
      raise CatalogError("unsupported stock manifest provenance")
    if set(manifest["assets"]) != {f"{MODEL_DIR}/{name}" for name in SIZES}:
      raise CatalogError("incomplete six-file stock pin set")
    return manifest
  except (OSError, KeyError, json.JSONDecodeError) as e:
    raise CatalogError("stock manifest unavailable or invalid") from e


def load_catalog(root: Path | None = None) -> Catalog:
  """Only source-reviewed, pinned compatible bundles; no network discovery."""
  m = _manifest(_root(root))
  assets = tuple(ModelAsset(name, m["assets"][f"{MODEL_DIR}/{name}"]["sha256"], size,
                           f"https://raw.githubusercontent.com/commaai/openpilot/{STOCK_COMMIT}/{MODEL_DIR}/{name}")
                 for name, size in SIZES.items())
  stock = ModelEntry(STOCK_ID, STOCK_NAME, "0.11.2", "comma_arm64", "QCOM", FORMAT, STOCK_COMMIT, assets)
  return Catalog((stock,), (BLOCKER,))


def _trusted(entry: ModelEntry, root: Path | None = None) -> None:
  if entry not in load_catalog(root).entries:
    raise CatalogError("entry is not in the pinned compatible catalog")


def _digest(path: Path) -> str:
  h = hashlib.sha256()
  with path.open("rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
      h.update(chunk)
  return h.hexdigest()


def _supplement(root: Path) -> dict[str, str]:
  """Hash-pinned attestation for the two lock files telemetry removal legitimately changed.

  Only ATTESTABLE paths, only exact attested sha256 values; any other drift (or a missing/modified
  supplement) leaves the original stock pin as the only accepted value, i.e. fail closed.
  """
  p = root / SUPPLEMENT
  try:
    if p.is_symlink() or not p.is_file():
      return {}
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SUPPLEMENT_SHA256:
      return {}
    d = json.loads(raw)
    if d.get("schema") != 1 or d.get("base_manifest_sha256") != MANIFEST_SHA256:
      return {}
    att = d.get("attestations", {})
    return {k: v["sha256"] for k, v in att.items()
            if k in ATTESTABLE and isinstance(v, dict) and isinstance(v.get("sha256"), str) and len(v["sha256"]) == 64}
  except (OSError, ValueError, KeyError, TypeError, AttributeError):
    return {}


def verify_runtime(root: Path | None = None, architecture: str = "comma_arm64", backend: str = "QCOM") -> None:
  """Check compiler, loader, camera geometry and model ABI without loading pickle."""
  root = _root(root)
  if architecture != "comma_arm64" or backend != "QCOM":
    raise CatalogError("stock bundle requires comma_arm64/QCOM, not host or chestnut models")
  m = _manifest(root)
  # Match the original gate inventory without importing build tooling on-device.
  paths = {p for p in glob.glob("tinygrad_repo/**", root_dir=root, recursive=True)
           if "pycache" not in p and (root / p).is_file()}
  for folder in ("openpilot/selfdrive/modeld", "openpilot/common/transformations", "openpilot/system/camerad/cameras"):
    paths.update(p.relative_to(root).as_posix() for p in (root / folder).rglob("*.py") if "__pycache__" not in p.parts)
  paths.update(p.relative_to(root).as_posix() for p in (root / MODEL_DIR).glob("*.onnx"))
  paths.update(("pyproject.toml", "uv.lock"))
  if paths != set(m["inputs"]):
    raise CatalogError("compiler/runtime input inventory drift")
  attested = _supplement(root)
  try:
    for rel, pin in m["inputs"].items():
      got = _digest(root / rel)
      if got != pin["sha256"] and not (rel in attested and got == attested[rel]):
        raise CatalogError(f"compiler/runtime ABI drift: {rel}")
    builder = (root / "openpilot/selfdrive/modeld/SConscript").read_bytes()
    begin = b"\n# BEGIN VERIFIED STOCK MODELS\n"
    end = b"# END VERIFIED STOCK MODELS\n"
    if builder.count(begin) != 1 or builder.count(end) != 1:
      raise CatalogError("model builder guard missing")
    a = builder.index(begin)
    b = builder.index(end, a) + len(end)
    if hashlib.sha256(builder[:a] + builder[b:]).hexdigest() != m["default_builder_sha256"]:
      raise CatalogError("default compiler model builder drift")
  except OSError as e:
    raise CatalogError("compiler/runtime input unavailable") from e


def verify_bundle(entry: ModelEntry, directory: Path, *, root: Path | None = None) -> None:
  """Hash/size/format validation of trusted bytes only; NEVER pickle.load."""
  _trusted(entry, root)
  directory = Path(directory)
  if directory.is_symlink() or not directory.is_dir():
    raise CatalogError("bundle directory missing or symlinked")
  try:
    for asset in entry.assets:
      p = directory / asset.name
      if p.is_symlink() or not p.is_file() or p.stat().st_size != asset.size:
        raise CatalogError(f"missing, linked or wrong-size model: {asset.name}")
      if _digest(p) != asset.sha256:
        raise CatalogError(f"model integrity failure: {asset.name}")
      with p.open("rb") as f:
        prefix = f.read(10)
      # Stock warp pickles have a pickle header; models have an OOB length prefix.
      if prefix[:1] != b"\x80":
        length = struct.unpack("<q", prefix[:8])[0]
        if not 0 < length <= asset.size - 8 or prefix[8:9] != b"\x80":
          raise CatalogError(f"unexpected model format: {asset.name}")
  except OSError as e:
    raise CatalogError("bundle verification failed") from e


def inspect_entry(entry: ModelEntry, directory: Path | None = None, *, root: Path | None = None,
                  architecture: str = "comma_arm64", backend: str = "QCOM") -> ModelInspection:
  """Fresh catalog/ABI/artifact facts for an adapter; do not run on the render loop.

  'downloaded' is independent of 'compatible': verified files can exist while
  runtime provenance has drifted. No active/pending identity is inferred here.
  """
  _trusted(entry, root)
  reasons = []
  compatible = downloaded = True
  try:
    verify_runtime(root, architecture, backend)
  except CatalogError as e:
    compatible = False
    reasons.append(str(e))
  try:
    verify_bundle(entry, directory if directory is not None else _root(root) / MODEL_DIR, root=root)
  except CatalogError as e:
    downloaded = False
    reasons.append(str(e))
  reason = "; ".join(reasons)
  fields = (MANIFEST_SHA256, entry.id, architecture, backend, compatible, downloaded, reason)
  revision = hashlib.sha256(json.dumps(fields).encode()).hexdigest()
  return ModelInspection(entry.id, entry.name, True, downloaded, compatible, reason, True, revision)


class _NoRedirect(HTTPRedirectHandler):
  def redirect_request(self, req, fp, code, msg, headers, newurl):
    raise CatalogError("model URL redirect rejected")


def _open_url(url: str, timeout: float):
  # No environment proxies, credentials, cookies, redirects or account services.
  return build_opener(ProxyHandler({}), _NoRedirect()).open(
    Request(url, headers={"User-Agent": "BogPilot-model-staging/1", "Accept-Encoding": "identity"}), timeout=timeout)


def download_bundle(entry: ModelEntry, cache_root: Path, cancel_event=None, *, root: Path | None = None,
                    architecture: str = "comma_arm64", backend: str = "QCOM", timeout: float = 180,
                    progress: Callable[[int, int], None] | None = None) -> Path:
  """Stage verified bundle atomically, never install. No retries; max 180s plus a 3s read.

  The trusted cache must be private to the application. Return value is a verified
  directory for lane2's offroad-only activation; existing stock files are untouched.
  A cancelled/failed attempt removes only its own unpublished temporary directory.
  """
  _trusted(entry, root)
  verify_runtime(root, architecture, backend)
  if not 0 < timeout <= 180:
    raise CatalogError("timeout must be in (0, 180] seconds")
  source = _root(root)
  cache = Path(cache_root).absolute()
  if cache.is_symlink() or any(p.is_symlink() for p in cache.parents):
    raise CatalogError("cache path must not traverse symlinks")
  cache = cache.resolve()
  if cache == source or source in cache.parents or cache in source.parents:
    raise CatalogError("cache must not overlap source checkout")
  deadline = time.monotonic() + timeout

  def check():
    if cancel_event is not None and cancel_event.is_set():
      raise DownloadCancelled("model download cancelled")
    if time.monotonic() >= deadline:
      raise CatalogError("model download deadline exceeded")

  check()
  cache.mkdir(mode=0o700, parents=True, exist_ok=True)
  target = cache / entry.id
  if target.exists() or target.is_symlink():
    verify_bundle(entry, target, root=root)
    check()
    return target
  total = sum(a.size for a in entry.assets)
  if shutil.disk_usage(cache).free < total + 16 * 1024 * 1024:
    raise CatalogError("insufficient space for verified model staging")
  staging = Path(tempfile.mkdtemp(prefix=f".{entry.id}-", dir=cache))
  done = 0
  try:
    for asset in entry.assets:
      check()
      p = staging / asset.name
      h = hashlib.sha256()
      count = 0
      with _open_url(asset.url, min(3, max(0.1, deadline - time.monotonic()))) as response:
        if response.status != 200 or response.geturl() != asset.url:
          raise CatalogError("unexpected model HTTP response")
        encoding = response.headers.get("Content-Encoding", "identity")
        length = response.headers.get("Content-Length")
        if encoding != "identity" or (length is not None and int(length) != asset.size):
          raise CatalogError(f"wrong encoded/model download size: {asset.name}")
        with p.open("xb") as f:
          while True:
            check()
            # read1 avoids a slow sender holding a multi-read .read() open forever.
            chunk = response.read1(min(256 * 1024, asset.size - count + 1))
            if not chunk:
              break
            count += len(chunk)
            if count > asset.size:
              raise CatalogError("model download exceeds pinned size")
            h.update(chunk)
            f.write(chunk)
            done += len(chunk)
            if progress is not None:
              progress(done, total)
          f.flush()
          os.fsync(f.fileno())
      if count != asset.size or h.hexdigest() != asset.sha256:
        raise CatalogError(f"download integrity/size failure: {asset.name}")
      p.chmod(0o444)
    verify_bundle(entry, staging, root=root)
    check()
    # Never overwrite a previously published cache. Concurrent winner must verify.
    try:
      staging.rename(target)
    except OSError:
      if not target.exists():
        raise
      verify_bundle(entry, target, root=root)
    return target
  except (OSError, ValueError) as e:
    if isinstance(e, CatalogError):
      raise
    raise CatalogError("model download failed; no bundle published") from e
  finally:
    if staging.exists():
      shutil.rmtree(staging)
