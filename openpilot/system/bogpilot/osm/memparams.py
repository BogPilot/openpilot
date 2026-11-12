"""Tiny reader/writer for mapd's memory params (/dev/shm/params/d/<Key>), the 0.9.7 v1.x interface.

mapd (Go) reads and writes these files directly with temp-file + rename, so this mirrors that. Keys are limited to
the fixed mapd set; anything else is rejected so a bug cannot write arbitrary files.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

MEM_ROOT = Path("/dev/shm/params/d")
KEYS = frozenset({
  "LastGPSPosition", "MapSpeedLimit", "NextMapSpeedLimit", "MapAdvisoryLimit", "NextMapAdvisoryLimit",
  "RoadName", "OSMDownloadLocations", "OSMDownloadBounds", "OSMDownloadProgress", "MapdLogLevel", "MapdPrettyLog",
  "MapCurvatures", "MapTargetVelocities", "MapHazard", "NextMapHazard",
})


class MemParams:
  def __init__(self, root: Path = MEM_ROOT):
    self.root = Path(root)

  def _path(self, key: str) -> Path:
    if key not in KEYS:
      raise KeyError(key)
    return self.root / key

  def get(self, key: str) -> bytes | None:
    try:
      return self._path(key).read_bytes()
    except FileNotFoundError:
      return None
    except OSError:
      return None

  def get_text(self, key: str) -> str | None:
    b = self.get(key)
    if b is None:
      return None
    try:
      return b.decode("utf-8")
    except UnicodeDecodeError:
      return None

  def age_s(self, key: str, now: float | None = None) -> float | None:
    """Seconds since the param file was last written (None if missing)."""
    try:
      return (time.time() if now is None else now) - self._path(key).stat().st_mtime
    except OSError:
      return None

  def put(self, key: str, value: str | bytes) -> bool:
    p = self._path(key)
    data = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    try:
      self.root.mkdir(parents=True, exist_ok=True)
      fd, tmp = tempfile.mkstemp(prefix=".tmp_value_" + key, dir=self.root)
      with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
      os.replace(tmp, p)
      return True
    except OSError:
      return False

  def remove(self, key: str) -> None:
    try:
      self._path(key).unlink()
    except FileNotFoundError:
      pass
    except OSError:
      pass
