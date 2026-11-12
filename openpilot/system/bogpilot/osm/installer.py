"""Pinned, hash-verified mapd binary (replaces the 0.9.7 'download latest mapd' runtime updater).

0.9.7 fetched whatever 'Versions/mapd_version_v2.json' pointed at and ran it. Here the version, size and
sha256 are pinned in mapd_manifest.json; a binary is only ever executed after it matches that sha256.
The fetcher is injected so tests never touch the network.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse

from openpilot.system.bogpilot.osm.storage import OsmStorage

MANIFEST_PATH = Path(__file__).with_name("mapd_manifest.json")
ELF_MAGIC = b"\x7fELF"
EM_AARCH64 = 0xB7
CHUNK = 256 * 1024
ALLOWED_HOSTS = ("github.com",)           # initial URL only; the sha256 pin is the real integrity check


class InstallError(Exception):
  pass


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
  with open(path, encoding="utf-8") as f:
    m = json.load(f)
  for k in ("version", "asset_url", "sha256", "size"):
    if k not in m:
      raise InstallError(f"manifest missing {k}")
  if len(m["sha256"]) != 64 or int(m["size"]) <= 0:
    raise InstallError("manifest sha256/size invalid")
  return m


def sha256_file(path: Path) -> str:
  h = hashlib.sha256()
  with open(path, "rb") as f:
    for chunk in iter(lambda: f.read(CHUNK), b""):
      h.update(chunk)
  return h.hexdigest()


def is_aarch64_elf(head: bytes) -> bool:
  return len(head) >= 20 and head[:4] == ELF_MAGIC and head[4] == 2 and int.from_bytes(head[18:20], "little") == EM_AARCH64


_VERIFY_CACHE: dict = {}


def verify_installed(storage: OsmStorage, manifest: dict, cached: bool = False) -> bool:
  """Full sha256 check. cached=True (manager polling only) re-hashes only when size/mtime/inode changed.

  The supervisor always calls with cached=False right before every exec, so a replaced file is never run.
  """
  p = storage.mapd_path
  try:
    st = p.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size != int(manifest["size"]):
      return False
    if not os.access(p, os.X_OK):
      return False
    key = (str(p), st.st_size, st.st_mtime_ns, st.st_ino, manifest["sha256"])
    if cached and key in _VERIFY_CACHE:
      return _VERIFY_CACHE[key]
    ok = sha256_file(p) == manifest["sha256"]
    _VERIFY_CACHE.clear()
    _VERIFY_CACHE[key] = ok
    return ok
  except OSError:
    return False


def install(storage: OsmStorage, manifest: dict, fetch: Callable[[str], Iterable[bytes]], *, require_arch: bool = True) -> bool:
  """Download into a temp file in the osm dir, verify, then atomically replace. Returns True on success.

  Never leaves a partial/unverified file at storage.mapd_path. Raises InstallError on any mismatch.
  """
  url = manifest["asset_url"]
  u = urlparse(url)
  if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
    raise InstallError(f"refusing url {url}")
  size = int(manifest["size"])
  storage.root.mkdir(parents=True, exist_ok=True)
  fd, tmp_name = tempfile.mkstemp(prefix=".mapd.", dir=storage.root)
  tmp = Path(tmp_name)
  try:
    h = hashlib.sha256()
    n = 0
    head = b""
    with os.fdopen(fd, "wb") as out:
      for chunk in fetch(url):
        n += len(chunk)
        if n > size:
          raise InstallError("download larger than pinned size")
        if len(head) < 20:
          head = (head + chunk)[:64]
        h.update(chunk)
        out.write(chunk)
      out.flush()
      os.fsync(out.fileno())
    if n != size:
      raise InstallError(f"size {n} != pinned {size}")
    if h.hexdigest() != manifest["sha256"]:
      raise InstallError("sha256 mismatch")
    if require_arch and not is_aarch64_elf(head):
      raise InstallError("not an aarch64 ELF")
    os.chmod(tmp, 0o755)
    os.replace(tmp, storage.mapd_path)
    with open(storage.version_path, "w", encoding="utf-8") as f:
      f.write(manifest["version"])
      f.flush()
      os.fsync(f.fileno())
    return True
  finally:
    if tmp.exists():
      try:
        tmp.unlink()
      except OSError:
        pass


def urllib_fetch(url: str, timeout: float = 30.0) -> Iterable[bytes]:
  """Production fetcher (https only, follows GitHub's release redirect). Not used by tests."""
  import urllib.request
  req = urllib.request.Request(url, headers={"User-Agent": "bogpilot-mapd-installer/1"})
  with urllib.request.urlopen(req, timeout=timeout) as resp:
    if urlparse(resp.geturl()).scheme != "https":
      raise InstallError("redirected off https")
    while True:
      chunk = resp.read(CHUNK)
      if not chunk:
        break
      yield chunk
