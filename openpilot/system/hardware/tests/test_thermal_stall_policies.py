"""Thermal-zone read stalls of 12 to 14.4 s (seen on Pre-AP cars) under both stale-thermal policies. The background readers
keep deviceState publishing during the stall, so the only effect is thermalStatus, i.e. selfdrived's stock overheat event
(soft-disable when engaged, no-entry otherwise; selfdrived/events.py). Part 1 (any OS): hardwared's staleness rule
(bg_reads) sampled at 2 Hz. Part 2 (needs msgq): the same through selfdrived's real Events and StateMachine at 100 Hz."""
import pathlib
import re

import pytest

from openpilot.cereal import log
import openpilot.system.hardware.bg_reads as bg

ThermalStatus = log.DeviceState.ThermalStatus
WARM_C = 88.0          # tici overheated band entry (hardwared THERMAL_BANDS)
STALLS = (12.0, 12.6, 13.5, 14.4)
ROOT = pathlib.Path(bg.__file__).resolve().parents[2]


class Clock:
  t = 0.0

  def __call__(self):
    return self.t


def statuses(stall_s, policy, temp_c, total_s=30.0, stall_at=5.0):
  """thermalStatus per 10 ms step (hardwared publishes at 2 Hz and selfdrived holds the last one)."""
  clk = Clock()
  age = bg.ThermalStaleness(clock=clk)
  last_fresh, status, out = 0.0, ThermalStatus.ok, []
  for i in range(int(total_s * 100)):
    clk.t = i * 0.01
    if not (stall_at <= clk.t < stall_at + stall_s):
      last_fresh = clk.t
    if i % 50 == 0:
      stale = age.update(clk.t - last_fresh)
      band = ThermalStatus.overheated if temp_c >= WARM_C else ThermalStatus.ok
      status = bg.fail_hot_thermal_status(band, stale, age.stale_s, temp_c, WARM_C, ThermalStatus.ok,
                                          ThermalStatus.overheated, strict=(policy == "strict"))
    out.append(status)
  return out


def overheated_s(st):
  return round(sum(s >= ThermalStatus.overheated for s in st) * 0.01, 2)


def soft_disable_time():
  src = (ROOT / "selfdrive/selfdrived/state.py").read_text()
  return float(re.search(r"^SOFT_DISABLE_TIME = (\d+(?:\.\d+)?)", src, re.M).group(1))


def test_constants():
  assert bg.THERMAL_STALE_S == 10.0 and bg.THERMAL_FAIL_HOT_S == 60.0 and bg.STALE_THERMAL_POLICY == "nap"
  assert set(bg.STALE_THERMAL_POLICIES) == {"nap", "strict"}
  assert soft_disable_time() == 3.0
  ev = (ROOT / "selfdrive/selfdrived/events.py").read_text()
  block = ev.split("EventName.overheat: {", 1)[1].split("},", 1)[0]
  assert 'ET.SOFT_DISABLE: soft_disable_alert("System Overheated")' in block and 'ET.NO_ENTRY: NoEntryAlert("System Overheated")' in block


@pytest.mark.parametrize("stall", STALLS)
def test_strict_cool_device_overheated_for_the_stall_beyond_10_s(stall):
  over = overheated_s(statuses(stall, "strict", 60.0))
  assert stall - bg.THERMAL_STALE_S - 0.5 <= over <= stall - bg.THERMAL_STALE_S + 0.6


def first_overheated_s(st):
  return next((i * 0.01 for i, s in enumerate(st) if s >= ThermalStatus.overheated), None)


@pytest.mark.parametrize("policy, after", [("nap", 70.0), ("strict", 10.0)])
def test_hung_reader_cool_last_reading(policy, after):
  # the thermal reader never returns again from t=5 s, last reading cool (60 C): nap holds ok for about 70 s, strict about 10 s
  st = statuses(1000.0, policy, 60.0, total_s=100.0, stall_at=5.0)
  t = first_overheated_s(st)
  print(f"hung thermal reader, cool last reading, {policy}: overheated from {t:.2f} s ({t - 5.0:.2f} s after the last reading)")
  assert t is not None and after - 0.1 <= t - 5.0 <= after + 0.6
  assert all(s >= ThermalStatus.overheated for s in st[int(t * 100):])


@pytest.mark.parametrize("stall", STALLS)
def test_nap_cool_device_never_overheated(stall):
  assert overheated_s(statuses(stall, "nap", 60.0)) == 0.0


@pytest.mark.parametrize("policy", ["strict", "nap"])
def test_warm_device_is_overheated_either_way(policy):
  assert overheated_s(statuses(12.0, policy, 90.0)) == 30.0


# ---- part 2: selfdrived's real state machine (Linux / VM: needs msgq) ----

def run_selfdrived(st, engaged):
  pytest.importorskip("msgq")
  from openpilot.selfdrive.selfdrived.events import ET, Events, EventName
  from openpilot.selfdrive.selfdrived.state import State, StateMachine
  sm = StateMachine()
  sm.state = State.enabled if engaged else State.disabled
  soft = no_entry = 0
  for s in st:
    ev = Events()
    if s >= ThermalStatus.overheated:
      ev.add(EventName.overheat)
      no_entry += (not engaged) and ev.contains(ET.NO_ENTRY)
    sm.update(ev)
    soft |= sm.state == State.softDisabling
  if not engaged:
    return "no-entry %.2f s" % (no_entry * 0.01) if no_entry else "none"
  return "disengaged" if sm.state == State.disabled else ("soft-disable warning, recovered" if soft else "none")


# 12.6 s gives 3.0 s overheated at 2 Hz sampling, exactly SOFT_DISABLE_TIME: either outcome is possible there, so the
# test records which one the real state machine gives instead of assuming it.
@pytest.mark.parametrize("stall,expected", [(12.0, {"soft-disable warning, recovered"}),
                                            (12.6, {"soft-disable warning, recovered", "disengaged"}),
                                            (13.5, {"disengaged"}), (14.4, {"disengaged"})])
def test_strict_engaged_outcome_through_selfdrived(stall, expected):
  got = run_selfdrived(statuses(stall, "strict", 60.0), engaged=True)
  print(f"thermal stall {stall} s strict engaged -> {got}")
  assert got in expected


@pytest.mark.parametrize("stall", STALLS)
def test_strict_disengaged_gets_no_entry_and_nap_nothing(stall):
  assert run_selfdrived(statuses(stall, "strict", 60.0), engaged=False).startswith("no-entry")
  assert run_selfdrived(statuses(stall, "nap", 60.0), engaged=True) == "none"
  assert run_selfdrived(statuses(stall, "nap", 60.0), engaged=False) == "none"
