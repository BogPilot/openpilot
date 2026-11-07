#!/usr/bin/env python3
"""CSC acceptance gate: synthetic native tests, NEVER hardware certification.

Run on matching AGNOS19.9 under the shared build lock. No daemons are started.
--plan is read-only planning and returns pending (2), never acceptance success.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[3]
SUITES = (
  "openpilot/selfdrive/controls/tests/test_ap1_curve_brake.py",
  "openpilot/selfdrive/controls/tests/test_bogpilot_csc.py",
  "openpilot/selfdrive/controls/tests/test_ap1_curve_speed_planner.py",
  "openpilot/tools/bogpilot/tests/test_rc_controls_transitions.py",
)
IMPORT_CHECK = """
from openpilot.selfdrive.controls import plannerd
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
from openpilot.cereal.services import SERVICE_LIST
from openpilot.common.realtime import DT_MDL
assert SERVICE_LIST['frogpilotPlan'].frequency == 20
assert SERVICE_LIST['modelV2'].frequency == 20
assert DT_MDL == 0.05
assert callable(plannerd.main)
assert callable(LongitudinalPlanner.publish_frogpilot_plan)
print('actual native publisher imports and declared 20Hz cadence; no daemon executed')
"""


def junit_counts(path):
  root = ET.parse(path).getroot()
  cases = list(root.iter("testcase"))
  # Collection errors can live directly under a testsuite, without testcases.
  return {"tests": len(cases), "failures": len(list(root.iter("failure"))),
          "errors": len(list(root.iter("error"))), "skipped": len(list(root.iter("skipped")))}


def acceptance(import_exit, pytest_exit, counts):
  return (import_exit == 0 and pytest_exit == 0 and counts["tests"] > 0
          and all(counts[k] == 0 for k in ("failures", "errors", "skipped")))


def is_agnos19():
  try:
    return platform.system() == "Linux" and Path("/VERSION").read_text().strip() == "19.9"
  except OSError:
    return False


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--sandbox-root", required=True, type=Path)
  parser.add_argument("--plan", action="store_true")
  parser.add_argument("--lock-owner", help="attest externally held AGNOS VM build lock owner")
  args = parser.parse_args(argv)
  sandbox = args.sandbox_root.expanduser().resolve()
  if sandbox == Path("/") or any(sandbox.is_relative_to(p) for p in (Path("/data"), Path("/cache"))):
    parser.error("sandbox must be outside live /data and /cache")
  suites = [str(REPO / s) for s in SUITES]
  report = {"status": "pending", "kind": "synthetic native controls acceptance; not hardware/replay",
            "suites": list(SUITES), "hardware_validated": False,
            "coverage_limits": ["synthetic point-mass simulations are not vehicle validation",
              "prior adapted 0.9.7 replay did not exercise meaningful curve braking or learning",
              "20Hz declaration/import checked, not runtime scheduling measurement"]}
  if args.plan:
    print(json.dumps(report, indent=2))
    return 2
  if not is_agnos19() or not args.lock_owner:
    report["blocker"] = "matching AGNOS19.9 and externally held build lock required"
    print(json.dumps(report, indent=2))
    return 2
  lock = Path.home() / ".bogpilot_locks/agnos_vm_build.lock"
  # Lock acquisition/liveness are orchestration's responsibility; never steal/release.
  if not lock.exists():
    report["blocker"] = "shared VM build lock absent; no execution"
    print(json.dumps(report, indent=2))
    return 2
  if not all(Path(s).is_file() for s in suites):
    report["blocker"] = "required suite absent"
    print(json.dumps(report, indent=2))
    return 2
  sandbox.mkdir(parents=True, exist_ok=True)
  run = Path(tempfile.mkdtemp(prefix="controls-gate-", dir=sandbox))
  env = dict(os.environ, PYTHONPATH=str(REPO), BOGPILOT_PARAMS_DIR=str(run / "file-settings"),
             PARAMS_ROOT=str(run / "params"), NOBOARD="1", BLOCK="all")
  imports = subprocess.run([sys.executable, "-c", IMPORT_CHECK], cwd=REPO, env=env,
                           capture_output=True, text=True, timeout=600)
  (run / "imports.log").write_text(imports.stdout + imports.stderr)
  report["import_exit"] = imports.returncode
  if imports.returncode:
    report["status"] = "failed"
    report["blocker"] = "actual native publisher import/rate check failed; tests unrun"
    exit_code = 1
  else:
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *suites,
                             "--basetemp", str(run / "pytest"), "--junitxml", str(run / "junit.xml")],
                            cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
    (run / "pytest.log").write_text(result.stdout + result.stderr)
    try:
      counts = junit_counts(run / "junit.xml")
    except (OSError, ET.ParseError):
      counts = {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}
    report.update(counts=counts, pytest_exit=result.returncode)
    report["status"] = "passed" if acceptance(imports.returncode, result.returncode, counts) else "failed"
    exit_code = int(report["status"] != "passed")
  (run / "report.json").write_text(json.dumps(report, indent=2) + "\n")
  print(json.dumps(report, indent=2))
  print("Evidence directory:", run)
  return exit_code


if __name__ == "__main__":
  raise SystemExit(main())
