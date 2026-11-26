"""Save cadence for BogPilot state, matched to stock openpilot 0.11.2.

Stock saves learned values and counters on a 10 to 60 s cadence and never from a realtime step:
  * paramsd LiveParametersV2 and lagd LiveDelay: every 60 s
  * hardwared UptimeOnroad: every 60 s
  * power_monitoring CarBatteryCapacity: every 10 s
  * selfdrived LongitudinalPersonality: once per button press
BogPilot modules use the interval of their closest stock analog. A Checkpoint holds no data and does no IO: the module
marks it dirty when something worth saving changed, asks due() from its own loop, writes with its existing writer, then
calls saved(). flush() style extra saves (park, offroad, process stop) just skip the interval check.
"""
from __future__ import annotations

import math
import time
import zlib

LEARNED_INTERVAL_S = 60.0       # paramsd LiveParametersV2, lagd LiveDelay
COUNTER_INTERVAL_S = 60.0       # hardwared UptimeOnroad / UptimeOffroad
RATE_LIMITED_INTERVAL_S = 10.0  # power_monitoring CarBatteryCapacity
MIN_INTERVAL_S = 10.0           # stock's fastest periodic save; nothing here may save more often


def phase_fraction(name: str) -> float:
  """Stable 0..1 per name, so modules that start together do not all save at the same moment."""
  return (zlib.crc32(name.encode("utf-8")) % 1000) / 1000.0


class Checkpoint:
  def __init__(self, name: str, interval_s: float, clock=time.monotonic, first_at_once: bool = False):
    interval_s = float(interval_s)
    if not math.isfinite(interval_s) or interval_s < MIN_INTERVAL_S:
      raise ValueError(f"{name}: save interval {interval_s} s is below the stock {MIN_INTERVAL_S} s floor")
    self.name = name
    self.interval_s = interval_s
    self._clock = clock
    self.dirty = False
    self.saves = 0
    if first_at_once:
      self._last = -math.inf
    else:
      # The first periodic save comes between half and one interval after start, at a stable per name phase.
      self._last = clock() - 0.5 * interval_s * phase_fraction(name)

  def mark(self) -> None:
    self.dirty = True

  def due(self) -> bool:
    return self.dirty and (self._clock() - self._last) >= self.interval_s

  def saved(self) -> None:
    self.dirty = False
    self.saves += 1
    self._last = self._clock()
