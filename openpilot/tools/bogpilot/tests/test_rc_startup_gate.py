"""Host-runnable gate contract tests; NOT native acceptance results."""
import json
from pathlib import Path

import pytest

from openpilot.tools.bogpilot import rc_startup_gate as gate
from openpilot.system.bogpilot import settings_backup as backup, toggle_reset as reset


@pytest.mark.parametrize("path", ["/", "/data", "/data/sandbox", "/cache/test", "/persist/a", "/dev/a", "/proc/a", "/sys/a", "/system/a"])
def test_live_and_system_paths_rejected(path):
  with pytest.raises(ValueError):
    gate.safe_root(path)


def test_source_tree_cannot_be_sandbox():
  with pytest.raises(ValueError):
    gate.safe_root(gate.REPO / "scratch")


def test_symlink_to_live_root_rejected(tmp_path):
  link = tmp_path / "not-safe"
  link.symlink_to("/data")
  with pytest.raises(ValueError):
    gate.safe_root(link / "sandbox")


def test_dedicated_sandbox_allowed(tmp_path):
  assert gate.safe_root(tmp_path / "dedicated") == tmp_path / "dedicated"


def test_actual_combined_scope_is_covered():
  assert gate.scope_coverage() == len(reset.reset_defaults()) > 200


def test_actual_scope_excludes_identity_calibration_and_freeform():
  keys = set(reset.reset_defaults())
  assert not keys & {"DongleId", "CalibrationParams", "CalibratedLateralAcceleration", "CarModel",
                     "GithubSshKeys", "SearchInput", "StartupMessageTop", "StartupMessageBottom",
                     "PreferredSchedule", "UpdatedToggles", "ShowUploadRate"}


def test_actual_backup_missing_and_corrupt_failclosed(tmp_path):
  with pytest.raises(FileNotFoundError):
    backup.read_snapshot(tmp_path / "absent.json")
  corrupt = tmp_path / "corrupt.json"
  corrupt.write_bytes(b"synthetic-corrupt")
  with pytest.raises(ValueError):
    backup.read_snapshot(corrupt)
  corrupt.write_text(json.dumps({"version": 1, "entries": {}, "digest": "synthetic-invalid-digest"}))
  with pytest.raises(ValueError):
    backup.read_snapshot(corrupt)


def test_stale_candidate_never_accepts_or_skips(tmp_path):
  assert gate.main(["--sandbox-root", str(tmp_path), "--expected-commit", "0" * 40]) == 1
  reports = list(tmp_path.glob("rc-startup-*/report.json"))
  assert len(reports) == 1
  doc = json.loads(reports[0].read_text())
  assert doc["status"] == "FAIL" and doc["skipped"] == 0 and not doc["cases"]
  assert doc["hardware_started"] is False


def test_environment_restored_on_failure(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", "synthetic-previous")
  monkeypatch.delenv("BOGPILOT_BACKUP_DIR", raising=False)
  import os
  with pytest.raises(RuntimeError):
    with gate.sandbox_environment(tmp_path / "files", tmp_path / "cache"):
      assert os.environ["BOGPILOT_PARAMS_DIR"] == str(tmp_path / "files")
      raise RuntimeError("synthetic")
  assert os.environ["BOGPILOT_PARAMS_DIR"] == "synthetic-previous"
  assert "BOGPILOT_BACKUP_DIR" not in os.environ


def test_manifest_cannot_omit_or_expand_source_scope(tmp_path):
  manifest = tmp_path / "source.json"
  manifest.write_text(json.dumps({"version": 1, "commit": "a" * 40, "files": {}}))
  with pytest.raises(RuntimeError):
    gate.source_identity("a" * 40, manifest)


def test_manifest_rejects_corrupt_actual_source_digest(tmp_path):
  manifest = tmp_path / "source.json"
  manifest.write_text(json.dumps({"version": 1, "commit": "a" * 40,
                                  "files": {path: "0" * 64 for path in gate.SOURCE_PATHS}}))
  with pytest.raises(RuntimeError):
    gate.source_identity("a" * 40, manifest)


def test_full_sha_required():
  with pytest.raises(ValueError):
    gate.source_identity("short")
