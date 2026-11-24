"""Planner-side inputs for the Speed Limit Controller's Map Data and Mapbox sources (0.9.7 update_map_speed_limit).

MapContext is what phase3_speed_control.SpeedLimitController consumes each planner tick:
  gps_position  - {"latitude","longitude","bearing"} or None, read from the LastGPSPosition file that bogpilot_mapd's
                  GpsFeed publishes (validated fix, removed when stale). 0.9.7 built the same dict in bogpilot_planner
                  from liveLocationKalman (absent in 0.11.2).
  map           - MapData: mapd's MapSpeedLimit with current + next + distance (look-ahead ceiling is applied in the planner)
  mapbox        - MapboxFiller (only with a user key; see mapbox.py)
Any problem (missing files, stale, garbage, import error) reads as "no data": Map Data = 0, never an exception.

mapd v2 (param MapdV2, default on): `map` comes from mapdOut (mapd_v2.shared_reader, fresh within 0.5 s) instead of the
v1 memparams. The same rule holds: no fresh GPS position (GpsFeed keeps running in both modes) = no map limit.
"""
from __future__ import annotations

import datetime
import json
import math
import time

from openpilot.system.bogpilot.osm.gps_feed import validate_fix
from openpilot.system.bogpilot.osm.map_data import NO_DATA, MapData, MapDataReader
from openpilot.system.bogpilot.osm.mapbox import MapboxFiller
from openpilot.system.bogpilot.osm.memparams import MemParams

ENGINE_RECHECK_S = 2.0

MIN_VALID_YEAR = 2025     # system clock sanity for the Mapbox monthly budget (0.9.7 used its time_validated flag)


def read_gps_position(mem: MemParams, now: float | None = None, max_age_s: float = 3.0):
  """LastGPSPosition -> dict or None (missing, stale, malformed, out of range)."""
  age = mem.age_s("LastGPSPosition", now)
  if age is None or not (0.0 <= age <= max_age_s):
    return None
  try:
    p = json.loads(mem.get_text("LastGPSPosition") or "{}")
    lat, lon, bearing = float(p["latitude"]), float(p["longitude"]), float(p["bearing"])
  except (KeyError, TypeError, ValueError):
    return None
  if not all(math.isfinite(x) for x in (lat, lon, bearing)) or abs(lat) > 90.0 or abs(lon) > 180.0:
    return None
  return {"latitude": lat, "longitude": lon, "bearing": bearing}


def time_validated(now_dt: datetime.datetime) -> bool:
  return now_dt.year >= MIN_VALID_YEAR


class OwnGps:
  """Position for the Mapbox filler when bogpilot_mapd is not running (no maps selected): the same validated fix
  (gps_feed.validate_fix) from gpsLocation / gpsLocationExternal through a private, non-polling SubMaster that is only
  created once the filler is really wanted (key present + toggle on). Heading is held from the last trusted one."""

  def __init__(self, sm_factory=None, wall=time.time):
    self._factory = sm_factory
    self._sm = None
    self._failed = False
    self._wall = wall
    self.last_bearing = None
    self.position = None
    self.t = None

  def _make(self):
    if self._sm is None and not self._failed:
      try:
        if self._factory is not None:
          self._sm = self._factory()
        else:
          from openpilot.cereal import messaging
          from openpilot.system.bogpilot.osm.supervisor import GPS_SERVICES
          self._sm = messaging.SubMaster(list(GPS_SERVICES))
      except Exception:
        self._failed = True
    return self._sm

  def update(self):
    sm = self._make()
    if sm is None:
      return None
    now = self._wall()
    try:
      sm.update(0)
      from openpilot.system.bogpilot.osm.supervisor import GPS_SERVICES
      for svc in GPS_SERVICES:
        if sm.updated[svc] and sm.valid[svc]:
          g = sm[svc]
          v = validate_fix(g.latitude, g.longitude, g.hasFix, g.horizontalAccuracy, g.speed, g.bearingDeg)
          if v is None:
            self.position = None
            continue
          lat, lon, bearing = v
          if bearing is not None:
            self.last_bearing = bearing
          if self.last_bearing is None:
            self.position = None
            continue
          self.position = {"latitude": lat, "longitude": lon, "bearing": self.last_bearing}
          self.t = now
    except Exception:
      self.position = None
    if self.t is None or now - self.t > 3.0:
      self.position = None
    return self.position


class MapContext:
  def __init__(self, mem: MemParams | None = None, store=None, mapbox: MapboxFiller | None = None, wall=time.time,
               now_dt=lambda: datetime.datetime.now(datetime.timezone.utc), own_gps=None, engine=None, v2_tick=None,
               mono=time.monotonic):
    self.mem = mem or MemParams()
    self.reader = MapDataReader(self.mem)
    self.mapbox = mapbox or MapboxFiller(store=store)
    self._wall = wall
    self._now_dt = now_dt
    self.gps_position = None
    self.map: MapData = NO_DATA
    self.own_gps = own_gps if own_gps is not None else OwnGps()
    self.want_own_gps = False     # set by the consumer: Mapbox filler enabled with a key
    self._store = store
    self._engine = engine         # callable -> bool (tests); default mapd_v2.engine_v2(store), re-read every 2 s
    self._v2_tick = v2_tick
    self._mono = mono
    self._engine_t = None
    self.v2 = False

  def _use_v2(self) -> bool:
    now = self._mono()
    if self._engine_t is None or now - self._engine_t >= ENGINE_RECHECK_S:
      self._engine_t = now
      try:
        if self._engine is not None:
          self.v2 = bool(self._engine())
        else:
          from openpilot.system.bogpilot.osm import mapd_v2
          self.v2 = mapd_v2.engine_v2(self._store)
      except Exception:
        self.v2 = False
    return self.v2

  def _read_v2(self) -> MapData:
    from openpilot.system.bogpilot.osm import mapd_v2
    if self._v2_tick is None:
      self._v2_tick = mapd_v2.SharedTick()
    d = self._v2_tick.get()
    if not d.fresh or d.speed_limit <= 0.0:
      return NO_DATA
    nxt = d.next_speed_limit if d.next_speed_limit > 0.0 else 0.0
    return MapData(d.speed_limit, d.speed_limit, nxt, d.next_distance if nxt else 0.0, False)

  def update(self, v_ego: float, lookahead_higher_s: float, lookahead_lower_s: float) -> MapData:
    """update_map_speed_limit inputs for this tick. 0.9.7 returned early (keeping the last value) without a GPS position;
    here no position = no map limit, so a stale value can never outlive the position feed."""
    try:
      now = self._wall()
      self.gps_position = read_gps_position(self.mem, now)
      if self.gps_position is None and self.want_own_gps:
        self.gps_position = self.own_gps.update()
      if not self.gps_position:
        self.map = NO_DATA
      elif self._use_v2():
        self.map = self._read_v2()
      else:
        self.map = self.reader.read(self.gps_position, v_ego, lookahead_higher_s, lookahead_lower_s, now=now)
    except Exception:
      self.gps_position, self.map = None, NO_DATA
    return self.map

  def now_dt(self):
    return self._now_dt()
