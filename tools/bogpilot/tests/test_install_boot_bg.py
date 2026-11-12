"""Tests for the official boot-screen installer helper. Temp files only; no remount."""
import hashlib
from pathlib import Path

import pytest

from openpilot.system.bogpilot import boot_logo as bl
from openpilot.system.bogpilot.tests.test_boot_logo import RecordingOps
from tools.bogpilot import install_boot_bg as helper

BG = bl.BOOT_BG_PNG_SHA256
HELPERS = Path(__file__).resolve().parents[1] / "rc_install_helpers"


def _mini_tree(tmp_path: Path, include_helper: bool = True) -> Path:
  assets = tmp_path / "openpilot/selfdrive/assets/images"
  assets.mkdir(parents=True)
  for name, _sha in helper.PACKAGED_ASSETS:
    src = bl.ASSETS / name
    (assets / name).write_bytes(src.read_bytes())
  if include_helper:
    dest = tmp_path / "tools/bogpilot/install_boot_bg.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text((Path(helper.__file__)).read_text())
  return tmp_path


def test_stage_check_passes_on_packaged_assets(tmp_path):
  tree = _mini_tree(tmp_path)
  assert helper.stage_check(tree) == []
  assert helper.cmd_stage_check(tree) == 0


def test_stage_check_fails_on_missing_or_bad_hash(tmp_path):
  tree = _mini_tree(tmp_path)
  (tree / helper.ASSETS_REL / "bogpilot_bg.png").write_bytes(b"stale")
  errors = helper.stage_check(tree)
  assert any("hash mismatch" in e and "bogpilot_bg.png" in e for e in errors)
  assert helper.cmd_stage_check(tree) == 2
  (tree / helper.ASSETS_REL / "bogpilot_bg.png").unlink()
  errors = helper.stage_check(tree)
  assert any("missing" in e and "bogpilot_bg.png" in e for e in errors)


def test_install_for_upgrade_writes_png_and_jpg(tmp_path):
  ops = RecordingOps()
  png = tmp_path / "bg.png"
  jpg = tmp_path / "bg.jpg"
  png.write_bytes((bl.stock_bg_png_path()).read_bytes())
  jpg.write_bytes(b"stale-jpg")
  token = helper.install_for_upgrade(
    png_ops=ops, jpg_ops=ops, png_target=png, jpg_target=jpg,
    png_source=bl.boot_bg_png_path(), jpg_source=bl.boot_logo_path(),
  )
  assert token == "BOOT_BG_INSTALLED"
  assert bl.sha256_file(png) == BG
  assert bl.sha256_file(jpg) == bl.BOOT_LOGO_SHA256
  assert helper.install_for_upgrade(
    png_ops=ops, jpg_ops=ops, png_target=png, jpg_target=jpg,
    png_source=bl.boot_bg_png_path(), jpg_source=bl.boot_logo_path(),
  ) == "BOOT_BG_ALREADY"


def test_install_for_upgrade_never_raises_on_failure(tmp_path):
  ops = RecordingOps(remount_rw_ok=False)
  png = tmp_path / "bg.png"
  png.write_bytes(b"leave-me")
  token = helper.install_for_upgrade(
    png_ops=ops, jpg_ops=ops, png_target=png, jpg_target=tmp_path / "bg.jpg",
    png_source=bl.boot_bg_png_path(), jpg_source=bl.boot_logo_path(),
  )
  assert token == "BOOT_BG_FAILED"
  assert png.read_bytes() == b"leave-me"


def test_install_for_upgrade_swallows_exceptions(monkeypatch, tmp_path):
  def boom(**kwargs):
    raise RuntimeError("unexpected")
  monkeypatch.setattr(bl, "install_boot_bg_png", boom)
  assert helper.install_for_upgrade() == "BOOT_BG_FAILED"


@pytest.mark.skipif(not HELPERS.exists(), reason="release install helpers are kept outside the public tree")
def test_official_install_upgrade_calls_helper_without_aborting():
  text = (HELPERS / "install_upgrade.py").read_text()
  assert "tools/bogpilot/install_boot_bg.py" in text
  assert "'install'" in text or '"install"' in text
  assert "BOOT_BG_INSTALLED" in text and "BOOT_BG_ALREADY" in text and "BOOT_BG_FAILED" in text
  # The helper call must not re-raise into the upgrade rollback handler.
  assert "print('BOOT_BG_FAILED', repr(e), flush=True)" in text
  assert "start_full_launch" in text
  boot_idx = text.index("install_boot_bg.py")
  fail_idx = text.index("print('BOOT_BG_FAILED', repr(e), flush=True)")
  launch_idx = text.index("start_full_launch(", fail_idx)
  rollback_idx = text.index("UPGRADE_FAILED_ROLLING_BACK")
  assert boot_idx < fail_idx < launch_idx < rollback_idx


@pytest.mark.skipif(not HELPERS.exists(), reason="release install helpers are kept outside the public tree")
def test_official_stage_and_verify_check_boot_bg():
  stage = (HELPERS / "stage.py").read_text()
  verify = (HELPERS / "verify.py").read_text()
  assert "install_boot_bg.py" in stage and "stage-check" in stage
  assert "boot_bg_assets" in stage
  assert "boot bg.png hash" in verify
  assert "6bd29b3c41f9da490e38d32f88b6132fd28780a4fffc44ff0ffe3063df47826a" in verify
  assert "install_boot_bg.py" in verify and "status" in verify
  # Both post_install_prereboot and post_reboot use the same script with a label arg;
  # the hash check must not be gated on the label.
  boot_section = verify.split("boot bg.png")[1].split("ps = subprocess")[0]
  assert "post_reboot" not in boot_section and "label.startswith" not in boot_section


def test_startup_hook_still_backstops_and_uninstall_still_restores():
  startup = (Path(bl.__file__).resolve().parents[1] / "manager" / "bogpilot_startup.py").read_text()
  manager = (Path(bl.__file__).resolve().parents[1] / "manager" / "manager.py").read_text()
  assert "install_boot_bg_png" in startup
  assert "restore_stock_boot_bg_png" in manager


def test_status_token_mapping():
  assert helper.status_token("installed") == "BOOT_BG_INSTALLED"
  assert helper.status_token("already-current") == "BOOT_BG_ALREADY"
  assert helper.status_token("failed") == "BOOT_BG_FAILED"
  assert helper.status_token("installed-remount-restore-failed") == "BOOT_BG_FAILED"
  assert helper.status_token("skipped-source-hash-mismatch") == "BOOT_BG_FAILED"
