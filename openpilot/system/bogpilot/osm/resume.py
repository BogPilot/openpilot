"""Resumable map downloads: finish a download across connection drops, mapd restarts and stalls.

mapd v1.12.0 (download.go) downloads the 2x2 degree cells of a request one by one, skips a cell whose download fails
("failed to download file, continuing to next"), has no HTTP timeout (a dropped 5G link can hang it), clears
OSMDownloadLocations / OSMDownloadBounds when it starts, and runs the download inside its main loop. So on its own a
download that loses the connection ends with holes, or hangs, and a restart forgets the request.

This module keeps a small job file next to the tiles (`download_job.json`: the selection and per-cell attempts) and, from
the `bogpilot_mapd` supervisor, once a second:
  * mapd busy: watch the progress file; no new cell for STALL_S -> report "stalled" (the supervisor restarts mapd);
  * mapd idle: list the selection's cells that are not on disk (offline/<lat>/<lon>/ has files only after a cell
    downloaded and unpacked) and ask mapd for the next missing one through OSMDownloadBounds (exactly one cell), waiting
    for the network with a backoff while offline; a cell that keeps failing is given up after MAX_CELL_ATTEMPTS
    (some cells do not exist on the server);
  * free space below SPACE_FLOOR_BYTES: stop cleanly ("no_space"), drop the request, keep what downloaded.
Finished cells are never fetched again, so a resume costs only the missing cells. No region selected -> no job.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time

from openpilot.system.bogpilot.osm import regions
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import RESERVE_BYTES, OsmStorage

JOB_FILE = "download_job.json"
FETCH_STALL_S = 120.0                 # mapd v2 mode: no new archive byte for 2 min = hung fetch (cell_fetch also has a 30 s socket timeout)
STALL_S = 900.0                       # 15 min without a finished cell while mapd says it downloads (a 100 MB cell on ~1 Mbit/s)
RETRY_BACKOFF_S = (30.0, 60.0, 120.0, 300.0)
MAX_CELL_ATTEMPTS = 6
SPACE_FLOOR_BYTES = RESERVE_BYTES     # stop when /data has less than 2 GiB free (the same floor a download needs to start)
TILE_HOST = ("map-data.pfeifer.dev", 443)
RUNNING, NO_SPACE = "running", "no_space"


def default_online() -> bool:
  try:
    with socket.create_connection(TILE_HOST, timeout=3.0):
      return True
  except OSError:
    return False


def cell_key(cell) -> str:
  return f"{cell[0]},{cell[1]}"


def cell_present(storage: OsmStorage, cell) -> bool:
  d = storage.offline_dir / str(cell[0]) / str(cell[1])
  try:
    return d.is_dir() and any(d.iterdir())
  except OSError:
    return False


def selection_cells(sel: regions.Selection) -> list[tuple[int, int]]:
  cells = set()
  for r in regions.resolve(sel):
    cells.update(regions.cells_for_region(r))
  return sorted(cells)


def missing_cells(storage: OsmStorage, sel: regions.Selection) -> list[tuple[int, int]]:
  return [c for c in selection_cells(sel) if not cell_present(storage, c)]


def cell_bounds(cell) -> str:
  """OSMDownloadBounds JSON (mapd Bounds: min_lat/min_lon/max_lat/max_lon) that adjustedBounds clips to exactly this cell."""
  lat, lon = cell
  g = regions.GROUP_AREA_BOX_DEGREES
  return json.dumps({"min_lat": lat + 0.25, "min_lon": lon + 0.25, "max_lat": lat + g - 0.25, "max_lon": lon + g - 0.25})


def backoff(n: int) -> float:
  return RETRY_BACKOFF_S[min(max(n, 0), len(RETRY_BACKOFF_S) - 1)]


class JobStore:
  """The job file under the osm root (atomic writes). Unreadable -> no job."""

  def __init__(self, storage: OsmStorage):
    self.path = storage.root / JOB_FILE

  def load(self) -> dict | None:
    try:
      job = json.loads(self.path.read_text())
      return job if isinstance(job, dict) else None
    except (OSError, ValueError):
      return None

  def save(self, job: dict) -> None:
    try:
      self.path.parent.mkdir(parents=True, exist_ok=True)
      fd, tmp = tempfile.mkstemp(prefix=".tmp_job", dir=self.path.parent)
      with os.fdopen(fd, "w") as f:
        json.dump(job, f)
      os.replace(tmp, self.path)
    except OSError:
      pass

  def clear(self) -> None:
    try:
      self.path.unlink()
    except OSError:
      pass

  def begin(self, sel: regions.Selection, now: float | None = None) -> None:
    self.save({"selection": json.loads(sel.to_param()), "attempts": {}, "status": RUNNING, "offline": 0, "next_try": 0.0,
               "requested_at": time.time() if now is None else now, "stalls": 0})

  @staticmethod
  def selection(job: dict) -> regions.Selection:
    return regions.parse_selection(json.dumps(job.get("selection") or {}))


class FetchProcess:
  """mapd v2 mode: one cell_fetch.py child at a time (low priority via preexec), never mapd itself."""

  def __init__(self, storage: OsmStorage, popen=subprocess.Popen, preexec=None, python: str = sys.executable):
    self.storage, self._popen, self._preexec, self._python = storage, popen, preexec, python
    self.proc = None
    self.cell = None

  def start(self, cell) -> bool:
    self.stop()
    kw = {"preexec_fn": self._preexec} if self._preexec is not None else {}
    try:
      self.proc = self._popen([self._python, "-m", "openpilot.system.bogpilot.osm.cell_fetch", str(int(cell[0])), str(int(cell[1])),
                               "--root", str(self.storage.root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
      self.cell = cell
      return True
    except Exception:
      self.proc, self.cell = None, None
      return False

  def running(self) -> bool:
    try:
      return self.proc is not None and self.proc.poll() is None
    except Exception:
      return False

  def stop(self) -> None:
    p, self.proc = self.proc, None
    if p is None:
      return
    try:
      if p.poll() is None:
        p.terminate()
        try:
          p.wait(timeout=5)
        except Exception:
          p.kill()
    except Exception:
      pass

  def token(self) -> str:
    """Bytes of the partial archive so far: the stall watch's progress signal."""
    if self.cell is None:
      return ""
    from openpilot.system.bogpilot.osm.cell_fetch import part_path
    try:
      return f"{self.cell[0]},{self.cell[1]}:{part_path(self.storage.root, *self.cell).stat().st_size}"
    except OSError:
      return f"{self.cell[0]},{self.cell[1]}:-"


class Resumer:
  def __init__(self, mem: MemParams, storage: OsmStorage, online=default_online, clock=time.time, allowed=None, fetcher=None):
    self.mem, self.storage, self.jobs = mem, storage, JobStore(storage)
    self._online, self._clock = online, clock
    self._allowed = allowed or (lambda: True)   # Speed Limit Controller on (supervisor passes downloads_allowed)
    # None = mapd v1 asks mapd for cells (OSMDownloadBounds). A FetchProcess = mapd v2: cells are fetched out of process.
    self.fetcher = fetcher

  def _busy(self) -> bool:
    if self.fetcher is not None:
      return self.fetcher.running()
    return bool((self.mem.get_text("OSMDownloadLocations") or "").strip() or (self.mem.get_text("OSMDownloadBounds") or "").strip())

  def _drop_request(self) -> None:
    self.mem.remove("OSMDownloadLocations")
    self.mem.remove("OSMDownloadBounds")
    if self.fetcher is not None:
      self.fetcher.stop()

  def _finish(self, total: int, done: int) -> None:
    """Hand the result to the usual completion path (DownloadController: no job + progress present = done)."""
    self.mem.put("OSMDownloadProgress", json.dumps({"total_files": total, "downloaded_files": done}))
    self.jobs.clear()

  def step(self) -> str:
    now = self._clock()
    job = self.jobs.load()
    if self.fetcher is not None:
      # mapd v2 never reads the v1 request params; the job file alone drives the download
      self.mem.remove("OSMDownloadLocations")
      self.mem.remove("OSMDownloadBounds")
      if job is None or job.get("status") != RUNNING:
        self.fetcher.stop()                    # cancelled / stopped: end a running fetch too
    if job is None:
      return "idle"
    if job.get("status") != RUNNING:
      return str(job.get("status"))
    sel = self.jobs.selection(job)
    if sel.is_empty():
      self.jobs.clear()
      return "idle"
    if not self._allowed():
      # downloads need the Speed Limit Controller on: ask mapd for nothing, keep the job so the
      # download carries on where it stopped once the SLC is back on
      self._drop_request()
      return "slc_off"
    if self.storage.disk_free() < SPACE_FLOOR_BYTES:
      self._drop_request()
      job["status"] = NO_SPACE
      self.jobs.save(job)
      return NO_SPACE
    if self._busy():
      # stall watch: mapd rewrites the progress param after every finished cell; no change for STALL_S = hung
      text = self.fetcher.token() if self.fetcher is not None else (self.mem.get_text("OSMDownloadProgress") or "")
      watch = job.get("watch")
      if not isinstance(watch, list) or len(watch) != 2 or watch[0] != text:
        job["watch"] = [text, now]
        self.jobs.save(job)
        return "busy"
      if now - float(watch[1]) > (FETCH_STALL_S if self.fetcher is not None else STALL_S):
        self._drop_request()
        job["stalls"] = int(job.get("stalls", 0)) + 1
        job["watch"] = None
        self.jobs.save(job)
        return "stalled"
      return "busy"
    cells = selection_cells(sel)
    missing = [c for c in cells if not cell_present(self.storage, c)]
    if not missing:
      self._finish(len(cells), len(cells))
      return "complete"
    attempts = job.setdefault("attempts", {})
    todo = [c for c in missing if int(attempts.get(cell_key(c), 0)) < MAX_CELL_ATTEMPTS]
    if not todo:
      self._finish(len(cells), len(cells) - len(missing))
      return "gave_up"
    if now < float(job.get("next_try", 0.0)):
      return "waiting"
    if not self._online():
      job["next_try"] = now + backoff(int(job.get("offline", 0)))
      job["offline"] = int(job.get("offline", 0)) + 1
      self.jobs.save(job)
      return "offline"
    cell = todo[0]
    attempts[cell_key(cell)] = int(attempts.get(cell_key(cell), 0)) + 1
    job["offline"], job["requested_at"], job["watch"] = 0, now, None
    if self.fetcher is not None:
      job["next_try"] = now + 1.0
      self.jobs.save(job)
      self.fetcher.start(cell)
      return "requested"
    job["next_try"] = now + 5.0          # let mapd pick the request up (it polls once a second) before looking again
    self.jobs.save(job)
    self.mem.put("OSMDownloadBounds", cell_bounds(cell))
    return "requested"

  def counts(self, job: dict) -> tuple[int, int]:
    """(cells on disk, cells in the selection) for the Progress row while a job runs."""
    cells = selection_cells(self.jobs.selection(job))
    return sum(1 for c in cells if cell_present(self.storage, c)), len(cells)
