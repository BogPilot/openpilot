"""Map downloads while the car is on: 5 Mbit/s cap, spaced unpack fsyncs, nice 19 off the driving cores, automatic updates
paused. Fake clock and fake OS calls; no network, no device."""
import json
import re
from pathlib import Path

from openpilot.system.bogpilot.osm import cell_fetch as C
from openpilot.system.bogpilot.osm import priority as PR
from openpilot.system.bogpilot.osm import regions as R
from openpilot.system.bogpilot.osm import resume as RS
from openpilot.system.bogpilot.osm.tests.test_cell_fetch import CELL, archive, getter
from openpilot.system.bogpilot.osm.tests.test_resume import SEL, Rig

OP = Path(__file__).resolve().parents[4]


def source_cores(rel: str) -> set[int]:
  src = (OP / rel).read_text()
  cores = set()
  for m in re.finditer(r"(?:config_realtime_process|set_core_affinity)\(\s*(\[[^\]]*\]|\{[^}]*\}|\d+)", src):
    cores |= {int(x) for x in re.findall(r"\d+", m.group(1))}
  return cores


DRIVING_SOURCES = {
  "card": "selfdrive/car/card.py",
  "controlsd": "selfdrive/controls/controlsd.py",
  "selfdrived": "selfdrive/selfdrived/selfdrived.py",
  "plannerd": "selfdrive/controls/plannerd.py",
  "radard": "selfdrive/controls/radard.py",
  "modeld": "selfdrive/modeld/modeld.py",
  "dmonitoringmodeld": "selfdrive/modeld/dmonitoringmodeld.py",
  "pandad": "selfdrive/pandad/main.cc",
  "encoderd": "system/loggerd/encoderd.cc",
  "camerad": "system/camerad/main.cc",
}


def test_map_cores_never_overlap_a_driving_process():
  for name, rel in DRIVING_SOURCES.items():
    cores = source_cores(rel)
    assert cores, f"{name}: no core pin found in {rel}"
    assert not cores & set(PR.MAP_CORES), f"{name} runs on {sorted(cores)}"
    assert cores <= PR.DRIVING_CORES, f"{name} on {sorted(cores)} missing from DRIVING_CORES"
  ui = re.search(r"cores = \{(\d+), \}", (OP / "selfdrive/ui/ui.py").read_text())
  assert ui is not None and int(ui.group(1)) in PR.DRIVING_CORES
  assert set(PR.MAP_CORES) == {0, 1, 2}


def test_same_cores_as_the_screen_recorder():
  src = (OP / "selfdrive/ui/onroad/bogpilot/screen_recorder.py").read_text()
  m = re.search(r"RECORDER_CORES\s*=\s*\(([^)]*)\)", src)
  assert m is not None and tuple(int(x) for x in re.findall(r"\d+", m.group(1))) == PR.MAP_CORES


class Clock:
  def __init__(self):
    self.t = 100.0

  def __call__(self):
    return self.t

  def sleep(self, dt):
    self.t += dt


def pacer(onroad, clk, placed):
  return C.Pacer(onroad=lambda: onroad[0], clock=clk, sleep=clk.sleep, place=placed.append)


def test_offroad_runs_at_full_speed():
  clk, placed = Clock(), []
  p = pacer([False], clk, placed)
  for _ in range(100):
    p.on_bytes(256 * 1024)
    p.before_fsync()
  assert p.slept == 0.0 and clk.t == 100.0 and placed == [False]


def test_onroad_download_is_capped_at_5_mbit():
  clk, placed = Clock(), []
  p = pacer([True], clk, placed)
  total = 10 * 1000 * 1000
  for _ in range(total // 10000):
    p.on_bytes(10000)
  rate_bits = total * 8 / (clk.t - 100.0)
  assert 4.6e6 < rate_bits <= 5.2e6                        # the BURST_S head start lets it a little over at the start
  assert placed == [True]
  assert PR.ONROAD_RATE_BYTES_S == 625000


def test_drive_off_mid_download_slows_it_and_parking_speeds_it_up():
  clk, placed = Clock(), []
  on = [False]
  p = pacer(on, clk, placed)
  p.on_bytes(5 * 1000 * 1000)
  assert clk.t == 100.0
  on[0] = True
  clk.t += 1.0                                             # the next IsOnroad read
  start = clk.t
  for _ in range(100):
    p.on_bytes(25000)                                      # 2.5 MB
  assert clk.t - start >= 3.4
  on[0] = False
  clk.t += 1.0
  t = clk.t
  p.on_bytes(5 * 1000 * 1000)
  assert clk.t == t and placed == [False, True, False]


def test_onroad_unpack_is_at_most_10_fsyncs_a_second():
  clk, placed = Clock(), []
  p = pacer([True], clk, placed)
  for _ in range(31):
    p.before_fsync()
  assert clk.t - 100.0 >= 2.99


def test_an_unreadable_car_state_counts_as_onroad():
  clk, placed = Clock(), []
  p = C.Pacer(onroad=lambda: (_ for _ in ()).throw(RuntimeError()), clock=clk, sleep=clk.sleep, place=placed.append)
  assert p.onroad() is True and placed == [True]


class FakeParams:
  def __init__(self, values):
    self.values, self.reads = values, 0

  def get_bool(self, key):
    assert key == "IsOnroad"
    self.reads += 1
    v = self.values.pop(0)
    if isinstance(v, Exception):
      raise v
    return v


def test_the_onroad_check_keeps_one_params_reader_and_sees_every_change():
  made = []
  fake = FakeParams([False, True, True, False])
  r = C.OnroadReader(make=lambda: made.append(1) or fake)
  assert [r(), r(), r(), r()] == [False, True, True, False]
  assert len(made) == 1 and r.made == 1 and fake.reads == 4


def test_a_failed_onroad_read_counts_as_onroad_and_the_next_check_makes_a_new_reader():
  readers = [FakeParams([OSError("gone")]), FakeParams([False])]
  r = C.OnroadReader(make=lambda: readers.pop(0))
  assert r() is True
  assert r() is False and r.made == 2


def test_a_reader_that_cannot_be_made_counts_as_onroad():
  r = C.OnroadReader(make=lambda: (_ for _ in ()).throw(ImportError()))
  assert r() is True and r() is True and r.made == 0


def test_the_kept_reader_sees_each_isonroad_change_in_params():
  from openpilot.common.params import Params
  params, r = Params(), C.OnroadReader()   # the writer stands in for the manager, a separate handle
  try:
    seen = []
    for v in (False, True, True, False):
      params.put_bool("IsOnroad", v, block=True)
      seen.append(r())
    assert seen == [False, True, True, False] and r.made == 1
  finally:
    params.remove("IsOnroad")


def test_the_default_checks_reuse_one_reader():
  assert isinstance(C.default_onroad, C.OnroadReader)
  assert C.Pacer()._onroad_fn is C.default_onroad
  try:
    RS._onroad_reader = C.OnroadReader(make=lambda: FakeParams([True, False]))
    assert RS.default_onroad() is True and RS.default_onroad() is False and RS._onroad_reader.made == 1
  finally:
    RS._onroad_reader = None


def test_a_paced_fetch_still_extracts_the_whole_cell(tmp_path):
  clk, placed = Clock(), []
  p = pacer([True], clk, placed)
  blob = archive({"offline/46/-68/a": bytes(range(256)) * 4000, "offline/46/-68/b": b"B" * 7000})
  assert C.fetch_cell(tmp_path, *CELL, get=getter(blob), pacer=p) == 2
  assert (tmp_path / "offline" / "46" / "-68" / "a").read_bytes() == bytes(range(256)) * 4000
  assert placed == [True] and p.slept > 0.09


def test_place_self_moves_to_little_cores_onroad_and_back():
  calls = []
  PR.place_self(True, set_nice_fn=lambda t, v: calls.append(("nice", t, v)) or True,
                set_affinity_fn=lambda t, c: calls.append(("aff", t, tuple(c))) or True)
  PR.place_self(False, set_nice_fn=lambda t, v: calls.append(("nice", t, v)) or True,
                set_affinity_fn=lambda t, c: calls.append(("aff", t, tuple(c))) or True)
  assert calls[:2] == [("nice", 0, 19), ("aff", 0, (0, 1, 2))]
  assert calls[2] == ("nice", 0, PR.BASE_NICE) and calls[3][2] == PR.all_cores()


def test_apply_pins_every_thread_when_cores_are_given():
  aff = []
  PR.apply(42, 19, set_nice_fn=lambda t, v: True, set_io_fn=lambda t, c, l: True, threads_fn=lambda pid: [42, 43],
           cores=PR.MAP_CORES, set_affinity_fn=lambda t, c: aff.append((t, tuple(c))))
  assert aff == [(42, (0, 1, 2)), (43, (0, 1, 2))]
  PR.apply(42, 10, set_nice_fn=lambda t, v: True, set_io_fn=lambda t, c, l: True, threads_fn=lambda pid: [42],
           set_affinity_fn=lambda t, c: aff.append(t))
  assert len(aff) == 2                                     # no cores given: affinity untouched


def test_set_affinity_failure_is_quiet():
  assert PR.set_affinity(-12345, PR.MAP_CORES) is False


# ------------------------------------------------------------------------------- automatic update vs manual download onroad
def onroad_rig(tmp_path):
  rig = Rig(tmp_path)
  rig.onroad = False
  rig.r._onroad = lambda: rig.onroad
  return rig


def first_pass_done(rig):
  rig.mapd_finishes_pass(rig.cells[:-1])


def test_an_automatic_update_pauses_while_onroad_and_carries_on_offroad(tmp_path):
  rig = onroad_rig(tmp_path)
  assert rig.dl.start(SEL, auto=True) and rig.dl.jobs.load()["auto"] is True
  first_pass_done(rig)
  assert rig.r.step() == "requested" and rig.gap.alive
  rig.onroad = True
  assert rig.r.step() == RS.PAUSED_ONROAD
  assert not rig.gap.alive and rig.gap.stops >= 1         # the running fetch is stopped
  assert rig.r.step() == RS.PAUSED_ONROAD and len(rig.gap.started) == 1
  assert rig.dl.jobs.load()["status"] == RS.RUNNING       # the job is kept
  rig.onroad = False
  rig.t += 10
  assert rig.r.step() == "requested" and len(rig.gap.started) == 2


def test_a_manual_download_keeps_going_onroad(tmp_path):
  rig = onroad_rig(tmp_path)
  rig.onroad = True
  assert rig.dl.start(SEL) and rig.dl.jobs.load()["auto"] is False
  first_pass_done(rig)
  assert rig.r.step() == "requested" and rig.gap.alive


def test_an_unreadable_car_state_pauses_an_automatic_update(tmp_path):
  rig = onroad_rig(tmp_path)
  rig.r._onroad = lambda: (_ for _ in ()).throw(RuntimeError())
  rig.dl.start(SEL, auto=True)
  first_pass_done(rig)
  assert rig.r.step() == RS.PAUSED_ONROAD


def test_a_job_saved_by_an_older_build_counts_as_manual(tmp_path):
  rig = onroad_rig(tmp_path)
  rig.dl.start(SEL)
  job = rig.dl.jobs.load()
  job.pop("auto")
  rig.dl.jobs.save(job)
  rig.onroad = True
  first_pass_done(rig)
  assert rig.r.step() == "requested"


def test_the_schedule_starts_automatic_jobs(tmp_path, monkeypatch):
  from openpilot.system.bogpilot.osm.tests.test_scheduler import SUN, Rig as SchedRig
  r = SchedRig(tmp_path, monkeypatch, now=SUN)
  assert r.sched.tick() == "started"
  assert r.sched.dl.jobs.load()["auto"] is True
  assert json.loads(r.requested()) == json.loads('{"nations":[],"states":["OH"]}')


def test_v1_mapd_is_restarted_once_for_a_pause_and_leaves_the_little_cores(tmp_path, monkeypatch):
  from openpilot.system.bogpilot.osm.memparams import MemParams
  from openpilot.system.bogpilot.osm.tests.test_supervisor import StepResumer, _run_with
  MemParams(tmp_path / "d").put("OSMDownloadLocations", '{"states":["WY"]}')   # mapd v1 is downloading
  seen = []
  res, procs, _kw, _mem, _st = _run_with(tmp_path, monkeypatch,
                                          resumer=StepResumer(["busy", "busy"] + ["paused_onroad"] * 20),
                                          prioritize=lambda pid, busy: seen.append(busy))
  assert res["restarts"] == 1 and procs[0].terminated
  assert seen[0] is True and seen[-1] is False
