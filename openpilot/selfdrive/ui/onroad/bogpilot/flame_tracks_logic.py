"""BogPilot 88 mph flame tire tracks — trigger logic (no UI deps).

Port of frogpilot/ui/qt/onroad/bsm_flame_tracks.h FlameTrigger / constants.
Paint lives in flame_tracks.py. Kept separate so host-side unit tests do not need pyray.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MPH_TO_MS = 0.44704
TRIGGER_SPEED_MS = 88.0 * MPH_TO_MS  # 39.3392 m/s; strictly faster than this
DURATION_MS = 3000
GRACE_MS = 500
# Flame tongue height. 1.0 = original tall; 0.55 = classic low tongues (fc276dd43 / 047561a56).
FLAME_HEIGHT_SCALE = 0.55
TOGGLE_KEY = "BSMFlameTracks"
TOGGLE_DEFAULT = True  # missing/unknown file = on; must match file_toggles + offroad toggle


@dataclass
class FlameSideInput:
  red_fill_shown: bool = False
  lead_status: bool = False
  lead_v: float = 0.0


@dataclass
class _Side:
  red_was: bool = False
  arm_until_ms: float = -1
  start_ms: float = -1


@dataclass
class FlameTrigger:
  """Edge-triggered: one burn per red-fill off edge. Index 0 = left, 1 = right."""

  side: list = field(default_factory=lambda: [_Side(), _Side()])

  def update(self, now_ms: float, enabled: bool, inputs: list[FlameSideInput]) -> None:
    for i in range(2):
      s, inp = self.side[i], inputs[i]
      if not enabled:
        self.side[i] = _Side()
        continue
      if s.red_was and not inp.red_fill_shown:
        s.arm_until_ms = now_ms + GRACE_MS
      if inp.red_fill_shown:
        s.arm_until_ms = -1
      s.red_was = inp.red_fill_shown
      fast = inp.lead_status and inp.lead_v > TRIGGER_SPEED_MS
      if s.arm_until_ms >= 0 and now_ms <= s.arm_until_ms and fast:
        s.start_ms = now_ms
        s.arm_until_ms = -1
      elif s.arm_until_ms >= 0 and now_ms > s.arm_until_ms:
        s.arm_until_ms = -1
      if s.start_ms >= 0 and now_ms - s.start_ms >= DURATION_MS:
        s.start_ms = -1

  def active(self, i: int) -> bool:
    return self.side[i].start_ms >= 0

  def any_active(self) -> bool:
    return self.active(0) or self.active(1)

  def progress(self, i: int, now_ms: float) -> float:
    if not self.active(i):
      return -1.0
    return min(1.0, max(0.0, (now_ms - self.side[i].start_ms) / DURATION_MS))
