import json
import os
import time
from types import SimpleNamespace as NS

from openpilot.system.bogpilot.osm import consumer as C
from openpilot.system.bogpilot.osm.memparams import MemParams


def put(mem, key, val, age=0.0):
  mem.put(key, val if isinstance(val, str) else json.dumps(val))
  if age:
    t = time.time() - age
    os.utime(mem._path(key), (t, t))


GPS = {"latitude": 0.5, "longitude": -0.5, "bearing": 90.0}


def test_read_gps_position_fresh_stale_and_malformed(tmp_path):
  mem = MemParams(tmp_path)
  assert C.read_gps_position(mem) is None
  put(mem, "LastGPSPosition", GPS)
  assert C.read_gps_position(mem) == GPS
  put(mem, "LastGPSPosition", GPS, age=10)
  assert C.read_gps_position(mem) is None
  for bad in ("garbage", "{}", json.dumps({"latitude": 95, "longitude": 0, "bearing": 0}),
              json.dumps({"latitude": "x", "longitude": 0, "bearing": 0}),
              json.dumps({"latitude": 1, "longitude": 1, "bearing": float("nan")})):
    put(mem, "LastGPSPosition", bad)
    assert C.read_gps_position(mem) is None


def test_context_returns_current_and_next_without_swapping(tmp_path):
  mem = MemParams(tmp_path)
  put(mem, "LastGPSPosition", GPS)
  put(mem, "MapSpeedLimit", "13.4")
  put(mem, "NextMapSpeedLimit", {"speedlimit": 20.0, "latitude": 0.5, "longitude": -0.5005})
  ctx = C.MapContext(mem=mem)
  m = ctx.update(15.0, 0, 0)
  assert m.limit == 13.4 and m.current == 13.4 and m.next_limit == 20.0 and not m.lookahead_applied
  m = ctx.update(15.0, 10, 0)           # would previously have swapped; current stays 13.4
  assert m.limit == 13.4 and m.current == 13.4 and m.next_limit == 20.0
  assert not m.lookahead_applied and m.distance_to_next > 0


def test_context_no_gps_means_no_map_limit(tmp_path):
  mem = MemParams(tmp_path)
  put(mem, "MapSpeedLimit", "13.4")
  ctx = C.MapContext(mem=mem)
  assert ctx.update(15.0, 0, 0).limit == 0.0 and ctx.gps_position is None


def test_context_stale_map_file_is_dropped(tmp_path):
  mem = MemParams(tmp_path)
  put(mem, "LastGPSPosition", GPS)
  put(mem, "MapSpeedLimit", "13.4", age=30)
  assert C.MapContext(mem=mem).update(15.0, 0, 0).limit == 0.0


def test_context_survives_broken_reader(tmp_path):
  ctx = C.MapContext(mem=MemParams(tmp_path))
  ctx.reader = NS(read=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
  put(ctx.mem, "LastGPSPosition", GPS)
  assert ctx.update(15.0, 0, 0).limit == 0.0


class SM:
  def __init__(self, msg):
    self.msg = msg
    self.updated = {"gpsLocation": True, "gpsLocationExternal": False}
    self.valid = {"gpsLocation": True, "gpsLocationExternal": True}

  def update(self, t):
    pass

  def __getitem__(self, k):
    return self.msg


def fix(lat=0.5, lon=-0.5, bearing=90.0, speed=12.0, acc=4.0, has=True):
  return NS(latitude=lat, longitude=lon, hasFix=has, horizontalAccuracy=acc, speed=speed, bearingDeg=bearing)


def test_own_gps_only_with_trusted_heading_and_fix():
  g = C.OwnGps(sm_factory=lambda: SM(fix()))
  pos = g.update()
  assert pos == {"latitude": 0.5, "longitude": -0.5, "bearing": 90.0}
  assert C.OwnGps(sm_factory=lambda: SM(fix(speed=0.5))).update() is None      # never saw a trusted heading
  assert C.OwnGps(sm_factory=lambda: SM(fix(has=False))).update() is None
  assert C.OwnGps(sm_factory=lambda: SM(fix(acc=80.0))).update() is None


def test_own_gps_failure_is_harmless():
  def boom():
    raise RuntimeError("no msgq")
  g = C.OwnGps(sm_factory=boom)
  assert g.update() is None and g.update() is None


def test_context_uses_own_gps_only_when_wanted(tmp_path):
  mem = MemParams(tmp_path)
  ctx = C.MapContext(mem=mem, own_gps=C.OwnGps(sm_factory=lambda: SM(fix())))
  ctx.update(15.0, 0, 0)
  assert ctx.gps_position is None
  ctx.want_own_gps = True
  ctx.update(15.0, 0, 0)
  assert ctx.gps_position["latitude"] == 0.5


def test_time_validated():
  import datetime
  assert C.time_validated(datetime.datetime(2026, 1, 1)) and not C.time_validated(datetime.datetime(2000, 1, 1))
