"""BogPilot 88 mph flame tire tracks (port of frogpilot/ui/qt/onroad/bsm_flame_tracks.h).

When the red blind-spot lane fill on a side turns off and that side's adjacent radar lead is faster than 88 mph within
0.5 s, two burning tire tracks run down that lane for 3 s. Display only. Toggle: /data/params_bogpilot/BSMFlameTracks
(default on). Needs an adjacent-lane lead source (frogpilotRadarState); without it this never fires.
"""
from __future__ import annotations
import math
import time

import numpy as np
import pyray as rl

from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import toggles
from openpilot.selfdrive.ui.onroad.bogpilot.flame_tracks_logic import (
  DURATION_MS,
  FLAME_HEIGHT_SCALE,
  GRACE_MS,
  MPH_TO_MS,
  TOGGLE_DEFAULT,
  TOGGLE_KEY,
  TRIGGER_SPEED_MS,
  FlameSideInput,
  FlameTrigger,
)
from openpilot.selfdrive.ui.onroad.bogpilot.style import C, line, fill_convex

# Re-export for bogpilot_model and tests
__all__ = [
  "DURATION_MS",
  "FLAME_HEIGHT_SCALE",
  "GRACE_MS",
  "MPH_TO_MS",
  "TOGGLE_DEFAULT",
  "TOGGLE_KEY",
  "TRIGGER_SPEED_MS",
  "FlameSideInput",
  "FlameTrigger",
  "FlameTracks",
  "paint_tracks",
]


def _lane_point(poly: np.ndarray, i: int, across: float):
  n = len(poly) // 2
  if n < 2 or i < 0 or i >= n:
    return None
  left, right = poly[n + i], poly[n - 1 - i]
  return left + (right - left) * across


def _lane_width_px(poly: np.ndarray, i: int) -> float:
  n = len(poly) // 2
  if n < 2 or i < 0 or i >= n:
    return 0.0
  return float(np.linalg.norm(poly[n + i] - poly[n - 1 - i]))


def _quad(p0, c, p1, steps: int = 6):
  return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
           (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1]) for t in np.linspace(0, 1, steps)]


def _rgbf(r: float, g: float, b: float, a: float) -> rl.Color:
  return C(int(r * 255), int(g * 255), int(b * 255), int(max(0.0, min(1.0, a)) * 255))


def paint_tracks(lane: np.ndarray, t: float, now_ms: float) -> None:
  n = len(lane) // 2
  if n < 2 or t < 0:
    return
  reach = min(1.0, t / 0.2)
  fade = 1.0 if t < 0.6 else 1.0 - (t - 0.6) / 0.4
  last = max(1, int(round((n - 1) * reach)))
  for across in (0.3, 0.7):
    for i in range(last):
      a, b = _lane_point(lane, i, across), _lane_point(lane, i + 1, across)
      if a is None or b is None:
        continue
      w = max(2.0, _lane_width_px(lane, i) * 0.07)
      flick = 0.75 + 0.25 * math.sin(now_ms * 0.025 + i * 1.7 + across * 11.0)
      far = i / n
      alpha = min(1.0, max(0.0, fade * (1.0 - 0.6 * far)))
      line(a[0], a[1], b[0], b[1], w * 2.2 * flick, _rgbf(1.0, 0.35, 0.0, 0.55 * alpha), round_cap=True)
      line(a[0], a[1], b[0], b[1], w * 1.1 * flick, _rgbf(1.0, 0.75, 0.1, 0.8 * alpha), round_cap=True)
      line(a[0], a[1], b[0], b[1], max(1.0, w * 0.35), _rgbf(1.0, 1.0, 0.85, 0.9 * alpha), round_cap=True)
      if i % 2 == 0 and fade > 0.05:
        h = FLAME_HEIGHT_SCALE * w * (2.5 + 1.5 * flick) * (1.0 - 0.5 * far)
        ax, ay = float(a[0]), float(a[1])
        tip = (ax + w * 0.15 * flick, ay - h)
        pts = _quad((ax - w * 0.6, ay), (ax - w * 0.2, ay - h * 0.6), tip) + _quad(tip, (ax + w * 0.4, ay - h * 0.5), (ax + w * 0.6, ay))[1:]
        fill_convex(pts, _rgbf(1.0, 0.5, 0.05, 0.45 * alpha))


class FlameTracks:
  def __init__(self):
    self.trigger = FlameTrigger()

  def update_and_paint(self, inputs: list[FlameSideInput], lanes: list[np.ndarray], now_ms: float | None = None) -> None:
    now = time.monotonic() * 1000 if now_ms is None else now_ms
    enabled = toggles.get(TOGGLE_KEY)
    self.trigger.update(now, enabled, inputs)
    if not enabled:
      return
    for i in range(2):
      if self.trigger.active(i) and lanes[i] is not None and len(lanes[i]):
        paint_tracks(lanes[i], self.trigger.progress(i, now), now)
