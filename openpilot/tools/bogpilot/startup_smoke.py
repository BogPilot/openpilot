#!/usr/bin/env python3
"""Sandbox-only startup/import smoke, never a hardware/boot certification.

Default: real Python imports with explicit hardware/IPC/Params mocks in tests.
--native-imports: matching AGNOS 19.9 VM ONLY; real native Params/schema imports,
no manager.main/thread/daemon start. Must run under the shared VM build lock.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def verify_manifest(path: Path) -> int:
  """Check recorded sources AND outputs; hashes must be produced after real build.

  JSON {"agnos":"19.9", "files":[{"path":"repo/relative", "sha256":"...",
        "kind":"source"|"output"}]}. Does not replace build/link/runtime tests.
  A manifest with only outputs is insufficient source/output consistency evidence.
  """
  manifest = json.loads(path.read_text())
  assert manifest["agnos"] == "19.9", "wrong manifest AGNOS"
  entries = manifest["files"]
  assert {row["kind"] for row in entries} == {"source", "output"}, "need sources and outputs"
  for row in entries:
    file = (REPO / row["path"]).resolve()
    assert file.is_relative_to(REPO), "manifest path escapes repository"
    assert hashlib.sha256(file.read_bytes()).hexdigest() == row["sha256"], row["path"]
  return len(entries)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--sandbox-root", required=True, type=Path)
  parser.add_argument("--native-imports", action="store_true")
  parser.add_argument("--native-manifest", type=Path)
  args = parser.parse_args()
  sandbox = args.sandbox_root.expanduser().resolve()
  assert sandbox not in (Path("/"), Path("/data"), Path("/cache")), "must use a dedicated sandbox subdirectory"
  sandbox.mkdir(parents=True, exist_ok=True)
  run = Path(tempfile.mkdtemp(prefix="startup-smoke-", dir=sandbox))
  data, cache = run / "data", run / "cache"
  data.mkdir()
  cache.mkdir()
  env = dict(os.environ, PYTHONPATH=str(REPO), BOGPILOT_PARAMS_DIR=str(data / "params_bogpilot"),
             BOGPILOT_SMOKE_DATA=str(data), BOGPILOT_SMOKE_CACHE=str(cache),
             BOGPILOT_BACKUP_DIR=str(cache / "settings"),
             NOBOARD="1", BLOCK="all")
  report = {"mode": "synthetic hardware/IPC/native-Params mocks; actual Python manager/config imports",
            "sandbox": str(run), "hardware_daemons_started": False}
  tests = ["openpilot/system/manager/test/test_bogpilot_startup.py",
           "openpilot/common/tests/test_bogpilot_shipping_defaults.py",
           "openpilot/common/tests/test_bogpilot_store.py"]
  result = subprocess.run([sys.executable, "-m", "pytest", "-q", *tests,
                           "--basetemp", str(run / "pytest")], cwd=REPO, env=env)
  report["synthetic_exit"] = result.returncode
  if args.native_imports or args.native_manifest:
    assert platform.system() == "Linux" and Path("/VERSION").read_text().strip() == "19.9", "native checks require matching AGNOS 19.9 VM"
  if args.native_manifest:
    report["manifest_files_verified"] = verify_manifest(args.native_manifest)
  if args.native_imports:
    # Deliberately do NOT call manager_init: registration/bootlog are not sandbox safe.
    code = """
import os
from pathlib import Path
from openpilot.common.params import Params
from openpilot.system.manager import manager, process_config
from openpilot.system.manager.bogpilot_startup import before_defaults, after_defaults
from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
p = Params(os.environ['BOGPILOT_SMOKE_DATA'] + '/params')
assert not (set(p.all_keys()) & FILE_ONLY_UI_KEYS)
p.put('CarModel', 'TESLA_AP1_MODELS', block=True)
# No reset request. Native Params, actual peer modules if assembled, no hardware starts.
a = before_defaults(p)
b = after_defaults(p)
assert not a.errors and not b.errors, (a, b)
assert 'plannerd' in process_config.managed_processes
assert all(proc.proc is None for proc in manager.managed_processes.values())
print('REAL native Params/schema/config/lifecycle imports; no manager boot/daemon execution')
"""
    native = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env)
    report["native_exit"] = native.returncode
    result = native if native.returncode else result
  # Optional w7 stdlib regression suite; absence is an explicit dependency, not pass.
  firmware = REPO / "panda/tests/test_build_identity.py"
  if firmware.exists():
    fw = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "panda/tests", "-p", "test_build_identity.py"], cwd=REPO, env=env)
    report["firmware_identity_exit"] = fw.returncode
    result = fw if fw.returncode else result
  else:
    report["firmware_identity"] = "w7 dependency absent; unvalidated"
  (run / "report.json").write_text(json.dumps(report, indent=2) + "\n")
  print(json.dumps(report, indent=2))
  return result.returncode


if __name__ == "__main__":
  raise SystemExit(main())
