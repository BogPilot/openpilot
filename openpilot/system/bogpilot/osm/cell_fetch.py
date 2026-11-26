"""Out-of-process map cell fetcher for mapd v2 ("Use mapd v2" on).

With mapd v2 BogPilot downloads the map archives itself, in this small low-priority process, instead of asking mapd.
mapd keeps running the whole time (no restart, no request through its loop), so speed limits stay live while maps
download. mapd v2 retries loading the tile for its position once a second while none is loaded, so a cell published
here is picked up without telling mapd anything.

Same host, archive names and on-disk layout as mapd v2.4.0 (settings/download.go):
  https://map-data.pfeifer.dev/offline/<lat>/<lon>.tar.gz -> <osm root>/tmp/offline/<lat>/<lon>.tar.gz -> extracted under <osm root>
and the same safety rules: the archive is read end to end (gzip CRC and length trailer included) BEFORE any live tile
is touched and entries may not escape the osm root. Added here: an HTTP timeout, Range resume of a partial archive
(the host sends accept-ranges: bytes), a size cap, entries limited to regular files and directories inside the
requested cell (offline/<lat>/<lon>/, the only thing the host's archives contain), and a whole-cell swap: the cell is
unpacked (each file fsynced) into tmp/stage/ and its directory renamed into place, so neither mapd nor the resumer
(resume.cell_present) can ever see a half-unpacked cell, even after a power cut.

While the car is on (IsOnroad, re-read once a second, so a download that started at home slows down on the road) a Pacer
caps the download at 5 Mbit/s, spaces the unpack to at most 10 file fsyncs a second, and runs this process at nice 19 on
the non driving cores (priority.MAP_CORES). Offroad it runs at full speed.

usage: python -m openpilot.system.bogpilot.osm.cell_fetch <lat> <lon> [--root /data/media/0/osm]
exit 0 = cell on disk, 1 = failed (the resumer counts the attempt and retries later), 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import tarfile
import time
import zlib
from pathlib import Path
from typing import Callable

from openpilot.system.bogpilot.osm import priority
from openpilot.system.bogpilot.osm.storage import OSM_ROOT

HOST = "https://map-data.pfeifer.dev/"
TIMEOUT_S = 30.0                       # per socket operation; a dead link fails the attempt instead of hanging it
MAX_ARCHIVE_BYTES = 512 * 1024 ** 2    # the largest cells seen are ~55 MB
MAX_EXTRACT_BYTES = 2 * 1024 ** 3
CHUNK = 256 * 1024


class FetchError(Exception):
  pass


class OnroadReader:
  """IsOnroad from the manager through one Params reader, made on first use and kept, so each check is one file read
  (about 4 us) instead of a new Params object (about 21 us). Any read problem counts as onroad (the slow, safe side) and
  the next check starts again with a new reader."""

  def __init__(self, make=None):
    self._make = make
    self._params = None
    self.made = 0

  def __call__(self) -> bool:
    try:
      if self._params is None:
        make = self._make
        if make is None:
          from openpilot.common.params import Params
          make = Params
        self._params = make()
        self.made += 1
      return bool(self._params.get_bool("IsOnroad"))
    except Exception:
      self._params = None
      return True


default_onroad = OnroadReader()


class Pacer:
  """Onroad pacing for one fetch. Offroad every call returns at once."""
  CHECK_S = 1.0     # how often IsOnroad is re-read
  BURST_S = 0.5     # the rate cap allows this much data ahead of the clock (about 300 kB at 5 Mbit/s)

  def __init__(self, onroad=default_onroad, clock=time.monotonic, sleep=time.sleep, place=priority.place_self,
               rate_bytes_s: float = priority.ONROAD_RATE_BYTES_S, fsync_hz: float = priority.ONROAD_MAX_FSYNC_HZ):
    self._onroad_fn, self._clock, self._sleep, self._place = onroad, clock, sleep, place
    self.rate, self.fsync_gap = float(rate_bytes_s), 1.0 / float(fsync_hz)
    self._state = None
    self._next_check = -float("inf")
    self._free_at = -float("inf")       # token bucket: when the bytes sent so far are paid for
    self._last_fsync = -float("inf")
    self.slept = 0.0

  def onroad(self) -> bool:
    now = self._clock()
    if now >= self._next_check:
      self._next_check = now + self.CHECK_S
      try:
        on = bool(self._onroad_fn())
      except Exception:
        on = True
      if on != self._state:
        self._state = on
        self._free_at = now
        try:
          self._place(on)
        except Exception:
          pass
    return bool(self._state)

  def _wait(self, dt: float) -> None:
    if dt > 0:
      self.slept += dt
      self._sleep(dt)

  def on_bytes(self, n: int) -> None:
    if not self.onroad():
      return
    now = self._clock()
    self._free_at = max(self._free_at, now) + n / self.rate
    self._wait(self._free_at - now - self.BURST_S)

  def before_fsync(self) -> None:
    if not self.onroad():
      return
    now = self._clock()
    self._wait(self._last_fsync + self.fsync_gap - now)
    self._last_fsync = max(now, self._last_fsync + self.fsync_gap)


def archive_name(lat: int, lon: int) -> str:
  return f"offline/{int(lat)}/{int(lon)}.tar.gz"


def archive_url(lat: int, lon: int) -> str:
  return HOST + archive_name(lat, lon)


def part_path(root: Path, lat: int, lon: int) -> Path:
  return Path(root) / "tmp" / (archive_name(lat, lon) + ".part")


def http_get(url: str, offset: int, timeout: float = TIMEOUT_S):
  """Returns (status, total_size or None, chunk iterator). Production only; tests inject their own."""
  import urllib.request
  req = urllib.request.Request(url, headers={"User-Agent": "bogpilot-map-fetch/1", **({"Range": f"bytes={offset}-"} if offset else {})})
  import urllib.error
  try:
    resp = urllib.request.urlopen(req, timeout=timeout)
  except urllib.error.HTTPError as e:
    if e.code == 416:
      return 416, None, iter(())                 # the partial archive is already complete
    raise FetchError(f"http status {e.code}") from e
  status = resp.status
  total = None
  if status == 206:
    cr = resp.headers.get("Content-Range", "")
    try:
      total = int(cr.rsplit("/", 1)[1])
    except (IndexError, ValueError):
      total = None
  else:
    cl = resp.headers.get("Content-Length")
    total = int(cl) if cl and cl.isdigit() else None

  def chunks():
    with resp:
      while True:
        b = resp.read(CHUNK)
        if not b:
          return
        yield b
  return status, total, chunks()


def download(root: Path, lat: int, lon: int, get: Callable = http_get, pacer: Pacer | None = None) -> Path:
  """Fetch (or resume) the archive into tmp/...tar.gz.part. Returns the complete .part path."""
  part = part_path(root, lat, lon)
  part.parent.mkdir(parents=True, exist_ok=True)
  offset = part.stat().st_size if part.exists() else 0
  status, total, chunks = get(archive_url(lat, lon), offset)
  if status == 200:
    offset = 0                                   # server ignored the Range: start over
    mode = "wb"
  elif status == 206 and offset > 0:
    mode = "ab"
  elif status == 416 and offset > 0 and total is None:
    mode = None                                  # already complete (the validator decides)
  else:
    raise FetchError(f"http status {status}")
  if total is not None and total > MAX_ARCHIVE_BYTES:
    raise FetchError("archive larger than the cap")
  if mode is not None:
    n = offset
    with open(part, mode) as f:
      for b in chunks:
        n += len(b)
        if n > MAX_ARCHIVE_BYTES:
          raise FetchError("archive larger than the cap")
        f.write(b)
        if pacer is not None:
          pacer.on_bytes(len(b))
      f.flush()
      os.fsync(f.fileno())
    if total is not None and n != total:
      raise FetchError(f"short download {n} != {total}")   # keep the .part: the next attempt resumes it
  return part


def validate(archive: Path) -> int:
  """Read the whole gzip+tar stream (CRC + length trailer included). Returns the entry count; raises on any damage."""
  entries = 0
  try:
    with gzip.open(archive, "rb") as gz:
      with tarfile.open(fileobj=gz, mode="r|") as tf:
        for m in tf:
          if m.isfile():
            f = tf.extractfile(m)
            while f is not None and f.read(CHUNK):
              pass
          entries += 1
      while gz.read(CHUNK):                       # drain to the gzip trailer (tar EOF comes before it)
        pass
  except (OSError, EOFError, tarfile.TarError, zlib.error) as e:
    raise FetchError(f"archive is corrupt or truncated: {e}") from e
  if entries == 0:
    raise FetchError("archive contains no files")
  return entries


def safe_target(root: Path, name: str, lat: int | None = None, lon: int | None = None) -> Path | None:
  """Path for an archive entry under root. Raises on anything outside offline/ (or, with lat/lon, outside that cell).
  None = one of the cell's parent directories (offline, offline/<lat>), nothing to write."""
  if name.startswith("/") or "\\" in name:
    raise FetchError(f"bad entry name {name!r}")
  rel = os.path.normpath(name)
  if rel.startswith("..") or os.path.isabs(rel) or not (rel == "offline" or rel.startswith("offline" + os.sep)):
    raise FetchError(f"entry outside offline/: {name!r}")
  if lat is not None:
    cell = os.path.join("offline", str(int(lat)), str(int(lon)))
    if rel in ("offline", os.path.join("offline", str(int(lat)))):
      return None
    if not (rel == cell or rel.startswith(cell + os.sep)):
      raise FetchError(f"entry outside cell {lat},{lon}: {name!r}")
  return Path(root) / rel


def _fsync_dir(d: Path) -> None:
  try:
    fd = os.open(d, os.O_RDONLY)
    try:
      os.fsync(fd)
    finally:
      os.close(fd)
  except OSError:
    pass


def extract(root: Path, archive: Path, lat: int, lon: int, pacer: Pacer | None = None) -> int:
  """Unpack a VALIDATED archive into tmp/stage/, then swap the whole cell directory into place. Returns files written."""
  root = Path(root)
  stage = root / "tmp" / "stage"
  cell_rel = Path("offline") / str(int(lat)) / str(int(lon))
  shutil.rmtree(stage, ignore_errors=True)
  written, total = 0, 0
  try:
    (stage / cell_rel).mkdir(parents=True, exist_ok=True)
    with gzip.open(archive, "rb") as gz, tarfile.open(fileobj=gz, mode="r|") as tf:
      for m in tf:
        target = safe_target(stage, m.name, lat, lon)
        if target is None:
          continue
        if m.isdir():
          target.mkdir(parents=True, exist_ok=True)
        elif m.isfile():
          total += m.size
          if total > MAX_EXTRACT_BYTES:
            raise FetchError("archive expands past the cap")
          target.parent.mkdir(parents=True, exist_ok=True)
          with open(target, "wb") as out:
            shutil.copyfileobj(tf.extractfile(m), out, CHUNK)
            out.flush()
            if pacer is not None:
              pacer.before_fsync()
            os.fsync(out.fileno())
          written += 1
        else:
          raise FetchError(f"unsupported entry type for {m.name!r}")   # no links, devices or fifos
    if written == 0:
      raise FetchError("archive has no files for the cell")
    _fsync_dir(stage / cell_rel)
    live = root / cell_rel
    live.parent.mkdir(parents=True, exist_ok=True)
    old = root / "tmp" / f"old_{int(lat)}_{int(lon)}"
    shutil.rmtree(old, ignore_errors=True)
    if live.exists():
      os.replace(live, old)                        # an updated cell: mapd re-reads within a second
    os.replace(stage / cell_rel, live)
    _fsync_dir(live.parent)
    shutil.rmtree(old, ignore_errors=True)
  finally:
    shutil.rmtree(stage, ignore_errors=True)
  return written


def fetch_cell(root: Path, lat: int, lon: int, get: Callable = http_get, pacer: Pacer | None = None) -> int:
  part = download(root, lat, lon, get, pacer)
  try:
    validate(part)
  except FetchError:
    part.unlink(missing_ok=True)                 # a complete but damaged archive is never resumed
    raise
  n = extract(root, part, lat, lon, pacer)
  part.unlink(missing_ok=True)
  return n


def main(argv=None) -> int:  # pragma: no cover - process entry
  ap = argparse.ArgumentParser()
  ap.add_argument("lat", type=int)
  ap.add_argument("lon", type=int)
  ap.add_argument("--root", type=Path, default=OSM_ROOT)
  try:
    a = ap.parse_args(argv)
  except SystemExit:
    return 2
  try:
    fetch_cell(a.root, a.lat, a.lon, pacer=Pacer())
    return 0
  except Exception as e:
    print(f"cell_fetch {a.lat},{a.lon}: {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
  sys.exit(main())
