"""Final stats save in bogpilot_trackd: signal, offroad transition, shutdown params, idempotence, atomic writes."""
from __future__ import annotations

import datetime
import json
import os
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.common import bogpilot_toggles
from openpilot.system.bogpilot import drive_tracking as dt

NOW = datetime.datetime(2026, 4, 11, 16, 0, 0, tzinfo=datetime.UTC)


class FakeParams(dict):
  def __init__(self, *a, **k):
    super().__init__(*a, **k)
    self.puts = []

  def get(self, key, *a, **k):
    return super().get(key)

  def get_bool(self, key, *a, **k):
    return bool(super().get(key, False))

  def put(self, key, val, block=None):
    self.puts.append((key, block))
    self[key] = val


class FakeSM:
  def __init__(self):
    self.updated = {"modelV2": False}
    self.seen = {"deviceState": False}
    self.data = {"deviceState": SimpleNamespace(started=False)}

  def __getitem__(self, key):
    return self.data[key]

  def frame(self, *, started=None, model=None):
    self.updated = {"modelV2": model is not None}
    if model is not None:
      self.data["carState"], self.data["selfdriveState"], self.data["carControl"] = model
    if started is not None:
      self.seen["deviceState"] = True
      self.data["deviceState"] = SimpleNamespace(started=started)


@pytest.fixture(autouse=True)
def bp_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(bogpilot_toggles, "BOGPILOT_DIR", tmp_path)
  monkeypatch.setattr(dt, "TIMEZONE_NAME_PATH", tmp_path / "missing-timezone")
  return tmp_path


def msgs(v=10.0, standstill=False, enabled=True, lat=True, experimental=False):
  return (
    SimpleNamespace(vEgo=v, standstill=standstill, vCruiseCluster=60.0),
    SimpleNamespace(state="enabled" if enabled else "disabled", enabled=enabled, alertType="", experimentalMode=experimental,
                    personality="standard"),
    SimpleNamespace(latActive=lat, longActive=False),
  )


def drive(t, seconds, **kw):
  for _ in range(round(seconds / dt.DT_MDL)):
    t.update(NOW, True, *msgs(**kw))


def saved(params):
  return json.loads(params["BogPilotStats"])


def tracker(bp_dir, params=None):
  params = params if params is not None else FakeParams()
  return params, dt.DriveTracker(params, history_path=bp_dir / "DriveHistory")


# what the regular save loses without a final save

def test_counters_since_last_standstill_are_saved_by_final_flush(bp_dir):
  params, t = tracker(bp_dir)
  drive(t, 30, experimental=True)
  assert saved(params)["TrackedTime"] == 0          # no standstill save yet
  assert t.final_flush(NOW, True) is True
  s = saved(params)
  assert s["TrackedTime"] == pytest.approx(30, abs=0.06)
  assert s["LateralTime"] == pytest.approx(30, abs=0.06)
  assert s["ExperimentalModeTime"] == pytest.approx(30, abs=0.06)
  assert s["BogPilotMeters"] == pytest.approx(300, rel=0.01)
  assert s["BogPilotDrives"] == 0                   # under DRIVE_CREDIT_S: counters kept, no drive credit
  day = dt.local_day(NOW, dt.bogpilot_timezone(None)).isoformat()
  h = json.loads((bp_dir / "DriveHistory").read_text())[day]
  assert h["routes"] == 0 and h["seconds"] == pytest.approx(30, abs=0.06)


def test_final_flush_credits_a_long_drive_once(bp_dir):
  params, t = tracker(bp_dir)
  drive(t, 75)                                      # moving the whole time: no standstill save
  t.final_flush(NOW, True)
  assert saved(params)["BogPilotDrives"] == 1


def test_never_engaged_drive_is_not_recorded(bp_dir):
  params, t = tracker(bp_dir)
  drive(t, 90, enabled=False, lat=False)
  before = list(params.puts)
  assert t.final_flush(NOW, True) is False
  assert params.puts == before and saved(params)["TrackedTime"] == 0


# idempotence / no double counting

def test_final_flush_twice_writes_once_and_adds_nothing(bp_dir):
  params, t = tracker(bp_dir)
  drive(t, 30)
  assert t.final_flush(NOW, True) is True
  first, writes = params["BogPilotStats"], len(params.puts)
  assert t.final_flush(NOW, True) is False
  assert params["BogPilotStats"] == first and len(params.puts) == writes


def test_regular_save_then_final_save_does_not_double_count(bp_dir):
  params, t = tracker(bp_dir)
  drive(t, 70)
  t.update(NOW, True, *msgs(v=0.0, standstill=True))        # regular standstill save
  after_regular = saved(params)
  assert after_regular["BogPilotDrives"] == 1
  assert t.final_flush(NOW, True) is False                   # nothing new since that save
  assert saved(params) == after_regular
  drive(t, 20)
  t.final_flush(NOW, True)
  s = saved(params)
  assert s["TrackedTime"] == pytest.approx(after_regular["TrackedTime"] + 20, abs=0.06)
  assert s["BogPilotDrives"] == 1


def test_final_save_then_more_driving_then_regular_save_sums_exactly(bp_dir):
  params, t = tracker(bp_dir)
  drive(t, 40)
  t.final_flush(NOW, True)
  drive(t, 30)
  t.update(NOW, True, *msgs(v=0.0, standstill=True))        # 70 s tracked in all: the first standstill credits the drive
  s = saved(params)
  assert s["TrackedTime"] == pytest.approx(40 + 30.05, abs=0.1)
  assert s["BogPilotDrives"] == 1
  drive(t, 31, v=0.0, standstill=True)                       # under the 60 s checkpoint: nothing new saved
  assert saved(params)["TrackedTime"] == pytest.approx(40 + 30.05, abs=0.1)
  assert t.tracked_time == pytest.approx(31, abs=0.1)
  day = dt.local_day(NOW, dt.bogpilot_timezone(None)).isoformat()
  assert json.loads((bp_dir / "DriveHistory").read_text())[day]["routes"] == 1


# 60 s checkpoint (hardwared UptimeOnroad cadence), moving or stopped

def test_highway_counters_are_checkpointed_every_60_s_without_credit(bp_dir):
  params, t = tracker(bp_dir)
  base = sum(1 for k, *_ in params.puts if k == "BogPilotStats")
  drive(t, 30 * 60)                                          # 30 min, never stopped
  s = saved(params)
  assert s["TrackedTime"] == pytest.approx(30 * 60, abs=60.1)   # at most one checkpoint interval unsaved
  assert s["BogPilotDrives"] == 0                            # a moving checkpoint never credits the drive
  stats_writes = [k for k, *_ in params.puts if k == "BogPilotStats"]
  assert 29 <= len(stats_writes) - base <= 30                # one per minute
  t.final_flush(NOW, True)
  s = saved(params)
  assert s["TrackedTime"] == pytest.approx(30 * 60, abs=0.1)
  assert s["BogPilotDrives"] == 1
  day = dt.local_day(NOW, dt.bogpilot_timezone(None)).isoformat()
  assert json.loads((bp_dir / "DriveHistory").read_text())[day]["routes"] == 1


def test_checkpoint_interval_matches_stock_uptime():
  from openpilot.common.bogpilot_checkpoint import COUNTER_INTERVAL_S
  assert dt.CHECKPOINT_S == COUNTER_INTERVAL_S == 60


def test_stop_and_go_credits_once_and_saves_at_most_once_a_minute_after(bp_dir):
  params, t = tracker(bp_dir)
  base = sum(1 for k, *_ in params.puts if k == "BogPilotStats")
  for _ in range(20):                                        # 20 x (25 s moving + 5 s stopped) = 10 min
    drive(t, 25)
    drive(t, 5, v=0.0, standstill=True)
  writes = [k for k, *_ in params.puts if k == "BogPilotStats"]
  assert saved(params)["BogPilotDrives"] == 1
  assert 9 <= len(writes) - base <= 10 + 1                   # checkpoints plus the one credit save


# triggers: signal, offroad transition, shutdown params

def test_signal_sets_flag_only_and_loop_saves_then_exits(bp_dir):
  params, t = tracker(bp_dir)
  stop = dt.StopFlag()
  old = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
  try:
    dt.install_stop_handlers(stop)
    assert signal.getsignal(signal.SIGTERM) is stop and signal.getsignal(signal.SIGINT) is stop
    drive(t, 25)
    writes = len(params.puts)
    os.kill(os.getpid(), signal.SIGTERM)
    assert stop.requested and stop.signum == signal.SIGTERM
    assert len(params.puts) == writes                        # the handler itself never writes
  finally:
    for sig, handler in old.items():
      signal.signal(sig, handler)
  sm, watch = FakeSM(), dt.ShutdownWatch(params.get_bool)
  sm.frame(model=msgs())                                     # last frame before the stop is still counted
  assert dt.loop_once(t, sm, stop, watch, 0.0, NOW, True) is False
  assert saved(params)["TrackedTime"] == pytest.approx(25.05, abs=0.06)


def test_sigint_also_requests_the_save(bp_dir):
  stop = dt.StopFlag()
  old = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
  try:
    dt.install_stop_handlers(stop)
    os.kill(os.getpid(), signal.SIGINT)
  finally:
    for sig, handler in old.items():
      signal.signal(sig, handler)
  assert stop.requested and stop.signum == signal.SIGINT


def test_offroad_transition_saves_and_keeps_running(bp_dir):
  params, t = tracker(bp_dir)
  sm, stop, watch = FakeSM(), dt.StopFlag(), dt.ShutdownWatch(params.get_bool)
  sm.frame(started=True, model=msgs())
  assert dt.loop_once(t, sm, stop, watch, 0.0, NOW, True)
  drive(t, 20)
  assert saved(params)["TrackedTime"] == 0
  sm.frame(started=False)                                    # no model frame: modeld already stopped
  assert dt.loop_once(t, sm, stop, watch, 0.5, NOW, True) is True
  assert saved(params)["TrackedTime"] == pytest.approx(20.05, abs=0.06)
  writes = len(params.puts)
  sm.frame(started=False)
  dt.loop_once(t, sm, stop, watch, 0.6, NOW, True)           # still offroad: no second save
  assert len(params.puts) == writes


def test_started_unknown_or_offroad_at_start_is_not_a_transition():
  w = dt.ShutdownWatch(lambda key: False)
  assert w.check(0.0, None) is None
  assert w.check(0.1, False) is None
  assert w.check(0.2, True) is None
  assert w.check(0.3, False) == "offroad"


@pytest.mark.parametrize("key", dt.SHUTDOWN_PARAMS)
def test_shutdown_param_saves_once(bp_dir, key):
  params, t = tracker(bp_dir)
  sm, stop, watch = FakeSM(), dt.StopFlag(), dt.ShutdownWatch(params.get_bool, check_interval=1.0)
  drive(t, 15)
  params[key] = True
  sm.frame(started=True)
  assert dt.loop_once(t, sm, stop, watch, 0.0, NOW, True) is True
  assert saved(params)["TrackedTime"] == pytest.approx(15, abs=0.06)
  writes = len(params.puts)
  for now in (0.5, 1.0, 2.0):
    dt.loop_once(t, sm, stop, watch, now, NOW, True)
  assert len(params.puts) == writes


def test_shutdown_param_read_error_is_ignored():
  def boom(key):
    raise OSError("read failed")
  assert dt.ShutdownWatch(boom).check(0.0, True) is None


def test_final_save_error_is_logged_not_raised(bp_dir):
  class Log:
    def __init__(self):
      self.errors = []
    def exception(self, msg):
      self.errors.append(msg)
    def info(self, msg):
      pass
  t = SimpleNamespace(final_flush=lambda now, valid: (_ for _ in ()).throw(OSError("disk")))
  log = Log()
  assert dt._final_save(t, NOW, True, "signal 15", log) is False
  assert log.errors and "signal 15" in log.errors[0]


# atomic writes

def test_every_stats_write_is_blocking(bp_dir):
  params, t = tracker(bp_dir)
  drive(t, 70)
  t.update(NOW, True, *msgs(v=0.0, standstill=True))
  drive(t, 10)
  t.final_flush(NOW, True)
  stats_puts = [block for key, block in params.puts if key == "BogPilotStats"]
  assert len(stats_puts) >= 3 and all(block is True for block in stats_puts)


def _real_params():
  try:
    from openpilot.common.params import Params
    p = Params()
    p.get("BogPilotStats")
    return p
  except Exception as e:  # no native libparams (e.g. a Mac checkout)
    pytest.skip(f"native Params unavailable: {type(e).__name__}")


def test_real_params_write_replaces_the_file_atomically(bp_dir):
  p = _real_params()
  p.put("BogPilotStats", json.dumps({"TrackedTime": 5, "BogPilotDrives": 2}), block=True)
  path = Path(p.get_param_path("BogPilotStats"))
  inode_before = path.stat().st_ino
  t = dt.DriveTracker(p, history_path=bp_dir / "DriveHistory", initialize_stores=False)
  drive(t, 12)
  assert t.final_flush(NOW, True)
  s = json.loads(path.read_text())
  assert s["TrackedTime"] == pytest.approx(17, abs=0.06) and s["BogPilotDrives"] == 2
  assert path.stat().st_ino != inode_before                  # renamed into place, never rewritten in place
  assert not [f for f in path.parent.iterdir() if f.name.startswith(".tmp_value_")]


def test_source_uses_blocking_put_and_wires_all_triggers():
  src = Path(dt.__file__).read_text(encoding="utf-8")
  assert 'self.params.put("BogPilotStats", raw, block=True)' in src
  assert "block=False" not in src
  assert '"deviceState"' in src and "install_stop_handlers(stop)" in src
  assert "loop_once(tracker, sm, stop, watch" in src
  assert "\u2014" not in src


def test_real_process_exits_cleanly_on_sigterm(bp_dir):
  _real_params()
  import subprocess
  import sys
  import time
  env = dict(os.environ, BOGPILOT_PARAMS_DIR=str(bp_dir / "bp"))
  proc = subprocess.Popen([sys.executable, "-m", "openpilot.system.bogpilot.drive_tracking"], env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
  try:
    time.sleep(3)
    assert proc.poll() is None                                 # running (or idling after a setup failure)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=5) == 0                           # well inside the manager's 5 s before SIGKILL
  finally:
    if proc.poll() is None:
      proc.kill()
      proc.wait()
