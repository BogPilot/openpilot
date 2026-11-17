"""hardwared: free space / memory stale > 60 s after their first read block NEW onroad entry only (bg_reads.StaleEntryGate)."""
import pytest

import openpilot.system.hardware.bg_reads as bg


class Log:
  def __init__(self):
    self.events = []

  def event(self, name, **kw):
    self.events.append(name)

  def warning(self, msg):
    self.events.append(msg)


@pytest.fixture
def log(monkeypatch):
  lg = Log()
  monkeypatch.setattr(bg, "cloudlog", lg)
  return lg


def ages(free=1.0, mem=1.0, **extra):
  return {"free_space": free, "memory": mem, **extra}


def test_threshold_is_60_s_on_free_space_and_memory():
  assert bg.ENTRY_STALE_S == 60.0 and set(bg.ENTRY_GATE_KEYS) == {"free_space", "memory"}


@pytest.mark.parametrize("key", ["free_space", "memory"])
def test_offroad_stale_over_60_s_blocks_onroad_entry(log, key):
  g = bg.StaleEntryGate()
  a = ages(); a[key] = 60.5
  assert g.update(a, onroad=False) is False
  assert g.stale == {key} and any("entry blocked" in e for e in log.events)


@pytest.mark.parametrize("key", ["free_space", "memory"])
def test_onroad_stale_over_60_s_stays_onroad_and_logs_once(log, key):
  g = bg.StaleEntryGate()
  a = ages(); a[key] = 61.0
  assert all(g.update(a, onroad=True) for _ in range(20))   # never false onroad: hardwared never goes offroad on it
  assert sum("staying onroad" in e for e in log.events) == 1
  assert g.update(a, onroad=False) is False                  # once offroad, the next entry is blocked


def test_fresh_value_clears_the_block(log):
  g = bg.StaleEntryGate()
  assert g.update(ages(free=90.0), onroad=False) is False
  assert g.update(ages(free=0.4), onroad=False) is True
  assert g.stale == set() and any("cleared" in e for e in log.events)


@pytest.mark.parametrize("age", [0.0, 10.0, 59.9, 60.0])
def test_stale_under_60_s_has_no_effect(log, age):
  g = bg.StaleEntryGate()
  assert g.update(ages(free=age, mem=age), onroad=False) is True and g.update(ages(free=age, mem=age), onroad=True) is True
  assert log.events == []


def test_before_first_read_and_other_keys_are_not_this_gates_job(log):
  g = bg.StaleEntryGate()
  assert g.update({"free_space": None, "memory": None, "cpu": 500.0, "booted": 500.0}, onroad=False) is True
  assert log.events == []


def test_hardwared_wires_it_as_a_startup_condition_only():
  import pathlib
  src = (pathlib.Path(bg.__file__).parent / "hardwared.py").read_text()
  assert 'startup_conditions["device_reads_fresh"] = entry_gate.update(dev_ages, onroad=started_ts is not None)' in src
  assert "device_reads_fresh" not in src.split('startup_conditions["device_reads_fresh"]', 1)[1]   # not an onroad condition
  assert "should_start = should_start and all(startup_conditions.values())" in src                  # startup conditions gate entry only
