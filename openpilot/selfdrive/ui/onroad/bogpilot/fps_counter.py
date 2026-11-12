"""FPS counter: one line at the bottom of the driving screen (0.9.7 FPS Display), display only.

"FPS: 20 | Min: 19 | Max: 21 | Avg: 20". FPS is the number of frames drawn in the last second. Min and max cover the current
drive; the average covers the last 60 seconds. Nothing here writes a param, a file or a message.
"""
from __future__ import annotations

from collections import deque

WINDOW_S = 1.0
AVG_WINDOW_S = 60.0
FONT_PX = 28
BOTTOM_GAP = 5


class FpsTracker:
  def __init__(self):
    self.reset()

  def reset(self):
    self._frames: deque = deque()
    self._history: deque = deque()   # (time, fps) over AVG_WINDOW_S
    self._total = 0.0
    self._start = None
    self.fps = 0.0
    self.min_fps = None
    self.max_fps = None

  def frame(self, now: float) -> None:
    """Call once per drawn frame with a monotonic clock."""
    if self._frames and now < self._frames[-1]:   # clock went backwards: start over
      self.reset()
    if self._start is None:
      self._start = now
    self._frames.append(now)
    while self._frames and now - self._frames[0] >= WINDOW_S - 1e-6:   # half-open window: a steady 20 Hz reads 20
      self._frames.popleft()
    if now - self._start < WINDOW_S - 1e-6:   # not a full second of frames yet
      return
    self.fps = float(len(self._frames))
    self.min_fps = self.fps if self.min_fps is None else min(self.min_fps, self.fps)
    self.max_fps = self.fps if self.max_fps is None else max(self.max_fps, self.fps)
    self._history.append((now, self.fps))
    self._total += self.fps
    while self._history and now - self._history[0][0] > AVG_WINDOW_S:
      self._total -= self._history.popleft()[1]

  @property
  def avg_fps(self) -> float:
    return self._total / len(self._history) if self._history else 0.0

  def text(self) -> str:
    if self.min_fps is None:
      return "FPS: -"
    return f"FPS: {round(self.fps)} | Min: {round(self.min_fps)} | Max: {round(self.max_fps)} | Avg: {round(self.avg_fps)}"


def paint(text: str, rect) -> None:
  """Centered on the bottom edge of `rect` (a raylib Rectangle)."""
  import pyray as rl  # noqa: F401  (kept local: the logic above imports without raylib)
  from openpilot.selfdrive.ui.onroad.bogpilot.style import C, W, draw_text, text_width
  width = text_width(text, FONT_PX, W.DEMI)
  draw_text(text, rect.x + (rect.width - width) / 2, rect.y + rect.height - BOTTOM_GAP, FONT_PX, C(255, 255, 255), W.DEMI)
