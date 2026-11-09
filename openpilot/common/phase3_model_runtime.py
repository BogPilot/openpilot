"""BogPilot phase 3 driving-model runtime: transactional install / select / activate / rollback.

Stdlib only. Lives outside selfdrive/modeld because modeld.py, helpers.py and the six model
payloads are pinned by tools/bogpilot/c3x_stock_models_f7db927.json; nothing here edits them.

Safety properties
* A running modeld never changes model: selection is read exactly once, at modeld start
  (modeld is only_onroad), via resolve_for_modeld(). Selection writes are offroad-only.
* Candidate artifacts are never unpickled with real classes or executed for validation. The ABI is
  read with a restricted unpickler (every global becomes an inert stub) and must EXACTLY equal the
  ABI read the same way from the verified stock driving_tinygrad.pkl: input_specs, output_specs,
  metadata shapes, output_slices and referenced class set. No tensor shape is hardcoded.
* Stock is never copied, moved or deleted; it is always the rollback target.
* Every state change is an atomic tmp+fsync+rename+dir-fsync write under an flock, so power loss
  leaves either the old or the new state. Unconfirmed alternates are retried at most
  MAX_UNCONFIRMED_STARTS times, then rolled back to stock automatically.
* "active" is only ever reported from ack.json, written by the modeld launcher after the first
  real (non-warmup) inference run succeeded.
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import io
import json
import os
import pickle
import re
import shutil
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

STOCK_ID = "stock-0.11.2-qcom"  # same opaque id as lane1 catalog
DRIVING_ASSET = "driving_tinygrad.pkl"
SCHEMA = 1
MAX_UNCONFIRMED_STARTS = 2
GATE_TTL = 60.0  # seconds; display only
MAX_OPCODE_BYTES = 16 << 20  # stock is ~0.78 MB; refuse absurd headers before reading
DEFAULT_ROOT = Path(os.environ.get("BOGPILOT_MODEL_RUNTIME_ROOT", "/data/bogpilot/model_runtime"))
REPO_ROOT = Path(__file__).resolve().parents[2]
STOCK_MODELS_DIR = REPO_ROOT / "openpilot/selfdrive/modeld/models"
STOCK_PIN_MANIFEST = REPO_ROOT / "tools/bogpilot/c3x_stock_models_f7db927.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
STOCK_LIMITATION = ("Default (stock) is the only validated driving model. No alternate with an identical 0.11.2 QCOM "
                    "ABI is installed; 0.9.7/0.10.3 and sunnypilot-container models cannot load.")


class RuntimeErrorBP(Exception):
  pass


# ---------------------------------------------------------------- static ABI (never executes payload)
class _Stub:
  _cls = "?"

  def __new__(cls, *a, **k):
    o = object.__new__(cls)
    o._a, o._k = a, k
    return o

  def __init__(self, *a, **k):
    pass

  def __setstate__(self, state):
    self._s = state

  def __setitem__(self, k, v):
    pass

  def append(self, v):
    pass

  def extend(self, v):
    pass


class _StubUnpickler(pickle.Unpickler):
  def __init__(self, f):
    super().__init__(f)
    self.types: dict[tuple[str, str], type] = {}

  def find_class(self, module, name):  # every global -> inert stub type; nothing is imported
    key = (module, name)
    if key not in self.types:
      self.types[key] = type("Stub", (_Stub,), {"_cls": f"{module}.{name}", "__module__": "phase3_stub"})
    return self.types[key]

  def persistent_load(self, pid):
    return ("out_of_band", pid)


class _SliceUnpickler(pickle.Unpickler):
  def find_class(self, module, name):
    if (module, name) == ("builtins", "slice"):
      return slice
    raise pickle.UnpicklingError(f"forbidden global {module}.{name}")


def _shape(v) -> tuple[int, ...]:
  if not isinstance(v, tuple) or not all(isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in v):
    raise RuntimeErrorBP(f"invalid shape {v!r}")
  return v


def _specs(d) -> dict:
  if not isinstance(d, dict) or not d:
    raise RuntimeErrorBP("missing specs")
  out = {}
  for name, spec in d.items():
    if not isinstance(name, str) or not isinstance(spec, tuple) or len(spec) != 3:
      raise RuntimeErrorBP(f"invalid spec {name!r}")
    shape, dtype, device = spec
    if not isinstance(dtype, str) or not isinstance(device, str):
      raise RuntimeErrorBP(f"invalid dtype/device for {name}")
    out[name] = [list(_shape(shape)), dtype, device]
  return out


def read_abi(path: Path) -> dict:
  """Interface metadata exactly as modeld.ModelState consumes it, read statically."""
  path = Path(path)
  size = path.stat().st_size
  with open(path, "rb") as f:
    head = f.read(8)
    if len(head) != 8:
      raise RuntimeErrorBP("truncated header")
    n = struct.unpack("<q", head)[0]
    if n <= 0 or n > MAX_OPCODE_BYTES or n + 8 > size:
      raise RuntimeErrorBP("not a 0.11.2 out-of-band tinygrad pickle")
    ops = f.read(n)
  u = _StubUnpickler(io.BytesIO(ops))
  try:
    obj = u.load()
  except Exception as e:
    raise RuntimeErrorBP(f"unreadable pickle: {type(e).__name__}") from None
  if not isinstance(obj, dict) or set(obj) != {"metadata", "run", "input_specs", "output_specs"}:
    raise RuntimeErrorBP("top-level keys differ from 0.11.2 modeld contract")
  md = obj["metadata"]
  if not isinstance(md, dict) or not isinstance(md.get("metadata"), dict):
    raise RuntimeErrorBP("missing metadata")
  raw = md["metadata"].get("output_slices")
  if not isinstance(raw, str):
    raise RuntimeErrorBP("missing output_slices")
  try:
    slices = _SliceUnpickler(io.BytesIO(base64.b64decode(raw))).load()
  except Exception as e:
    raise RuntimeErrorBP(f"invalid output_slices: {type(e).__name__}") from None
  if not isinstance(slices, dict) or not all(isinstance(k, str) and isinstance(v, slice) for k, v in slices.items()):
    raise RuntimeErrorBP("invalid output_slices")
  abi = {
    "input_specs": _specs(obj["input_specs"]),
    "output_specs": _specs(obj["output_specs"]),
    "input_shapes": {k: list(_shape(v)) for k, v in md.get("input_shapes", {}).items()},
    "output_shapes": {k: list(_shape(v)) for k, v in md.get("output_shapes", {}).items()},
    "output_slices": {k: [v.start, v.stop, v.step] for k, v in slices.items()},
    "classes": sorted(t._cls for t in u.types.values()),
    "run": getattr(type(obj["run"]), "_cls", type(obj["run"]).__name__),
  }
  abi["digest"] = hashlib.sha256(json.dumps(abi, sort_keys=True).encode()).hexdigest()
  abi["model_checkpoint"] = str(md["metadata"].get("model_checkpoint", ""))[:200]
  return abi


def compare_abi(stock: dict, cand: dict) -> tuple[bool, str]:
  for key in ("input_specs", "output_specs", "input_shapes", "output_shapes", "output_slices", "classes", "run"):
    if stock.get(key) != cand.get(key):
      return False, f"incompatible: {key} differs from stock 0.11.2 modeld ABI"
  return True, "ABI identical to stock 0.11.2 modeld"


# ---------------------------------------------------------------- durable file helpers
def _fsync_dir(d: Path):
  fd = os.open(d, os.O_RDONLY)
  try:
    os.fsync(fd)
  finally:
    os.close(fd)


def atomic_write_json(path: Path, obj):
  path = Path(path)
  tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
  with open(tmp, "w") as f:
    json.dump(obj, f, sort_keys=True)
    f.flush()
    os.fsync(f.fileno())
  os.replace(tmp, path)
  _fsync_dir(path.parent)


def _read_json(path: Path, default):
  try:
    with open(path) as f:
      v = json.load(f)
    return v if isinstance(v, type(default)) else default
  except (OSError, ValueError):
    return default


def sha256_file(path: Path) -> str:
  h = hashlib.sha256()
  with open(path, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
      h.update(chunk)
  return h.hexdigest()


def _boot_id() -> str:
  try:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
  except OSError:
    return "unknown"


# ---------------------------------------------------------------- runtime
@dataclass(frozen=True)
class Installed:
  id: str
  name: str
  sha256: str
  size: int
  compatible: bool | None
  reason: str
  verified: bool


@dataclass(frozen=True)
class Status:
  revision: str
  stock_verified: bool
  stock_reason: str
  installed: tuple[Installed, ...]
  selected_id: str
  pending_id: str | None
  active_id: str | None  # last runtime-acknowledged inference only
  active_detail: dict = field(default_factory=dict)
  failed: dict = field(default_factory=dict)
  error: str = ""
  limitation: str = ""


@dataclass(frozen=True)
class Resolved:
  id: str
  path: Path
  sha256: str


def _default_runtime_gate():
  try:
    from openpilot.common.phase3_model_catalog import verify_runtime
  except Exception:
    raise RuntimeErrorBP("runtime provenance gate (lane1 verify_runtime) unavailable") from None
  verify_runtime()


def _empty_state():
  return {"schema": SCHEMA, "selected_id": STOCK_ID, "pending_id": None, "trial": None, "failed": {}, "error": ""}


class Runtime:
  def __init__(self, root: Path | None = None, stock_dir: Path | None = None, pin_manifest: Path | None = None,
               runtime_gate=None):
    """runtime_gate(): raises if the compiler/loader closure is not the pinned one (lane1 verify_runtime).
    Alternates are only selectable/loadable while it passes; stock never depends on it."""
    self.runtime_gate = runtime_gate or _default_runtime_gate
    self.root = Path(root or DEFAULT_ROOT)
    self.stock_dir = Path(stock_dir or STOCK_MODELS_DIR)
    self.pin_manifest = Path(pin_manifest or STOCK_PIN_MANIFEST)
    self._cache: dict = {}

  # paths
  @property
  def bundles(self) -> Path:
    return self.root / "bundles"

  def _ensure(self):
    self.bundles.mkdir(parents=True, exist_ok=True)
    for p in self.bundles.glob(".tmp-*"):  # interrupted installs; only our own staging dirs
      shutil.rmtree(p, ignore_errors=True)
    for p in self.bundles.glob(".trash-*"):
      shutil.rmtree(p, ignore_errors=True)

  @contextlib.contextmanager
  def _locked(self):
    self.root.mkdir(parents=True, exist_ok=True)
    with open(self.root / "lock", "a+") as lf:
      fcntl.flock(lf, fcntl.LOCK_EX)
      try:
        yield
      finally:
        fcntl.flock(lf, fcntl.LOCK_UN)

  def _state(self) -> dict:
    s = _read_json(self.root / "state.json", {})
    base = _empty_state()
    if s.get("schema") != SCHEMA:
      return base
    base.update({k: s[k] for k in base if k in s})
    if not isinstance(base["failed"], dict):
      base["failed"] = {}
    return base

  def _write_state(self, s: dict):
    atomic_write_json(self.root / "state.json", s)

  def _ack(self) -> dict:
    return _read_json(self.root / "ack.json", {})

  # stock
  def stock_path(self) -> Path:
    return self.stock_dir / DRIVING_ASSET

  def _cached(self, key, path: Path, fn):
    st = path.stat()
    sig = (str(path), st.st_size, st.st_mtime_ns, st.st_ino)
    hit = self._cache.get(key)
    if hit and hit[0] == sig:
      return hit[1]
    v = fn(path)
    self._cache[key] = (sig, v)
    return v

  def stock_verification(self) -> tuple[bool, str]:
    """Verify the stock driving payload against the immutable repo pin (asset hash only)."""
    try:
      pins = json.loads(self.pin_manifest.read_text())["assets"]
      want = pins[f"openpilot/selfdrive/modeld/models/{DRIVING_ASSET}"]["sha256"]
      got = self._cached("stock_sha", self.stock_path(), sha256_file)
    except Exception as e:
      return False, f"stock pin unavailable: {type(e).__name__}"
    return (True, "stock payload matches pin") if got == want else (False, "stock payload differs from pin")

  def stock_abi(self) -> dict:
    return self._cached("stock_abi", self.stock_path(), read_abi)

  def runtime_gate_result(self, max_age: float = 0.0) -> tuple[bool, str]:
    """Fresh for authorization (select / modeld start); status() may reuse a result up to GATE_TTL old."""
    hit = self._cache.get("gate")
    if max_age and hit and time.monotonic() - hit[0] < max_age:
      return hit[1]
    try:
      self.runtime_gate()
      res = (True, "")
    except Exception as e:
      res = (False, f"runtime provenance gate failed: {str(e) or type(e).__name__}"[:200])
    self._cache["gate"] = (time.monotonic(), res)
    return res

  # bundles
  def _manifest(self, bid: str) -> dict:
    return _read_json(self.bundles / bid / "manifest.json", {})

  def _installed_ids(self) -> list[str]:
    if not self.bundles.is_dir():
      return []
    return sorted(p.name for p in self.bundles.iterdir() if p.is_dir() and ID_RE.match(p.name) and p.name != STOCK_ID)

  def _bundle_compat(self, bid: str, deep: bool = False) -> tuple[bool | None, str, bool]:
    m = self._manifest(bid)
    p = self.bundles / bid / DRIVING_ASSET
    if m.get("schema") != SCHEMA or m.get("id") != bid or not p.is_file():
      return False, "incomplete bundle", False
    if p.stat().st_size != m.get("size"):
      return False, "size mismatch", False
    if deep and sha256_file(p) != m.get("sha256"):
      return False, "hash mismatch", False
    try:
      stock = self.stock_abi()
    except Exception as e:
      return None, f"stock ABI unreadable: {e}", True
    if m.get("abi_digest") != stock["digest"]:
      return False, "incompatible with current stock ABI", True
    return True, "ABI identical to stock 0.11.2 modeld", True

  def verify_bundle_deep(self, bundle_id: str) -> tuple[bool | None, str]:
    """Full re-hash + ABI check of one installed bundle (used for rolled-back entries; never raises)."""
    try:
      comp, reason, _ = self._bundle_compat(bundle_id, deep=True)
    except Exception as e:
      return False, f"verification failed: {type(e).__name__}"
    return comp, reason

  def install(self, bundle_id: str, staged_dir: Path, manifest: dict, name: str = "") -> Installed:
    """Copy a lane1-verified staged bundle into immutable storage. Offroad or onroad safe (never activates)."""
    if not ID_RE.match(bundle_id or "") or bundle_id == STOCK_ID:
      raise RuntimeErrorBP("invalid bundle id")
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(assets, list) or [a.get("name") for a in assets] != [DRIVING_ASSET]:
      raise RuntimeErrorBP(f"unsupported bundle: runtime substitutes only {DRIVING_ASSET}; warps/DM stay stock")
    want = assets[0]
    if not (isinstance(want.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", want["sha256"]) and isinstance(want.get("size"), int)):
      raise RuntimeErrorBP("manifest lacks exact sha256/size")
    src = Path(staged_dir) / DRIVING_ASSET
    with self._locked():
      self._ensure()
      final = self.bundles / bundle_id
      if final.exists():
        raise RuntimeErrorBP("bundle id already installed")
      tmp = self.bundles / f".tmp-{bundle_id}-{uuid.uuid4().hex[:8]}"
      tmp.mkdir()
      try:
        h, n = hashlib.sha256(), 0
        with open(src, "rb") as fi, open(tmp / DRIVING_ASSET, "wb") as fo:
          for chunk in iter(lambda: fi.read(1 << 20), b""):
            h.update(chunk); fo.write(chunk); n += len(chunk)
          fo.flush(); os.fsync(fo.fileno())
        if n != want["size"] or h.hexdigest() != want["sha256"]:
          raise RuntimeErrorBP("staged artifact does not match manifest sha256/size")
        if h.hexdigest() == self._cached("stock_sha", self.stock_path(), sha256_file):
          raise RuntimeErrorBP("artifact is the stock model; not an alternate")
        ok, reason = compare_abi(self.stock_abi(), cand := read_abi(tmp / DRIVING_ASSET))
        if not ok:
          raise RuntimeErrorBP(reason)
        atomic_write_json(tmp / "manifest.json", {"schema": SCHEMA, "id": bundle_id, "name": name or bundle_id,
                                                  "sha256": want["sha256"], "size": n, "abi_digest": cand["digest"],
                                                  "model_checkpoint": cand["model_checkpoint"], "installed_at": time.time()})
        os.chmod(tmp / DRIVING_ASSET, 0o444)
        os.rename(tmp, final)
        _fsync_dir(self.bundles)
      except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
      s = self._state()
      s["failed"].pop(bundle_id, None)
      self._write_state(s)
    return Installed(bundle_id, name or bundle_id, want["sha256"], n, True, reason, True)

  # status / revision
  def status(self) -> Status:
    stock_ok, stock_reason = self.stock_verification()
    s, ack = self._state(), self._ack()
    inst = []
    for bid in self._installed_ids():
      comp, reason, verified = self._bundle_compat(bid)
      m = self._manifest(bid)
      inst.append(Installed(bid, str(m.get("name", bid)), str(m.get("sha256", "")), int(m.get("size", 0) or 0),
                            comp, reason, verified))
    known = {STOCK_ID} | {i.id for i in inst}
    active = ack.get("id") if ack.get("id") in known else None
    pending = s["pending_id"] if s["pending_id"] in known else None
    gate_ok, gate_reason = self.runtime_gate_result(GATE_TTL) if inst else (True, "")
    if not gate_ok:
      inst = [Installed(i.id, i.name, i.sha256, i.size, None if i.compatible else i.compatible, gate_reason, i.verified)
              for i in inst]
    limitation = "" if any(i.compatible is True for i in inst) else STOCK_LIMITATION
    if not gate_ok:
      limitation = (limitation + " Alternates blocked: " + gate_reason).strip()
    if ack.get("chestnut"):
      limitation = (limitation + " Chestnut big model always runs stock.").strip()
    payload = {"s": s, "ack": ack, "inst": [i.__dict__ for i in inst], "stock": [stock_ok, stock_reason]}
    rev = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return Status(rev, stock_ok, stock_reason, tuple(inst), s["selected_id"] if s["selected_id"] in known else STOCK_ID,
                  pending, active, dict(ack), dict(s["failed"]), str(s.get("error") or ""), limitation)

  # offroad transactions
  def _txn(self, expected_revision: str, is_offroad) -> tuple[bool, str]:
    if self.status().revision != expected_revision:
      return False, "Model state changed. Review and confirm again."
    if not is_offroad():
      return False, "Model changes are only allowed while offroad."
    return True, ""

  def select(self, bundle_id: str, expected_revision: str, is_offroad) -> tuple[bool, str]:
    with self._locked():
      ok, msg = self._txn(expected_revision, is_offroad)
      if not ok:
        return ok, msg
      st = self.status()
      if bundle_id != STOCK_ID:
        gate_ok, gate_reason = self.runtime_gate_result()
        if not gate_ok:
          return False, f"Cannot select: {gate_reason}"
        comp, reason, _ = self._bundle_compat(bundle_id, deep=True)
        if comp is not True:
          return False, f"Cannot select: {reason}"
      if bundle_id == st.active_id and st.pending_id is None and st.selected_id == bundle_id:
        return False, "Already active."
      prev = self._state()
      s = dict(prev, selected_id=bundle_id, pending_id=None if bundle_id == st.active_id else bundle_id,
               trial=None, error="")
      s["failed"] = {k: v for k, v in prev["failed"].items() if k != bundle_id}
      self._write_state(s)
      if not is_offroad():  # lost the race with onroad transition: undo, nothing applied
        self._write_state(prev)
        return False, "Went onroad; selection not changed."
    return True, "Queued. It becomes active only after the next drive starts and inference confirms it."

  def rollback_to_stock(self, expected_revision: str, is_offroad) -> tuple[bool, str]:
    return self.select(STOCK_ID, expected_revision, is_offroad)

  def delete(self, bundle_id: str, expected_revision: str, is_offroad) -> tuple[bool, str]:
    with self._locked():
      ok, msg = self._txn(expected_revision, is_offroad)
      if not ok:
        return ok, msg
      st = self.status()
      if bundle_id == STOCK_ID or bundle_id not in {i.id for i in st.installed}:
        return False, "Stock is protected." if bundle_id == STOCK_ID else "Not installed."
      if bundle_id in (st.active_id, st.pending_id, st.selected_id):
        return False, "Active, selected or pending models cannot be deleted."
      trash = self.bundles / f".trash-{bundle_id}-{uuid.uuid4().hex[:8]}"
      os.rename(self.bundles / bundle_id, trash)
      _fsync_dir(self.bundles)
      shutil.rmtree(trash, ignore_errors=True)
    return True, "Deleted."

  # modeld side (launcher only)
  def _fail(self, s: dict, bid: str, reason: str):
    s["failed"][bid] = reason[:200]
    s.update(selected_id=STOCK_ID, pending_id=None, trial=None, error=f"{bid} rolled back to stock: {reason}"[:300])
    self._write_state(s)

  def resolve_for_modeld(self, chestnut: bool) -> Resolved:
    stock = Resolved(STOCK_ID, self.stock_path(), "")
    if chestnut:
      return stock
    try:
      with self._locked():
        s = self._state()
        target = s["pending_id"] or s["selected_id"]
        if target == STOCK_ID or target not in self._installed_ids():
          if target != STOCK_ID:
            self._fail(s, target, "bundle missing")
          return stock
        if target in s["failed"]:
          return stock
        if not self.runtime_gate_result()[0]:
          return stock  # closure not provably the pinned one: run stock, keep selection pending
        trial = s["trial"] if isinstance(s["trial"], dict) and s["trial"].get("id") == target else {"id": target, "attempts": 0}
        if trial["attempts"] >= MAX_UNCONFIRMED_STARTS:
          self._fail(s, target, f"not confirmed after {MAX_UNCONFIRMED_STARTS} starts")
          return stock
        comp, reason, _ = self._bundle_compat(target, deep=True)
        if comp is not True:
          self._fail(s, target, reason)
          return stock
        trial["attempts"] += 1
        s["trial"] = trial
        self._write_state(s)
        m = self._manifest(target)
        return Resolved(target, self.bundles / target / DRIVING_ASSET, m["sha256"])
    except Exception:
      return stock  # any runtime-state problem: stock, never block modeld

  def record_failure(self, bid: str, reason: str):
    if bid == STOCK_ID:
      return
    with self._locked():
      self._fail(self._state(), bid, reason)

  def confirm(self, bid: str, sha: str, chestnut: bool):
    with self._locked():
      atomic_write_json(self.root / "ack.json", {"id": bid, "sha256": sha, "chestnut": bool(chestnut), "pid": os.getpid(),
                                                 "boot_id": _boot_id(), "t": time.time()})
      s = self._state()
      if s["pending_id"] == bid:
        s["pending_id"] = None
      if isinstance(s["trial"], dict) and s["trial"].get("id") == bid:
        s["trial"] = None
      self._write_state(s)
