"""Resumable map downloads (resume.py): connection drops, stalls, mapd restarts, the free-space floor. No network, no mapd."""
import json

import pytest

from openpilot.system.bogpilot.osm import regions as R
from openpilot.system.bogpilot.osm import resume as RS
from openpilot.system.bogpilot.osm.downloads import DownloadController
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage

SEL = R.Selection((), ("RI",))       # a small state: few cells


class Rig:
  def __init__(self, tmp_path, free=50 * 1024 ** 3):
    self.mem = MemParams(tmp_path / "d")
    self.storage = OsmStorage(tmp_path / "osm")
    self.free = free
    self.storage.disk_free = lambda: self.free
    self.t = 1000.0
    self.online = True
    self.dl = DownloadController(self.mem, self.storage)
    self.r = RS.Resumer(self.mem, self.storage, online=lambda: self.online, clock=lambda: self.t)
    self.cells = RS.selection_cells(SEL)

  def put_cell(self, cell):
    d = self.storage.offline_dir / str(cell[0]) / str(cell[1])
    d.mkdir(parents=True, exist_ok=True)
    (d / "tile").write_bytes(b"x")

  def mapd_finishes_pass(self, cells_done):
    for c in cells_done:
      self.put_cell(c)
    self.mem.put("OSMDownloadLocations", "")
    self.mem.put("OSMDownloadBounds", "")


@pytest.fixture
def rig(tmp_path):
  return Rig(tmp_path)


def test_cell_bounds_clip_to_exactly_one_mapd_cell():
  from types import SimpleNamespace
  for cell in [(40, -72), (-34, 150), (0, 0), (-2, -2)]:
    b = json.loads(RS.cell_bounds(cell))
    box = SimpleNamespace(min_lat=b["min_lat"], min_lon=b["min_lon"], max_lat=b["max_lat"], max_lon=b["max_lon"])
    assert R.cells_for_region(box) == [cell]            # mapd download.go adjustedBounds (ported in regions.py)


def test_no_job_is_idle_and_selection_without_regions_never_requests(rig):
  assert rig.r.step() == "idle"
  rig.r.jobs.begin(R.Selection((), ()))
  assert rig.r.step() == "idle" and rig.r.jobs.load() is None
  assert rig.mem.get("OSMDownloadBounds") is None


def test_first_pass_busy_then_missing_cells_are_requested_one_at_a_time(rig):
  assert rig.dl.start(SEL)
  assert rig.r.step() == "busy"
  rig.mapd_finishes_pass(rig.cells[:-1])                        # the link dropped on the last cell: mapd skipped it
  p = rig.dl.progress()
  assert p.active and (p.total_files, p.downloaded_files) == (len(rig.cells), len(rig.cells) - 1)
  assert rig.r.step() == "requested"
  b = json.loads(rig.mem.get_text("OSMDownloadBounds"))
  last = rig.cells[-1]
  assert last[0] < b["min_lat"] < last[0] + 2 and last[1] < b["min_lon"] < last[1] + 2
  assert rig.r.step() == "busy"                                  # mapd has the request
  rig.mapd_finishes_pass([last])
  rig.t += 10
  assert rig.r.step() == "complete"
  p = rig.dl.progress()
  assert p.done and (p.total_files, p.downloaded_files) == (len(rig.cells), len(rig.cells))


def test_offline_waits_with_backoff_then_resumes(rig):
  assert rig.dl.start(SEL)
  rig.mapd_finishes_pass([])
  rig.online = False
  assert rig.r.step() == "offline"
  assert rig.r.step() == "waiting"
  rig.t += RS.RETRY_BACKOFF_S[0] + 1
  assert rig.r.step() == "offline"                               # still no 5G: next wait is longer
  rig.t += RS.RETRY_BACKOFF_S[0] + 1
  assert rig.r.step() == "waiting"
  rig.t += RS.RETRY_BACKOFF_S[1]
  rig.online = True
  assert rig.r.step() == "requested"
  assert rig.mem.get_text("OSMDownloadBounds")


def test_finished_cells_are_never_fetched_again(rig):
  assert rig.dl.start(SEL)
  rig.mapd_finishes_pass(rig.cells)
  assert rig.r.step() == "complete" and not (rig.mem.get_text("OSMDownloadBounds") or "").strip()


def test_a_cell_missing_on_the_server_is_given_up_and_the_download_ends(rig):
  assert rig.dl.start(SEL)
  rig.mapd_finishes_pass(rig.cells[1:])
  for _ in range(RS.MAX_CELL_ATTEMPTS):
    assert rig.r.step() == "requested"
    rig.mapd_finishes_pass([])                                   # 404: nothing appears
    rig.t += 10
  assert rig.r.step() == "gave_up"
  p = rig.dl.progress()
  assert p.done and p.downloaded_files == len(rig.cells) - 1


def test_stall_is_reported_and_the_request_dropped(rig):
  assert rig.dl.start(SEL)
  assert rig.r.step() == "busy"                                  # watch starts
  rig.t += RS.STALL_S - 5
  assert rig.r.step() == "busy"
  rig.mem.put("OSMDownloadProgress", json.dumps({"total_files": 3, "downloaded_files": 1}))   # a cell finished: watch restarts
  rig.t += 10
  assert rig.r.step() == "busy"
  rig.t += RS.STALL_S - 5
  assert rig.r.step() == "busy"
  rig.t += 10
  assert rig.r.step() == "stalled"
  assert not (rig.mem.get_text("OSMDownloadLocations") or "").strip()
  assert rig.r.jobs.load()["stalls"] == 1                         # the job survives: the gaps are fetched after the restart


def test_free_space_floor_stops_cleanly_and_keeps_tiles(rig):
  assert rig.dl.start(SEL)
  rig.put_cell(rig.cells[0])
  rig.free = RS.SPACE_FLOOR_BYTES - 1
  assert rig.r.step() == RS.NO_SPACE
  assert rig.mem.get("OSMDownloadLocations") is None and rig.mem.get("OSMDownloadBounds") is None
  assert RS.cell_present(rig.storage, rig.cells[0])
  p = rig.dl.progress()
  assert not p.active and not p.done and p.stopped == RS.NO_SPACE
  assert rig.r.step() == RS.NO_SPACE                             # stays stopped; a new Download press starts over
  assert rig.dl.start(SEL) and rig.r.jobs.load()["status"] == RS.RUNNING


def test_cancel_drops_the_job(rig):
  assert rig.dl.start(SEL)
  rig.dl.cancel()
  assert rig.r.jobs.load() is None and rig.r.step() == "idle"


def test_mapd_progress_is_read_from_the_persistent_params_dir(tmp_path):
  from openpilot.system.bogpilot.osm import memparams as MP
  m = MP.MemParams()
  assert m._path("OSMDownloadProgress") == MP.PERSIST_ROOT / "OSMDownloadProgress"   # mapd params.go: persistent
  assert m._path("OSMDownloadLocations") == MP.MEM_ROOT / "OSMDownloadLocations"
  assert m._path("OSMDownloadBounds") == MP.MEM_ROOT / "OSMDownloadBounds"
  t = MP.MemParams(tmp_path / "mem", persist_root=tmp_path / "persist")
  assert t.put("OSMDownloadProgress", "{}") and (tmp_path / "persist" / "OSMDownloadProgress").exists()


def test_slc_off_pauses_the_job_and_slc_on_resumes_it(tmp_path):
  # downloads need the Speed Limit Controller on: the resumer asks mapd for nothing while it is off and keeps the job
  from openpilot.system.bogpilot.osm import resume as RS2
  from openpilot.system.bogpilot.osm import regions as R2
  from openpilot.system.bogpilot.osm.memparams import MemParams as MP
  from openpilot.system.bogpilot.osm.storage import OsmStorage as OS
  mem, storage = MP(tmp_path / "d"), OS(tmp_path / "osm")
  storage.disk_free = lambda: 50 * 1024 ** 3
  slc = {"on": False}
  r = RS2.Resumer(mem, storage, online=lambda: True, clock=lambda: 1000.0, allowed=lambda: slc["on"])
  r.jobs.begin(R2.parse_selection('{"nations": [], "states": ["RI"]}'))
  mem.put("OSMDownloadLocations", '{"nations": [], "states": ["RI"]}')
  assert r.step() == "slc_off"
  assert mem.get("OSMDownloadLocations") is None and mem.get("OSMDownloadBounds") is None
  assert r.jobs.load() is not None                                    # job kept
  slc["on"] = True
  assert r.step() == "requested" and mem.get_text("OSMDownloadBounds")
