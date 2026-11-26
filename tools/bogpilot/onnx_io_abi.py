#!/usr/bin/env python3
"""Read the tensor interface of a driving ONNX without onnx, tinygrad or numpy, and without loading any weights.

Prints (or returns) a dict in the same layout as common/bogpilot_models/abi.read_driving_abi, so the 0.11.2 contract
check (compat.check_driving_abi) can screen a candidate ONNX before anyone compiles it:
  input_specs / output_specs  {name: [shape, dtype, device]}   (device is the target, default QCOM)
  input_shapes / output_shapes {name: shape}                     (what compile_onnx.py stores as metadata)
  output_slices                {name: [start, stop]}             (from the ONNX `output_slices` metadata)
`classes` and `run` are filled with the stock values: they describe the compiled pickle, not the ONNX, and the
compiled file is checked again by registry.validate_entry after the bench compile.

Usage: onnx_io_abi.py <model.onnx> [--device QCOM] [--check]
"""
from __future__ import annotations

import base64
import io
import json
import pickle
import sys

# onnx TensorProto.DataType -> numpy dtype name (what compile_onnx.py writes into the specs)
_DTYPES = {1: "float32", 2: "uint8", 3: "int8", 6: "int32", 7: "int64", 9: "bool", 10: "float16", 11: "float64"}


class _Reader:
  def __init__(self, f, end):
    self.f, self.end = f, end

  def varint(self):
    shift = result = 0
    while True:
      b = self.f.read(1)
      if not b:
        raise ValueError("truncated varint")
      result |= (b[0] & 0x7F) << shift
      if not b[0] & 0x80:
        return result
      shift += 7

  def fields(self, end):
    while self.f.tell() < end:
      tag = self.varint()
      yield tag >> 3, tag & 7

  def skip(self, wt):
    if wt == 0:
      self.varint()
    elif wt == 1:
      self.f.seek(8, io.SEEK_CUR)
    elif wt == 5:
      self.f.seek(4, io.SEEK_CUR)
    elif wt == 2:
      self.f.seek(self.varint(), io.SEEK_CUR)
    else:
      raise ValueError(f"unsupported wire type {wt}")

  def sub_end(self):
    n = self.varint()
    return self.f.tell() + n

  def string(self):
    return self.f.read(self.varint()).decode()


def _value_info(r):
  name, elem, dims = None, None, []
  for fid, wt in r.fields(r.sub_end()):
    if fid == 1:
      name = r.string()
    elif fid == 2:  # TypeProto
      for tf, twt in r.fields(r.sub_end()):
        if tf != 1:
          r.skip(twt)
          continue
        for tt, ttwt in r.fields(r.sub_end()):  # TypeProto.Tensor
          if tt == 1:
            elem = r.varint()
          elif tt == 2:
            for sf, swt in r.fields(r.sub_end()):  # TensorShapeProto
              if sf != 1:
                r.skip(swt)
                continue
              dim = None
              for df, dwt in r.fields(r.sub_end()):
                if df == 1:
                  dim = r.varint()
                elif df == 2:
                  dim = r.string()
                else:
                  r.skip(dwt)
              dims.append(dim)
          else:
            r.skip(ttwt)
    else:
      r.skip(wt)
  return name, elem, dims


def _initializer_name(r):
  name = None
  for fid, wt in r.fields(r.sub_end()):
    if fid == 8:
      name = r.string()
    else:
      r.skip(wt)
  return name


def read_onnx_io(path) -> dict:
  with open(path, "rb") as f:
    f.seek(0, io.SEEK_END)
    size = f.tell()
    f.seek(0)
    r = _Reader(f, size)
    inputs, outputs, inits, meta = [], [], set(), {}
    for fid, wt in r.fields(size):
      if fid == 7:  # graph
        for gf, gwt in r.fields(r.sub_end()):
          if gf == 11:
            inputs.append(_value_info(r))
          elif gf == 12:
            outputs.append(_value_info(r))
          elif gf == 5:
            inits.add(_initializer_name(r))
          else:
            r.skip(gwt)
      elif fid == 14:  # metadata_props
        k = v = None
        for mf, mwt in r.fields(r.sub_end()):
          if mf == 1:
            k = r.string()
          elif mf == 2:
            v = r.string()
          else:
            r.skip(mwt)
        meta[k] = v
      else:
        r.skip(wt)
  return {"inputs": [i for i in inputs if i[0] not in inits], "outputs": outputs, "metadata": meta}


class _SliceOnly(pickle.Unpickler):
  def find_class(self, module, name):
    if (module, name) == ("builtins", "slice"):
      return slice
    raise ValueError(f"forbidden global {module}.{name}")


def onnx_driving_abi(path, device: str = "QCOM") -> dict:
  from openpilot.common.bogpilot_models.stock import STOCK_DRIVING_ABI
  io_ = read_onnx_io(path)

  def specs(items):
    out = {}
    for name, elem, dims in items:
      if any(not isinstance(d, int) for d in dims):
        raise ValueError(f"{name} has a symbolic shape {dims}")
      out[name] = [list(dims), _DTYPES.get(elem, f"onnx:{elem}"), device]
    return out

  raw = io_["metadata"].get("output_slices")
  slices = {}
  if raw:
    s = _SliceOnly(io.BytesIO(base64.b64decode(raw))).load()
    slices = {k: [v.start, v.stop] for k, v in s.items()}
  ins, outs = specs(io_["inputs"]), specs(io_["outputs"])
  return {
    "input_specs": ins,
    "output_specs": outs,
    "input_shapes": {k: v[0] for k, v in ins.items()},
    "output_shapes": {k: v[0] for k, v in outs.items()},
    "output_slices": slices,
    "classes": list(STOCK_DRIVING_ABI["classes"]),
    "run": STOCK_DRIVING_ABI["run"],
  }


def main(argv):
  path = argv[0]
  device = argv[argv.index("--device") + 1] if "--device" in argv else "QCOM"
  abi = onnx_driving_abi(path, device)
  if "--check" in argv:
    from openpilot.common.bogpilot_models import compat
    problems = compat.check_driving_abi(abi, device=device)
    print(json.dumps({"path": path, "fits_0_11_2": not problems, "problems": problems}, indent=1))
    return 0 if not problems else 1
  print(json.dumps(abi, indent=1, sort_keys=True))
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
