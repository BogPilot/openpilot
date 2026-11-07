"""Pure placement/freshness policy; no camera, Params, or alert generation."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Box:
  x: float
  y: float
  width: float
  height: float

  def overlaps(self, other):
    return (self.x < other.x + other.width and self.x + self.width > other.x and
            self.y < other.y + other.height and self.y + self.height > other.y)


def box(r):
  return Box(*r) if isinstance(r, (tuple, list)) else Box(r.x, r.y, r.width, r.height)


def placement(rect, rhd=False, personality=False, keepouts=()):
  """Screen-space 150px daily DM, content-space centre (251/105,900).

  Compact uses its native mici UI, never a scaled C3X face. Obstacles include
  current capsule/graph, alert and other controls, EXCLUDING DM's own reservation.
  None means keep the native DM, not suppress it. No arbitrary moving target.
  """
  r = box(rect)
  if r.width < 1800 or r.height < 975:
    return None
  x = 251 if personality else 105
  cx = r.x + (r.width - x if rhd else x)
  b = Box(cx - 75, r.y + 825, 150, 150)
  if b.x < r.x or b.y < r.y or b.x + b.width > r.x + r.width or b.y + b.height > r.y + r.height:
    return None
  return None if any(b.overlaps(box(k)) for k in keepouts) else b


def fresh(sm, now, started_frame, drive_start):
  """Both native DM topics must be valid/alive, <=0.5s and current-drive."""
  try:
    return all(sm.alive[k] and sm.valid[k] and sm.recv_frame[k] > started_frame and
               math.isfinite(sm.recv_time[k]) and drive_start <= sm.recv_time[k] <= now and
               now - sm.recv_time[k] <= 0.5 for k in ('driverStateV2', 'driverMonitoringState'))
  except (AttributeError, KeyError, TypeError):
    return False
