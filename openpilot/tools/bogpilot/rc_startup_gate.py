#!/usr/bin/env python3
"""Fail-closed release acceptance for REAL native Params/settings lifecycle.

Run only in matching AGNOS 19.9 build VM, externally serialized by its build lock.
No manager main/init/thread, network, daemon or live data/cache access. All fixtures
are synthetic and every mutation lives under a new explicit sandbox directory.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback

REPO = Path(__file__).resolve().parents[3]
SOURCE_PATHS = (
  "openpilot/tools/bogpilot/rc_startup_gate.py",
  "openpilot/system/manager/bogpilot_startup.py",
  "openpilot/system/manager/manager.py",
  "openpilot/system/bogpilot/settings_backup.py",
  "openpilot/system/bogpilot/toggle_reset.py",
  "openpilot/common/params.py",
  "openpilot/common/params_keys_bogpilot.h",
  "openpilot/common/bogpilot_params.py",
  "openpilot/common/bogpilot_toggles.py",
  "openpilot/common/bogpilot_shipping_defaults.py",
  "openpilot/common/bogpilot_ap1_profile.py",
  "openpilot/common/bogpilot_store.py",
  "openpilot/common/bogpilot_alert_volumes.py",
)
FORBIDDEN = ("/data", "/cache", "/persist", "/dev", "/sys", "/proc", "/system")


def safe_root(value):
  root = Path(value).expanduser().resolve()
  if root == Path("/") or any(root == Path(p) or Path(p) in root.parents for p in FORBIDDEN):
    raise ValueError("live/system sandbox roots forbidden")
  if root == REPO or REPO in root.parents:
    raise ValueError("sandbox must be outside source tree")
  return root


def source_identity(expected_commit, manifest=None):
  """Verify HEAD, or an operator-exported scoped source manifest on archive VM.

  This identifies tested lifecycle source only, not full build/output provenance.
  """
  if len(expected_commit) != 40 or any(c not in "0123456789abcdef" for c in expected_commit):
    raise ValueError("full lowercase candidate SHA required")
  if manifest is None:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if actual != expected_commit:
      raise RuntimeError("candidate commit does not match explicit final source")
    if subprocess.run(["git", "ls-files", "--error-unmatch", *SOURCE_PATHS], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
      raise RuntimeError("lifecycle source must be committed before identity export")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *SOURCE_PATHS], cwd=REPO).returncode != 0:
      raise RuntimeError("lifecycle source differs from candidate HEAD")
    return {"version": 1, "commit": actual, "files": {
      path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}}
  doc = json.loads(Path(manifest).read_text())
  if doc.get("version") != 1 or doc.get("commit") != expected_commit or set(doc.get("files", {})) != set(SOURCE_PATHS):
    raise RuntimeError("missing or mismatched lifecycle source manifest")
  for path, digest in doc["files"].items():
    if hashlib.sha256((REPO / path).read_bytes()).hexdigest() != digest:
      raise RuntimeError("lifecycle source digest mismatch")
  return doc


def require_native_runtime():
  if platform.system() != "Linux" or not Path("/VERSION").is_file() or Path("/VERSION").read_text().strip() != "19.9":
    raise RuntimeError("requires matching AGNOS 19.9 build VM; no mocked acceptance")


def scope_coverage():
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  from openpilot.system.bogpilot import settings_backup as backup, toggle_reset as reset
  covered = set(backup.FILE_KEYS) | {k for k in backup.SETTING_KEYS if BOGPILOT_PARAMS.get(k, (None,))[0] == "PERSISTENT"}
  missing = set(reset.reset_defaults()) - covered
  if missing:
    raise AssertionError("reset scope not durably covered: " + ",".join(sorted(missing)))
  return len(reset.reset_defaults())


@contextmanager
def sandbox_environment(files, cache):
  env = {"BOGPILOT_PARAMS_DIR": str(files), "BOGPILOT_BACKUP_DIR": str(cache)}
  previous = {k: os.environ.get(k) for k in env}
  os.environ.update(env)
  try:
    yield
  finally:
    for k, v in previous.items():
      if v is None:
        os.environ.pop(k, None)
      else:
        os.environ[k] = v


def known_keys(params):
  return {k.decode() if isinstance(k, bytes) else k for k in params.all_keys()}


def raw_values(params):
  # Only an explicitly constructed sandbox Params instance may be supplied.
  return {k: p.read_bytes() for k in known_keys(params) if (p := Path(params.get_param_path(k))).is_file()}


def seed(params, key, raw):
  params.check_key(key)
  value = params.cpp2python(key, raw)
  if value is None:
    raise AssertionError("fixture incompatible with native registry: " + key)
  params.put(key, value, block=True)


class FaultBoundary:
  """Delegate to REAL native Params; fail one selected mutation before it occurs.

  Also tripwire file-only access. This is fault injection, not emulated storage.
  """
  def __init__(self, params, *, fail_key=None, fail_remove=False):
    self.params = params
    self.fail_key = fail_key
    self.fail_remove = fail_remove
    self.fired = False

  def __getattr__(self, name):
    target = getattr(self.params, name)
    if not callable(target) or name in ("all_keys", "clear_all"):
      return target
    def call(*args, **kwargs):
      from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
      key = args[0] if args else None
      key = key.decode() if isinstance(key, bytes) else key
      if key in FILE_ONLY_UI_KEYS:
        raise AssertionError("file-only key reached native boundary: " + key)
      if key == self.fail_key and not self.fired and name == ("remove" if self.fail_remove else "put"):
        self.fired = True
        raise OSError("synthetic one-shot write failure")
      return target(*args, **kwargs)
    return call


def native_defaults(params):
  """Actual manager default initializer, not manager_init's unsafe boot IO."""
  for key in params.all_keys():
    default = params.get_default_value(key)
    if default is not None and params.get(key) is None:
      params.put(key, default, block=True)


def boot_settings(params, files, cache):
  from openpilot.common.params import ParamKeyFlag
  from openpilot.system.manager.bogpilot_startup import before_defaults, after_defaults
  for flag in (ParamKeyFlag.CLEAR_ON_MANAGER_START, ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION,
               ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION, ParamKeyFlag.CLEAR_ON_IGNITION_ON):
    params.clear_all(flag)
  before = before_defaults(params, file_root=files, cache_root=cache)
  native_defaults(params)
  after = after_defaults(params, file_root=files, startup=before)
  if before.errors or after.errors:
    raise AssertionError("startup stage errors: " + repr((before.errors, after.errors)))
  return before, after


def run_native_cases(root):
  # These imports are mandatory. No fallback fake, skip, or mock can yield PASS.
  from openpilot.common.params import Params
  from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS, FILE_TOGGLES
  from openpilot.system.bogpilot import settings_backup as backup, toggle_reset as reset
  from openpilot.system.manager import bogpilot_startup as startup
  results = []

  def case(name, check):
    directory = root / name
    directory.mkdir()
    files, cache = directory / "files", directory / "cache"
    files.mkdir()
    params = Params(str(directory / "params"))
    assert Path(params.get_param_path()).resolve().is_relative_to(directory.resolve())
    assert not (known_keys(params) & FILE_ONLY_UI_KEYS), "stale native file-only registry"
    with sandbox_environment(files, cache):
      try:
        check(params, files, cache)
        results.append({"name": name, "status": "PASS"})
      except Exception as exc:
        # Never record parameter values, routes, identities or native exception text.
        results.append({"name": name, "status": "FAIL", "error_type": type(exc).__name__,
                        "frames": [{"function": frame.name, "line": frame.lineno} for frame in traceback.extract_tb(exc.__traceback__)]})
    return params

  def preserve(p, f, c):
    fixtures = {"CarModel": b"TESLA_AP1_MODELS", "ScreenTimeout": b"47",
                "CalibrationParams": b"synthetic-calibration-only", "DongleId": b"synthetic-identity-only",
                "GithubSshKeys": b"synthetic-not-a-key", "CalibratedLateralAcceleration": b"1.31"}
    for k, v in fixtures.items():
      seed(p, k, v)
    initial = {k: raw_values(p)[k] for k in fixtures}
    (f / "ShowUploadRate").write_bytes(b"synthetic-owner-choice")
    boot_settings(p, f, c)
    seed(p, "ScreenTimeout", b"53")  # deliberate edit after first profile/defaults
    initial["ScreenTimeout"] = raw_values(p)["ScreenTimeout"]
    reopened = Params(p.d)
    boot_settings(reopened, f, c)
    assert {k: raw_values(reopened)[k] for k in fixtures} == initial
    assert (f / "ShowUploadRate").read_bytes() == b"synthetic-owner-choice"
    assert not (f / "AP1StockReset1").exists()
    assert not reopened.get_bool(reset.REQUEST_KEY)

  def successful_reset(p, f, c):
    seed(p, "CarModel", b"TESLA_AP1_MODELS")
    seed(p, "AlwaysOnLateral", b"1")
    seed(p, "CalibrationParams", b"synthetic-calibration-only")
    seed(p, "DongleId", b"synthetic-identity-only")
    protected = {k: raw_values(p)[k] for k in ("CalibrationParams", "DongleId", "CarModel")}
    inactive = f / "AlwaysOnLateral"
    inactive.write_bytes(b"synthetic-inactive-original")
    (f / "OffroadScreensaver").write_text("1")
    seed(p, reset.REQUEST_KEY, b"1")
    pre, post = boot_settings(FaultBoundary(p), f, c)
    assert "reset:completed" in pre.events
    assert "ap1:suppressed-stock-reset" in post.events
    assert (f / "AP1StockReset1").read_text().strip() == "1"
    assert not p.get_bool(reset.REQUEST_KEY) and not p.get_bool("AlwaysOnLateral")
    assert inactive.read_bytes() == b"synthetic-inactive-original"
    assert (f / "OffroadScreensaver").read_text().strip() == "0"
    assert FILE_TOGGLES["OffroadScreensaver"][0] is False
    assert {k: raw_values(p)[k] for k in protected} == protected
    originals = {path: path.read_bytes() for path in c.glob("*.json") if path.name != "latest.json"}
    assert originals
    assert any(base64.b64decode(backup.read_snapshot(path)["entries"]["AlwaysOnLateral"]["value"]) == b"1" for path in originals)
    owned = {k: v for k, v in raw_values(p).items() if k in reset.reset_defaults()}
    # Fresh interpreter proves marker-based anti-replay without inherited Python
    # singleton/profile caches. This is NOT a hardware power-cycle certification.
    child_code = """
import sys
from pathlib import Path
from openpilot.common.params import Params
from openpilot.tools.bogpilot.rc_startup_gate import boot_settings, sandbox_environment
with sandbox_environment(Path(sys.argv[2]), Path(sys.argv[3])):
  p = Params(sys.argv[1])
  before, after = boot_settings(p, Path(sys.argv[2]), Path(sys.argv[3]))
  assert 'reset:not_requested' in before.events
  assert 'ap1:suppressed-stock-reset' in after.events
"""
    child = subprocess.run([sys.executable, "-c", child_code, p.d, str(f), str(c)],
                           env=dict(os.environ, PYTHONPATH=str(REPO)), capture_output=True)
    assert child.returncode == 0, "fresh-interpreter startup failed"
    assert {k: v for k, v in raw_values(p).items() if k in reset.reset_defaults()} == owned
    assert not (f / "AP1DefaultsApplied").exists()
    assert all(path.read_bytes() == content for path, content in originals.items())

  def failed_backup(p, f, c):
    seed(p, reset.REQUEST_KEY, b"1")
    seed(p, "ScreenTimeout", b"47")
    initial = raw_values(p)
    c.write_bytes(b"synthetic-unavailable-storage")
    outcome = startup.before_defaults(p, file_root=f, cache_root=c)
    assert "reset:failed" in outcome.events and outcome.errors
    assert raw_values(p) == initial and not (f / "AP1StockReset1").exists()
    assert c.read_bytes() == b"synthetic-unavailable-storage"

  def corrupt_backup(p, f, c):
    seed(p, reset.REQUEST_KEY, b"1")
    seed(p, "AlwaysOnLateral", b"1")
    receipt = backup.backup_settings(p, file_root=f, backup_root=c)
    assert receipt.success
    receipt.path.write_bytes(b"synthetic-corrupt-archive")
    initial = raw_values(p)
    outcome = startup.before_defaults(p, file_root=f, cache_root=c)
    assert "reset:failed" in outcome.events and outcome.errors
    assert raw_values(p) == initial and p.get_bool(reset.REQUEST_KEY)
    assert receipt.path.read_bytes() == b"synthetic-corrupt-archive"
    assert not (f / "AP1StockReset1").exists()

  def missing_dependency(p, f, c):
    # Exercise actual reset API with no backup authority, not a fake module import.
    seed(p, reset.REQUEST_KEY, b"1")
    initial = raw_values(p)
    assert reset.reset_requested(p, f, backup=None).status == "failed"
    assert raw_values(p) == initial
    try:
      backup.read_snapshot(c / "missing.json")
    except FileNotFoundError:
      pass
    else:
      raise AssertionError("missing snapshot accepted")

  def rollback(p, f, c, clear=False):
    seed(p, reset.REQUEST_KEY, b"1")
    seed(p, "AlwaysOnLateral", b"1")
    seed(p, "ScreenTimeout", b"47")
    (f / "DeveloperHUD").write_bytes(b"1")
    (f / "AlwaysOnLateral").write_bytes(b"synthetic-inactive-original")
    initial = raw_values(p)
    original_files = {path.name: path.read_bytes() for path in f.iterdir()}
    boundary = FaultBoundary(p, fail_key=reset.REQUEST_KEY if clear else "ScreenTimeout", fail_remove=clear)
    outcome = startup.before_defaults(boundary, file_root=f, cache_root=c)
    assert boundary.fired and "reset:failed" in outcome.events
    assert raw_values(p) == initial and p.get_bool(reset.REQUEST_KEY)
    assert all((f / key).read_bytes() == value for key, value in original_files.items())
    assert (f / "AP1StockReset1").exists()  # durable intent survives rollback/reboot
    docs = [backup.read_snapshot(path) for path in c.glob("*.json")]
    assert any(base64.b64decode(doc["entries"]["ScreenTimeout"]["value"]) == b"47" for doc in docs)

  def inactive_file_only(p, f, c):
    for key in FILE_ONLY_UI_KEYS:
      (f / key).write_text("1")
    (f / "AlwaysOnLateral").write_bytes(b"synthetic-inactive-original")
    seed(p, "AlwaysOnLateral", b"1")
    seed(p, reset.REQUEST_KEY, b"1")
    boundary = FaultBoundary(p)
    receipt = backup.backup_settings(boundary, file_root=f, backup_root=c)
    assert receipt.success
    doc = backup.read_snapshot(receipt.path)
    assert all(doc["entries"][key]["store"] == "file" for key in FILE_ONLY_UI_KEYS)
    assert reset.reset_requested(boundary, f, backup=lambda: receipt).status == "completed"
    assert (f / "AlwaysOnLateral").read_bytes() == b"synthetic-inactive-original"

  case("ordinary-boot-preservation", preserve)
  case("stock-reset-reboot-antireplay", successful_reset)
  case("unavailable-backup-retains-request", failed_backup)
  case("corrupt-backup-retains-request", corrupt_backup)
  case("missing-backup-retains-request", missing_dependency)
  case("native-write-failure-rollback", rollback)
  case("request-clear-failure-rollback", lambda p, f, c: rollback(p, f, c, clear=True))
  case("inactive-and-file-only-ownership", inactive_file_only)
  return results


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--sandbox-root", type=safe_root, required=True)
  parser.add_argument("--expected-commit", required=True, help="exact FINAL candidate full SHA; no stale-base acceptance")
  parser.add_argument("--source-manifest", type=Path, help="operator-exported scoped source identity for git-free VM archives")
  parser.add_argument("--write-source-manifest", type=Path, help="export clean HEAD scoped lifecycle identity on source host; NOT acceptance")
  args = parser.parse_args(argv)
  if args.write_source_manifest:
    doc = source_identity(args.expected_commit)
    safe_root(args.write_source_manifest.resolve().parent)
    with args.write_source_manifest.open("x") as output:
      output.write(json.dumps(doc, indent=2) + "\n")
    print("Scoped lifecycle identity exported; no native acceptance run")
    return 0
  args.sandbox_root.mkdir(parents=True, exist_ok=True)
  run = Path(tempfile.mkdtemp(prefix="rc-startup-", dir=args.sandbox_root))
  report = {"gate": "C3X real-native startup acceptance", "status": "FAIL", "skipped": 0,
            "fixtures": "synthetic only", "hardware_started": False, "cases": []}
  try:
    source = source_identity(args.expected_commit, args.source_manifest)
    report["candidate_commit"] = source["commit"]
    report["lifecycle_source_files"] = len(source["files"])
    require_native_runtime()
    report["reset_scope_keys"] = scope_coverage()
    report["cases"] = run_native_cases(run)
    if len(report["cases"]) != 8 or any(c["status"] != "PASS" for c in report["cases"]):
      raise AssertionError("native acceptance cases failed")
    report["status"] = "PASS"
  except Exception as exc:
    report["blocker_type"] = type(exc).__name__
    # Full trace deliberately limited to symbol/line metadata, never private values.
    report["blocker_frames"] = [{"function": f.name, "line": f.lineno} for f in traceback.extract_tb(exc.__traceback__)]
  path = run / "report.json"
  path.write_text(json.dumps(report, indent=2) + "\n")
  print(json.dumps(report, indent=2))
  print("Report:", path)
  return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
