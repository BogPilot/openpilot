import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from openpilot.system.bogpilot.osm import installer as I
from openpilot.system.bogpilot.osm import supervisor as S
from openpilot.system.bogpilot.osm.gps_feed import GpsFeed
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage
from openpilot.system.bogpilot.osm.tests.test_installer import elf, fetcher, manifest_for

SEL = '{"states":["WY"]}'


def installed(tmp_path):
  blob = elf()
  man = manifest_for(blob)
  st = OsmStorage(tmp_path / "osm")
  I.install(st, man, fetcher(blob))
  return st, man


def test_wanted_gate_is_fail_closed(tmp_path):
  st, man = installed(tmp_path)
  assert S.wanted(SEL, True, st, man)
  assert not S.wanted(SEL, False, st, man)                  # not adopted
  assert not S.wanted("", True, st, man)                    # no regions
  assert not S.wanted("garbage", True, st, man)
  assert not S.wanted('{"states":["ZZ"]}', True, st, man)   # unknown region only
  st.mapd_path.write_bytes(b"tampered")
  assert not S.wanted(SEL, True, st, man)                   # binary not verified
  assert not S.wanted(SEL, True, OsmStorage(tmp_path / "none"), man)


def test_adopted_reads_marker_and_defaults_false(tmp_path, monkeypatch):
  from openpilot.common import bogpilot_store as bs
  monkeypatch.setattr(bs, "read_text", lambda key, default=None: None)
  assert S.adopted(None) is False
  monkeypatch.setattr(bs, "read_text", lambda key, default=None: "1" if key == S.ADOPTION_MARKER else None)
  assert S.adopted(None) is True
  monkeypatch.setattr(bs, "read_text", lambda key, default=None: (_ for _ in ()).throw(OSError("x")))
  assert S.adopted(None) is False


def test_manager_condition_default_off(tmp_path):
  # fresh device: no marker, no maps, no binary -> never starts
  params = SimpleNamespace(get=lambda k: None)
  assert S.manager_condition(True, params, None) is False
  assert S.manager_condition(False, SimpleNamespace(get=lambda k: (_ for _ in ()).throw(RuntimeError())), None) is False


class FakeProc:
  def __init__(self, exits_after=1):
    self.polls = 0
    self.exits_after = exits_after
    self.terminated = False

  def poll(self):
    self.polls += 1
    return 0 if self.polls > self.exits_after else None

  def terminate(self):
    self.terminated = True


class Clock:
  def __init__(self):
    self.t = 0.0

  def __call__(self):
    return self.t

  def sleep(self, dt):
    self.t += dt


def test_run_launches_verified_binary_with_backoff(tmp_path):
  st, _ = installed(tmp_path)
  mem = MemParams(tmp_path / "d")
  clk = Clock()
  launched = []

  def popen(cmd, **kw):
    launched.append(cmd)
    return FakeProc(exits_after=2)

  # production loads the pinned manifest; point it at the test blob's manifest
  import openpilot.system.bogpilot.osm.supervisor as sup
  man = manifest_for(st.mapd_path.read_bytes())
  orig = sup.installer.load_manifest
  sup.installer.load_manifest = lambda *a, **k: man
  try:
    res = S.run(st, mem, popen=popen, sm=None, sleep=clk.sleep, monotonic=clk, max_ticks=400)
  finally:
    sup.installer.load_manifest = orig
  assert res["launches"] >= 3
  assert all(c == [str(st.mapd_path)] for c in launched)
  assert mem.get_text("MapdLogLevel") == "disabled"


def test_run_never_executes_unverified_binary(tmp_path):
  st, man = installed(tmp_path)
  st.mapd_path.write_bytes(b"evil")
  os.chmod(st.mapd_path, 0o755)
  import openpilot.system.bogpilot.osm.supervisor as sup
  orig = sup.installer.load_manifest
  sup.installer.load_manifest = lambda *a, **k: man
  launched = []
  def bad_fetch(url):
    raise OSError("offline")

  clk = Clock()
  try:
    res = S.run(st, MemParams(tmp_path / "d"), popen=lambda c, **kw: launched.append(c) or FakeProc(), sm=None,
                sleep=clk.sleep, monotonic=clk, max_ticks=10, fetch=bad_fetch)
  finally:
    sup.installer.load_manifest = orig
  assert launched == [] and res["launches"] == 0 and res["installs"] >= 1


def test_run_installs_pinned_binary_then_launches(tmp_path):
  blob = elf()
  man = manifest_for(blob)
  st = OsmStorage(tmp_path / "osm")                       # nothing installed yet
  import openpilot.system.bogpilot.osm.supervisor as sup
  orig = sup.installer.load_manifest
  sup.installer.load_manifest = lambda *a, **k: man
  clk = Clock()
  launched = []
  try:
    res = S.run(st, MemParams(tmp_path / "d"), popen=lambda c, **kw: launched.append(c) or FakeProc(exits_after=1000), sm=None,
                sleep=clk.sleep, monotonic=clk, max_ticks=10, fetch=fetcher(blob))
  finally:
    sup.installer.load_manifest = orig
  assert res["installs"] == 1 and res["launches"] == 1 and launched == [[str(st.mapd_path)]]
  assert I.verify_installed(st, man)


def test_run_wrong_hash_download_is_rejected_and_never_executed(tmp_path):
  blob = elf()
  man = manifest_for(blob)
  st = OsmStorage(tmp_path / "osm")
  import openpilot.system.bogpilot.osm.supervisor as sup
  orig = sup.installer.load_manifest
  sup.installer.load_manifest = lambda *a, **k: man
  clk = Clock()
  launched = []
  try:
    res = S.run(st, MemParams(tmp_path / "d"), popen=lambda c, **kw: launched.append(c) or FakeProc(), sm=None,
                sleep=clk.sleep, monotonic=clk, max_ticks=10, fetch=fetcher(elf() + b"tampered"))
  finally:
    sup.installer.load_manifest = orig
  assert launched == [] and res["installs"] >= 1


def test_wanted_default_on_gate_needs_no_binary(tmp_path):
  st = OsmStorage(tmp_path / "none")
  assert S.wanted(SEL, True, st, require_binary=False)
  assert not S.wanted("", True, st, require_binary=False)
  assert not S.wanted(SEL, False, st, require_binary=False)


def test_backoff_schedule():
  assert [S.backoff(i) for i in range(6)] == [2.0, 5.0, 15.0, 60.0, 60.0, 60.0]


class FakeSM:
  def __init__(self, msgs, svc="gpsLocation"):
    self.svc = svc
    self.msgs = list(msgs)
    self.updated = {"gpsLocation": False, "gpsLocationExternal": False}
    self.valid = {"gpsLocation": True, "gpsLocationExternal": True}
    self.cur = None

  def update(self, _t):
    if self.msgs:
      self.cur = self.msgs.pop(0)
      self.updated[self.svc] = True
    else:
      self.updated[self.svc] = False

  def __getitem__(self, k):
    return self.cur


def gps(lat=0.5, lon=-0.5, fix=True, acc=4.0, speed=12.0, bearing=90.0):
  return SimpleNamespace(latitude=lat, longitude=lon, hasFix=fix, horizontalAccuracy=acc, speed=speed, bearingDeg=bearing)


def test_feed_step_publishes_and_goes_stale(tmp_path):
  mem = MemParams(tmp_path / "d")
  feed = GpsFeed(mem)
  sm = FakeSM([gps()])
  sm.update(0)
  S.feed_step(sm, feed, 1.0)
  assert json.loads(mem.get_text("LastGPSPosition"))["bearing"] == 90.0
  sm.update(0)
  S.feed_step(sm, feed, 1.0 + 10.0)
  assert mem.get("LastGPSPosition") is None


def test_feed_step_uses_external_receiver(tmp_path):
  mem = MemParams(tmp_path / "d")
  feed = GpsFeed(mem)
  sm = FakeSM([gps(lat=0.75)], svc="gpsLocationExternal")
  sm.update(0)
  S.feed_step(sm, feed, 1.0)
  assert json.loads(mem.get_text("LastGPSPosition"))["latitude"] == 0.75


def test_feed_step_ignores_invalid_service(tmp_path):
  mem = MemParams(tmp_path / "d")
  feed = GpsFeed(mem)
  sm = FakeSM([gps()])
  sm.valid["gpsLocation"] = False
  sm.update(0)
  S.feed_step(sm, feed, 1.0)
  assert mem.get("LastGPSPosition") is None


def test_feed_step_survives_broken_sm(tmp_path):
  feed = GpsFeed(MemParams(tmp_path / "d"))
  S.feed_step(SimpleNamespace(updated={}, valid={}), feed, 0.0)
  S.feed_step(SimpleNamespace(updated={"gpsLocation": True}, valid={"gpsLocation": True}, __getitem__=None), feed, 0.0)


def test_memparams_rejects_unknown_keys(tmp_path):
  mem = MemParams(tmp_path / "d")
  for bad in ("../x", "Anything", "MapsSelected"):
    try:
      mem.put(bad, "x")
      raise AssertionError(bad)
    except KeyError:
      pass


def test_mapd_is_started_in_the_osm_root(tmp_path):
  """mapd v1.12.0 resolves ./offline and tmp/ against its cwd (found with the real binary on aarch64)."""
  blob = elf()
  man = manifest_for(blob)
  st = OsmStorage(tmp_path / "osm")
  import openpilot.system.bogpilot.osm.supervisor as sup
  seen = {}
  def popen(cmd, **kw):
    seen.update(kw)
    return FakeProc()
  orig = sup.installer.load_manifest
  sup.installer.load_manifest = lambda *a, **k: man
  clk = Clock()
  try:
    S.run(st, MemParams(tmp_path / "d"), popen=popen, sm=None, sleep=clk.sleep, monotonic=clk, max_ticks=10, fetch=fetcher(blob))
  finally:
    sup.installer.load_manifest = orig
  assert seen.get("cwd") == str(st.root)


# ---------------------------------------------------------------- downloads while driving: resume, priority, no drive gate
class StepResumer:
  def __init__(self, results):
    self.results, self.calls = list(results), 0

  def step(self):
    self.calls += 1
    return self.results.pop(0) if self.results else "idle"


def _run_with(tmp_path, monkeypatch, **kw):
  st, _ = installed(tmp_path)
  mem = MemParams(tmp_path / "d")
  clk = Clock()
  procs, kwargs = [], []

  def popen(cmd, **k):
    kwargs.append(k)
    procs.append(FakeProc(exits_after=10 ** 9))
    procs[-1].pid = 4242
    return procs[-1]

  man = manifest_for(st.mapd_path.read_bytes())
  monkeypatch.setattr(S.installer, "load_manifest", lambda *a, **k: man)
  res = S.run(st, mem, popen=popen, sm=None, sleep=clk.sleep, monotonic=clk, max_ticks=60, **kw)
  return res, procs, kwargs, mem, st


def test_stalled_or_full_download_restarts_mapd(tmp_path, monkeypatch):
  res, procs, _kw, _mem, _st = _run_with(tmp_path, monkeypatch, resumer=StepResumer(["busy", "stalled", "busy", "no_space"]))
  assert res["restarts"] == 2 and procs[0].terminated


def test_priority_follows_the_download_state_and_preexec_is_passed(tmp_path, monkeypatch):
  seen = []
  marker = object()
  st, _ = installed(tmp_path)
  mem = MemParams(tmp_path / "d")
  res, procs, kwargs, mem, st = _run_with(tmp_path, monkeypatch, resumer=StepResumer([]),
                                          prioritize=lambda pid, busy: seen.append((pid, busy)), preexec=marker)
  assert kwargs[0]["preexec_fn"] is marker and kwargs[0]["cwd"] == str(st.root)
  assert seen == [(4242, False)]                                  # set once at launch, again only when it changes


def test_installs_and_runs_regardless_of_the_car_state():
  import inspect
  src = inspect.getsource(S.run).split('"""')[2]                  # the code, without the docstring
  assert "IsOnroad" not in src and "gearShifter" not in src and "parked" not in src   # map downloads are never drive-gated


# ---------------------------------------------------------------- heartbeat and crash cleanup (Map Data: stopped vs busy)
def test_heartbeat_is_written_while_running_and_removed_on_exit(tmp_path, monkeypatch):
  seen = []

  class BeatResumer(StepResumer):
    def step(self):
      seen.append(mem_ref[0].get_text("BogPilotMapdHeartbeat"))
      return super().step()

  mem_ref = [MemParams(tmp_path / "d")]
  st, _ = installed(tmp_path)
  man = manifest_for(st.mapd_path.read_bytes())
  monkeypatch.setattr(S.installer, "load_manifest", lambda *a, **k: man)
  clk = Clock()
  S.run(st, mem_ref[0], popen=lambda cmd, **k: FakeProc(exits_after=10 ** 9), sm=None, sleep=clk.sleep, monotonic=clk,
        max_ticks=30, resumer=BeatResumer([]))
  assert seen and all(v == "1" for v in seen)
  assert mem_ref[0].get("BogPilotMapdHeartbeat") is None


def test_an_exception_terminates_mapd_and_propagates_for_main_to_retry(tmp_path, monkeypatch):
  st, _ = installed(tmp_path)
  man = manifest_for(st.mapd_path.read_bytes())
  monkeypatch.setattr(S.installer, "load_manifest", lambda *a, **k: man)
  mem = MemParams(tmp_path / "d")
  procs = []

  def popen(cmd, **k):
    procs.append(FakeProc(exits_after=10 ** 9))
    return procs[-1]

  class Boom:
    calls = 0

    def update(self, timeout):
      Boom.calls += 1
      if Boom.calls > 3:
        raise RuntimeError("msgq gone")

  clk = Clock()
  with pytest.raises(RuntimeError):
    S.run(st, mem, popen=popen, sm=Boom(), sleep=clk.sleep, monotonic=clk, max_ticks=50)
  assert procs and procs[0].terminated                           # no orphan mapd for the next run() to duplicate
  assert mem.get("BogPilotMapdHeartbeat") is None


def test_main_restarts_run_after_an_exception(monkeypatch):
  import sys
  import types
  calls = []

  def fake_run(**kw):
    calls.append(kw)
    if len(calls) == 1:
      raise RuntimeError("first run failed")
    raise KeyboardInterrupt                                      # end the test loop

  monkeypatch.setattr(S, "run", fake_run)
  monkeypatch.setattr(S.time, "sleep", lambda s: None)
  fake_messaging = types.SimpleNamespace(SubMaster=lambda *a, **k: object())
  monkeypatch.setitem(sys.modules, "openpilot.cereal.messaging", fake_messaging)
  import openpilot.cereal
  monkeypatch.setattr(openpilot.cereal, "messaging", fake_messaging, raising=False)
  import openpilot.common.bogpilot_store as bs
  monkeypatch.setattr(bs, "ParamStore", lambda *a, **k: SimpleNamespace(get_bool=lambda *a, **k: False))
  with pytest.raises(KeyboardInterrupt):
    S.main()
  assert len(calls) == 2
  assert calls[0]["resumer"]._gap is not None                    # v1 gaps go through cell_fetch, never OSMDownloadBounds
