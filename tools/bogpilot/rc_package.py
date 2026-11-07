#!/usr/bin/env python3
"""Offline C3X test-build inventory and deterministic local packaging, never installation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile

NATIVE_REQUIRED = (
  "openpilot/common/libparams_c.so", "msgq_repo/msgq/ipc_pyx.so",
  "msgq_repo/msgq/visionipc/visionipc_pyx.so", "rednose_repo/rednose/helpers/ekf_sym_pyx.so",
  "openpilot/system/camerad/camerad", "openpilot/system/loggerd/loggerd",
  "openpilot/system/loggerd/encoderd", "openpilot/selfdrive/pandad/pandad",
  "openpilot/cereal/messaging/bridge", "openpilot/selfdrive/locationd/models/generated/libcar.so",
  "openpilot/selfdrive/locationd/models/generated/libpose.so",
  "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so",
)
SOURCE_REQUIRED = (
  "launch_openpilot.sh", "launch_chffrplus.sh", "launch_env.sh", "SConstruct", "pyproject.toml",
  "openpilot/system/manager/manager.py", "openpilot/system/manager/build.py",
  "openpilot/system/manager/process_config.py", "openpilot/selfdrive/ui/ui.py",
  "openpilot/selfdrive/modeld/modeld.py", "openpilot/selfdrive/modeld/dmonitoringmodeld.py",
  "openpilot/system/hardware/comma/agnos.json", "panda/build_identity.py",
  "msgq_repo/msgq/__init__.py", "opendbc_repo/opendbc/__init__.py",
  "rednose_repo/rednose/__init__.py",
  "tinygrad_repo/tinygrad/__init__.py",
)
MODELS = ("driving_tinygrad.pkl", "dmonitoring_model_tinygrad.pkl",
          "dm_warp_1344x760_tinygrad.pkl", "dm_warp_1928x1208_tinygrad.pkl",
          "driving_warp_1344x760_tinygrad.pkl", "driving_warp_1928x1208_tinygrad.pkl")
SHA = re.compile(r"[0-9a-f]{40}")
# build.json mirrors openpilot.common.version.BuildMetadata/OpenpilotMetadata (asdict shape).
BUILD_METADATA = "build.json"
METADATA_FIELDS = ("build_style", "git_commit", "git_commit_date", "git_origin", "is_dirty", "release_notes", "version")
METADATA_RUNTIME = ("openpilot/common/version.py", "openpilot/common/git.py", "openpilot/common/basedir.py",
                    "openpilot/common/swaglog.py", "openpilot/common/version.h", "RELEASES.md")
RELEASE_LIKE = ("release-tizi-staging", "release-mici-staging", "release-tizi", "release-mici", "nightly",
                "nightly-chestnut", "devel-staging", "nightly-dev", "nightly-chestnut-dev")
# Credential-free public remote forms only: no user:password@, token or query.
ORIGIN = re.compile(r"(git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
COMMIT_DATE = re.compile(r"'[0-9]+ [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} [+-][0-9]{4}'")
HASH = re.compile(r"[0-9a-f]{64}")


def canonical(value):
  return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(path):
  h = hashlib.sha256()
  with path.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
      h.update(chunk)
  return h.hexdigest()


def safe_name(name):
  p = PurePosixPath(name)
  if not name or str(p) != name or p.is_absolute() or any(x in ("..", ".git") for x in p.parts) or "\\" in name:
    raise ValueError("unsafe relative path")
  if name in ("RC_PACKAGE.json", BUILD_METADATA):
    raise ValueError("reserved package metadata path")
  lower = [x.lower() for x in p.parts]
  if any(x in (".ssh", ".aws", ".gnupg", "secrets", "private", "params", "params_bogpilot", "rlogs", "routes") for x in lower):
    raise ValueError("private path refused")
  if (p.name.lower().startswith((".env", "id_rsa", "id_ed25519")) or
      (p.name.lower().startswith(("rlog", "qlog")) and p.suffix.lower() not in (".py", ".capnp")) or
      p.suffix.lower() in (".pem", ".key", ".b64") and name != "openpilot/common/esim/gsma_ci_bundle.pem"):
    raise ValueError("private file refused")
  return name


def git(root, *args):
  return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL)


def source_catalog(root, ref):
  """Original Git mode/blob catalogue, including nonshipping entries (never contents)."""
  result = {}
  for raw in git(root, "ls-tree", "-rz", "--full-tree", ref).split(b"\0"):
    if not raw:
      continue
    meta, name = raw.split(b"\t", 1)
    mode, kind, blob = meta.decode().split()
    result[name.decode()] = {"mode": mode, "blob": blob}
  return result


def validate_build_metadata(raw, candidate):
  """Strict schema for packaged build.json; returns parsed dict or raises."""
  try:
    data = json.loads(raw)
  except (ValueError, UnicodeDecodeError):
    raise ValueError("build metadata is not valid JSON") from None
  op = data.get("openpilot") if isinstance(data, dict) else None
  if set(data) != {"channel", "openpilot"} or not isinstance(op, dict) or set(op) != set(METADATA_FIELDS):
    raise ValueError("build metadata schema mismatch")
  if any(type(op[k]) is not str for k in METADATA_FIELDS if k != "is_dirty") or type(data["channel"]) is not str:
    raise ValueError("build metadata field types invalid")
  if op["git_commit"] != candidate:
    raise ValueError("build metadata candidate SHA mismatch")
  if op["is_dirty"] is not False:
    raise ValueError("build metadata dirty")
  if op["build_style"] != "unknown":
    raise ValueError("build metadata must not claim a release build style")
  if data["channel"] in ("", "HEAD", "unknown") or data["channel"] in RELEASE_LIKE:
    raise ValueError("build metadata channel missing or release/tested-like")
  if not ORIGIN.fullmatch(op["git_origin"]):
    raise ValueError("build metadata origin not a credential-free public remote")
  if not COMMIT_DATE.fullmatch(op["git_commit_date"]) or op["version"] in ("", "unknown") or not op["release_notes"]:
    raise ValueError("build metadata date/version/notes invalid")
  return data


def generate_build_metadata(root, candidate):
  """Truthful build.json from the exact clean Git checkout, using stock field semantics."""
  root = Path(root)
  if git(root, "rev-parse", "HEAD").decode().strip() != candidate:
    raise ValueError("metadata checkout HEAD does not match candidate")
  if git(root, "status", "--porcelain", "--untracked-files=no").strip():
    raise ValueError("metadata checkout dirty")
  version_h = (root / "openpilot/common/version.h").read_text()
  data = {"channel": git(root, "rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
          "openpilot": {"build_style": "unknown", "git_commit": candidate,
                        "git_commit_date": git(root, "show", "--no-patch", "--format='%ct %ci'", candidate).decode().strip(),
                        "git_origin": git(root, "config", "--get", "remote.origin.url").decode().strip(),
                        "is_dirty": False,
                        "release_notes": (root / "RELEASES.md").read_text().split("\n\n", 1)[0],
                        "version": version_h.split('"')[1]}}
  raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
  validate_build_metadata(raw, candidate)
  return raw


def check_metadata_runtime(root, names):
  """Static prerequisites so packaged get_build_metadata() can read build.json."""
  for name in METADATA_RUNTIME:
    if name not in names:
      raise ValueError("metadata runtime prerequisite missing: " + name)
  text = (Path(root) / "openpilot/common/version.py").read_text()
  for needle in ('BUILD_METADATA_FILENAME = "build.json"', "def build_metadata_from_dict(", "def get_build_metadata("):
    if needle not in text:
      raise ValueError("metadata runtime API missing: " + needle)


def check_archive(archive, candidate):
  """Archive must carry validated build.json bound to RC_PACKAGE.json."""
  with tarfile.open(archive) as tar:
    names = tar.getnames()
    if names.count(BUILD_METADATA) != 1 or names.count("RC_PACKAGE.json") != 1:
      raise ValueError("archive build/package metadata missing or duplicated")
    raw = tar.extractfile(BUILD_METADATA).read()
    report = json.load(tar.extractfile("RC_PACKAGE.json"))
  validate_build_metadata(raw, candidate)
  if (report.get("candidate_sha") != candidate or
      report.get("build_metadata_sha256") != hashlib.sha256(raw).hexdigest()):
    raise ValueError("archive build metadata not bound to package report")
  for name in METADATA_RUNTIME:
    if name not in names:
      raise ValueError("archive metadata runtime prerequisite missing: " + name)
  return hashlib.sha256(raw).hexdigest()


def path_id(name):
  return hashlib.sha256(name.encode()).hexdigest()


def inventory(root, ref, artifacts, prefix="", exclusions=None):
  """Read committed full source, recursively verifying exact initialized gitlinks."""
  if Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root.resolve():
    raise ValueError("not a standalone initialized checkout")
  if git(root, "rev-parse", "HEAD").decode().strip() != ref:
    raise ValueError("checkout HEAD does not match candidate/gitlink")
  changed = git(root, "diff", "--name-only", ref, "--").decode().splitlines()
  def native_override(name):
    return (name in NATIVE_REQUIRED or name.startswith("panda/board/obj/") or
            name.endswith((".so", ".elf", ".bin", ".bin.signed")) or
            name == "openpilot/common/hardware/comma/updater")
  if any(prefix + n not in artifacts or not native_override(prefix + n) for n in changed):
    raise ValueError("source differs from candidate")
  result = {}
  for record in git(root, "ls-tree", "-rz", "--full-tree", ref).split(b"\0"):
    if not record:
      continue
    metadata, name = record.split(b"\t", 1)
    mode, kind, oid = metadata.decode().split()
    name = name.decode()
    rel = prefix + name
    if rel in (exclusions or {}):
      continue  # Catalogue-bound exclusion; never open its contents.
    rel = safe_name(rel)
    if kind == "commit":
      result.update(inventory(root / name, oid, artifacts, rel + "/", exclusions))
    elif kind == "blob":
      result[rel] = mode
    else:
      raise ValueError("unsupported git entry")
  return result


def validate_panda(root, candidate, exclusions=None):
  path = root / ".panda-source.json"
  data = json.loads(path.read_text())
  if data.get("schema") != 1 or data.get("source_commit") != candidate or data.get("dirty") is not False:
    raise ValueError("panda source provenance missing/stale/dirty")
  expected = {"SConstruct", "common/version.h"}
  for scope in ("panda", "opendbc_repo/opendbc/safety"):
    for p in (root / scope).rglob("*"):
      rel = p.relative_to(root)
      if any(x in rel.parts for x in (".git", "__pycache__", ".pytest_cache", "obj")):
        continue
      if p.name in (".sconsign.dblite", "compile_commands.json"):
        continue
      if p.is_file() and not p.name.endswith((".pyc", ".o", ".so")):
        expected.add(rel.as_posix())
  files = {}
  for name in sorted(expected):
    if name in (exclusions or {}):
      # This unsigned manifest hash remains bound to the native/firmware gate.
      # Do not open excluded key/build-host material merely to rehash it.
      value = data.get("files", {}).get(name)
      if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError("excluded panda input lacks provenance hash")
      files[name] = value
    else:
      files[name] = digest(root / safe_name(name))
  if data.get("files") != files or data.get("source_sha256") != hashlib.sha256(canonical(files)).hexdigest():
    raise ValueError("panda source inventory mismatch")
  if data.get("version") != (root / "common/version.h").read_text().strip():
    raise ValueError("panda version mismatch")
  return digest(path)


def verify(root, candidate, manifest, shipping_manifest=None):
  """Return report or raise. This is static verification, not native runtime validation."""
  root = Path(root).resolve()
  if not SHA.fullmatch(candidate):
    raise ValueError("full candidate SHA required")
  raw_manifest = Path(manifest).read_bytes()
  data = json.loads(raw_manifest)
  if (data.get("schema") != 1 or data.get("candidate_sha") != candidate or
      data.get("agnos_version") != "19.9" or data.get("architecture") != "aarch64"):
    raise ValueError("artifact manifest target mismatch")
  artifacts = {}
  for entry in data["artifacts"]:
    name = safe_name(entry["path"])
    if name in artifacts or not HASH.fullmatch(entry["sha256"]):
      raise ValueError("duplicate artifact or invalid hash")
    if entry.get("mode") not in ("0644", "0755") or type(entry.get("size")) is not int or entry["size"] <= 0:
      raise ValueError("invalid artifact mode/size")
    if entry.get("format") not in ("elf-aarch64", "elf-arm", "data"):
      raise ValueError("unsupported artifact format")
    artifacts[name] = entry
  catalog = source_catalog(root, candidate)
  exclusions = {}
  if shipping_manifest is not None:
    shipping_input = json.loads(Path(shipping_manifest).read_bytes())
    if shipping_input.get("source_commit") != candidate or shipping_input.get("schema_version") != 1:
      raise ValueError("shipping manifest source mismatch")
    exclusions = shipping_input.get("source_exclusions", {})
    if not isinstance(exclusions, dict):
      raise ValueError("invalid exclusions")
    for name, record in exclusions.items():
      original = catalog.get(name)
      if (original is None or not isinstance(record, dict) or
          record != {"source_mode": original["mode"], "source_blob": original["blob"], "reason": "private_or_build_host_only"} or
          name in SOURCE_REQUIRED + NATIVE_REQUIRED or
          PurePosixPath(name).name.lower().startswith(("license", "notice", "copying", "authors", "copyright"))):
        raise ValueError("invalid/required source exclusion")
  source = inventory(root, candidate, artifacts, exclusions=exclusions)
  names = set(source) | set(artifacts) | {".panda-source.json"}
  for name in SOURCE_REQUIRED + NATIVE_REQUIRED:
    if name not in names:
      raise ValueError("required runtime/source inventory missing: " + name)
  if not (root / "launch_env.sh").read_text().find('AGNOS_VERSION="19.9"') >= 0:
    raise ValueError("launcher AGNOS mismatch")
  for model in MODELS:
    name = "openpilot/selfdrive/modeld/models/" + model
    if name not in names or (root / name).stat().st_size < 100000:
      raise ValueError("missing/truncated model: " + name)
  for name in ("panda/board/obj/panda_h7.bin.signed", "panda/board/obj/bootstub.panda_h7.bin"):
    if name not in artifacts:
      raise ValueError("missing H7 firmware artifact: " + name)
  # NativeProcess entries are detected without importing process_config/hardware.
  import ast
  module = ast.parse((root / "openpilot/system/manager/process_config.py").read_text())
  native = set(NATIVE_REQUIRED)
  native_executables = set()
  for node in ast.walk(module):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("PythonProcess", "DaemonProcess"):
      module_name = ast.literal_eval(node.args[1]).replace(".", "/")
      if module_name + ".py" not in names and module_name + "/__init__.py" not in names:
        raise ValueError("missing Python runtime module: " + module_name)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "NativeProcess":
      directory = ast.literal_eval(node.args[1])
      executable = ast.literal_eval(node.args[2])[0]
      executable = safe_name(str(PurePosixPath(directory) / executable.removeprefix("./")))
      native.add(executable)
      native_executables.add(executable)
  if not native <= artifacts.keys():
    raise ValueError("native runtime missing manifest coverage: " + ",".join(sorted(native - artifacts.keys())))
  entries = {}
  for name in sorted(names):
    safe_name(name)
    path = root / name
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if path.is_symlink():
      target = os.readlink(path)
      resolved = path.resolve(strict=True)
      if os.path.isabs(target) or not resolved.is_relative_to(root):
        raise ValueError("external/absolute symlink: " + name)
      resolved_name = safe_name(resolved.relative_to(root).as_posix())
      if resolved_name not in names and not any(n.startswith(resolved_name + "/") for n in names):
        raise ValueError("symlink target not shipped: " + name)
      if name in artifacts:
        raise ValueError("artifact must be regular file")
      entries[name] = {"mode": "120000", "target": target, "resolved_target": resolved_name,
                       "sha256": hashlib.sha256(os.fsencode(target)).hexdigest()}
      continue
    if mode & 0o6022:
      raise ValueError("unsafe permissions: " + name)
    if not stat.S_ISREG(info.st_mode):
      raise ValueError("special file refused")
    if name in source and source[name] == "100755" and not mode & 0o111:
      raise ValueError("lost executable permission: " + name)
    with path.open("rb") as f:
      head = f.read(256)
    if head.startswith(b"version https://git-lfs.github.com/spec/v1"):
      raise ValueError("unresolved LFS pointer: " + name)
    if name.endswith(".pem") and (b"PRIVATE KEY" in path.read_bytes() or b"BEGIN CERTIFICATE" not in path.read_bytes()):
      raise ValueError("not a public CA certificate")
    elf = head.startswith(b"\x7fELF")
    if elf or name.endswith(".so") or (name.startswith("panda/board/obj/") and not name.endswith("/.placeholder")):
      if name not in artifacts:
        raise ValueError("unmanifested native/firmware artifact: " + name)
    if name in artifacts:
      expected = artifacts[name]
      if expected["format"] == "elf-aarch64":
        if not elf or len(head) < 20 or head[4:6] != b"\x02\x01" or int.from_bytes(head[18:20], "little") != 183:
          raise ValueError("not little-endian AArch64 ELF: " + name)
      elif expected["format"] == "elf-arm":
        if not elf or len(head) < 20 or head[4:6] != b"\x01\x01" or int.from_bytes(head[18:20], "little") != 40:
          raise ValueError("not little-endian ARM ELF: " + name)
      elif elf:
        raise ValueError("ELF mislabeled as data")
      if name in native_executables and expected["mode"] != "0755":
        raise ValueError("native executable lost execute permission")
      if name in native and expected["format"] != "elf-aarch64":
        raise ValueError("native runtime must be ELF")
      if info.st_size != expected["size"] or mode != int(expected["mode"], 8):
        raise ValueError("artifact size/permission mismatch: " + name)
    checksum = digest(path)
    if name in artifacts and checksum != artifacts[name]["sha256"]:
      raise ValueError("artifact checksum mismatch: " + name)
    entries[name] = {"sha256": checksum, "size": info.st_size, "mode": "0755" if mode & 0o111 else "0644"}
  provenance = validate_panda(root, candidate, exclusions)
  check_metadata_runtime(root, names)
  build_metadata = generate_build_metadata(root, candidate)
  return {"schema": 1, "kind": "cataloged-excluded-source-test-build" if exclusions else "full-tree-test-build",
          "source_scope": "cataloged_source_with_explicit_exclusions" if exclusions else "complete_tracked_source_and_explicit_artifacts",
          "source_catalog": catalog, "source_catalog_sha256": hashlib.sha256(canonical(catalog)).hexdigest(),
          "source_exclusions": exclusions, "excluded_source_contents_read": False, "installable": False,
          "provenance_gate_pass": False, "road_validated": False, "hardware_validated": False, "native_imports_executed": False,
          "dynamic_linkage_validated": False, "candidate_sha": candidate,
          "agnos_version": "19.9", "architecture": "aarch64", "entries": entries,
          "inventory_sha256": hashlib.sha256(canonical(entries)).hexdigest(),
          "artifact_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
          "panda_source_manifest_sha256": provenance,
          "build_metadata": build_metadata.decode(),
          "build_metadata_sha256": hashlib.sha256(build_metadata).hexdigest(),
          "prerequisites": ["assembled native/runtime gate still required", "AGNOS 19.9 comma3X only",
                            "DEBUG policy unchanged; no automatic flash", "known-good rollback source+artifacts required"]}


def outside(root, path):
  path = Path(path).resolve()
  if path.is_relative_to(Path(root).resolve()) or path.is_relative_to(Path("/data")) or path.is_relative_to(Path("/cache")):
    raise ValueError("output must be outside source and device data/cache")
  return path


def bind_provenance(report, evidence_path, shipping_manifest_path, review_record_path=None):
  """Bind track9 gate output to every shipping byte, not a worker/source-only audit.

  These are unsigned local evidence inputs, not signatures or independent trust.
  A passing gate for a different inventory/source is never reusable here.
  """
  evidence_raw = Path(evidence_path).read_bytes()
  evidence = json.loads(evidence_raw)
  shipping_raw = Path(shipping_manifest_path).read_bytes()
  shipping = json.loads(shipping_raw)
  expected = {name: entry["sha256"] for name, entry in report["entries"].items()}
  if (evidence.get("schema_version") != 1 or evidence.get("status") != "pass" or
      evidence.get("checks") != [] or evidence.get("source", {}).get("commit") != report["candidate_sha"] or
      evidence.get("source", {}).get("clean") is not True):
    raise ValueError("provenance gate missing/blocked/stale/dirty")
  if (shipping.get("schema_version") != 1 or shipping.get("source_commit") != report["candidate_sha"] or
      shipping.get("files") != expected or
      evidence.get("shipping", {}).get("manifest_sha256") != hashlib.sha256(canonical(shipping)).hexdigest() or
      evidence.get("shipping", {}).get("declared_files") != len(expected) or
      evidence.get("shipping", {}).get("scanned_files") != len(expected)):
    raise ValueError("provenance does not cover exact shipping inventory")
  catalog_hash = report["source_catalog_sha256"]
  exclusions = report.get("source_exclusions", {})
  if shipping.get("source_exclusions", {}) != exclusions:
    raise ValueError("shipping exclusions differ from package")
  expected_exclusions = [{"path_id": path_id(name), **row} for name, row in sorted(exclusions.items())]
  if (evidence.get("source_catalog_sha256") != catalog_hash or
      evidence.get("source_catalog_entries") != len(report["source_catalog"]) or
      evidence.get("source_scope") != report["source_scope"] or
      evidence.get("source_exclusions", []) != expected_exclusions):
    raise ValueError("provenance catalogue/exclusion scope mismatch")
  links = {name: row for name, row in report["entries"].items() if "target" in row}
  review = None
  if review_record_path is not None:
    review = json.loads(Path(review_record_path).read_bytes())
    if (review.get("schema_version") != 1 or review.get("source_commit") != report["candidate_sha"] or
        review.get("source_catalog_sha256") != catalog_hash or
        review.get("manifest_sha256") != hashlib.sha256(canonical(shipping)).hexdigest() or
        not isinstance(review.get("records"), dict)):
      raise ValueError("review source/catalogue/inventory binding mismatch")
    expected_review = {"sha256": hashlib.sha256(canonical(review)).hexdigest(),
                       "source_catalog_sha256": catalog_hash, "record_count": len(review["records"])}
    if evidence.get("review") != expected_review:
      raise ValueError("review attestation mismatch")
    for name, record in review["records"].items():
      original = report["source_catalog"].get(name)
      if (name not in report["entries"] or original is None or
          record.get("source_mode") != original["mode"] or record.get("source_blob") != original["blob"] or
          record.get("shipping_sha256") != report["entries"][name]["sha256"]):
        raise ValueError("review original source/blob/shipping mismatch")
      if original["mode"] == "120000":
        if record.get("kind") != "internal_link":
          raise ValueError("source link requires internal-link review")
      elif (record.get("kind") not in ("public_reference", "public_source_name") or
            record.get("public_commit") != "f7db927c728bab57bb1263e05465766a8f28fc9d"):
        raise ValueError("nonlink review requires exact public-source anchor")
  elif links or evidence.get("review") is not None:
    raise ValueError("exact review record required")
  expected_links = []
  for name, row in sorted(links.items()):
    record = review["records"].get(name, {}) if review else {}
    original = report["source_catalog"].get(name, {})
    target = row["resolved_target"]
    target_entry = report["entries"].get(target, {})
    if (original.get("mode") != "120000" or record.get("kind") != "internal_link" or
        record.get("representation") != "symlink" or record.get("link_sha256") != row["sha256"] or
        record.get("target") != target or "target" in target_entry or
        record.get("target_sha256") != target_entry.get("sha256")):
      raise ValueError("reviewed link payload/target/representation mismatch")
    expected_links.append({"path_id": path_id(name), "source_mode": "120000", "source_blob": original["blob"],
                           "link_sha256": row["sha256"], "target_path_id": path_id(target),
                           "target_sha256": target_entry["sha256"], "representation": "symlink"})
  actual_links = evidence.get("shipping", {}).get("reviewed_links", [])
  if sorted(actual_links, key=lambda row: row["path_id"]) != sorted(expected_links, key=lambda row: row["path_id"]):
    raise ValueError("reviewed link evidence incomplete/extra/mismatched")
  result = dict(report)
  result.update(provenance_gate_pass=True,
                provenance_review=review,
                provenance_report_sha256=hashlib.sha256(evidence_raw).hexdigest(),
                shipping_manifest_sha256=hashlib.sha256(shipping_raw).hexdigest())
  return result


def bundle(root, report, output):
  """Deterministic uncompressed tar; exclusive local output, no device operations."""
  if report.get("provenance_gate_pass") is not True:
    raise ValueError("bundle requires exact passing provenance evidence")
  root = Path(root).resolve()
  output = outside(root, output)
  if output.exists():
    raise ValueError("refuse overwriting output")
  fd, temp = tempfile.mkstemp(prefix=".rc-package-", dir=output.parent)
  try:
    os.close(fd)
    with tarfile.open(temp, "w", format=tarfile.PAX_FORMAT) as tar:
      for name, entry in sorted(report["entries"].items()):
        path = root / name
        if path.is_symlink():
          if os.readlink(path) != entry.get("target"):
            raise ValueError("source changed since verify")
        elif path.is_file():
          if digest(path) != entry["sha256"] or path.stat().st_size != entry["size"]:
            raise ValueError("source changed since verify")
        else:
          raise ValueError("source missing since verify")
        info = tar.gettarinfo(str(path), arcname=name)
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        info.mode = 0o777 if path.is_symlink() else int(entry["mode"], 8)
        info.pax_headers = {}
        if path.is_symlink():
          tar.addfile(info)
        else:
          with path.open("rb") as f:
            tar.addfile(info, f)
          if digest(path) != entry["sha256"]:
            raise ValueError("source changed during archive read")
      import io
      build_raw = report["build_metadata"].encode()
      validate_build_metadata(build_raw, report["candidate_sha"])
      if hashlib.sha256(build_raw).hexdigest() != report["build_metadata_sha256"]:
        raise ValueError("build metadata changed since verify")
      info = tarfile.TarInfo(BUILD_METADATA)
      info.size, info.mode, info.mtime = len(build_raw), 0o644, 0
      tar.addfile(info, io.BytesIO(build_raw))
      metadata = canonical(report) + b"\n"
      info = tarfile.TarInfo("RC_PACKAGE.json")
      info.size, info.mode, info.mtime = len(metadata), 0o644, 0
      tar.addfile(info, io.BytesIO(metadata))
    # link is exclusive and atomic on same filesystem; do not overwrite a rival.
    check_archive(temp, report["candidate_sha"])
    os.link(temp, output)
    return digest(output)
  finally:
    Path(temp).unlink(missing_ok=True)


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("command", choices=("verify", "bundle", "check-archive"))
  ap.add_argument("--root", required=True, type=Path)
  ap.add_argument("--candidate", required=True)
  ap.add_argument("--artifact-manifest", required=True, type=Path)
  ap.add_argument("--report", required=True, type=Path)
  ap.add_argument("--output", type=Path)
  ap.add_argument("--provenance-report", type=Path)
  ap.add_argument("--shipping-manifest", type=Path)
  ap.add_argument("--review-record", type=Path)
  args = ap.parse_args(argv)
  if args.command == "check-archive":
    try:
      print("PASS archive build.json", check_archive(args.output, args.candidate), "(static; not runtime/road validation)")
      return 0
    except Exception as exc:
      print("BLOCKED:", type(exc).__name__, str(exc) if isinstance(exc, ValueError) else "archive unreadable")
      return 1
  try:
    report_path = outside(args.root, args.report)
    if report_path.exists():
      raise ValueError("refuse overwriting report")
    if args.output is not None and outside(args.root, args.output) == report_path:
      raise ValueError("report and archive paths must differ")
    report = verify(args.root, args.candidate, args.artifact_manifest, args.shipping_manifest)
    if args.review_record is not None and args.provenance_report is None:
      raise ValueError("review record requires passing provenance report")
    if args.provenance_report is not None:
      if args.shipping_manifest is None:
        raise ValueError("both provenance inputs required")
      report = bind_provenance(report, args.provenance_report, args.shipping_manifest, args.review_record)
    if args.command == "bundle":
      if args.output is None:
        raise ValueError("bundle requires --output")
      report["bundle_sha256"] = bundle(args.root, report, args.output)
    with report_path.open("x") as f:
      json.dump(report, f, sort_keys=True, indent=2)
      f.write("\n")
    print("PASS static package checks; test-build only, NOT road/hardware validated or install-approved")
    return 0
  except Exception as exc:
    print("BLOCKED:", type(exc).__name__, str(exc) if isinstance(exc, ValueError) else "verification/output prerequisite failed")
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
