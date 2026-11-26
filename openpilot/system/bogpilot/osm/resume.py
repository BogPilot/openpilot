"""Resumable map downloads: finish a download across connection drops, mapd restarts and stalls.

mapd v1.12.0 (download.go) downloads the 2x2 degree cells of a request one by one, skips a cell whose download fails
("failed to download file, continuing to next"), has no HTTP timeout (a dropped 5G link can hang it), clears
OSMDownloadLocations / OSMDownloadBounds when it starts, and runs the download inside its main loop. So on its own a
download that loses the connection ends with holes, or hangs, and a restart forgets the request.

This module keeps a small job file next to the tiles (`download_job.json`: the selection and per-cell attempts) and, from
the `bogpilot_mapd` supervisor, once a second:
  * mapd busy: watch the progress file; no new cell for STALL_S -> report "stalled" (the supervisor restarts mapd);
  * mapd idle: list the selection's cells that are not on disk (offline/<lat>/<lon>/ has files only after a cell
    downloaded and unpacked) and fetch the next missing one with cell_fetch.py in its own process (the same archive
    URL and layout mapd uses), waiting for the network with a backoff while offline; a cell that keeps failing is given
    up after MAX_CELL_ATTEMPTS (some cells do not exist on the server);
  * free space below SPACE_FLOOR_BYTES: stop cleanly ("no_space"), drop the request, keep what downloaded.
Finished cells are never fetched again, so a resume costs only the missing cells. No region selected -> no job.

Never OSMDownloadBounds: mapd v1.12.0 panics on it (download.go DownloadBounds writes
progress.LocationDetails["CUSTOM"], a map entry DownloadIfTriggered never creates: nil pointer, recovered by loop()),
so the request is never cleared and nothing downloads. Seen with the real binary on the AGNOS VM. mapd v1 also wipes
OSMDownloadLocations when it starts (ResetParams), so a request written just before mapd launched is lost; the job file
and the gap fetch below finish that download anyway. A leftover OSMDownloadBounds is removed on every step.
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
PAUSED_ONROAD = "paused_onroad"       # an automatic update waits while the car is on; a manual download keeps going (paced)


_onroad_reader = None


def default_onroad() -> bool:
  """IsOnroad from the manager through one kept Params reader. Any read problem counts as onroad (an automatic update
  then waits)."""
  global _onroad_reader
  if _onroad_reader is None:
    from openpilot.system.bogpilot.osm.cell_fetch import OnroadReader
    _onroad_reader = OnroadReader()
  return _onroad_reader()


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
  """OSMDownloadBounds JSON (mapd Bounds: min_lat/min_lon/max_lat/max_lon) that adjustedBounds clips to exactly this cell.
  Kept for reference and tests only: the resumer never writes OSMDownloadBounds (mapd v1.12.0 panics on it)."""
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

  def begin(self, sel: regions.Selection, now: float | None = None, auto: bool = False) -> None:
    """auto = started by the "Automatically Update Maps" schedule (it pauses while the car is on), not by a Download press."""
    self.save({"selection": json.loads(sel.to_param()), "attempts": {}, "status": RUNNING, "offline": 0, "next_try": 0.0,
               "requested_at": time.time() if now is None else now, "stalls": 0, "auto": bool(auto)})

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
  def __init__(self, mem: MemParams, storage: OsmStorage, online=default_online, clock=time.time, allowed=None, fetcher=None,
               gap_fetcher=None, onroad=default_onroad):
    self.mem, self.storage, self.jobs = mem, storage, JobStore(storage)
    self._online, self._clock = online, clock
    self._onroad = onroad
    self._allowed = allowed or (lambda: True)   # Speed Limit Controller on (supervisor passes downloads_allowed)
    # fetcher: None = mapd v1 (mapd downloads the OSMDownloadLocations pass). A FetchProcess = mapd v2: every cell out of process.
    self.fetcher = fetcher
    # gap_fetcher: mapd v1 only, a FetchProcess for the cells mapd's pass missed (None = lazily a real FetchProcess)
    self._gap = gap_fetcher

  def gap_fetcher(self):
    if self._gap is None:
      self._gap = FetchProcess(self.storage)
    return self._gap

  def _gap_running(self) -> bool:
    return self._gap is not None and self._gap.running()

  def _stop_gap(self) -> None:
    if self._gap is not None:
      self._gap.stop()

  def _busy(self) -> bool:
    if self.fetcher is not None:
      return self.fetcher.running()
    return bool((self.mem.get_text("OSMDownloadLocations") or "").strip()) or self._gap_running()

  def _drop_request(self) -> None:
    self.mem.remove("OSMDownloadLocations")
    self.mem.remove("OSMDownloadBounds")
    if self.fetcher is not None:
      self.fetcher.stop()
    self._stop_gap()

  def _finish(self, total: int, done: int) -> None:
    """Hand the result to the usual completion path (DownloadController: no job + progress present = done)."""
    self.mem.put("OSMDownloadProgress", json.dumps({"total_files": total, "downloaded_files": done}))
    self.jobs.clear()

  def step(self) -> str:
    now = self._clock()
    job = self.jobs.load()
    self.mem.remove("OSMDownloadBounds")       # never used: mapd v1.12.0 panics on it every loop (see the module doc)
    if self.fetcher is not None:
      # mapd v2 never reads the v1 request params; the job file alone drives the download
      self.mem.remove("OSMDownloadLocations")
      self._stop_gap()                         # switched from v1 mid-download: the v2 fetcher takes over
      if job is None or job.get("status") != RUNNING:
        self.fetcher.stop()                    # cancelled / stopped: end a running fetch too
    elif job is None or job.get("status") != RUNNING:
      self._stop_gap()
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
    if job.get("auto"):
      try:
        onroad = bool(self._onroad())
      except Exception:
        onroad = True
      if onroad:
        # an automatic update never runs while the car is on: stop the fetch, keep the job (the partial archive resumes by
        # HTTP Range), carry on offroad. The schedule only starts one offroad; this covers one still running at drive off.
        self._drop_request()
        return PAUSED_ONROAD
    if self.storage.disk_free() < SPACE_FLOOR_BYTES:
      self._drop_request()
      job["status"] = NO_SPACE
      self.jobs.save(job)
      return NO_SPACE
    if self._busy():
      # stall watch: mapd rewrites the progress param after every finished cell; no change for STALL_S = hung
      fetching = self.fetcher if self.fetcher is not None else (self._gap if self._gap_running() else None)
      text = fetching.token() if fetching is not None else (self.mem.get_text("OSMDownloadProgress") or "")
      watch = job.get("watch")
      if not isinstance(watch, list) or len(watch) != 2 or watch[0] != text:
        job["watch"] = [text, now]
        self.jobs.save(job)
        return "busy"
      if now - float(watch[1]) > (FETCH_STALL_S if fetching is not None else STALL_S):
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
    job["next_try"] = now + 1.0
    self.jobs.save(job)
    (self.fetcher if self.fetcher is not None else self.gap_fetcher()).start(cell)
    return "requested"

  def counts(self, job: dict) -> tuple[int, int]:
    """(cells on disk, cells in the selection) for the Progress row while a job runs."""
    cells = selection_cells(self.jobs.selection(job))
    return sum(1 for c in cells if cell_present(self.storage, c)), len(cells)
