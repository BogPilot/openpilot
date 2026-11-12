"""Install or restore the BogPilot AGNOS boot background.

On AGNOS 19.x, magic.py shows /usr/comma/bg.png before the openpilot UI
starts. /usr/comma/bg.jpg is the older weston splash path and is still
kept in sync for older AGNOS. This is a userspace file write on the
AGNOS root filesystem (system partition remounted read-write only for
the copy), not a splash-partition flash.

Off-device runs, including unit tests, are a no-op. Failures are logged
and never block manager startup. The root filesystem is remounted
read-write only for the copy, then restored to its previous options.

stock_bg.jpg and stock_bg.png are comma's stock AGNOS userspace splashes.
They are used only to restore /usr/comma/bg.jpg and /usr/comma/bg.png on
uninstall and are not BogPilot art. The bootloader splash partition is
not touched.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("boot_logo")

BOOT_LOGO_SHA256 = "9077efdd277bfdd0ca59501fd8a73de3b090b864a8133d27d7a2be12d52892d6"
STOCK_BG_SHA256 = "420c4402fb2a6efa5e4ec3fed5b8fff14e1d22ab43d2393ba7cffb42ff35fa18"
# AGNOS 19.x magic.py shows /usr/comma/bg.png (2160x1080 grayscale) at boot; bg.jpg is only the old weston splash.
BOOT_BG_PNG_SHA256 = "6bd29b3c41f9da490e38d32f88b6132fd28780a4fffc44ff0ffe3063df47826a"
STOCK_BG_PNG_SHA256 = "a00615fa3128a693e44bafce86e651f351174cb20e4efe1dec7d9dafe606eaab"  # AGNOS 19.9 stock bg.png
BG_PNG_TARGET = Path("/usr/comma/bg.png")
DEFAULT_TARGET = Path("/usr/comma/bg.jpg")
ROOT_MOUNT = Path("/")
ASSETS = Path(__file__).resolve().parents[2] / "selfdrive" / "assets" / "images"
BOOT_LOGO_NAME = "bogpilot_boot_logo.png"
STOCK_BG_NAME = "stock_bg.jpg"
BOOT_BG_PNG_NAME = "bogpilot_bg.png"
STOCK_BG_PNG_NAME = "stock_bg.png"


def sha256_file(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1 << 16), b""):
      digest.update(chunk)
  return digest.hexdigest()


def boot_logo_path() -> Path:
  return ASSETS / BOOT_LOGO_NAME


def stock_bg_path() -> Path:
  return ASSETS / STOCK_BG_NAME


def boot_bg_png_path() -> Path:
  return ASSETS / BOOT_BG_PNG_NAME


def stock_bg_png_path() -> Path:
  return ASSETS / STOCK_BG_PNG_NAME


def _has_mount_option(options: str, name: str) -> bool:
  return name in {part.strip() for part in options.split(",") if part.strip()}


def _default_on_device() -> bool:
  # Never write the live AGNOS file from a test run, even if this is a device.
  if "pytest" in sys.modules:
    return False
  if not (DEFAULT_TARGET.is_file() or BG_PNG_TARGET.is_file()):
    return False
  return Path("/AGNOS").is_file()


def _sudo(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
  return subprocess.run(["sudo", *args], check=False, capture_output=True, text=True, timeout=timeout)


def _default_mount_options() -> str | None:
  try:
    result = subprocess.run(
      ["findmnt", "-n", "-o", "OPTIONS", str(ROOT_MOUNT)],
      check=False, capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
      return None
    options = result.stdout.strip()
    return options or None
  except Exception:
    log.exception("failed to read root mount options")
    return None


def _default_remount(options: str) -> bool:
  try:
    result = _sudo(["mount", "-o", f"remount,{options}", str(ROOT_MOUNT)])
    if result.returncode != 0:
      log.error("remount %s failed: %s", options, (result.stderr or result.stdout).strip())
      return False
    return True
  except Exception:
    log.exception("remount %s failed", options)
    return False


def _fsync_path(path: Path) -> None:
  result = _sudo([
    "python3", "-c",
    "import os, sys; fd = os.open(sys.argv[1], os.O_RDONLY); os.fsync(fd); os.close(fd)",
    str(path),
  ])
  if result.returncode != 0:
    # Fall back to a full sync rather than leaving the new image only in the cache.
    _sudo(["sync"])


def _default_copy(source: Path, target: Path) -> None:
  tmp = target.with_name(target.name + ".tmp")
  try:
    result = _sudo(["cp", "--", str(source), str(tmp)])
    if result.returncode != 0:
      raise RuntimeError((result.stderr or result.stdout or "copy failed").strip())
    _sudo(["chmod", "644", str(tmp)])
    _fsync_path(tmp)
    result = _sudo(["mv", "-f", "--", str(tmp), str(target)])
    if result.returncode != 0:
      raise RuntimeError((result.stderr or result.stdout or "replace failed").strip())
    _fsync_path(target)
    _fsync_path(target.parent)
  finally:
    _sudo(["rm", "-f", "--", str(tmp)])


@dataclass
class BootLogoOps:
  mount_options: Callable[[], str | None]
  remount: Callable[[str], bool]
  copy: Callable[[Path, Path], None]
  file_hash: Callable[[Path], str] = sha256_file


def default_ops() -> BootLogoOps:
  return BootLogoOps(mount_options=_default_mount_options, remount=_default_remount, copy=_default_copy)


def _replace(source: Path, expected_sha: str, target: Path, ops: BootLogoOps, success_status: str) -> str:
  if not target.exists():
    return "skipped-absent-target"
  if not source.is_file():
    return "skipped-missing-source"
  try:
    source_sha = ops.file_hash(source)
  except OSError:
    log.exception("failed to hash boot logo source")
    return "failed"
  if source_sha != expected_sha:
    log.error("boot logo source hash mismatch: %s != %s", source_sha, expected_sha)
    return "skipped-source-hash-mismatch"
  try:
    if ops.file_hash(target) == expected_sha:
      return "already-current"
  except OSError:
    log.exception("failed to hash current boot background; will try to replace")

  previous = ops.mount_options()
  if not previous:
    log.error("refusing to replace %s without current root mount options", target)
    return "failed"

  was_readonly = _has_mount_option(previous, "ro")
  remounted = False
  if was_readonly:
    if not ops.remount("rw"):
      return "failed"
    remounted = True

  written = False
  restore_failed = False
  try:
    ops.copy(source, target)
    if ops.file_hash(target) != expected_sha:
      raise RuntimeError("boot background hash mismatch after copy")
    written = True
  except Exception:
    log.exception("failed to write %s", target)
  finally:
    if remounted and not ops.remount(previous):
      restore_failed = True
      log.error("failed to restore root mount options %s; root may still be read-write", previous)

  if restore_failed:
    return f"{success_status}-remount-restore-failed" if written else "failed"
  return success_status if written else "failed"


def install_boot_logo(*, target: Path | None = None, source: Path | None = None,
                      on_device: bool | None = None, ops: BootLogoOps | None = None) -> str:
  try:
    if target is None:
      target = DEFAULT_TARGET
      if on_device is None:
        on_device = _default_on_device()
    elif on_device is None:
      on_device = True
    if not on_device:
      return "skipped-off-device"
    return _replace(source or boot_logo_path(), BOOT_LOGO_SHA256, target, ops or default_ops(), "installed")
  except Exception:
    log.exception("boot logo install failed")
    return "failed"


def restore_stock_boot_logo(*, target: Path | None = None, source: Path | None = None,
                            on_device: bool | None = None, ops: BootLogoOps | None = None) -> str:
  try:
    if target is None:
      target = DEFAULT_TARGET
      if on_device is None:
        on_device = _default_on_device()
    elif on_device is None:
      on_device = True
    if not on_device:
      return "skipped-off-device"
    return _replace(source or stock_bg_path(), STOCK_BG_SHA256, target, ops or default_ops(), "restored")
  except Exception:
    log.exception("stock boot logo restore failed")
    return "failed"


def install_boot_bg_png(*, target: Path | None = None, source: Path | None = None,
                        on_device: bool | None = None, ops: BootLogoOps | None = None) -> str:
  """Same guarded root-remount replace as install_boot_logo, for /usr/comma/bg.png (the file AGNOS 19.x magic.py shows)."""
  try:
    if target is None:
      target = BG_PNG_TARGET
      if on_device is None:
        on_device = _default_on_device()
    elif on_device is None:
      on_device = True
    if not on_device:
      return "skipped-off-device"
    return _replace(source or boot_bg_png_path(), BOOT_BG_PNG_SHA256, target, ops or default_ops(), "installed")
  except Exception:
    log.exception("boot bg.png install failed")
    return "failed"


def restore_stock_boot_bg_png(*, target: Path | None = None, source: Path | None = None,
                              on_device: bool | None = None, ops: BootLogoOps | None = None) -> str:
  try:
    if target is None:
      target = BG_PNG_TARGET
      if on_device is None:
        on_device = _default_on_device()
    elif on_device is None:
      on_device = True
    if not on_device:
      return "skipped-off-device"
    return _replace(source or stock_bg_png_path(), STOCK_BG_PNG_SHA256, target, ops or default_ops(), "restored")
  except Exception:
    log.exception("stock boot bg.png restore failed")
    return "failed"
