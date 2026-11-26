"""Temp-file tests for the BogPilot boot background install path. No real remount."""
import hashlib
import os
from pathlib import Path

import pytest

from openpilot.system.bogpilot import boot_logo as bl


BOOT = "9077efdd277bfdd0ca59501fd8a73de3b090b864a8133d27d7a2be12d52892d6"
STOCK = "420c4402fb2a6efa5e4ec3fed5b8fff14e1d22ab43d2393ba7cffb42ff35fa18"
BG_PNG = "6bd29b3c41f9da490e38d32f88b6132fd28780a4fffc44ff0ffe3063df47826a"
STOCK_PNG = "a00615fa3128a693e44bafce86e651f351174cb20e4efe1dec7d9dafe606eaab"


class RecordingOps:
  def __init__(self, options="ro,relatime", remount_rw_ok=True, remount_restore_ok=True, copy_error=None):
    self.options = options
    self.remount_rw_ok = remount_rw_ok
    self.remount_restore_ok = remount_restore_ok
    self.copy_error = copy_error
    self.remounts = []
    self.copies = []

  def mount_options(self):
    return self.options

  def remount(self, options):
    self.remounts.append(options)
    if options == "rw":
      if not self.remount_rw_ok:
        return False
      self.options = "rw,relatime"
      return True
    if not self.remount_restore_ok:
      return False
    self.options = options
    return True

  def copy(self, source, target):
    self.copies.append((Path(source), Path(target)))
    if self.copy_error:
      raise self.copy_error
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(Path(source).read_bytes())
    os.replace(tmp, target)

  def file_hash(self, path):
    return bl.sha256_file(Path(path))


@pytest.fixture
def assets():
  logo = bl.boot_logo_path()
  stock = bl.stock_bg_path()
  assert logo.is_file() and stock.is_file()
  return logo, stock


def test_bundled_assets_match_pinned_hashes(assets):
  logo, stock = assets
  assert bl.BOOT_LOGO_SHA256 == BOOT
  assert bl.STOCK_BG_SHA256 == STOCK
  assert bl.sha256_file(logo) == BOOT
  assert bl.sha256_file(stock) == STOCK
  assert hashlib.sha256(logo.read_bytes()).hexdigest() == BOOT
  assert hashlib.sha256(stock.read_bytes()).hexdigest() == STOCK


def test_default_install_is_noop_off_device(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps()
  # Default target is the live AGNOS path; unit tests must not remount or copy it.
  assert bl.install_boot_logo(ops=ops) == "skipped-off-device"
  assert bl.restore_stock_boot_logo(ops=ops) == "skipped-off-device"
  assert bl.install_boot_bg_png(ops=ops) == "skipped-off-device"
  assert bl.restore_stock_boot_bg_png(ops=ops) == "skipped-off-device"
  assert ops.remounts == [] and ops.copies == []
  assert not Path("/usr/comma/bg.jpg").exists() or bl._default_on_device() is False


def test_missing_target_is_noop(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps()
  target = tmp_path / "bg.jpg"
  assert bl.install_boot_logo(target=target, source=logo, ops=ops) == "skipped-absent-target"
  assert ops.remounts == [] and ops.copies == []


def test_already_current_skips_remount_and_copy(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps()
  target = tmp_path / "bg.jpg"
  target.write_bytes(logo.read_bytes())
  assert bl.install_boot_logo(target=target, source=logo, ops=ops) == "already-current"
  assert ops.remounts == [] and ops.copies == []
  assert bl.sha256_file(target) == BOOT


def test_install_writes_boot_image_and_restores_mount(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps()
  target = tmp_path / "bg.jpg"
  target.write_bytes(b"stale-background")
  assert bl.install_boot_logo(target=target, source=logo, ops=ops) == "installed"
  assert ops.remounts == ["rw", "ro,relatime"]
  assert ops.copies == [(logo, target)]
  assert ops.options == "ro,relatime"
  assert bl.sha256_file(target) == BOOT
  assert not target.with_name("bg.jpg.tmp").exists()


def test_restore_writes_stock_hash(tmp_path, assets):
  logo, stock = assets
  ops = RecordingOps()
  target = tmp_path / "bg.jpg"
  target.write_bytes(logo.read_bytes())
  assert bl.restore_stock_boot_logo(target=target, source=stock, ops=ops) == "restored"
  assert ops.remounts == ["rw", "ro,relatime"]
  assert bl.sha256_file(target) == STOCK


def test_source_hash_mismatch_does_not_write(tmp_path, assets):
  _, stock = assets
  ops = RecordingOps()
  target = tmp_path / "bg.jpg"
  original = b"leave-me"
  target.write_bytes(original)
  assert bl.install_boot_logo(target=target, source=stock, ops=ops) == "skipped-source-hash-mismatch"
  assert ops.remounts == [] and ops.copies == []
  assert target.read_bytes() == original


def test_missing_source_does_not_write(tmp_path, assets):
  ops = RecordingOps()
  target = tmp_path / "bg.jpg"
  target.write_bytes(b"leave-me")
  assert bl.install_boot_logo(target=target, source=tmp_path / "missing.png", ops=ops) == "skipped-missing-source"
  assert ops.remounts == [] and target.read_bytes() == b"leave-me"


def test_remount_rw_failure_does_not_write(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps(remount_rw_ok=False)
  target = tmp_path / "bg.jpg"
  original = b"leave-me"
  target.write_bytes(original)
  assert bl.install_boot_logo(target=target, source=logo, ops=ops) == "failed"
  assert ops.remounts == ["rw"]
  assert ops.copies == []
  assert target.read_bytes() == original


def test_copy_failure_remounts_back_and_does_not_raise(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps(copy_error=RuntimeError("disk full"))
  target = tmp_path / "bg.jpg"
  original = b"leave-me"
  target.write_bytes(original)
  assert bl.install_boot_logo(target=target, source=logo, ops=ops) == "failed"
  assert ops.remounts == ["rw", "ro,relatime"]
  assert ops.options == "ro,relatime"
  assert target.read_bytes() == original


def test_restore_mount_failure_after_write_is_reported(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps(remount_restore_ok=False)
  target = tmp_path / "bg.jpg"
  target.write_bytes(b"stale-background")
  assert bl.install_boot_logo(target=target, source=logo, ops=ops) == "installed-remount-restore-failed"
  assert ops.remounts == ["rw", "ro,relatime"]
  assert bl.sha256_file(target) == BOOT


def test_already_readwrite_does_not_remount(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps(options="rw,relatime")
  target = tmp_path / "bg.jpg"
  target.write_bytes(b"stale-background")
  assert bl.install_boot_logo(target=target, source=logo, ops=ops) == "installed"
  assert ops.remounts == []
  assert bl.sha256_file(target) == BOOT


def test_missing_mount_options_does_not_write(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps()
  ops.mount_options = lambda: None
  target = tmp_path / "bg.jpg"
  original = b"leave-me"
  target.write_bytes(original)
  assert bl.install_boot_logo(target=target, source=logo, ops=ops) == "failed"
  assert ops.remounts == [] and target.read_bytes() == original


def test_explicit_off_device_flag_is_noop(tmp_path, assets):
  logo, _ = assets
  ops = RecordingOps()
  target = tmp_path / "bg.jpg"
  target.write_bytes(b"stale")
  assert bl.install_boot_logo(target=target, source=logo, on_device=False, ops=ops) == "skipped-off-device"
  assert ops.remounts == [] and target.read_bytes() == b"stale"



def test_bg_png_assets_packaged_and_referenced():
  png = bl.boot_bg_png_path()
  stock = bl.stock_bg_png_path()
  assert png.is_file() and stock.is_file()
  assert bl.BOOT_BG_PNG_SHA256 == BG_PNG
  assert bl.STOCK_BG_PNG_SHA256 == STOCK_PNG
  assert bl.sha256_file(png) == BG_PNG
  assert bl.sha256_file(stock) == STOCK_PNG
  manager_dir = Path(bl.__file__).resolve().parents[1] / "manager"
  startup = (manager_dir / "bogpilot_startup.py").read_text()
  manager = (manager_dir / "manager.py").read_text()
  assert "install_boot_bg_png" in startup and "boot-bg-png:" in startup
  assert "restore_stock_boot_bg_png" in manager


def test_install_and_restore_bg_png_roundtrip(tmp_path):
  ops = RecordingOps()
  target = tmp_path / "bg.png"
  source = bl.boot_bg_png_path()
  stock = bl.stock_bg_png_path()
  target.write_bytes(stock.read_bytes())
  assert bl.install_boot_bg_png(target=target, source=source, ops=ops) == "installed"
  assert ops.remounts == ["rw", "ro,relatime"] and bl.sha256_file(target) == BG_PNG
  assert bl.install_boot_bg_png(target=target, source=source, ops=ops) == "already-current"
  assert bl.restore_stock_boot_bg_png(target=target, source=stock, ops=ops) == "restored"
  assert bl.sha256_file(target) == STOCK_PNG and ops.options == "ro,relatime"
