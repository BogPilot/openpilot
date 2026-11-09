"""Local model registry: the built-in stock Default plus any models a user installed under the models dir.

Layout:  <models_dir>/<id>/manifest.json  (+ the files it lists, plain file names in the same directory)
Default models_dir is /data/bogpilot/models; BOGPILOT_MODELS_DIR overrides it. Nothing is ever downloaded:
installing a model means putting a directory there. Fresh installs have no such directory at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, STOCK_NAME, TARGET_OPENPILOT
from openpilot.common.bogpilot_models import abi as abi_mod
from openpilot.common.bogpilot_models import compat
from openpilot.common.bogpilot_models.stock import ROLE_STOCK_FILES, STOCK_HASHES

MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_FILE_BYTES = 400 * 1024 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
RESERVED_IDS = frozenset({STOCK_ID, "stock", "none", "auto"})
STOCK_LICENSE = "MIT (openpilot)"
ROLES = tuple(ROLE_STOCK_FILES)


def models_dir() -> Path:
  return Path(os.getenv("BOGPILOT_MODELS_DIR", "/data/bogpilot/models"))


def stock_models_dir() -> Path:
  return Path(__file__).resolve().parents[2] / "selfdrive" / "modeld" / "models"


class ManifestError(ValueError):
  pass


@dataclass(frozen=True)
class FileSpec:
  role: str
  name: str
  sha256: str
  size: int


@dataclass(frozen=True)
class Manifest:
  id: str
  name: str
  version: str
  openpilot: str
  license: str
  files: tuple[FileSpec, ...]
  abi_digest: str | None
  description: str
  sha256: str  # of the raw manifest bytes; selection pins it

  def file(self, role: str) -> FileSpec | None:
    return next((f for f in self.files if f.role == role), None)


@dataclass(frozen=True)
class Entry:
  id: str
  name: str
  version: str
  license: str
  builtin: bool
  directory: Path | None
  manifest: Manifest | None
  file_names: tuple[tuple[str, str, str], ...] = ()  # (role, file name, sha256) for display
  problem: str = ""  # non-empty: the entry cannot be used (invalid manifest)

  @property
  def model_sha256(self) -> str:
    return next((h for r, _, h in self.file_names if r == "driving_model"), "")


@dataclass
class Validation:
  ok: bool
  problems: list[str] = field(default_factory=list)
  model_sha256: str = ""
  manifest_sha256: str = ""
  abi_digest: str = ""
  paths: dict = field(default_factory=dict)  # role -> Path of verified files

  @property
  def reason(self) -> str:
    return "; ".join(self.problems)


def _text(d: dict, key: str, limit: int, required: bool = True) -> str:
  v = d.get(key, "")
  if not isinstance(v, str) or (required and not v.strip()):
    raise ManifestError(f"{key} must be a non-empty string" if required else f"{key} must be a string")
  v = v.strip()
  if len(v) > limit or any(ord(c) < 32 for c in v):
    raise ManifestError(f"{key} is too long or has control characters")
  return v


def parse_manifest(raw: bytes) -> Manifest:
  if len(raw) > MAX_MANIFEST_BYTES:
    raise ManifestError("manifest is too large")
  try:
    d = json.loads(raw.decode("utf-8"))
  except (UnicodeDecodeError, ValueError):
    raise ManifestError("manifest is not valid JSON") from None
  if not isinstance(d, dict):
    raise ManifestError("manifest must be a JSON object")
  if d.get("schema") != 1:
    raise ManifestError("unsupported manifest schema (expected 1)")
  if d.get("kind", "driving") != "driving":
    raise ManifestError("only driving models are supported")
  mid = _text(d, "id", 48)
  if not ID_RE.match(mid) or mid in RESERVED_IDS:
    raise ManifestError("id must be lowercase letters, digits, . _ - and not a reserved word")
  lic = d.get("license")
  if isinstance(lic, dict):
    lic = lic.get("name")
  if not isinstance(lic, str) or not lic.strip() or len(lic) > 120 or any(ord(c) < 32 for c in lic):
    raise ManifestError("license is required (a license name or {\"name\": ...})")
  files = d.get("files")
  if not isinstance(files, list) or not 1 <= len(files) <= len(ROLES):
    raise ManifestError("files must list the driving model and optional warp programs")
  specs, seen_roles, seen_names = [], set(), set()
  for f in files:
    if not isinstance(f, dict):
      raise ManifestError("each file entry must be an object")
    role, name, sha, size = f.get("role"), f.get("name"), f.get("sha256"), f.get("size")
    if role in ("vision", "policy", "vision_model", "policy_model"):
      raise ManifestError("split vision/policy models are not supported by 0.11.2 modeld (one fused driving program)")
    if role not in ROLES or role in seen_roles:
      raise ManifestError(f"unknown or duplicate file role {role!r}")
    if not isinstance(name, str) or not FILE_RE.match(name) or name in seen_names or name == MANIFEST_NAME:
      raise ManifestError(f"invalid file name for {role}")
    if not isinstance(sha, str) or not SHA_RE.match(sha):
      raise ManifestError(f"sha256 for {role} must be 64 lowercase hex characters")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_FILE_BYTES:
      raise ManifestError(f"size for {role} is missing or out of range")
    seen_roles.add(role)
    seen_names.add(name)
    specs.append(FileSpec(role, name, sha, size))
  if "driving_model" not in seen_roles:
    raise ManifestError("files must include role driving_model")
  digest = d.get("abi_digest")
  if digest is not None and (not isinstance(digest, str) or not SHA_RE.match(digest)):
    raise ManifestError("abi_digest must be 64 lowercase hex characters")
  return Manifest(mid, _text(d, "name", 60), _text(d, "version", 40), _text(d, "openpilot", 20), lic.strip(),
                  tuple(specs), digest, _text(d, "description", 300, required=False), hashlib.sha256(raw).hexdigest())


def stock_entry() -> Entry:
  names = tuple((role, fname, STOCK_HASHES[fname]) for role, fname in ROLE_STOCK_FILES.items())
  return Entry(STOCK_ID, STOCK_NAME, TARGET_OPENPILOT, STOCK_LICENSE, True, None, None, names)


def _read_manifest_file(directory: Path) -> bytes:
  p = directory / MANIFEST_NAME
  st = os.lstat(p)
  if not stat.S_ISREG(st.st_mode):
    raise ManifestError("manifest.json is not a regular file")
  if st.st_size > MAX_MANIFEST_BYTES:
    raise ManifestError("manifest is too large")
  with open(p, "rb") as f:
    return f.read(MAX_MANIFEST_BYTES + 1)


def list_entries(root: Path | None = None) -> list[Entry]:
  """Stock Default first, then installed models sorted by id. Broken installs are listed with a problem."""
  root = models_dir() if root is None else Path(root)
  entries = [stock_entry()]
  try:
    dirs = sorted(p for p in root.iterdir() if not p.name.startswith("."))
  except OSError:
    return entries
  for d in dirs:
    try:
      if d.is_symlink() or not d.is_dir():
        continue
      m = parse_manifest(_read_manifest_file(d))
      if m.id != d.name:
        raise ManifestError("directory name must equal the manifest id")
      entries.append(Entry(m.id, m.name, m.version, m.license, False, d, m,
                           tuple((f.role, f.name, f.sha256) for f in m.files)))
    except (ManifestError, OSError) as e:
      entries.append(Entry(d.name, d.name, "", "", False, d, None, (), problem=str(e) or type(e).__name__))
  return entries


def get_entry(model_id: str, root: Path | None = None) -> Entry | None:
  return next((e for e in list_entries(root) if e.id == model_id), None)


def _check_file(directory: Path, spec: FileSpec, cache: dict | None) -> tuple[Path | None, str]:
  p = directory / spec.name
  try:
    st = os.lstat(p)
  except OSError:
    return None, f"{spec.role}: file {spec.name} is missing"
  if not stat.S_ISREG(st.st_mode):
    return None, f"{spec.role}: {spec.name} is not a regular file"
  if st.st_size != spec.size:
    return None, f"{spec.role}: size {st.st_size} does not match the manifest ({spec.size})"
  key = (str(p), st.st_size, st.st_mtime_ns)
  got = cache.get(key) if cache is not None else None
  if got is None:
    try:
      got, _ = abi_mod.sha256_file(p)
    except OSError:
      return None, f"{spec.role}: {spec.name} is unreadable"
    if cache is not None:
      cache[key] = got
  if got != spec.sha256:
    return None, f"{spec.role}: hash mismatch (file changed or corrupt)"
  return p, ""


def validate_entry(entry: Entry, cache: dict | None = None) -> Validation:
  """Full check of an installed model: manifest, openpilot version, file hashes, then ABI compatibility.

  Never raises. The built-in Default is valid by construction (its hashes are pinned in stock.py and guarded
  by the release gates), so it is not re-hashed here.
  """
  try:
    return _validate(entry, cache)
  except Exception as e:  # defensive: validation must report, not crash modeld or the UI
    return Validation(False, [f"validation error: {type(e).__name__}"])


def _validate(entry: Entry, cache: dict | None) -> Validation:
  if entry.builtin:
    return Validation(True, [], STOCK_HASHES["driving_tinygrad.pkl"], "", "", {})
  if entry.problem or entry.manifest is None or entry.directory is None:
    return Validation(False, [entry.problem or "invalid manifest"])
  m, d = entry.manifest, entry.directory
  try:
    fresh = hashlib.sha256(_read_manifest_file(d)).hexdigest()
  except (OSError, ManifestError):
    return Validation(False, ["manifest.json is unreadable"])
  if fresh != m.sha256:
    return Validation(False, ["manifest changed since it was listed"])
  v = Validation(True, [], "", m.sha256)
  if m.openpilot != TARGET_OPENPILOT:
    v.problems.append(f"built for openpilot {m.openpilot}, this build is {TARGET_OPENPILOT}")
  for spec in m.files:
    p, why = _check_file(d, spec, cache)
    if p is None:
      v.problems.append(why)
    else:
      v.paths[spec.role] = p
  if v.problems:
    v.ok = False
    return v
  v.model_sha256 = m.file("driving_model").sha256
  try:
    abi = abi_mod.read_driving_abi(v.paths["driving_model"])
    v.abi_digest = abi_mod.digest(abi)
    v.problems += compat.check_driving_abi(abi)
    if m.abi_digest is not None and m.abi_digest != v.abi_digest:
      v.problems.append("manifest abi_digest does not match the model")
    for role in ROLES[1:]:
      if role in v.paths:
        v.problems += compat.check_warp_abi(abi_mod.read_warp_abi(v.paths[role]), role)
  except abi_mod.AbiError as e:
    v.problems.append(f"model unreadable: {e}")
  v.ok = not v.problems
  return v
