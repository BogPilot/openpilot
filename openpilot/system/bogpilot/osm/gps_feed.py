"""Position feed for mapd: 0.9.7 wrote LastGPSPosition from liveLocationKalman; 0.11.2 has no such service, so this
validates a gpsLocation message and writes the same {"latitude","longitude","bearing"} JSON.

Fail-closed: no valid fix, a poor fix, or a stale one removes LastGPSPosition (as 0.9.7 did when gpsOK was false),
so mapd stops producing new output and the reader's freshness check drops the limit.
"""
from __future__ import annotations

import json
import math

from openpilot.system.bogpilot.osm.memparams import MemParams

MAX_HORIZONTAL_ACCURACY_M = 30.0
MIN_BEARING_SPEED_MS = 3.0         # GNSS course over ground is noise below this
STALE_S = 3.0


def _finite(x):
  try:
    x = float(x)
  except (TypeError, ValueError):
    return None
  return x if math.isfinite(x) else None


def validate_fix(lat, lon, has_fix, h_acc, speed, bearing_deg):
  """Returns (lat, lon, bearing|None) when the fix is usable, else None. bearing None = not trustworthy yet."""
  if not has_fix:
    return None
  lat, lon, h_acc = _finite(lat), _finite(lon), _finite(h_acc)
  if lat is None or lon is None or h_acc is None:
    return None
  if abs(lat) > 90.0 or abs(lon) > 180.0 or (lat == 0.0 and lon == 0.0):
    return None
  if not (0.0 < h_acc <= MAX_HORIZONTAL_ACCURACY_M):
    return None
  speed, bearing = _finite(speed), _finite(bearing_deg)
  if speed is not None and bearing is not None and speed >= MIN_BEARING_SPEED_MS and 0.0 <= bearing < 360.0 + 1e-6:
    return lat, lon, bearing % 360.0
  return lat, lon, None


class GpsFeed:
  def __init__(self, mem: MemParams):
    self.mem = mem
    self.last_bearing = None
    self.last_fix_t = None
    self.published = False

  def update(self, now: float, lat, lon, has_fix, h_acc, speed, bearing_deg) -> bool:
    """Feed one gpsLocation sample (now = monotonic seconds). True when a position was published."""
    v = validate_fix(lat, lon, has_fix, h_acc, speed, bearing_deg)
    if v is None:
      return self._drop()
    lat, lon, bearing = v
    if bearing is not None:
      self.last_bearing = bearing
    if self.last_bearing is None:
      return self._drop()          # never publish a position without any trusted heading
    self.last_fix_t = now
    ok = self.mem.put("LastGPSPosition", json.dumps({"latitude": lat, "longitude": lon, "bearing": self.last_bearing}))
    self.published = ok
    return ok

  def tick(self, now: float) -> None:
    """Call every loop: remove the position when no valid sample arrived for STALE_S."""
    if self.published and (self.last_fix_t is None or now - self.last_fix_t > STALE_S):
      self._drop()

  def _drop(self) -> bool:
    if self.published:
      self.mem.remove("LastGPSPosition")
    self.published = False
    return False
