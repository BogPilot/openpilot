import json

import pytest

from openpilot.selfdrive.ui.bogpilot.drive_summary import (
  DriveSummary, DriveSummaryController, Phase, diff_summary, distance_value, parse_stats, percent, time_parts,
)


def blob(tracked=0.0, lateral=0.0, experimental=0.0, meters=0.0, **extra):
  return json.dumps(dict(TrackedTime=tracked, LateralTime=lateral, ExperimentalModeTime=experimental,
                         BogPilotMeters=meters, **extra))


class FakeStore:
  def __init__(self, raw=None):
    self.raw = raw
    self.reads = 0

  def get(self):
    self.reads += 1
    if isinstance(self.raw, Exception):
      raise self.raw
    return self.raw


# difference math

def test_per_drive_difference_and_percentages():
  before = parse_stats(blob(1000, 600, 100, 50000))
  after = parse_stats(blob(1000 + 1800, 600 + 1350, 100 + 450, 50000 + 40000))
  s = diff_summary(before, after)
  assert s == DriveSummary(1800, 1350, 450, 40000)
  assert (s.engaged_pct, s.experimental_pct) == (75, 25)


def test_percent_truncates_and_clamps():
  assert percent(2, 3) == 66
  assert percent(5, 0) == 0
  assert percent(-1, 10) == 0
  assert percent(20, 10) == 100


def test_counters_unrelated_to_the_card_are_ignored():
  before = parse_stats(blob(10, Engages=4, CruiseSpeedTimes={"30.0": 5}))
  after = parse_stats(blob(70, 35, Engages=9, CruiseSpeedTimes={"30.0": 9}))
  assert diff_summary(before, after) == DriveSummary(60, 35, 0, 0)


def test_reset_during_drive_uses_new_totals():
  assert diff_summary(parse_stats(blob(5000, 4000, 10, 9e5)), parse_stats(blob(120, 60, 0, 2000))) == DriveSummary(120, 60, 0, 2000)


def test_missing_store_counts_as_zero_and_bad_values_are_zero():
  assert parse_stats(None) == {} and parse_stats("") == {} and parse_stats(b"") == {}
  bad = {"TrackedTime": 100, "LateralTime": "x", "BogPilotMeters": float("inf"), "ExperimentalModeTime": True}
  s = diff_summary(parse_stats(None), parse_stats(json.dumps(bad)))
  assert s == DriveSummary(100, 0, 0, 0)


@pytest.mark.parametrize("raw", ["{broken", "[]", "null", "7", b"\xff\xfe", "x" * (2 * 1024 * 1024 + 1)])
def test_unreadable_stats_give_no_summary(raw):
  assert parse_stats(raw) is None
  assert diff_summary({}, parse_stats(raw)) is None
  assert diff_summary(parse_stats(raw), {}) is None


def test_units_and_time():
  assert distance_value(1609.344 * 2.5, False) == 3       # rounds half up like qRound
  assert distance_value(1499, True) == 1
  assert distance_value(0, False) == 0
  assert time_parts(59) == (0, 0, 0)
  assert time_parts(3600 + 125) == (0, 1, 2)
  assert time_parts(86400 * 2 + 3600 * 3 + 60 * 4 + 59) == (2, 3, 4)
  assert time_parts(-5) == (0, 0, 0)


# zero cases

def test_zero_time_drive_is_not_recorded():
  s = diff_summary(parse_stats(blob(100, 50)), parse_stats(blob(100, 50)))
  assert s is not None and not s.recorded and s.engaged_pct == 0 and s.experimental_pct == 0


# transition behaviour

def make(raw):
  store = FakeStore(raw)
  return store, DriveSummaryController(store.get, poll_interval=1.0, timeout=10.0)


def test_ui_start_offroad_shows_nothing():
  store, c = make(blob(100))
  c.on_transition(False, 0.0)        # frame-1 callback while parked
  assert c.phase == Phase.HIDDEN and not c.visible and store.reads == 0


def test_drive_ready_immediately_when_save_landed_before_offroad():
  store, c = make(blob(100, 50, 0, 1000))
  c.on_transition(True, 0.0)
  store.raw = blob(100 + 600, 50 + 300, 60, 1000 + 8000)
  c.on_transition(False, 1000.0)
  assert c.phase == Phase.READY and c.visible
  assert c.summary == DriveSummary(600, 300, 60, 8000)


def test_waits_for_tracked_time_then_ready_and_picks_up_late_save():
  store, c = make(blob(100, 50))
  c.on_transition(True, 0.0)
  c.on_transition(False, 100.0)
  assert c.phase == Phase.WAITING and c.summary is None
  c.poll(100.5)                       # inside the poll interval: no re-read
  assert store.reads == 2
  store.raw = blob(160, 80)
  c.poll(101.0)
  assert c.phase == Phase.READY and c.summary.tracked_s == 60
  store.raw = blob(190, 100)          # a later save inside the window replaces the numbers
  c.poll(102.0)
  assert c.summary == DriveSummary(90, 50, 0, 0)
  c.poll(110.0)
  reads = store.reads
  store.raw = blob(999, 999)
  c.poll(200.0)                       # window over: no more reads, card stays
  assert store.reads == reads and c.phase == Phase.READY and c.summary.tracked_s == 90


def test_timeout_without_tracked_time_is_no_drive():
  store, c = make(blob(100, 50))
  c.on_transition(True, 0.0)
  c.on_transition(False, 100.0)
  for t in range(101, 111):
    c.poll(float(t))
  assert c.phase == Phase.NO_DRIVE and c.visible and c.summary is None


def test_unreadable_stats_end_as_no_drive():
  store, c = make("{broken")
  c.on_transition(True, 0.0)
  store.raw = blob(500, 400)
  c.on_transition(False, 10.0)
  c.poll(25.0)
  assert c.phase == Phase.NO_DRIVE


def test_param_read_error_is_handled():
  store, c = make(OSError("read failed"))
  c.on_transition(True, 0.0)
  c.on_transition(False, 1.0)
  c.poll(20.0)
  assert c.phase == Phase.NO_DRIVE


def test_dismiss_hides_and_stops_polling():
  store, c = make(blob(100))
  c.on_transition(True, 0.0)
  c.on_transition(False, 10.0)
  c.dismiss()
  reads = store.reads
  store.raw = blob(200, 100)
  c.poll(12.0)
  assert c.phase == Phase.HIDDEN and store.reads == reads and not c.visible


def test_repeated_offroad_callback_does_not_reopen_after_dismiss():
  store, c = make(blob(100))
  c.on_transition(True, 0.0)
  store.raw = blob(200, 100)
  c.on_transition(False, 10.0)
  c.dismiss()
  c.on_transition(False, 11.0)
  assert c.phase == Phase.HIDDEN


def test_going_onroad_again_hides_card_and_takes_new_copy():
  store, c = make(blob(100))
  c.on_transition(True, 0.0)
  store.raw = blob(200, 100)
  c.on_transition(False, 10.0)
  assert c.phase == Phase.READY
  c.on_transition(True, 20.0)
  assert c.phase == Phase.HIDDEN and c.summary is None
  store.raw = blob(260, 130, 30, 1609.344)
  c.on_transition(False, 30.0)
  assert c.summary == DriveSummary(60, 30, 30, 1609.344)
