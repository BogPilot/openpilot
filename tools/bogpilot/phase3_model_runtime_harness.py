#!/usr/bin/env python3
"""
from __future__ import annotationsNative load harness for lane2 (Mac/AGNOS VM). Uses REAL artifacts, static reads only (no inference).

usage: phase3_model_runtime_harness.py <scratch_dir> [legacy_artifact ...]
"""
import json, sys, tempfile
from pathlib import Path
from openpilot.common.phase3_model_runtime import Runtime, RuntimeErrorBP, read_abi, compare_abi, sha256_file


def main():
  scratch = Path(sys.argv[1]); scratch.mkdir(parents=True, exist_ok=True)
  rt = Runtime(root=scratch / "rt")
  out = {"stock_path": str(rt.stock_path()), "stock_verification": rt.stock_verification()}
  abi = rt.stock_abi()
  out["stock_abi"] = {k: abi[k] for k in ("input_specs", "output_specs", "output_slices", "run", "digest", "model_checkpoint")}
  out["stock_abi"]["classes"] = len(abi["classes"])
  out["stock_self_compare"] = compare_abi(abi, read_abi(rt.stock_path()))
  legacy = {}
  for p in sys.argv[2:]:
    try:
      ok = compare_abi(abi, read_abi(Path(p)))
      legacy[p] = ["READ", *ok]
    except RuntimeErrorBP as e:
      legacy[p] = ["REJECTED", str(e)]
  out["legacy_artifacts"] = legacy
  staged = Path(tempfile.mkdtemp(dir=scratch))
  (staged / "driving_tinygrad.pkl").symlink_to(rt.stock_path())
  try:
    rt.install("stock-copy", staged, {"assets": [{"name": "driving_tinygrad.pkl", "sha256": sha256_file(rt.stock_path()),
                                                   "size": rt.stock_path().stat().st_size}]})
    out["stock_as_alternate"] = "ACCEPTED (BUG)"
  except RuntimeErrorBP as e:
    out["stock_as_alternate"] = f"REJECTED: {e}"
  st = rt.status()
  out["status"] = {"selected": st.selected_id, "pending": st.pending_id, "active": st.active_id,
                   "installed": [i.id for i in st.installed], "limitation": st.limitation}
  out["resolve_nonchestnut"] = str(rt.resolve_for_modeld(False).path)
  print(json.dumps(out, indent=1, default=str))
  ok = out["stock_verification"][0] and out["stock_self_compare"][0] and out["stock_as_alternate"].startswith("REJECTED") \
       and all(v[0] == "REJECTED" or v[1] is False for v in legacy.values()) and not st.installed
  print("HARNESS", "PASS" if ok else "FAIL")
  return 0 if ok else 1


if __name__ == "__main__":
  sys.exit(main())
