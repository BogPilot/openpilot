"""Offline map storage under /data/media/0/osm (0.9.7 layout, same paths so existing downloads are reused)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

OSM_ROOT = Path("/data/media/0/osm")
RESERVE_BYTES = 2 * 1024 ** 3        # never let map downloads take the last 2 GiB of the data partition
MB = 1024.0 * 1024.0
GB = 1024.0 * MB


def human_size(total_bytes: float) -> str:
  """0.9.7 calculateDirectorySize format: '0 MB', '12.34 MB', '1.50 GB'."""
  if total_bytes <= 0:
    return "0 MB"
  if total_bytes >= GB:
    return f"{total_bytes / GB:.2f} GB"
  return f"{total_bytes / MB:.2f} MB"


class OsmStorage:
  def __init__(self, root: Path = OSM_ROOT):
    self.root = Path(root)

  @property
  def mapd_path(self) -> Path:
    return self.root / "mapd"

  @property
  def version_path(self) -> Path:
    return self.root / "mapd_version"

  @property
  def offline_dir(self) -> Path:
    return self.root / "offline"

  @property
  def tmp_dir(self) -> Path:
    return self.root / "tmp"

  def _safe_root(self) -> bool:
    """Deletion guard: absolute path whose final component is 'osm' and is not a symlink."""
    return self.root.is_absolute() and self.root.name == "osm" and not self.root.is_symlink()

  def disk_free(self) -> int:
    probe = self.root
    while not probe.exists() and probe != probe.parent:
      probe = probe.parent
    return shutil.disk_usage(probe).free

  def size_bytes(self) -> int:
    total = 0
    if not self.offline_dir.exists():
      return 0
    for dirpath, _dirs, files in os.walk(self.offline_dir, followlinks=False):
      for f in files:
        try:
          total += os.lstat(os.path.join(dirpath, f)).st_size
        except OSError:
          pass
    return total

  def size_text(self) -> str:
    return human_size(self.size_bytes())

  def has_maps(self) -> bool:
    try:
      return self.offline_dir.is_dir() and any(self.offline_dir.iterdir())
    except OSError:
      return False

  def enough_space(self, needed_bytes: int) -> bool:
    return self.disk_free() - int(needed_bytes) >= RESERVE_BYTES

  def remove_maps(self) -> bool:
    """'Remove Maps': delete downloaded tiles and any partial download. Keeps the pinned mapd binary."""
    if not self._safe_root():
      return False
    for d in (self.offline_dir, self.tmp_dir):
      if d.is_symlink():
        d.unlink()
      elif d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return not self.offline_dir.exists()

  def reset(self) -> bool:
    """'Reset Downloader': delete everything under the osm root (tiles, partial downloads, binary, version)."""
    if not self._safe_root():
      return False
    if self.root.exists():
      for child in list(self.root.iterdir()):
        if child.is_symlink() or child.is_file():
          child.unlink()
        else:
          shutil.rmtree(child, ignore_errors=True)
    return not any(self.root.iterdir()) if self.root.exists() else True
