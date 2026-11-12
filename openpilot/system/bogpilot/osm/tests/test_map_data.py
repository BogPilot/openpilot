import json
import os

from openpilot.system.bogpilot.osm.map_data import FRESH_S, MAX_LIMIT_MS, MIN_LIMIT_MS, NO_DATA, MapDataReader, haversine_m
from openpilot.system.bogpilot.osm.memparams import MemParams

NOW = 1_000_000.0
POS = {"latitude": 0.5, "longitude": -0.5}
MPH = 0.44704


def setup(tmp_path, cur=None, nxt=None, age=0.0, gps_age=0.0):
  mem = MemParams(tmp_path / "d")
  if cur is not None:
    mem.put("MapSpeedLimit", json.dumps(cur))
    os.utime(mem._path("MapSpeedLimit"), (NOW - age, NOW - age))
  if nxt is not None:
    mem.put("NextMapSpeedLimit", json.dumps(nxt))
    os.utime(mem._path("NextMapSpeedLimit"), (NOW - age, NOW - age))
  mem.put("LastGPSPosition", json.dumps({"latitude": 0.5, "longitude": -0.5, "bearing": 0}))
  os.utime(mem._path("LastGPSPosition"), (NOW - gps_age, NOW - gps_age))
  return mem, MapDataReader(mem)


def test_current_limit_passthrough(tmp_path):
  _, r = setup(tmp_path, cur=25 * MPH)
  d = r.read(POS, 10.0, now=NOW)
  assert abs(d.limit - 25 * MPH) < 1e-9 and d.next_limit == 0.0 and not d.lookahead_applied


def test_no_position_no_data(tmp_path):
  _, r = setup(tmp_path, cur=25 * MPH)
  assert r.read(None, 10.0, now=NOW) == NO_DATA


def test_stale_limit_file_is_dropped(tmp_path):
  _, r = setup(tmp_path, cur=25 * MPH, age=FRESH_S + 0.5)
  assert r.read(POS, 10.0, now=NOW) == NO_DATA
  _, r2 = setup(tmp_path / "b", cur=25 * MPH, age=FRESH_S - 0.5)
  assert r2.read(POS, 10.0, now=NOW).limit > 0


def test_dead_position_feed_drops_limit(tmp_path):
  _, r = setup(tmp_path, cur=25 * MPH, gps_age=10.0)
  assert r.read(POS, 10.0, now=NOW) == NO_DATA
  mem, r2 = setup(tmp_path / "b", cur=25 * MPH)
  mem.remove("LastGPSPosition")
  assert r2.read(POS, 10.0, now=NOW) == NO_DATA


def test_bounds(tmp_path):
  for v in (0.0, MIN_LIMIT_MS - 0.01, MAX_LIMIT_MS + 0.01, -5.0, 1e9, "x", None, [1], float("nan")):
    mem, r = setup(tmp_path / str(abs(hash(repr(v)))), cur=v if not isinstance(v, float) or v == v else None)
    if isinstance(v, float) and v != v:
      mem.put("MapSpeedLimit", "NaN")
      os.utime(mem._path("MapSpeedLimit"), (NOW, NOW))
    assert r.read(POS, 10.0, now=NOW).limit == 0.0, v
  _, r = setup(tmp_path / "ok1", cur=MIN_LIMIT_MS)
  assert r.read(POS, 10.0, now=NOW).limit == MIN_LIMIT_MS
  _, r = setup(tmp_path / "ok2", cur=MAX_LIMIT_MS)
  assert r.read(POS, 10.0, now=NOW).limit == MAX_LIMIT_MS


def test_corrupt_files(tmp_path):
  mem, r = setup(tmp_path, cur=25 * MPH)
  mem.put("MapSpeedLimit", "{broken")
  os.utime(mem._path("MapSpeedLimit"), (NOW, NOW))
  assert r.read(POS, 10.0, now=NOW) == NO_DATA
  mem2, r2 = setup(tmp_path / "b", cur=25 * MPH)
  mem2.put("NextMapSpeedLimit", "{broken")
  os.utime(mem2._path("NextMapSpeedLimit"), (NOW, NOW))
  d = r2.read(POS, 10.0, 5.0, 5.0, now=NOW)
  assert d.limit > 0 and d.next_limit == 0.0


def nxt_at(lat_offset_deg, mph):
  return {"latitude": 0.5 + lat_offset_deg, "longitude": -0.5, "speedlimit": mph * MPH}


def test_lookahead_never_swaps_current_but_reports_next_and_distance(tmp_path):
  """The reader no longer swaps MapSpeedLimit for NextMapSpeedLimit (planner applies a ceiling)."""
  far = nxt_at(0.003, 45)     # ~333 m
  _, r = setup(tmp_path, cur=25 * MPH, nxt=far)
  dist = haversine_m(0.5, -0.5, 0.503, -0.5)
  v = 10.0
  d = r.read(POS, v, dist / v + 1.0, 0, now=NOW)   # would have swapped to the higher next
  assert not d.lookahead_applied
  assert abs(d.limit - 25 * MPH) < 1e-9 and abs(d.current - 25 * MPH) < 1e-9
  assert abs(d.next_limit - 45 * MPH) < 1e-9
  assert abs(d.distance_to_next - dist) < 1.0

  _, r2 = setup(tmp_path / "lo", cur=45 * MPH, nxt=nxt_at(0.001, 25))
  d2 = r2.read(POS, 20.0, 0, 15, now=NOW)          # would have swapped to the lower next
  assert not d2.lookahead_applied and abs(d2.limit - 45 * MPH) < 1e-9
  assert abs(d2.next_limit - 25 * MPH) < 1e-9 and d2.distance_to_next > 0


def test_zero_lookahead_and_equal_limits_still_report_next(tmp_path):
  _, r = setup(tmp_path, cur=25 * MPH, nxt=nxt_at(0.0, 45))
  d = r.read(POS, 30.0, 0, 0, now=NOW)
  assert not d.lookahead_applied and abs(d.limit - 25 * MPH) < 1e-9
  _, r2 = setup(tmp_path / "b", cur=25 * MPH, nxt=nxt_at(0.0001, 25))
  d2 = r2.read(POS, 30.0, 30, 30, now=NOW)
  assert not d2.lookahead_applied and abs(d2.limit - 25 * MPH) < 1e-9
  assert abs(d2.next_limit - 25 * MPH) < 1e-9


def test_bad_next_payloads_ignored(tmp_path):
  for payload in ({"speedlimit": 20.0}, {"latitude": "x", "longitude": 1, "speedlimit": 20.0}, {"latitude": 0.5, "longitude": -0.5, "speedlimit": 9999},
                  [1, 2], {"latitude": float("nan"), "longitude": -0.5, "speedlimit": 20.0}):
    _, r = setup(tmp_path / str(abs(hash(repr(payload)))), cur=25 * MPH, nxt=payload)
    d = r.read(POS, 10.0, 30, 30, now=NOW)
    assert d.next_limit == 0.0 and not d.lookahead_applied and abs(d.limit - 25 * MPH) < 1e-9


def test_negative_or_nan_speed(tmp_path):
  _, r = setup(tmp_path, cur=25 * MPH, nxt=nxt_at(0.0001, 45))
  assert not r.read(POS, -1.0, 30, 30, now=NOW).lookahead_applied
  assert not r.read(POS, float("nan"), 30, 30, now=NOW).lookahead_applied


def test_never_returns_value_not_in_files(tmp_path):
  _, r = setup(tmp_path, cur=25 * MPH, nxt=nxt_at(0.0005, 45))
  for v in (0.0, 5.0, 15.0, 40.0):
    d = r.read(POS, v, 10, 10, now=NOW)
    assert abs(d.limit - d.current) < 1e-9
