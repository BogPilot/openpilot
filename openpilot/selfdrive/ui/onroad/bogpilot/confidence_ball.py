"""BogPilot confidence ball on the driving screen (port of BogPilot 0.9.7's confidence ball; display only).

A small ball rides up and down a 60 px strip at the left edge (default) or right edge of the onroad view, covering the
status border and the camera margin. Its height comes from the driving model's own disengage predictions and its
colour from the UI status (see confidence_ball_logic for the exact math and colour rules). It is shown in every state
while the toggle is on: engaged (stock colours), override (stock muted grey), disengaged (slate grey at high
confidence fading to white at low, confidence_ball_logic.disengaged_color, shaded top to bottom like stock).

Settings (Appearance page, through the BogPilot store; default ON, left edge, as in 0.9.7):
  /data/params_bogpilot/ConfidenceBall      off hides it
  /data/params_bogpilot/ConfidenceBallSide  "right" puts it on the right edge

Draw order (augmented_road_view): after the status border and BEFORE the alert, so every alert paints over the ball;
no ball at all while a full-screen alert is showing.
Input: this is deliberately NOT a Widget. It has no rect, no mouse handlers and is never a child widget, so it never
receives touch events; a tap on the strip reaches AugmentedRoadView exactly as before.
Reads modelV2 and the UI status only. Never writes, never touches control. A failure disables only the ball.
"""
from __future__ import annotations

import time

import pyray as rl

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.onroad.bogpilot import confidence_ball_logic as L


def _read_toggle() -> bool:
  from openpilot.common.bogpilot_store import read_text
  return L.parse_toggle(read_text(L.TOGGLE_KEY), L.TOGGLE_DEFAULT)


def _read_side_right() -> bool:
  from openpilot.common.bogpilot_store import read_text
  return L.parse_side_right(read_text(L.SIDE_KEY))


def _fps() -> float:
  try:
    from openpilot.system.ui.lib.application import gui_app
    return float(gui_app.target_fps) or 20.0
  except Exception:
    return 20.0


class ConfidenceBallRenderer:
  def __init__(self, read_toggle=_read_toggle, read_side=_read_side_right, clock=time.monotonic, fps: float | None = None):
    self.state = L.ConfidenceBallState(read_toggle, read_side, clock, 1.0 / (fps if fps else _fps()))
    self.failed = False
    self.last_draw: tuple[float, float, tuple, tuple] | None = None   # (x, y, top, bottom) of the last drawn ball
    self.edge_right: bool | None = None   # edge used by the last frame (None: hidden)

  def _model_probs(self, sm):
    """Missing / unreadable modelV2 -> empty lists -> confidence 0 (stock `or [1]`): bottom of the strip."""
    try:
      p = sm['modelV2'].meta.disengagePredictions
      return list(p.brakeDisengageProbs), list(p.steerOverrideProbs)
    except Exception:
      return [], []

  def keepouts(self, content_rect) -> list:
    """Screen rects the HUD must keep clear while the ball is shown: the 60 px edge strip it rides in. `content_rect` is the camera
    view (the onroad view minus its 30 px border). Empty while the ball is off, failed or hidden."""
    if self.failed or self.edge_right is None or not self.state.enabled:
      return []
    from openpilot.selfdrive.ui import UI_BORDER_SIZE
    x, y, w, h = L.strip_rect(content_rect.x - UI_BORDER_SIZE, content_rect.y - UI_BORDER_SIZE,
                              content_rect.width + 2 * UI_BORDER_SIZE, content_rect.height + 2 * UI_BORDER_SIZE, self.edge_right)
    return [rl.Rectangle(x, y, w, h)]

  def hide(self) -> None:
    """Nothing drawn this frame (e.g. a full-screen alert owns the screen): no reservation either."""
    self.last_draw = None
    self.edge_right = None

  def render(self, rect, started: bool, status_name: str, sm, blocked=(False, False)) -> bool:
    """Draw the ball in `rect` (the onroad view incl. its border). Returns True when something was drawn.
    `blocked` = (left, right): a flame track is burning on that side, so the ball uses the other edge for those 3 s."""
    self.hide()
    if self.failed:
      return False
    try:
      brake, steer = self._model_probs(sm)
      drawn = self.state.update(started, status_name, brake, steer)
      edge = L.pick_edge(self.state.right, bool(blocked[0]), bool(blocked[1])) if drawn else None
      self.edge_right = edge
      if edge is None:
        return False
      x = self.state.filter.x
      cx = L.ball_center_x(rect.x, rect.width, edge)
      cy = rect.y + L.ball_center_y(x, rect.height)
      top, bottom = L.ball_colors(status_name, x)
      self._draw_ball(cx, cy, top, bottom)
      self.last_draw = (cx, cy, top, bottom)
      return True
    except Exception as exc:   # display only: never break the driving screen
      self.failed = True
      self.hide()
      cloudlog.error(f"bogpilot confidence ball disabled: {type(exc).__name__}")
      return False

  @staticmethod
  def _draw_ball(cx: float, cy: float, top, bottom) -> None:
    """A vertical gradient clipped to a circle, as 1 px rows (no black corner ring, so it never paints over the camera).
    Same top-to-bottom gradient as stock draw_circle_gradient (mici/onroad/confidence_ball.py:10-13), which paints
    rl.draw_rectangle_gradient_v under a black ring; the rows here keep the camera visible around the ball."""
    y0 = cy - L.RADIUS
    for i, half, frac in L.circle_scanlines():
      if half <= 0:
        continue
      r, g, b, a = L.lerp_color(top, bottom, frac)
      rl.draw_rectangle_rec(rl.Rectangle(cx - half, y0 + i, 2 * half, 1), rl.Color(r, g, b, a))
