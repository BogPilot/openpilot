"""mapd v2 wiring: engine switch in the supervisor, out-of-process downloads in the resumer, MapContext from mapdOut.
v1 stays the default everywhere (MapdV2 off / unreadable)."""
import json

from openpilot.system.bogpilot.osm import consumer as CO
from openpilot.system.bogpilot.osm import installer as I
from openpilot.system.bogpilot.osm import mapd_v2 as M
from openpilot.system.bogpilot.osm import regions as R
from openpilot.system.bogpilot.osm import resume as RS
from openpilot.system.bogpilot.osm import supervisor as S
from openpilot.system.bogpilot.osm.downloads import DownloadController
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage
from openpilot.system.bogpilot.osm.tests.test_installer import elf, fetcher, manifest_for
from openpilot.system.bogpilot.osm.tests.test_supervisor import Clock, FakeProc

SEL = R.Selection((), ("RI",))


def two_engines(tmp_path):
  st = OsmStorage(tmp_path / "osm")
  b1, b2 = elf(n=4096), elf(n=8192)
  m1, m2 = manifest_for(b1), dict(manifest_for(b2), version="v2.4.0", install_name="mapd_v2")
  I.install(st, m1, fetcher(b1))
  I.install(st, m2, fetcher(b2))
  return st, {False: m1, True: m2}


class FakeFetcher:
  def __init__(self):
    self.started, self.stops, self.busy = [], 0, False

  def start(self, cell):
    self.started.append(cell)
    self.busy = True
    return True

  def running(self):
    return self.busy

  def stop(self):
    self.stops += 1
    self.busy = False

  def token(self):
    return "t"


def test_supervisor_default_v1_then_switches_engines(tmp_path, monkeypatch):
  st, mans = two_engines(tmp_path)
  monkeypatch.setattr(S.installer, "load_engine_manifest", lambda v2: mans[bool(v2)])
  mem, clk, launched, procs, settings, envs = MemParams(tmp_path / "d"), Clock(), [], [], [], []

  def popen(cmd, **kw):
    launched.append((cmd, kw.get("cwd"), "preexec_fn" in kw))
    envs.append(kw.get("env"))
    procs.append(FakeProc(exits_after=10 ** 9))
    return procs[-1]

  class Res:
    fetcher = None

    def step(self):
      return "idle"

  res = Res()
  S.run(st, mem, popen=popen, sm=None, sleep=clk.sleep, monotonic=clk, max_ticks=100, resumer=res,
        preexec=lambda: None, engine=lambda: clk.t > 3.0, fetcher_factory=FakeFetcher,
        write_settings=lambda: settings.append(1))
  cmds = [c for c, _, _ in launched]
  assert cmds == [[str(st.mapd_path)], [str(st.root / "mapd_v2")]]   # v1 first (default), then v2 after the flip
  assert launched[0][2] is True                                     # v1 keeps its low-priority preexec
  assert procs[0].terminated                                        # the v1 mapd was stopped for the switch
  assert launched[1][1] == str(st.root) and launched[1][2] is False  # v2: osm cwd, normal priority
  assert settings == [1] and isinstance(res.fetcher, FakeFetcher)
  assert envs[0] is None and envs[1]["USE_MSGQ_PREFIX"] == "true"     # v1 launch unchanged


def test_supervisor_engine_read_error_is_v1(tmp_path, monkeypatch):
  st, mans = two_engines(tmp_path)
  monkeypatch.setattr(S.installer, "load_engine_manifest", lambda v2: mans[bool(v2)])
  clk, launched = Clock(), []
  S.run(st, MemParams(tmp_path / "d"), popen=lambda c, **kw: launched.append(c) or FakeProc(10 ** 9), sm=None,
        sleep=clk.sleep, monotonic=clk, max_ticks=50, engine=lambda: (_ for _ in ()).throw(OSError()))
  assert launched == [[str(st.mapd_path)]]


def test_supervisor_v2_never_restarts_mapd_for_a_stalled_download(tmp_path, monkeypatch):
  st, mans = two_engines(tmp_path)
  monkeypatch.setattr(S.installer, "load_engine_manifest", lambda v2: mans[bool(v2)])
  clk, procs = Clock(), []

  class Res:
    fetcher = None

    def step(self):
      return "stalled"

  def popen(c, **kw):
    procs.append(FakeProc(10 ** 9))
    return procs[-1]
  out = S.run(st, MemParams(tmp_path / "d"), popen=popen, sm=None, sleep=clk.sleep, monotonic=clk, max_ticks=200,
              resumer=Res(), engine=lambda: True, fetcher_factory=FakeFetcher, write_settings=lambda: True)
  assert len(procs) == 1 and out["restarts"] == 0


class Rig:
  def __init__(self, tmp_path):
    self.mem = MemParams(tmp_path / "d")
    self.storage = OsmStorage(tmp_path / "osm")
    self.storage.disk_free = lambda: 50 * 1024 ** 3
    self.t = 1000.0
    self.f = FakeFetcher()
    self.dl = DownloadController(self.mem, self.storage)
    self.r = RS.Resumer(self.mem, self.storage, online=lambda: True, clock=lambda: self.t, fetcher=self.f)
    self.cells = RS.selection_cells(SEL)

  def finish(self, ok=True):
    if ok:
      c = self.f.started[-1]
      d = self.storage.offline_dir / str(c[0]) / str(c[1])
      d.mkdir(parents=True, exist_ok=True)
      (d / "tile").write_bytes(b"x")
    self.f.busy = False
    self.t += 2


def test_resumer_v2_fetches_every_cell_out_of_process_without_touching_mapd(tmp_path):
  g = Rig(tmp_path)
  assert g.dl.start(SEL)
  for _ in g.cells:
    assert g.r.step() == "requested"
    assert g.mem.get("OSMDownloadLocations") is None and g.mem.get("OSMDownloadBounds") is None
    assert g.r.step() == "busy"
    g.finish()
  assert g.r.step() == "complete"
  assert sorted(g.f.started) == sorted(g.cells)
  p = g.dl.progress()
  assert p.done and p.downloaded_files == len(g.cells)


def test_resumer_v2_failed_cell_is_retried_then_given_up(tmp_path):
  g = Rig(tmp_path)
  assert g.dl.start(SEL)
  for c in g.cells[1:]:
    d = g.storage.offline_dir / str(c[0]) / str(c[1])
    d.mkdir(parents=True)
    (d / "tile").write_bytes(b"x")
  for _ in range(RS.MAX_CELL_ATTEMPTS):
    assert g.r.step() == "requested"
    g.finish(ok=False)
    g.t += 10
  assert g.r.step() == "gave_up"


def test_resumer_v2_stall_stops_only_the_fetch(tmp_path):
  g = Rig(tmp_path)
  assert g.dl.start(SEL)
  assert g.r.step() == "requested"
  assert g.r.step() == "busy"
  g.t += RS.FETCH_STALL_S + 1
  assert g.r.step() == "stalled"
  assert g.f.stops >= 1 and not g.f.busy and g.r.jobs.load() is not None


def test_resumer_v2_cancel_stops_a_running_fetch(tmp_path):
  g = Rig(tmp_path)
  assert g.dl.start(SEL)
  assert g.r.step() == "requested"
  g.dl.cancel()
  g.r.step()
  assert not g.f.busy


def test_fetch_process_command_line(tmp_path):
  calls = []

  class P:
    def poll(self):
      return None

    def terminate(self):
      calls.append("term")

    def wait(self, timeout=None):
      return 0

  st = OsmStorage(tmp_path / "osm")
  fp = RS.FetchProcess(st, popen=lambda cmd, **kw: calls.append(cmd) or P(), python="py")
  assert fp.start((46, -68)) and fp.running()
  assert calls[0] == ["py", "-m", "openpilot.system.bogpilot.osm.cell_fetch", "46", "-68", "--root", str(st.root)]
  assert fp.token() == "46,-68:-"
  fp.stop()
  assert calls[-1] == "term" and not fp.running()


class Tick:
  def __init__(self, d):
    self.d = d

  def get(self):
    return self.d


def test_context_v2_reads_mapd_out_only_with_gps(tmp_path):
  mem = MemParams(tmp_path)
  ctx = CO.MapContext(mem=mem, engine=lambda: True, v2_tick=Tick(M.MapdV2Data(True, 20.0, 15.0, 300.0, 12.0)))
  assert ctx.update(15.0, 0, 0) == CO.NO_DATA                                 # no GPS position: no limit
  mem.put("LastGPSPosition", json.dumps({"latitude": 0.5, "longitude": -0.5, "bearing": 90.0}))
  m = ctx.update(15.0, 0, 0)
  assert (m.limit, m.current, m.next_limit, m.distance_to_next, m.lookahead_applied) == (20.0, 20.0, 15.0, 300.0, False)
  ctx._v2_tick = Tick(M.NO_V2)
  assert ctx.update(15.0, 0, 0) == CO.NO_DATA


def test_context_v1_default_ignores_mapd_out(tmp_path):
  mem = MemParams(tmp_path)
  mem.put("LastGPSPosition", json.dumps({"latitude": 0.5, "longitude": -0.5, "bearing": 90.0}))
  mem.put("MapSpeedLimit", "13.4")
  ctx = CO.MapContext(mem=mem, engine=lambda: False, v2_tick=Tick(M.MapdV2Data(True, 20.0, 0, 0, 0)))
  assert ctx.update(15.0, 0, 0).limit == 13.4
  ctx = CO.MapContext(mem=mem, engine=lambda: (_ for _ in ()).throw(OSError()), v2_tick=Tick(M.MapdV2Data(True, 20.0, 0, 0, 0)))
  assert ctx.update(15.0, 0, 0).limit == 13.4
