import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openpilot.selfdrive.ui.bogpilot.offroad_stats import cumulative_row, past_week_row, read_rows, resolve_timezone


class FakeParams:
  def __init__(self, values=None):
    self.values = values or {}
  def get(self, name):
    return self.values.get(name)
  def get_bool(self, name):
    return bool(self.values.get(name, False))


def stats(drives=3, meters=1609.344, seconds=7200):
  return json.dumps(dict(FrogPilotDrives=drives, FrogPilotMeters=meters, FrogPilotSeconds=seconds))


@pytest.mark.parametrize("metric,expected", [(False, 1), (True, 1)])
def test_authentic_counters_and_units(metric, expected):
  row = cumulative_row(stats(), metric)
  assert (row.drives, row.distance, row.hours, row.available) == (3, expected, 2, True)


@pytest.mark.parametrize("raw", [None, "", b""])
def test_missing_is_not_fabricated_zero(raw):
  row = cumulative_row(raw, False)
  assert not row.available and row.drives is None


@pytest.mark.parametrize("raw", ["{}", "[]", "broken", "null", '{"FrogPilotDrives":1}', stats(-1), stats(True), stats(1.5), stats(meters=float("nan")), stats(seconds=-1), stats(meters="100")])
def test_invalid_is_honestly_unavailable(raw):
  assert not cumulative_row(raw, False).available


def test_valid_recorded_zero_is_zero():
  row = cumulative_row(stats(0, 0, 0), False)
  assert row.available and (row.drives, row.distance, row.hours) == (0, 0, 0)


def test_original_truncation_not_rounding():
  row = cumulative_row(stats(2, 3218.687, 7199), False)
  assert (row.drives, row.distance, row.hours) == (2, 1, 1)


def test_week_local_window_and_future_zone_labels():
  data = {"2026-10-31": dict(routes=100, meters=100000, seconds=100000),
          "2026-11-01": dict(routes=2, meters=1609.344, seconds=3600),
          "2026-11-07": dict(routes=3, meters=1609.344, seconds=3600),
          "2026-11-08": dict(routes=1, meters=1609.344, seconds=3600),
          "bad": dict(routes=999, meters=999, seconds=999)}
  row = past_week_row(json.dumps(data), False, date(2026, 11, 7))
  assert row.available and (row.drives, row.distance, row.hours) == (6, 3, 3)


def test_week_invalid_in_range_not_silently_counted_zero():
  row = past_week_row(json.dumps({"2026-11-07": {"routes": 1}}), False, date(2026, 11, 7))
  assert not row.available


def test_empty_recorded_history_and_old_only_history():
  assert past_week_row("{}", False, date(2026, 11, 7)).drives == 0
  assert past_week_row('{"2025-01-01":{}}', False, date(2026, 11, 7)).drives == 0
  assert not past_week_row('{"bad":{}}', False, date(2026, 11, 7)).available


def test_timezone_precedence(tmp_path):
  p = tmp_path / "timezone"
  p.write_text("America/Los_Angeles")
  assert str(resolve_timezone("America/New_York", p)) == "America/New_York"
  assert str(resolve_timezone("Bad/Zone", p)) == "America/Los_Angeles"


def test_dst_and_local_day_read_only(tmp_path):
  history = tmp_path / "DriveHistory"
  raw = '{"2026-11-01":{"routes":2,"meters":2000,"seconds":3600}}'
  history.write_text(raw)
  p = FakeParams({"FrogPilotStats": stats(), "Timezone": "America/New_York", "IsMetric": True})
  # UTC Nov8 is still Nov7 locally, so Nov1 remains in the seven-day window.
  rows = read_rows(p, history_path=history, timezone_path=tmp_path / "missing", now=datetime(2026, 11, 8, 2, tzinfo=UTC))
  assert rows[0] == rows[2] and rows[1].drives == 2
  assert history.read_text() == raw
  assert p.values["FrogPilotStats"] == stats()


def test_missing_ledger_unavailable(tmp_path):
  rows = read_rows(FakeParams({"FrogPilotStats": stats()}), history_path=tmp_path / "missing")
  assert rows[0].available and not rows[1].available


def test_naive_clock_rejected(tmp_path):
  with pytest.raises(ValueError):
    read_rows(FakeParams(), history_path=tmp_path / "missing", now=datetime(2026, 11, 7))


def test_header_truthful_metadata_and_fallback():
  from openpilot.selfdrive.ui.layouts import home
  obj = home.HomeLayout.__new__(home.HomeLayout)
  obj.params = FakeParams({"Version": "0.11.2", "UpdaterCurrentDescription": "stale-other-version"})
  with patch.object(home, "get_build_metadata", return_value=SimpleNamespace(openpilot=SimpleNamespace(version="0.11.2"))):
    assert obj._get_version_text() == "BogPilot 0.11.2"
  with patch.object(home, "get_build_metadata", side_effect=ValueError("unavailable")):
    assert obj._get_version_text() == "BogPilot 0.11.2"
    obj.params = FakeParams()
    assert obj._get_version_text() == "BogPilot"


def test_real_card_wiring_and_no_prime_or_account_mutation():
  from openpilot.selfdrive.ui.layouts import home
  source = Path(home.__file__).read_text()
  assert "BogPilotStatsWidget" in source and "self._stats_widget.render(self.left_column_rect)" in source
  assert "PrimeWidget" not in source
  assert "self.update_alert" in source and "self.offroad_alert" in source


def test_widget_draws_original_rows_and_honest_absence():
  import pyray as rl
  from openpilot.selfdrive.ui.widgets import bogpilot_stats as widget
  obj = widget.BogPilotStatsWidget(params=FakeParams())
  with patch.object(widget, "gui_label") as label, patch.object(widget.rl, "draw_rectangle_rounded"):
    obj._render(rl.Rectangle(0, 0, 765, 865))
    texts = [call.args[1] for call in label.call_args_list]
    assert all(title in texts for title in ["ALL TIME (ON DEVICE)", "PAST WEEK (ON DEVICE)", "BOGPILOT"])
    assert texts.count("–") == 9  # EN DASH: EM DASH is not in the font atlas (t994 driveStats) and "0" not in texts
    for call in label.call_args_list:
      rect = call.args[0]
      assert rect.x >= 0 and rect.y >= 0 and rect.x + rect.width <= 765 and rect.y + rect.height <= 865
