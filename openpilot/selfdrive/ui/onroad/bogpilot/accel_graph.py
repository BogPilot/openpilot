"""Port of frogpilot/ui/qt/onroad/accel_graph: 10 s rolling plot of the longitudinal acceleration command
(carControl.actuators.accel) against the measured acceleration (carState.aEgo)."""
from __future__ import annotations
import math
from collections import deque

import pyray as rl

from openpilot.selfdrive.ui.onroad.bogpilot.style import (
  C, W, MUTED, TEXT, ACTUAL_GREEN, panel, line, polyline, fill_circle, draw_text, text_width, cap_height, clamp,
)

DESCENT = 495 / 2048


def _baseline_vcenter(y: float, h: float, size: float) -> float:
  return y + h / 2 + cap_height(size) / 2


class AccelGraph:
  def __init__(self, hz: int = 20, seconds: float = 10.0):
    self.capacity = max(2, int(hz * seconds))
    self.seconds = seconds
    self._cmd: deque[float] = deque(maxlen=self.capacity)
    self._act: deque[float] = deque(maxlen=self.capacity)

  def push(self, cmd: float, actual: float) -> None:
    self._cmd.append(cmd if math.isfinite(cmd) else 0.0)
    self._act.append(actual if math.isfinite(actual) else 0.0)

  def clear(self) -> None:
    self._cmd.clear()
    self._act.clear()

  def __len__(self) -> int:
    return len(self._cmd)

  def range(self) -> float:
    m = 0.0
    for c, a in zip(self._cmd, self._act, strict=True):
      m = max(m, abs(c), abs(a))
    return clamp(math.ceil((m + 0.25) * 2.0) / 2.0, 1.5, 4.0)

  def paint(self, r: rl.Rectangle) -> None:
    panel(r, 26)
    x0, y0, x1, y1 = r.x, r.y, r.x + r.width, r.y + r.height

    draw_text("ACCEL", x0 + 26, _baseline_vcenter(y0 + 12, 40, 24), 24, MUTED, W.DEMI)
    draw_text(f"{int(round(self.seconds))} s", x0 + 116, _baseline_vcenter(y0 + 12, 40, 22), 22, C(255, 255, 255, 90), W.REGULAR)

    lx = x1 - 250
    line(lx, y0 + 32, lx + 34, y0 + 32, 4, TEXT, round_cap=True)
    draw_text("cmd", lx + 44, _baseline_vcenter(y0 + 12, 40, 22), 22, MUTED, W.MEDIUM)
    lx += 112
    line(lx, y0 + 32, lx + 34, y0 + 32, 4, ACTUAL_GREEN, round_cap=True)
    draw_text("actual", lx + 44, _baseline_vcenter(y0 + 12, 40, 22), 22, MUTED, W.MEDIUM)

    px0, py0, px1, py1 = x0 + 26, y0 + 64, x1 - 26, y1 - 22
    rng = self.range()

    def Y(v: float) -> float:
      return py0 + (py1 - py0) * (rng - clamp(v, -rng, rng)) / (2 * rng)

    grid = 2.0 if rng >= 3.0 else 1.0
    for v in (grid, -grid):
      line(px0, Y(v), px1, Y(v), 1.5, C(255, 255, 255, 22))
      label = f"{v:+.0f}"
      draw_text(label, px1 - text_width(label, 18, W.REGULAR), Y(v) - 4 - DESCENT * 18 * 1.026, 18, C(255, 255, 255, 80), W.REGULAR)
    line(px0, Y(0), px1, Y(0), 1.5, C(255, 255, 255, 55))

    n = len(self)
    if n >= 2:
      dx = (px1 - px0) / (self.capacity - 1)
      act = [(px1 - (n - 1 - i) * dx, Y(v)) for i, v in enumerate(self._act)]
      cmd = [(px1 - (n - 1 - i) * dx, Y(v)) for i, v in enumerate(self._cmd)]
      polyline(act, 5, ACTUAL_GREEN)
      polyline(cmd, 3.5, TEXT)
      fill_circle(px1, Y(self._act[-1]), 7, ACTUAL_GREEN)
