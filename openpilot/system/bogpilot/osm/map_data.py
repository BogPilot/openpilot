"""Map Data source: validated reader of mapd's MapSpeedLimit / NextMapSpeedLimit (0.9.7 update_map_speed_limit).

This is the producer side only. Nothing here changes planner behaviour. The planner-side SpeedLimitController
(phase3_speed_control.SpeedLimitController.map_speed_limit) calls MapDataReader.read().

Safety bounds (stricter than 0.9.7, which trusted whatever file mapd had last written):
  - limit must be finite and MIN_LIMIT_MS <= v <= MAX_LIMIT_MS, else 0 (no limit)
  - the MapSpeedLimit file must have been written within FRESH_S (mapd keeps the old file when it loses its tile)
  - a position must have been published to mapd within POSITION_FRESH_S, i.e. the feed is alive
  - NextMapSpeedLimit + distance are reported for the planner's early-slowdown ceiling; this reader never swaps the current limit
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from openpilot.system.bogpilot.osm.memparams import MemParams

MIN_LIMIT_MS = 1.0        # speed_limit_controller.update_limits: limits below 1 m/s are "no limit"
MAX_LIMIT_MS = 45.0       # ~100 mph; Offset7 band tops out at 99 mph
FRESH_S = 3.0
POSITION_FRESH_S = 3.0
EARTH_RADIUS = 6373000.0  # mapd settings/const.go R, and BogPilot EARTH_RADIUS


def _limit(x) -> float:
  try:
    x = float(x)
  except (TypeError, ValueError):
    return 0.0
  return x if math.isfinite(x) and MIN_LIMIT_MS <= x <= MAX_LIMIT_MS else 0.0


def haversine_m(lat1, lon1, lat2, lon2) -> float:
  if not all(math.isfinite(x) for x in (lat1, lon1, lat2, lon2)):
    return math.nan
  p1, p2 = math.radians(lat1), math.radians(lat2)
  dp, dl = p2 - p1, math.radians(lon2 - lon1)
  a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
  return 2 * EARTH_RADIUS * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class MapData:
  limit: float = 0.0          # m/s, 0 = none (always the current way limit)
  current: float = 0.0        # m/s, mapd's current way limit
  next_limit: float = 0.0     # m/s, 0 = none
  distance_to_next: float = 0.0
  lookahead_applied: bool = False


NO_DATA = MapData()


class MapDataReader:
  def __init__(self, mem: MemParams):
    self.mem = mem

  def _fresh(self, key: str, now: float, max_age: float) -> bool:
    age = self.mem.age_s(key, now)
    return age is not None and 0.0 <= age <= max_age

  def read(self, position, v_ego: float, lookahead_higher_s: float = 0.0, lookahead_lower_s: float = 0.0,
           now: float | None = None) -> MapData:
    """position = {"latitude","longitude"} of the car (same fused/gps source that fed mapd) or None."""
    if not position:
      return NO_DATA
    import time as _t
    now = _t.time() if now is None else now
    if not self._fresh("LastGPSPosition", now, POSITION_FRESH_S) or not self._fresh("MapSpeedLimit", now, FRESH_S):
      return NO_DATA
    try:
      cur = _limit(json.loads(self.mem.get_text("MapSpeedLimit") or "0"))
    except ValueError:
      return NO_DATA
    if cur == 0.0:
      return NO_DATA

    nxt, dist = 0.0, 0.0
    try:
      nd = json.loads(self.mem.get_text("NextMapSpeedLimit") or "{}")
    except ValueError:
      nd = {}
    if isinstance(nd, dict) and self._fresh("NextMapSpeedLimit", now, FRESH_S):
      nxt = _limit(nd.get("speedlimit", 0))
      if nxt:
        try:
          lat, lon = float(position["latitude"]), float(position["longitude"])
          nlat, nlon = float(nd["latitude"]), float(nd["longitude"])
          dist = haversine_m(lat, lon, nlat, nlon)
          if not math.isfinite(dist) or abs(nlat) > 90.0 or abs(nlon) > 180.0:
            nxt, dist = 0.0, 0.0
        except (KeyError, TypeError, ValueError):
          nxt, dist = 0.0, 0.0

    # Look-ahead is applied as a v_cruise ceiling in phase3_speed_control, not by swapping
    # the current Map Data limit. Higher/lower second arguments are accepted for compatibility
    # and ignored here. lookahead_applied stays False.
    _ = (v_ego, lookahead_higher_s, lookahead_lower_s)
    return MapData(cur, cur, nxt, dist, False)
