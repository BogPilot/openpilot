"""Static reader for the tinygrad pickles modeld loads. It never imports tinygrad and never runs model code.

A 0.11.2 driving model is ONE out-of-band tinygrad pickle (vision and policy are fused into a single compiled
program; there are no separate vision/policy files). Its sibling "warp" programs turn camera frames into the
model's `new_img` input and are plain pickles. Both are read with an unpickler whose every global is replaced by
an inert stub, so unknown or hostile payloads can describe themselves but cannot execute anything.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import pickle
import struct
from pathlib import Path

MAX_OPCODE_BYTES = 32 * 1024 * 1024
MAX_WARP_BYTES = 64 * 1024 * 1024


class AbiError(ValueError):
  """The file is not a readable 0.11.2 tinygrad pickle."""


class _Stub:
  _cls = "?"

  def __new__(cls, *a, **k):
    return object.__new__(cls)

  def __init__(self, *a, **k):
    pass

  def __setstate__(self, state):
    pass

  def __setitem__(self, key, value):
    pass

  def append(self, value):
    pass

  def extend(self, values):
    pass


class _StubUnpickler(pickle.Unpickler):
  def __init__(self, f):
    super().__init__(f)
    self.seen: dict[tuple[str, str], type] = {}

  def find_class(self, module, name):
    key = (module, name)
    if key not in self.seen:
      self.seen[key] = type("Stub", (_Stub,), {"_cls": f"{module}.{name}"})
    return self.seen[key]

  def persistent_load(self, pid):
    return ("out_of_band", pid)


class _SliceUnpickler(pickle.Unpickler):
  def find_class(self, module, name):
    if (module, name) == ("builtins", "slice"):
      return slice
    raise AbiError(f"forbidden global {module}.{name} in output_slices")


def _shape(v) -> list[int]:
  if not isinstance(v, tuple) or not all(isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in v):
    raise AbiError(f"invalid shape {v!r}")
  return list(v)


def _specs(d) -> dict[str, list]:
  if not isinstance(d, dict) or not d:
    raise AbiError("missing tensor specs")
  out = {}
  for name, spec in d.items():
    if not isinstance(name, str) or not isinstance(spec, tuple) or len(spec) != 3:
      raise AbiError(f"invalid tensor spec {name!r}")
    shape, dtype, device = spec
    if not isinstance(dtype, str) or not isinstance(device, str):
      raise AbiError(f"invalid dtype/device for {name}")
    out[name] = [_shape(shape), dtype, device]
  return out


def _load_stubbed(data: bytes):
  u = _StubUnpickler(io.BytesIO(data))
  try:
    obj = u.load()
  except Exception as e:  # truncated / corrupt / not a pickle
    raise AbiError(f"unreadable pickle ({type(e).__name__})") from None
  return obj, sorted(f"{m}.{n}" for m, n in u.seen)


def read_driving_abi(path) -> dict:
  """Interface of a driving model, JSON-able. Raises AbiError."""
  path = Path(path)
  size = path.stat().st_size
  with open(path, "rb") as f:
    head = f.read(8)
    if len(head) != 8:
      raise AbiError("truncated header")
    n = struct.unpack("<q", head)[0]
    if n <= 0 or n > MAX_OPCODE_BYTES or n + 8 > size:
      raise AbiError("not an out-of-band tinygrad pickle")
    ops = f.read(n)
  obj, classes = _load_stubbed(ops)
  if not isinstance(obj, dict) or set(obj) != {"metadata", "run", "input_specs", "output_specs"}:
    raise AbiError("top-level keys differ from the 0.11.2 modeld contract")
  md = obj["metadata"]
  if not isinstance(md, dict) or not isinstance(md.get("metadata"), dict):
    raise AbiError("missing metadata")
  raw = md["metadata"].get("output_slices")
  if not isinstance(raw, str):
    raise AbiError("missing output_slices")
  try:
    slices = _SliceUnpickler(io.BytesIO(base64.b64decode(raw))).load()
  except AbiError:
    raise
  except Exception as e:
    raise AbiError(f"invalid output_slices ({type(e).__name__})") from None
  if not isinstance(slices, dict) or not all(isinstance(k, str) and isinstance(v, slice) for k, v in slices.items()):
    raise AbiError("invalid output_slices")
  for s in slices.values():
    if not all(x is None or (isinstance(x, int) and not isinstance(x, bool)) for x in (s.start, s.stop)) or s.step not in (None, 1):
      raise AbiError("unsupported output slice")
  return {
    "input_specs": _specs(obj["input_specs"]),
    "output_specs": _specs(obj["output_specs"]),
    "input_shapes": {str(k): _shape(v) for k, v in md.get("input_shapes", {}).items()},
    "output_shapes": {str(k): _shape(v) for k, v in md.get("output_shapes", {}).items()},
    "output_slices": {k: [v.start, v.stop] for k, v in slices.items()},
    "classes": classes,
    "run": getattr(type(obj["run"]), "_cls", type(obj["run"]).__name__),
  }


def read_warp_abi(path) -> dict:
  path = Path(path)
  if path.stat().st_size > MAX_WARP_BYTES:
    raise AbiError("warp program too large")
  obj, classes = _load_stubbed(path.read_bytes())
  if not isinstance(obj, dict) or "run" not in obj or "input_specs" not in obj:
    raise AbiError("warp pickle keys differ from the 0.11.2 modeld contract")
  return {"input_specs": _specs(obj["input_specs"]), "classes": classes,
          "run": getattr(type(obj["run"]), "_cls", type(obj["run"]).__name__)}


def digest(abi: dict) -> str:
  """Stable fingerprint of the tensor interface (what a manifest may pin as `abi_digest`). The pickle's class
  list is checked separately against the stock allow-list and is not part of the interface."""
  iface = {k: v for k, v in abi.items() if k != "classes"}
  return hashlib.sha256(json.dumps(iface, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_file(path, chunk: int = 1 << 20) -> tuple[str, int]:
  h, n = hashlib.sha256(), 0
  with open(path, "rb") as f:
    while True:
      b = f.read(chunk)
      if not b:
        return h.hexdigest(), n
      h.update(b)
      n += len(b)
