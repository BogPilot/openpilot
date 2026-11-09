"""Helpers that build tiny, fake 0.11.2-shaped model directories for the BogPilot model selector tests.

Models are synthetic pickles that only DESCRIBE the stock interface (they reference tinygrad class names but are
never imported or run), so tests are fast and no third-party weights are involved.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import json
import pickle
import struct
import sys
import types
from pathlib import Path

from openpilot.common.bogpilot_models.stock import STOCK_DRIVING_ABI, STOCK_WARP_ABI


@contextlib.contextmanager
def _fake_globals(names):
  """Temporarily provide importable fake classes so pickle can dump them under their tinygrad names."""
  made, saved = [], {}
  try:
    for full in names:
      mod, _, cls = full.rpartition(".")
      parts = mod.split(".")
      for i in range(1, len(parts) + 1):
        prefix = ".".join(parts[:i])
        if prefix not in sys.modules:
          sys.modules[prefix] = types.ModuleType(prefix)
          made.append(prefix)
      m = sys.modules[mod]
      if hasattr(m, cls):
        saved[(mod, cls)] = getattr(m, cls)
      k = type(cls, (), {})
      k.__module__, k.__qualname__ = mod, cls
      setattr(m, cls, k)
    yield
  finally:
    for (mod, cls), v in saved.items():
      setattr(sys.modules[mod], cls, v)
    for mod in made:
      sys.modules.pop(mod, None)


def _inst(full):
  mod, _, cls = full.rpartition(".")
  return getattr(sys.modules[mod], cls)()


def _specs(d):
  return {k: (tuple(s), dt, dev) for k, (s, dt, dev) in d.items()}


def driving_pickle_bytes(abi: dict | None = None, extra_class: str | None = None) -> bytes:
  abi = copy.deepcopy(STOCK_DRIVING_ABI if abi is None else abi)
  classes = list(abi["classes"]) + ([extra_class] if extra_class else [])
  slices = {k: slice(a, b) for k, (a, b) in abi["output_slices"].items()}
  with _fake_globals(classes):
    run = _inst(abi["run"])
    obj = {"metadata": {"metadata": {"output_slices": base64.b64encode(pickle.dumps(slices, protocol=4)).decode(),
                                     "model_checkpoint": "synthetic-test-model"},
                        "input_shapes": {k: tuple(v) for k, v in abi["input_shapes"].items()},
                        "output_shapes": {k: tuple(v) for k, v in abi["output_shapes"].items()}},
           "run": run, "input_specs": _specs(abi["input_specs"]), "output_specs": _specs(abi["output_specs"])}
    if extra_class:
      obj["metadata"]["extra"] = _inst(extra_class)
    ops = pickle.dumps(obj, protocol=4)
  return struct.pack("<q", len(ops)) + ops + b"\0" * 64  # trailing out-of-band buffer bytes


def warp_pickle_bytes(role: str, abi: dict | None = None) -> bytes:
  abi = copy.deepcopy(STOCK_WARP_ABI[role] if abi is None else abi)
  with _fake_globals(abi["classes"]):
    return pickle.dumps({"metadata": {}, "run": _inst(abi["run"]), "input_specs": _specs(abi["input_specs"])}, protocol=4)


def stock_abi_variant(**edits) -> dict:
  """Copy of the stock driving ABI with edits applied via dotted keys, e.g. {'input_specs.new_img': [[2,6,64,64],'uint8','QCOM']}.
  A value of None deletes the key."""
  abi = copy.deepcopy(STOCK_DRIVING_ABI)
  for dotted, value in edits.items():
    parts = dotted.split(".")
    d = abi
    for p in parts[:-1]:
      d = d[p]
    if value is None:
      d.pop(parts[-1])
    else:
      d[parts[-1]] = value
  return abi


def sha(b: bytes) -> str:
  return hashlib.sha256(b).hexdigest()


def install_model(root: Path, model_id: str = "test-model", name: str = "Test Model", version: str = "1.0", *,
                  driving: bytes | None = None, warps: dict | None = None, license="MIT", openpilot: str = "0.11.2",
                  declared_driving: bytes | None = None, extra_manifest: dict | None = None) -> Path:
  """Create <root>/<id>/ with a manifest that declares `declared_driving` (default: the bytes written)."""
  d = Path(root) / model_id
  d.mkdir(parents=True)
  driving = driving_pickle_bytes() if driving is None else driving
  declared = driving if declared_driving is None else declared_driving
  (d / "driving.pkl").write_bytes(driving)
  files = [{"role": "driving_model", "name": "driving.pkl", "sha256": sha(declared), "size": len(declared)}]
  for role, data in (warps or {}).items():
    (d / f"{role}.pkl").write_bytes(data)
    files.append({"role": role, "name": f"{role}.pkl", "sha256": sha(data), "size": len(data)})
  manifest = {"schema": 1, "id": model_id, "name": name, "version": version, "openpilot": openpilot, "license": license, "files": files}
  manifest.update(extra_manifest or {})
  (d / "manifest.json").write_text(json.dumps(manifest))
  return d


def rewrite_manifest(d: Path, **edits) -> None:
  p = Path(d) / "manifest.json"
  m = json.loads(p.read_text())
  m.update(edits)
  p.write_text(json.dumps(m))


class MemStore:
  """In-memory stand-in for the BogPilot ParamStore (raw/put/remove)."""

  def __init__(self, **kv):
    self.kv = dict(kv)
    self.writes = []

  def raw(self, key):
    return self.kv.get(key)

  def put(self, key, value, **_):
    self.kv[key] = value if isinstance(value, str) else str(value)
    self.writes.append(("put", key))

  def remove(self, key):
    self.kv.pop(key, None)
    self.writes.append(("remove", key))
