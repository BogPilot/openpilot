"""Synthetic stdlib fixtures only; fake ELF/model bytes are NEVER runtime artifacts."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("rc_build_gate", Path(__file__).parents[1] / "rc_build_gate.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class BuildGateTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.base = Path(self.tmp.name)
    self.source = self.base / "source"
    self.art = self.base / "artifacts"
    self.logs = self.base / "evidence"
    for p in (self.source, self.art, self.logs):
      p.mkdir()
    for rel in M.LAUNCHERS:
      p = self.source / rel
      p.parent.mkdir(parents=True, exist_ok=True)
      text = '#!/bin/bash\nexport AGNOS_VERSION="19.9"\n' if p.suffix == ".sh" else '#!/usr/bin/env python3\n'
      p.write_text(text)
      p.chmod(0o755)
    for name in M.VENDORS:
      p = self.source / name / "README"
      p.parent.mkdir()
      p.write_text("Synthetic dependency inventory fixture\n")
    for name in M.MODELS:
      p = self.source / "openpilot/selfdrive/modeld/models" / name
      p.parent.mkdir(parents=True, exist_ok=True)
      p.write_bytes(b"synthetic-not-a-model" * 100)
    p = self.source / "openpilot/system/manager/process_config.py"
    p.write_text('procs = [PythonProcess("fixture", "openpilot.fixture"), NativeProcess("fixture", "bin", ["./fixture"])]\n')
    (self.source / "openpilot/fixture.py").write_text("# Synthetic import inventory; never imported\n")
    (self.source / "git_src_commit").write_text("0" * 40)
    self.git("init", "-q")
    self.git("config", "user.name", "BogPilot")
    self.git("config", "user.email", "bogpilot@users.noreply.github.com")
    self.git("add", ".")
    self.git("commit", "-qm", "test: synthetic candidate fixture")
    self.sha = self.git("rev-parse", "HEAD")
    p = self.art / "bin/fixture"
    p.parent.mkdir()
    elf = bytearray(64)
    elf[:6] = b"\x7fELF\x02\x01"
    elf[18:20] = (183).to_bytes(2, "little")
    p.write_bytes(elf)
    p.chmod(0o755)
    self.manifest = {"schema": 1, "candidate_sha": self.sha, "agnos_version": "19.9", "architecture": "aarch64",
                     "artifacts": [{"path": "bin/fixture", "sha256": M.digest(p), "size": 64, "mode": "0755", "format": "elf-aarch64"}]}
    log = self.logs / "fixture.log"
    log.write_text("RC_SOURCE_SHA=" + self.sha + "\nSYNTHETIC evidence; not an actual native build or import run\nscons: done building targets.\n")
    receipt = {"status": "pass", "candidate_sha": self.sha, "logs": [{"path": "fixture.log", "sha256": M.digest(log)}]}
    self.evidence = {"schema": 1, "candidate_sha": self.sha, "gates": {n: copy.deepcopy(receipt) for n in M.GATES},
                     "primary_ui": {"status": "ready", "candidate_sha": self.sha, "feature_tip": self.sha}}
    self.evidence["gates"]["build"].update(kind="full_scons", targets=[], exit_code=0, environment="agnos:19.9-build/aarch64")
    self.evidence["gates"]["imports"].update(modules={"openpilot.fixture": "pass"}, daemons_started=False)

  def git(self, *args):
    return subprocess.check_output(["git", "-C", str(self.source), *args], stderr=subprocess.PIPE, text=True).strip()

  def run_gate(self):
    return M.inspect(self.source, self.sha, self.art, self.manifest, self.logs, self.evidence, release_base=self.sha)

  def blocked(self, name):
    result = self.run_gate()
    self.assertFalse(result["candidate_ready"])
    self.assertEqual(next(c for c in result["checks"] if c["name"] == name)["status"], "blocked")

  def test_complete_synthetic_receipts_are_not_device_validation(self):
    r = self.run_gate()
    self.assertTrue(r["candidate_ready"])
    self.assertFalse(r["installable"])
    self.assertFalse(r["device_boot_validated"])
    self.assertFalse(r["road_validated"])
    self.assertEqual(r["native_plan"]["build"], ["scons", "-j4"])

  def test_missing_gate(self):
    del self.evidence["gates"]["controls"]
    self.blocked("gate_controls")

  def test_recorder_fail_and_skips_never_pass(self):
    for status in ("fail", "skip", "pending", "blocked"):
      self.evidence["gates"]["recorder"]["status"] = status
      self.blocked("gate_recorder")

  def test_source_sha_mismatch(self):
    r = M.inspect(self.source, "f" * 40, release_base=self.sha)
    self.assertFalse(r["candidate_ready"])

  def test_dirty_source(self):
    (self.source / "untracked.txt").write_text("fixture")
    self.blocked("clean_exact_source_and_release_ancestry")

  def test_stale_artifacts(self):
    self.manifest["candidate_sha"] = "f" * 40
    self.blocked("final_native_artifacts")

  def test_artifact_digest(self):
    (self.art / "bin/fixture").write_bytes(b"changed" * 10)
    self.blocked("final_native_artifacts")

  def test_non_arm64_elf(self):
    p = self.art / "bin/fixture"
    data = bytearray(p.read_bytes()); data[18:20] = (62).to_bytes(2, "little"); p.write_bytes(data)
    self.manifest["artifacts"][0]["sha256"] = M.digest(p)
    self.blocked("final_native_artifacts")

  def test_data_cannot_disguise_elf(self):
    self.manifest["artifacts"][0]["format"] = "data"
    self.blocked("final_native_artifacts")

  def test_panda_arm32_format_is_not_runtime_arm64(self):
    p = self.art / "panda/board/obj/panda_h7/main.elf"
    p.parent.mkdir(parents=True)
    data = bytearray(64); data[:6] = b"\x7fELF\x01\x01"; data[18:20] = (40).to_bytes(2, "little")
    p.write_bytes(data); p.chmod(0o644)
    self.manifest["artifacts"].append({"path": str(p.relative_to(self.art)), "sha256": M.digest(p), "size": 64, "mode": "0644", "format": "elf-arm"})
    self.assertTrue(self.run_gate()["candidate_ready"])

  def test_arm32_cannot_replace_runtime_service(self):
    self.manifest["artifacts"][0]["format"] = "elf-arm"
    self.blocked("final_native_artifacts")

  def test_log_tampering(self):
    (self.logs / "fixture.log").write_text("tampered")
    self.blocked("gate_build")

  def test_stale_log_identity_even_with_fresh_checksum(self):
    p = self.logs / "fixture.log"
    p.write_text("RC_SOURCE_SHA=" + "f" * 40 + "\nold run\n")
    for item in self.evidence["gates"].values():
      item["logs"][0]["sha256"] = M.digest(p)
    self.blocked("gate_build")

  def test_json_log_source_and_failed_status(self):
    p = self.logs / "json_receipt.log"
    p.write_text(json.dumps({"source_sha": self.sha, "status": "pass"}))
    for item in self.evidence["gates"].values():
      item["logs"].append({"path": "json_receipt.log", "sha256": M.digest(p)})
    self.assertTrue(self.run_gate()["candidate_ready"])
    p.write_text(json.dumps({"source_sha": self.sha, "status": "fail"}))
    for item in self.evidence["gates"].values():
      item["logs"][-1]["sha256"] = M.digest(p)
    self.blocked("gate_build")

  def test_new_header_cannot_relabel_stale_json(self):
    p = self.logs / "fixture.log"
    p.write_text("RC_SOURCE_SHA=" + self.sha + "\n" + json.dumps({"source_sha": "f" * 40, "status": "pass"}))
    for item in self.evidence["gates"].values():
      item["logs"][0]["sha256"] = M.digest(p)
    self.blocked("gate_controls")

  def test_targeted_build_not_full(self):
    self.evidence["gates"]["build"]["targets"] = ["one.so"]
    self.blocked("gate_build")

  def test_gpu_import_blocker_not_a_skip(self):
    self.evidence["gates"]["imports"]["modules"]["openpilot.fixture"] = "blocked_gpu"
    self.blocked("gate_imports")

  def test_daemons_forbidden(self):
    self.evidence["gates"]["imports"]["daemons_started"] = True
    self.blocked("gate_imports")

  def test_primary_ui_pending(self):
    self.evidence["primary_ui"]["status"] = "wip"
    self.blocked("primary_ui_final_readiness")

  def test_path_escape_and_symlink(self):
    with self.assertRaises(ValueError):
      M.safe_path(self.logs, "../source/git_src_commit")
    (self.logs / "escape").symlink_to(self.source / "git_src_commit")
    with self.assertRaises(ValueError):
      M.safe_path(self.logs, "escape")

  def test_generated_firmware_identity_is_only_allowed_untracked_file(self):
    p = self.source / ".panda-source.json"
    p.write_text(json.dumps({"source_commit": self.sha, "dirty": False}))
    self.assertTrue(self.run_gate()["candidate_ready"])
    p.write_text(json.dumps({"source_commit": "f" * 40, "dirty": False}))
    self.blocked("clean_exact_source_and_release_ancestry")

  def test_pass_label_cannot_hide_skip_count(self):
    self.evidence["gates"]["startup"]["skipped"] = 1
    self.blocked("gate_startup")

  def test_launcher_no_execute(self):
    (self.source / "launch_openpilot.sh").chmod(0o644)
    self.blocked("launcher_permissions_and_syntax")

  def test_missing_evidence_no_pass(self):
    r = M.inspect(self.source, self.sha, release_base=self.sha)
    self.assertFalse(r["candidate_ready"])
    self.assertEqual(next(c for c in r["checks"] if c["name"] == "model_assets")["status"], "pass")


if __name__ == "__main__":
  unittest.main()
