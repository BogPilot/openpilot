"""BogPilot 88 mph flame tire tracks (port of bogpilot/ui/qt/onroad/bsm_flame_tracks.h).

When the red blind-spot lane fill on a side turns off and that side's adjacent radar lead is faster than 88 mph within
BSM_FLAME_WINDOW_MS (2222 ms), two burning tire tracks run down that lane for 3 s. Display only. Toggle: /data/params_bogpilot/BSMFlameTracks
(default on). Needs an adjacent-lane lead source (bogpilotRadarState); without it this never fires.

The tracks start at the passing car: they ignite at the lead's projected screen point and run down the lane to the
bottom of the screen (see paint_trail_from_car and docs/tesla/DIVERGENCES.md). paint_tracks() is the fail-closed
fallback when no car point is known.
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
  BSM_FLAME_WINDOW_MS,
  MPH_TO_MS,
  TOGGLE_DEFAULT,
  TOGGLE_KEY,
  TRIGGER_SPEED_MS,
  FlameSideInput,
  FlameTrigger,
)
from openpilot.selfdrive.ui.onroad.bogpilot.style import C, line, fill_convex, fill_circle

# Re-export for bogpilot_model and tests
__all__ = [
  "DURATION_MS",
  "FLAME_HEIGHT_SCALE",
  "BSM_FLAME_WINDOW_MS",
  "MPH_TO_MS",
  "TOGGLE_DEFAULT",
  "TOGGLE_KEY",
  "TRIGGER_SPEED_MS",
  "FlameSideInput",
  "FlameTrigger",
  "FlameTracks",
  "paint_tracks",
  "paint_trail_from_car",
  "trail_span",
  "trail_tracks",
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


# ---- Tracks from the passing car down the lane ------------------------------------------------------------------
# paint_tracks() above indexes the lane polygon from its far end (i = 0 is the far point of the 0.11.2 polygon), so it
# lights the lane from the horizon down. The trail below starts at the passing car instead: at ignition it is anchored
# on the adjacent lead's screen point (BlindspotOverlay._bp_adjacent_points, the same calibrated projection as the
# adjacent lead box), a ring flashes there, the front runs down the lane to the screen bottom, and the tracks burn out
# from the car end downward. Same palette, flame tongues, 3 s burn and trigger as paint_tracks().

# True: the top of the trail follows the car every frame, so the flames stay behind it as it pulls away.
# False: the top stays on the screen point captured at ignition. Either way, no car point -> paint_tracks().
TRAIL_FOLLOWS_CAR = True
TRAIL_SAMPLES = 36           # points per track, index 0 = screen bottom, TRAIL_SAMPLES - 1 = car end
TRAIL_FRONT_FRAC = 1.0 / 6.0  # front reaches the screen bottom after 0.5 s of the 3 s burn
TRAIL_BURNOUT_FROM = 0.6     # burn-out runs from the car end down over the last 1.2 s (paint_tracks' fade window)
TRAIL_FLASH_FRAC = 0.2       # ring flash at the car for the first 0.6 s
TRAIL_ACROSS = (0.3, 0.7)    # track positions across the lane, as in paint_tracks()


def _envelope(t: float, fade_in: float, fade_out_from: float) -> float:
  a = min(1.0, t / fade_in) if fade_in > 0 else 1.0
  if t > fade_out_from:
    a *= max(0.0, 1.0 - (t - fade_out_from) / (1.0 - fade_out_from))
  return a


def _flow(u: float, now_ms: float, k: float, period_ms: float) -> float:
  """Bright bands that travel toward larger u (from the car toward the screen bottom) as time goes on."""
  return 0.5 + 0.5 * math.sin(2.0 * math.pi * (k * u - now_ms / period_ms))


def _fire_segment(a, b, w: float, alpha: float, flick: float) -> None:
  line(a[0], a[1], b[0], b[1], w * 2.2 * flick, _rgbf(1.0, 0.35, 0.0, 0.55 * alpha), round_cap=True)
  line(a[0], a[1], b[0], b[1], w * 1.1 * flick, _rgbf(1.0, 0.75, 0.1, 0.8 * alpha), round_cap=True)
  line(a[0], a[1], b[0], b[1], max(1.0, w * 0.35), _rgbf(1.0, 1.0, 0.85, 0.9 * alpha), round_cap=True)


def _tongue(ax: float, ay: float, w: float, h: float, alpha: float, flick: float) -> None:
  tip = (ax + w * 0.15 * flick, ay - h)
  pts = _quad((ax - w * 0.6, ay), (ax - w * 0.2, ay - h * 0.6), tip) + _quad(tip, (ax + w * 0.4, ay - h * 0.5), (ax + w * 0.6, ay))[1:]
  fill_convex(pts, _rgbf(1.0, 0.5, 0.05, 0.45 * alpha))


def _resample(pts: np.ndarray, count: int) -> np.ndarray:
  seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
  s = np.concatenate(([0.0], np.cumsum(seg)))
  if s[-1] < 1e-3:
    return np.repeat(pts[:1], count, axis=0).astype(np.float32)
  q = np.linspace(0.0, s[-1], count)
  return np.stack((np.interp(q, s, pts[:, 0]), np.interp(q, s, pts[:, 1])), axis=1).astype(np.float32)


def _lane_track(lane: np.ndarray, across: float) -> np.ndarray:
  """Lane polyline near -> far (bottom of the screen first) at the given across-fraction."""
  n = len(lane) // 2
  pts = [_lane_point(lane, i, across) for i in range(n - 1, -1, -1)]
  return np.array([p for p in pts if p is not None], dtype=np.float32)


def _lane_width_at_y(lane: np.ndarray, y: float) -> float:
  n = len(lane) // 2
  if n < 2:
    return 0.0
  ys = np.array([float(_lane_point(lane, i, 0.5)[1]) for i in range(n)])
  ws = np.array([_lane_width_px(lane, i) for i in range(n)])
  order = np.argsort(ys)
  return float(np.interp(y, ys[order], ws[order]))


def _extend_down(track: np.ndarray, bottom: float) -> np.ndarray:
  """Continue a near -> far track along its nearest direction down to y = bottom (as extend_to_bottom does for the fill)."""
  if len(track) < 2 or track[0, 1] >= bottom:
    return track
  d = track[0] - track[min(3, len(track) - 1)]
  if d[1] <= 1e-3:
    return track
  return np.concatenate(((track[0] + (bottom - track[0, 1]) / d[1] * d)[None, :], track), axis=0).astype(np.float32)


def _finite_point(p):
  try:
    x, y = float(p[0]), float(p[1])
  except (TypeError, ValueError, IndexError):
    return None
  return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def trail_tracks(lane: np.ndarray, anchor, bottom: float) -> list[np.ndarray] | None:
  """The two tracks from the screen bottom (index 0) up the lane to the car (last index), or None.

  Each track is the lane polyline below the car, extended down to `bottom`. When the car sits so low that fewer than two
  lane points are below it, the two nearest lane points are used. Both tracks are then shifted so their top midpoint is
  exactly the anchor; the shift fades to zero at the screen bottom, so the lower trail keeps the lane geometry."""
  if lane is None or len(lane) < 4 or anchor is None:
    return None
  tracks = []
  for across in TRAIL_ACROSS:
    full = _lane_track(lane, across)
    if len(full) < 2:
      return None
    below = int(np.count_nonzero(full[:, 1] >= anchor[1] - 2.0))
    tracks.append(_resample(_extend_down(full[:max(2, below)], bottom), TRAIL_SAMPLES))
  shift = np.asarray(anchor, dtype=np.float32) - (tracks[0][-1] + tracks[1][-1]) / 2.0
  weight = np.linspace(0.0, 1.0, TRAIL_SAMPLES, dtype=np.float32)[:, None]
  return [tr + shift * weight for tr in tracks]


def _trail_progress(t: float) -> tuple[float, float]:
  """(head, tail) as fractions of the trail measured from the car: how far the front has run down, and how far the
  burn-out has followed it."""
  head = min(1.0, max(0.0, t) / TRAIL_FRONT_FRAC)
  tail = min(1.0, max(0.0, (t - TRAIL_BURNOUT_FROM) / (1.0 - TRAIL_BURNOUT_FROM)))
  return head, tail


def trail_span(t: float) -> tuple[int, int]:
  """Lit segment indices [lo, hi) at burn progress t. The front grows from the car end (hi) down to index 0, then the
  burn-out moves hi down from the car end until nothing is left."""
  last = TRAIL_SAMPLES - 1
  head, tail = _trail_progress(t)
  return last - int(round(last * head)), last - int(round(last * tail))


def paint_trail_from_car(lane: np.ndarray, anchor, view, t: float, now_ms: float) -> bool:
  """Paint the tracks from the car down the lane. Returns False (nothing painted) when the geometry is missing."""
  if view is None or t < 0:
    return False
  tracks = trail_tracks(lane, anchor, view[1] + view[3])
  if tracks is None:
    return False
  last = TRAIL_SAMPLES - 1
  env = _envelope(t, fade_in=0.03, fade_out_from=0.85)
  lo, hi = trail_span(t)
  head_u, tail_u = _trail_progress(t)
  w_near = max(6.0, view[2] * 0.011)
  for tr, across in zip(tracks, TRAIL_ACROSS, strict=True):
    for j in range(lo, hi):
      a, b = tr[j], tr[j + 1]
      u = (last - j) / last                    # 0 at the car, 1 at the screen bottom
      lw = _lane_width_at_y(lane, float(a[1]))
      wid = max(2.0, 0.07 * lw if lw > 0 else w_near * (0.35 + 0.65 * u))
      flick = 0.75 + 0.25 * math.sin(now_ms * 0.025 + j * 1.7 + across * 11.0)
      edge = min(1.0, (hi - j) / 4.0)          # soft burnt-out edge at the car end
      alpha = env * edge * (0.5 + 0.5 * _flow(u, now_ms, k=4.0, period_ms=300.0))
      _fire_segment(a, b, wid, alpha, flick)
    for m in range(9):                         # flame tongues stream down the track
      u = (m / 9.0 + now_ms / 900.0) % 1.0
      if not tail_u <= u <= head_u:
        continue
      p = tr[last - min(last, int(u * last))]
      lw = _lane_width_at_y(lane, float(p[1]))
      wid = max(2.0, 0.07 * lw if lw > 0 else w_near)
      flick = 0.75 + 0.25 * math.sin(now_ms * 0.03 + m * 2.3)
      _tongue(float(p[0]), float(p[1]), wid, FLAME_HEIGHT_SCALE * wid * (3.0 + 1.5 * flick), env, flick)
  if t < TRAIL_FLASH_FRAC:                     # ring flash at the car at ignition
    k = t / TRAIL_FLASH_FRAC
    cx, cy = float(anchor[0]), float(anchor[1])
    r = w_near * (2.0 + 9.0 * k)
    ring = _rgbf(1.0, 0.95, 0.7, 0.85 * (1.0 - k))
    for q in range(24):
      a0, a1 = 2 * math.pi * q / 24, 2 * math.pi * (q + 1) / 24
      line(cx + r * math.cos(a0), cy + r * 0.45 * math.sin(a0), cx + r * math.cos(a1), cy + r * 0.45 * math.sin(a1),
           max(2.0, w_near * 0.6 * (1.0 - k)), ring)
    fill_circle(cx, cy, w_near * 1.8 * (1.0 - k), _rgbf(1.0, 1.0, 0.9, 0.8 * (1.0 - k)))
  return True


class FlameTracks:
  def __init__(self):
    self.trigger = FlameTrigger()
    self.targets = [None, None]          # per side: adjacent lead screen point, set by the model renderer each frame
    self.view = None                     # (x, y, w, h) of the road view, set by the model renderer each frame
    self.ignition_point = [None, None]   # per side: car screen point captured when the current burn started
    self._burn_start_ms = [-1.0, -1.0]

  def update_and_paint(self, inputs: list[FlameSideInput], lanes: list[np.ndarray], now_ms: float | None = None) -> None:
    now = time.monotonic() * 1000 if now_ms is None else now_ms
    enabled = toggles.get(TOGGLE_KEY)
    self.trigger.update(now, enabled, inputs)
    if not enabled:
      return
    for i in range(2):
      if not self.trigger.active(i):
        continue
      t = self.trigger.progress(i, now)
      start_ms = self.trigger.side[i].start_ms
      if start_ms != self._burn_start_ms[i]:   # new burn: capture where the car is right now
        self._burn_start_ms[i] = start_ms
        self.ignition_point[i] = _finite_point(self.targets[i]) if self.targets[i] is not None else None
      if self._paint_from_car(i, lanes[i], t, now):
        continue
      if lanes[i] is not None and len(lanes[i]):
        paint_tracks(lanes[i], t, now)

  def _paint_from_car(self, i: int, lane, t: float, now: float) -> bool:
    """Fail closed: no car point at ignition -> False for the whole burn; in follow mode a frame without a car point
    -> False for that frame. False means the caller paints the base tracks."""
    if self.ignition_point[i] is None:
      return False
    if TRAIL_FOLLOWS_CAR:
      anchor = _finite_point(self.targets[i]) if self.targets[i] is not None else None
    else:
      anchor = self.ignition_point[i]
    return anchor is not None and paint_trail_from_car(lane, anchor, self.view, t, now)
