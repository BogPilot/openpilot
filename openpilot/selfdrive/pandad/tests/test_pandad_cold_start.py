"""pandad.py cold start: polled wait with backoff, reflash only when needed, timing logs, "Connecting to panda..." alert.

No panda: Panda, HARDWARE, the flash and ./pandad are fakes; a fake clock replaces time.
"""
import json
import os
import signal

import pytest

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.pandad import pandad


class Clock:
  def __init__(self):
    self.t = 100.0

  def monotonic(self):
    return self.t

  def sleep(self, s):
    self.t += s


@pytest.fixture
def env(monkeypatch):
  clock = Clock()
  monkeypatch.setattr(pandad, "time", clock)
  ev = {"alerts": [], "flash": 0, "reset": 0, "run": 0, "timing": [], "waits": []}
  script = []          # one entry per wait_for_panda call: (found, seconds it takes)
  state = {"bootstub": False, "up_to_date": True}

  class FakePanda:
    def __init__(self, *a, **k):
      self.bootstub = state["bootstub"]
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_version(self): return "DEV-cafe0001-DEBUG"
    def up_to_date(self): return state["up_to_date"]
    @staticmethod
    def list(): return []
    @staticmethod
    def wait_for_panda(serial, timeout):
      found, took = script.pop(0) if script else (True, 0.2)
      ev["waits"].append(timeout)
      clock.t += min(took, timeout)
      return found and took <= timeout

  class FakeHW:
    @staticmethod
    def reset_internal_panda(): ev["reset"] += 1

  def fake_flash():
    ev["flash"] += 1
    state["bootstub"] = False
    state["up_to_date"] = True

  class FakeProc:
    def __init__(self, *a, **k): ev["run"] += 1
    def send_signal(self, s): pass
    def wait(self): signal.raise_signal(signal.SIGINT)   # main's handler sets do_exit

  monkeypatch.setattr(pandad, "Panda", FakePanda)
  monkeypatch.setattr(pandad, "HARDWARE", FakeHW)
  monkeypatch.setattr(pandad, "flash_panda", fake_flash)
  monkeypatch.setattr(pandad.subprocess, "Popen", FakeProc)
  monkeypatch.setattr(pandad, "record_panda_firmware", lambda text: None)
  monkeypatch.setattr(pandad, "show_connecting_alert", lambda show: ev["alerts"].append(show))
  monkeypatch.setattr(pandad.cloudlog, "event", lambda name, **kw: ev["timing"].append((name, kw)) if name == "pandad.timing" else None)
  old = signal.getsignal(signal.SIGINT)
  yield ev, script, state, clock
  signal.signal(signal.SIGINT, old)


def test_healthy_cold_start_runs_pandad_without_alert_or_flash(env):
  ev, script, _state, _clock = env
  script.append((True, 0.3))
  pandad.main()
  assert ev["run"] == 1 and ev["flash"] == 0 and ev["alerts"] == []
  assert ev["waits"][0] == pandad.ALERT_AFTER_S, "first look is polled, alert threshold first"
  steps = [kw["step"] for _n, kw in ev["timing"]]
  assert steps == ["reset", "wait_for_panda", "ready"]


def test_slow_cold_panda_is_waited_for_not_reflashed(env):
  ev, script, _state, _clock = env
  script += [(False, 99), (True, 8.0 - pandad.ALERT_AFTER_S)]   # not there within the alert time, answers at ~8 s
  pandad.main()
  assert ev["flash"] == 0 and ev["run"] == 1 and ev["reset"] == 1
  assert ev["alerts"] == [True, False], "alert while waiting, cleared once ready"
  assert sum(ev["waits"][:2]) <= pandad.COLD_START_WAIT_S + 1e-6


def test_bootstub_or_out_of_date_is_reflashed_at_once(env):
  ev, script, state, _clock = env
  state["bootstub"] = True
  pandad.main()
  assert ev["flash"] == 1 and ev["run"] == 1 and ev["alerts"] == [True, False]
  steps = [kw["step"] for _n, kw in ev["timing"]]
  assert "flash" in steps and steps[-1] == "ready"


def test_out_of_date_is_reflashed(env):
  ev, _script, state, _clock = env
  state["up_to_date"] = False
  pandad.main()
  assert ev["flash"] == 1 and ev["run"] == 1


def test_missing_panda_backs_off_then_recovers_through_dfu(env):
  ev, script, _state, clock = env
  t0 = clock.t
  # never shows up on its own: a look is split in two polls only when the alert time falls inside it
  polls = lambda wait_s: 2 if pandad.ALERT_AFTER_S < wait_s else 1
  script += [(False, 99)] * (polls(pandad.COLD_START_WAIT_S) + (pandad.MISSING_BEFORE_RECOVER - 1) * polls(pandad.RETRY_WAIT_S))
  pandad.main()
  assert ev["flash"] == 1, "DFU recover only after MISSING_BEFORE_RECOVER misses in a row"
  assert ev["reset"] == pandad.MISSING_BEFORE_RECOVER
  assert ev["alerts"][0] is True and ev["alerts"][-1] is False
  # backoff between the missing attempts: 0.5 s, then 1 s
  assert clock.t - t0 >= pandad.COLD_START_WAIT_S + 2 * pandad.RETRY_WAIT_S + 0.5 + 1.0 - 1e-6


def test_next_action_table():
  assert pandad.next_action(pandad.READY, 0) == "run"
  for s in pandad.NEEDS_FLASH:
    assert pandad.next_action(s, 0) == "flash"
  assert pandad.next_action(pandad.MISSING, 1) == "retry"
  assert pandad.next_action(pandad.MISSING, pandad.MISSING_BEFORE_RECOVER) == "flash"
  assert [pandad.backoff_s(i) for i in range(6)] == [0.5, 1.0, 2.0, 4.0, 4.0, 4.0]


def test_connecting_alert_is_defined_like_the_other_offroad_alerts():
  with open(os.path.join(BASEDIR, "openpilot/selfdrive/selfdrived/alerts_offroad.json")) as f:
    alerts = json.load(f)
  assert alerts[pandad.CONNECTING_ALERT]["text"] == "Connecting to panda..."
  with open(os.path.join(BASEDIR, "openpilot/common/params_keys.h")) as f:
    assert f'"{pandad.CONNECTING_ALERT}", {{CLEAR_ON_MANAGER_START, JSON}}' in f.read()


def test_vin_query_is_not_part_of_pandad():
  src = open(pandad.__file__).read()
  assert "vin" not in src.lower()


def test_alert_threshold_is_one_constant_in_the_measured_range():
  assert isinstance(pandad.ALERT_AFTER_S, float) and 5.0 <= pandad.ALERT_AFTER_S <= 8.0
  assert pandad.ALERT_AFTER_S < pandad.COLD_START_WAIT_S
  src = open(pandad.__file__).read()
  assert src.count("ALERT_AFTER_S = ") == 1 and "ALERT_AFTER_S, lambda: set_alert(True)" in src


@pytest.mark.parametrize("took", [0.72, 2.98, 3.02, 5.9])   # measured p50, p90, slowest normal start, and just under
def test_a_normal_slow_start_shows_no_alert(env, took):
  ev, script, _state, _clock = env
  script.append((True, took))
  pandad.main()
  assert ev["run"] == 1 and ev["flash"] == 0 and ev["alerts"] == []


def test_the_alert_shows_once_the_threshold_passes(env, monkeypatch):
  ev, script, _state, clock = env
  shown_at = []
  monkeypatch.setattr(pandad, "show_connecting_alert", lambda show: (ev["alerts"].append(show), shown_at.append(clock.t)))
  script += [(False, 99), (True, 1.0)]
  pandad.main()
  assert ev["alerts"] == [True, False] and ev["run"] == 1
  assert shown_at[0] - 100.0 == pytest.approx(pandad.ALERT_AFTER_S)
