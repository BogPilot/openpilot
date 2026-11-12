import json

from openpilot.system.bogpilot.osm.gps_feed import MAX_HORIZONTAL_ACCURACY_M, STALE_S, GpsFeed, validate_fix
from openpilot.system.bogpilot.osm.memparams import MemParams


def feed(tmp_path):
  mem = MemParams(tmp_path / "d")
  return mem, GpsFeed(mem)


def test_validate_fix_rejects_bad():
  ok = dict(lat=0.5, lon=-0.5, has_fix=True, h_acc=5.0, speed=15.0, bearing_deg=90.0)
  assert validate_fix(**ok) == (0.5, -0.5, 90.0)
  for k, v in (("has_fix", False), ("lat", 91.0), ("lon", -181.0), ("h_acc", 0.0), ("h_acc", MAX_HORIZONTAL_ACCURACY_M + 0.1),
               ("lat", float("nan")), ("lon", None), ("h_acc", float("inf"))):
    assert validate_fix(**{**ok, k: v}) is None
  assert validate_fix(**{**ok, "lat": 0.0, "lon": 0.0}) is None


def test_bearing_untrusted_at_low_speed():
  assert validate_fix(0.5, -0.5, True, 5.0, 1.0, 90.0) == (0.5, -0.5, None)
  assert validate_fix(0.5, -0.5, True, 5.0, 10.0, float("nan")) == (0.5, -0.5, None)
  assert validate_fix(0.5, -0.5, True, 5.0, 10.0, 450.0) == (0.5, -0.5, None)


def test_publish_json_matches_mapd_input(tmp_path):
  mem, f = feed(tmp_path)
  assert f.update(0.0, 0.6, -0.7, True, 4.0, 12.0, 271.5)
  d = json.loads(mem.get_text("LastGPSPosition"))
  assert d == {"latitude": 0.6, "longitude": -0.7, "bearing": 271.5}


def test_never_publishes_without_trusted_heading(tmp_path):
  mem, f = feed(tmp_path)
  assert not f.update(0.0, 0.6, -0.7, True, 4.0, 0.5, 10.0)
  assert mem.get("LastGPSPosition") is None


def test_heading_held_when_slow(tmp_path):
  mem, f = feed(tmp_path)
  f.update(0.0, 0.6, -0.7, True, 4.0, 12.0, 100.0)
  assert f.update(1.0, 0.7, -0.7, True, 4.0, 0.2, 5.0)
  assert json.loads(mem.get_text("LastGPSPosition"))["bearing"] == 100.0


def test_bad_fix_removes_position(tmp_path):
  mem, f = feed(tmp_path)
  f.update(0.0, 0.6, -0.7, True, 4.0, 12.0, 100.0)
  assert mem.get("LastGPSPosition")
  assert not f.update(1.0, 0.6, -0.7, False, 4.0, 12.0, 100.0)
  assert mem.get("LastGPSPosition") is None


def test_stale_removes_position(tmp_path):
  mem, f = feed(tmp_path)
  f.update(10.0, 0.6, -0.7, True, 4.0, 12.0, 100.0)
  f.tick(10.0 + STALE_S - 0.1)
  assert mem.get("LastGPSPosition")
  f.tick(10.0 + STALE_S + 0.1)
  assert mem.get("LastGPSPosition") is None
  f.tick(100.0)          # idempotent
