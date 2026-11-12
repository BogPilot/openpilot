#!/usr/bin/env python3
"""Official BogPilot installer entry for the AGNOS userspace boot screen.

Copies the packaged lily-pad image over /usr/comma/bg.png (what AGNOS 19.x
magic.py shows) and keeps /usr/comma/bg.jpg in sync for older AGNOS. Uses
the same guarded remount / atomic replace / fsync / hash-verify path as
openpilot.system.bogpilot.boot_logo.install_boot_bg_png. The bootloader
splash partition is never touched.

Commands:
  install            write bg.png + bg.jpg on the device; always exit 0;
                     print BOOT_BG_INSTALLED, BOOT_BG_ALREADY, or BOOT_BG_FAILED
  stage-check TREE   verify the packaged assets in a staged or packaged tree
  status             read-only check of the live /usr/comma/bg.png hash

The manager after_defaults hook remains a backstop. Uninstall restores
stock via restore_stock_boot_bg_png / restore_stock_boot_logo.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from openpilot.system.bogpilot import boot_logo as bl

ASSETS_REL = Path("openpilot/selfdrive/assets/images")
PACKAGED_ASSETS = (
  ("bogpilot_bg.png", bl.BOOT_BG_PNG_SHA256),
  ("stock_bg.png", bl.STOCK_BG_PNG_SHA256),
  ("bogpilot_boot_logo.png", bl.BOOT_LOGO_SHA256),
  ("stock_bg.jpg", bl.STOCK_BG_SHA256),
)


def sha256_file(path: Path) -> str:
  return bl.sha256_file(path)


def stage_check(tree: Path) -> list[str]:
  """Return a list of error strings; empty means the packaged assets are present and pinned."""
  errors: list[str] = []
  root = Path(tree)
  for name, expected in PACKAGED_ASSETS:
    path = root / ASSETS_REL / name
    if not path.is_file():
      errors.append(f"missing {ASSETS_REL / name}")
      continue
    got = sha256_file(path)
    if got != expected:
      errors.append(f"hash mismatch {ASSETS_REL / name}: {got} != {expected}")
  helper = root / "tools/bogpilot/install_boot_bg.py"
  if not helper.is_file():
    errors.append("missing tools/bogpilot/install_boot_bg.py")
  return errors


def live_bg_png_sha() -> str | None:
  target = bl.BG_PNG_TARGET
  if not target.is_file():
    return None
  return sha256_file(target)


def status_token(result: str) -> str:
  if result == "installed":
    return "BOOT_BG_INSTALLED"
  if result == "already-current":
    return "BOOT_BG_ALREADY"
  return "BOOT_BG_FAILED"


def install_for_upgrade(*, png_ops=None, jpg_ops=None, png_target=None, jpg_target=None,
                        png_source=None, jpg_source=None, on_device=None) -> str:
  """Install bg.png and bg.jpg. Never raises. Returns the bg.png BOOT_BG_* token."""
  try:
    png = bl.install_boot_bg_png(target=png_target, source=png_source, on_device=on_device, ops=png_ops)
    jpg = bl.install_boot_logo(target=jpg_target, source=jpg_source, on_device=on_device, ops=jpg_ops if jpg_ops is not None else png_ops)
  except Exception as exc:
    print(f"BOOT_BG_FAILED {type(exc).__name__}: {exc}", flush=True)
    return "BOOT_BG_FAILED"
  token = status_token(png)
  print(f"{token} bg.png={png}", flush=True)
  print(f"BOOT_BG_JPG_{status_token(jpg).removeprefix('BOOT_BG_')} bg.jpg={jpg}", flush=True)
  return token


def cmd_stage_check(tree: Path) -> int:
  errors = stage_check(tree)
  if errors:
    for item in errors:
      print(f"BOOT_BG_STAGE_FAIL {item}", flush=True)
    return 2
  print("BOOT_BG_STAGE_OK", flush=True)
  return 0


def cmd_status() -> int:
  expected = bl.BOOT_BG_PNG_SHA256
  got = live_bg_png_sha()
  if got is None:
    print(f"BOOT_BG_MISMATCH MISSING expected {expected}", flush=True)
    return 2
  if got != expected:
    print(f"BOOT_BG_MISMATCH {got} expected {expected}", flush=True)
    return 2
  print(f"BOOT_BG_OK {got}", flush=True)
  return 0


def cmd_install() -> int:
  install_for_upgrade()
  return 0


def main(argv: list[str] | None = None) -> int:
  args = list(sys.argv[1:] if argv is None else argv)
  if not args or args[0] in ("-h", "--help"):
    print("usage: install_boot_bg.py install|stage-check TREE|status", flush=True)
    return 2
  cmd = args[0]
  if cmd == "install":
    return cmd_install()
  if cmd == "stage-check":
    if len(args) < 2:
      print("usage: install_boot_bg.py stage-check TREE", flush=True)
      return 2
    return cmd_stage_check(Path(args[1]))
  if cmd == "status":
    return cmd_status()
  print(f"unknown command: {cmd}", flush=True)
  return 2


if __name__ == "__main__":
  sys.exit(main())
