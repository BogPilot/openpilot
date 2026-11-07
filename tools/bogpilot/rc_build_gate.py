#!/usr/bin/env python3
"""Read-only C3X candidate acceptance. Never launches services, builds, or takes locks.

All native evidence is supplied by the coordinated AGNOS VM run. A green report
means build/import evidence is complete, NOT booted, flashed, or road validated.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess

RELEASE_BASE = "f7db927c728bab57bb1263e05465766a8f28fc9d"
VENDORS = ("msgq_repo", "opendbc_repo", "rednose_repo", "teleoprtc_repo", "tinygrad_repo")
GATES = ("startup", "firmware", "package", "controls", "settings", "ui", "recorder", "provenance", "build", "imports")
MODELS = ("driving_tinygrad.pkl", "dmonitoring_model_tinygrad.pkl", "driving_warp_1344x760_tinygrad.pkl",
          "driving_warp_1928x1208_tinygrad.pkl", "dm_warp_1344x760_tinygrad.pkl", "dm_warp_1928x1208_tinygrad.pkl")
LAUNCHERS = ("launch_openpilot.sh", "launch_chffrplus.sh", "launch_env.sh",
             "openpilot/system/manager/manager.py", "openpilot/system/manager/build.py")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def git(root: Path, *args: str) -> str:
  return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE, text=True).strip()


def digest(path: Path) -> str:
  h = hashlib.sha256()
  with path.open("rb") as f:
    for block in iter(lambda: f.read(1024 * 1024), b""):
      h.update(block)
  return h.hexdigest()


def safe_path(root: Path, value: str) -> Path:
  """Manifest references cannot escape their explicit evidence/artifact root."""
  if not isinstance(value, str) or not value or "\\" in value:
    raise ValueError("invalid relative manifest path")
  p = PurePosixPath(value)
  if p.is_absolute() or ".." in p.parts or p == PurePosixPath("."):
    raise ValueError("unsafe manifest path")
  result = root / value
  if not result.resolve().is_relative_to(root.resolve()):
    raise ValueError("manifest symlink escapes root")
  return result


def service_inventory(root: Path) -> tuple[list[str], list[str]]:
  """Read service declarations as AST, NEVER import process_config or call main."""
  tree = ast.parse((root / "openpilot/system/manager/process_config.py").read_text())
  modules, executables = set(), set()
  for node in ast.walk(tree):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or len(node.args) < 2:
      continue
    if node.func.id in ("PythonProcess", "DaemonProcess"):
      modules.add(ast.literal_eval(node.args[1]))
    elif node.func.id == "NativeProcess":
      directory = ast.literal_eval(node.args[1])
      command = ast.literal_eval(node.args[2])
      executables.add(str(PurePosixPath(directory) / command[0].removeprefix("./")))
  if not modules or not executables:
    raise ValueError("empty or unsupported process inventory")
  return sorted(modules), sorted(executables)


def conditional_webcam_imports(root: Path) -> list[str]:
  """Only the exact stock USE_WEBCAM guard can classify this import optional.

  Unknown/reassigned guards remain required. No process config is executed.
  """
  tree = ast.parse((root / "openpilot/system/manager/process_config.py").read_text())
  writes = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "WEBCAM" and isinstance(n.ctx, ast.Store)]
  expected = ast.parse('os.getenv("USE_WEBCAM") is not None', mode="eval").body
  verified = len(writes) == 1 and any(
    isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
    and n.targets[0].id == "WEBCAM" and ast.dump(n.value) == ast.dump(expected) for n in tree.body)
  if not verified:
    return []
  modules = []
  for n in ast.walk(tree):
    if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "PythonProcess" and len(n.args) >= 2):
      continue
    if ast.literal_eval(n.args[0]) != "webcamerad" or ast.literal_eval(n.args[1]) != "openpilot.system.camerad.webcam.camerad":
      continue
    if any(k.arg == "enabled" and isinstance(k.value, ast.Name) and k.value.id == "WEBCAM" for k in n.keywords):
      modules.append(ast.literal_eval(n.args[1]))
  return sorted(set(modules))


def elf_kind(path: Path, elf_class: int, machine: int) -> bool:
  with path.open("rb") as f:
    h = f.read(64)
  return len(h) >= 64 and h[:6] == b"\x7fELF" + bytes((elf_class, 1)) and struct.unpack_from("<H", h, 18)[0] == machine


def verify_record(root: Path, record: dict) -> Path:
  p = safe_path(root, record["path"])
  expected = record["sha256"]
  if not isinstance(expected, str) or not DIGEST.fullmatch(expected) or digest(p) != expected:
    raise ValueError("missing or mismatched content checksum")
  return p


def verify_bound_log(root: Path, record: dict, candidate: str) -> None:
  p = verify_record(root, record)
  with p.open("rb") as f:
    prefix = f.read(4096)
  headed = prefix.splitlines()[:1] == [("RC_SOURCE_SHA=" + candidate).encode()]
  body_prefix = prefix.partition(b"\n")[2] if headed else prefix
  if headed and not body_prefix.lstrip().startswith(b"{"):
    return  # Plain compiler/pytest log; execution outcome is in the receipt.
  require(p.stat().st_size <= 16 * 1024 * 1024, "JSON receipt too large")
  text = p.read_text()
  data = json.loads(text.partition("\n")[2] if headed else text)
  require(isinstance(data, dict), "JSON evidence must be a report object")
  identities = [data[k] for k in ("candidate_sha", "source_sha", "source_commit") if k in data]
  require((headed or bool(identities)) and all(value == candidate for value in identities), "log has stale/missing source identity")
  if "status" in data:
    require(isinstance(data["status"], str) and data["status"].lower() == "pass", "gate log is not passing")
  require(not any(isinstance(data.get(k), int) and data[k] > 0 for k in ("skipped", "unrun", "pending", "failed", "xfailed")), "gate log has unaccepted cases")


class Gate:
  def __init__(self):
    self.checks = []

  def check(self, name, fn):
    try:
      detail = fn()
      self.checks.append({"name": name, "status": "pass", "detail": detail})
    except (OSError, ValueError, KeyError, TypeError, SyntaxError, subprocess.SubprocessError) as exc:
      # No external document contents, private paths, or environment values in errors.
      self.checks.append({"name": name, "status": "blocked", "reason": type(exc).__name__})


def require(condition, message):
  if not condition:
    raise ValueError(message)


def inspect(root: Path, candidate: str, artifact_root: Path | None = None, manifest: dict | None = None,
            evidence_root: Path | None = None, evidence: dict | None = None, release_base: str = RELEASE_BASE) -> dict:
  gate = Gate()
  modules, native = [], []

  def identity():
    require(bool(SHA.fullmatch(candidate)), "full candidate SHA required")
    require(git(root, "rev-parse", "HEAD") == candidate, "not candidate HEAD")
    status = git(root, "status", "--porcelain", "--untracked-files=all").splitlines()
    generated = "?? .panda-source.json" in status
    if generated:
      identity = json.loads((root / ".panda-source.json").read_text())
      require(identity["source_commit"] == candidate and identity["dirty"] is False, "generated firmware identity stale/dirty")
      status.remove("?? .panda-source.json")
    require(not status, "source not clean")
    git(root, "merge-base", "--is-ancestor", release_base, candidate)
    marker = (root / "git_src_commit").read_text().strip()
    return {"candidate_sha": candidate, "release_base": release_base,
            "upstream_marker_is_candidate": marker == candidate,
            "upstream_marker_policy": "upstream marker is never candidate identity",
            "generated_firmware_manifest_present": generated}
  gate.check("clean_exact_source_and_release_ancestry", identity)

  def vendors():
    result = {}
    for name in VENDORS:
      require((root / name).is_dir(), "missing dependency tree")
      entry = git(root, "ls-tree", candidate, name).split()
      require(bool(entry), "untracked dependency")
      if entry[0] == "160000":
        require(git(root / name, "rev-parse", "HEAD") == entry[2], "wrong submodule pin")
        require(not git(root / name, "status", "--porcelain"), "dirty submodule")
        result[name] = {"kind": "submodule", "sha": entry[2]}
      else:
        require(entry[0] == "040000", "dependency not tracked tree")
        result[name] = {"kind": "vendored_tree", "sha": entry[2]}
    return result
  gate.check("dependency_pins", vendors)

  def launchers():
    for rel in LAUNCHERS:
      p = safe_path(root, rel)
      require(p.is_file() and bool(p.stat().st_mode & stat.S_IXUSR), "launcher missing/not executable")
      require(p.read_bytes().startswith(b"#!"), "missing shebang")
      if p.suffix == ".sh":
        subprocess.run(["bash", "-n", str(p)], check=True, capture_output=True, timeout=10)
      else:
        ast.parse(p.read_text())
    require('AGNOS_VERSION="19.9"' in (root / "launch_env.sh").read_text(), "wrong launch AGNOS")
    return {"syntax_only": True, "executed_launchers": False, "checked": list(LAUNCHERS)}
  gate.check("launcher_permissions_and_syntax", launchers)

  def models():
    found = {}
    for name in MODELS:
      p = safe_path(root, "openpilot/selfdrive/modeld/models/" + name)
      require(p.stat().st_size > 1024, "missing/truncated model")
      with p.open("rb") as f:
        require(not f.read(128).startswith(b"version https://git-lfs.github.com/spec/"), "LFS pointer")
      found[name] = {"sha256": digest(p), "size": p.stat().st_size}
    return found
  gate.check("model_assets", models)

  def inventory():
    nonlocal modules, native
    modules, native = service_inventory(root)
    for module in modules:
      prefix, _, rest = module.partition(".")
      base = root / (prefix + "_repo") if prefix in ("opendbc", "msgq", "rednose", "tinygrad", "teleoprtc") else root
      p = base / module.replace(".", "/")
      require(p.with_suffix(".py").is_file() or (p / "__init__.py").is_file(), "missing service module")
    return {"python_modules": modules, "native_executables": native, "method": "AST only; imports NOT run"}
  gate.check("declared_service_paths", inventory)

  def artifacts():
    require(manifest is not None and artifact_root is not None, "final artifact manifest absent")
    require(manifest["schema"] == 1 and manifest["candidate_sha"] == candidate, "stale artifact identity")
    require(manifest["agnos_version"] == "19.9" and manifest["architecture"] == "aarch64", "wrong native environment")
    records = manifest["artifacts"]
    require(isinstance(records, list) and bool(records) and bool(native), "empty artifact inventory")
    seen = set()
    for item in records:
      require(item["path"] not in seen, "duplicate artifact")
      seen.add(item["path"])
      p = verify_record(artifact_root, item)
      require(p.stat().st_size == item["size"], "wrong size")
      require(item["mode"] in ("0644", "0755"), "unsupported mode")
      require(stat.S_IMODE(p.stat().st_mode) == int(item["mode"], 8), "wrong artifact permissions")
      if item["format"] == "elf-aarch64":
        require(elf_kind(p, 2, 183), "wrong ELF architecture/class")
      elif item["format"] == "elf-arm":
        require(item["path"].startswith("panda/board/obj/") and p.suffix == ".elf", "ARM32 only allowed for panda firmware ELF")
        require(elf_kind(p, 1, 40), "wrong firmware ELF architecture/class")
      else:
        require(item["format"] == "data", "unknown artifact format")
        with p.open("rb") as f:
          require(f.read(4) != b"\x7fELF", "ELF disguised as data")
    require(set(native) <= seen, "missing service executables")
    by_path = {r["path"]: r for r in records}
    require(all(by_path[p]["format"] == "elf-aarch64" and by_path[p]["mode"] == "0755" for p in native), "wrong service artifact")
    # The packager owns complete shipping .so/firmware coverage; its gate is mandatory below.
    return {"verified_artifacts": len(seen), "required_native_executables": native}
  gate.check("final_native_artifacts", artifacts)

  def receipt(name):
    require(evidence is not None and evidence_root is not None, "acceptance evidence absent")
    require(evidence["schema"] == 1 and evidence["candidate_sha"] == candidate, "stale evidence envelope")
    item = evidence["gates"][name]
    require(item["status"] == "pass" and item["candidate_sha"] == candidate, "gate unrun/skipped/stale")
    require(bool(item["logs"]), "missing log evidence")
    require(not any(isinstance(item.get(k), int) and item[k] > 0 for k in ("skipped", "unrun", "pending", "failed", "xfailed")), "gate has unaccepted cases")
    for log in item["logs"]:
      verify_bound_log(evidence_root, log, candidate)
    if name == "build":
      require(item["kind"] == "full_scons" and item["exit_code"] == 0 and item["targets"] == [], "not full successful build")
      require(item["environment"] == "agnos:19.9-build/aarch64", "wrong build environment")
      completed = False
      for record in item["logs"]:
        p = safe_path(evidence_root, record["path"])
        with p.open("rb") as f:
          f.seek(max(0, p.stat().st_size - 8192))
          completed |= b"scons: done building targets." in f.read()
      require(completed, "missing full build completion log")
    if name == "imports":
      statuses = item["modules"]
      required = modules
      if item.get("profile") == {"target": "comma3x", "use_webcam": False}:
        required = [m for m in modules if m not in conditional_webcam_imports(root)]
      require(bool(required) and all(statuses.get(m) == "pass" for m in required), "missing/blocked required service import")
      require(item["daemons_started"] is False, "daemon execution forbidden")
    return {"status": "pass", "hashed_logs": len(item["logs"])}
  for name in GATES:
    gate.check("gate_" + name, lambda name=name: receipt(name))

  def primary():
    require(evidence is not None, "primary UI readiness absent")
    p = evidence["primary_ui"]
    require(p["status"] == "ready" and p["candidate_sha"] == candidate, "primary UI not ready for final source")
    require(bool(SHA.fullmatch(p["feature_tip"])), "full primary feature SHA required")
    git(root, "merge-base", "--is-ancestor", p["feature_tip"], candidate)
    return {"feature_tip": p["feature_tip"], "candidate_sha": candidate}
  gate.check("primary_ui_final_readiness", primary)
  passed = all(c["status"] == "pass" for c in gate.checks)
  return {"schema": 1, "candidate_sha": candidate, "status": "pass" if passed else "blocked",
          "candidate_ready": passed, "installable": False, "device_boot_validated": False,
          "road_validated": False, "checks": gate.checks,
          "native_plan": {"build": ["scons", "-j4"], "targets": [], "python_imports": modules, "conditional_webcam_imports": conditional_webcam_imports(root),
                      "default_c3x_required_python_imports": [m for m in modules if m not in conditional_webcam_imports(root)],
                          "native_executables_not_executed": native,
                          "constraints": ["One primary-coordinated VM lock slot only after final SHA and UI ready",
                                          "Imports require isolated container HOME/PARAMS_ROOT/LOG_ROOT and timeouts",
                                          "GPU/device-only imports blocked on VM remain blocked, never passed/skipped",
                                          "Never run launch scripts, manager_init, process prepare/start, camera/GPU daemons"]}}


def main():
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--source", type=Path, required=True)
  ap.add_argument("--candidate", required=True)
  ap.add_argument("--artifact-root", type=Path)
  ap.add_argument("--artifact-manifest", type=Path)
  ap.add_argument("--evidence-root", type=Path)
  ap.add_argument("--evidence", type=Path)
  ap.add_argument("--output", type=Path, required=True)
  args = ap.parse_args()
  try:
    require(not args.output.resolve().is_relative_to(args.source.resolve()), "report must be outside source")
    manifest = json.loads(args.artifact_manifest.read_text()) if args.artifact_manifest else None
    evidence = json.loads(args.evidence.read_text()) if args.evidence else None
    result = inspect(args.source, args.candidate, args.artifact_root, manifest, args.evidence_root, evidence)
  except (OSError, ValueError, TypeError) as exc:
    result = {"schema": 1, "candidate_sha": args.candidate, "status": "blocked", "candidate_ready": False,
              "installable": False, "device_boot_validated": False, "road_validated": False,
              "checks": [{"name": "input", "status": "blocked", "reason": type(exc).__name__}]}
  args.output.write_text(json.dumps(result, indent=2) + "\n")
  print(result["status"])
  return 0 if result["candidate_ready"] else 2


if __name__ == "__main__":
  raise SystemExit(main())
