"""BogPilot confidence ball: logic (no UI deps, so host-side tests do not need pyray).

Port of BogPilot 0.9.7 frogpilot/ui/qt/onroad/confidence_ball.h, itself a port of openpilot
selfdrive/ui/mici/onroad/confidence_ball.py (MIT, Copyright (c) 2018, Comma.ai, Inc.). Same math, ball geometry and
colour values as 0.9.7 / stock:

  confidence = (1 - max(brakeDisengageProbs or [1])) * (1 - max(steerOverrideProbs or [1]))   (modelV2.meta.disengagePredictions)
  smoothed by a first-order filter, rc 0.5 s
  ball     : radius 27 px, margin 3 px, centre y = (1 - x) * (h - 2r - 2m) + r + m, in a 60 px strip (status border + camera margin)

Deliberate differences (docs/tesla/DIVERGENCES.md, onroad confidence ball):
  * Always shown. Stock and 0.9.7 drive the filter to -0.5 while disengaged, so the ball slides out below the screen
    (mici confidence_ball.py:38-39, 0.9.7 confidence_ball.h:181-182). Here the filter always follows the model, and starts at
    0 (bottom), so the ball is on screen in every state while the toggle is on.
  * Colours: the engaged palette (teal/green, yellow/orange, red) is used ONLY while the status is ENGAGED (the stock
    mici rule, confidence_ball.py:57). OVERRIDE uses the stock muted white-to-grey ball (mici :68-70, 0.9.7 :120-121);
    DISENGAGED and anything else use the stock dark ball (mici :72-74, 0.9.7 :123). Engagement itself is shown by the
    border only. Missing model data reads as confidence 0: bottom position; red only while engaged (stock / 0.9.7).

Settings (files under /data/params_bogpilot, written by the Appearance rows through the BogPilot store):
  ConfidenceBall      "0"/"false"/"off" hides the ball; anything else, or no file, shows it (0.9.7 default: ON)
  ConfidenceBallSide  "right" puts it on the right edge; anything else, or no file, the left edge (0.9.7 default: LEFT)
Display only. It never writes a setting and never touches control.
"""
from __future__ import annotations

STRIP_WIDTH = 60          # 2 * UI_BORDER_SIZE: the 30 px status border plus the 30 px camera margin
RADIUS = 27.0             # 54 px ball
MARGIN = 3.0
RC = 0.5                  # filter time constant, seconds
START = 0.0               # filter start: bottom of the strip (on screen). Stock / 0.9.7 start at -0.5 (off screen).
REREAD_S = 2.0            # 0.9.7 re-reads the two files every 2 s

TOGGLE_KEY = "ConfidenceBall"
SIDE_KEY = "ConfidenceBallSide"
TOGGLE_DEFAULT = True     # 0.9.7: no file = shown
SIDE_DEFAULT = "left"     # 0.9.7: no file = left edge

# (top, bottom) RGBA, exactly the 0.9.7 / comma four values
GREEN = ((0, 255, 204, 255), (0, 255, 38, 255))
ORANGE = ((255, 200, 0, 255), (255, 115, 0, 255))
RED = ((255, 0, 21, 255), (255, 0, 89, 255))
OVERRIDE = ((255, 255, 255, 255), (82, 82, 82, 255))
DARK = ((50, 50, 50, 255), (13, 13, 13, 255))
ENGAGED_PALETTE = (GREEN, ORANGE, RED)   # never used unless the status is ENGAGED


class FirstOrderFilter:
  """Same recurrence as openpilot.common.filter_simple.FirstOrderFilter (kept local so this module has no imports)."""

  def __init__(self, x0: float, rc: float, dt: float):
    self.x = x0
    self.dt = dt
    self.alpha = dt / (rc + dt)

  def update(self, x: float) -> float:
    self.x = (1.0 - self.alpha) * self.x + self.alpha * x
    return self.x


def max_or_one(probs) -> float:
  """Python `max(probs or [1])`: an empty or missing list counts as 1."""
  vals = [float(p) for p in (probs or [])]
  return max(vals) if vals else 1.0


def model_confidence(brake_disengage_probs, steer_override_probs) -> float:
  return (1.0 - max_or_one(brake_disengage_probs)) * (1.0 - max_or_one(steer_override_probs))


def engaged_status(status_name: str) -> bool:
  """Only ENGAGED gets the engaged palette (stock mici rule; stricter than 0.9.7, which treated every status except
  disengaged / override as engaged). 0.11.2 UIStatus has exactly DISENGAGED, ENGAGED and OVERRIDE."""
  return status_name == "ENGAGED"


def ball_colors(status_name: str, x: float):
  if engaged_status(status_name):
    if x > 0.5:
      return GREEN
    if x > 0.2:
      return ORANGE
    return RED
  if status_name == "OVERRIDE":
    return OVERRIDE
  return DARK


def ball_center_y(x: float, track_height: float, radius: float = RADIUS, margin: float = MARGIN) -> float:
  return (1.0 - x) * (track_height - 2.0 * radius - 2.0 * margin) + radius + margin


def strip_x(rect_x: float, rect_width: float, right: bool) -> float:
  return rect_x + rect_width - STRIP_WIDTH if right else rect_x


def ball_center_x(rect_x: float, rect_width: float, right: bool) -> float:
  return strip_x(rect_x, rect_width, right) + STRIP_WIDTH / 2.0


def pick_edge(prefer_right: bool, blocked_left: bool = False, blocked_right: bool = False):
  """The edge to draw on: the chosen one, unless something sits there (a flame track on that side) and the other edge is free.
  0.9.7 did the same for the map panel (useRightEdge). Both edges blocked -> None (hide the ball until one is free)."""
  if blocked_left and blocked_right:
    return None
  if prefer_right and blocked_right:
    return False
  if not prefer_right and blocked_left:
    return True
  return prefer_right


def strip_rect(rect_x: float, rect_y: float, rect_w: float, rect_h: float, right: bool):
  """(x, y, w, h) of the full-height strip the ball can occupy, in the coordinates of the onroad view incl. its border."""
  return (strip_x(rect_x, rect_w, right), rect_y, float(STRIP_WIDTH), rect_h)


def parse_toggle(text, default: bool = TOGGLE_DEFAULT) -> bool:
  if text is None:
    return default
  t = str(text).strip().lower()
  if t in ("0", "false", "off"):
    return False
  if t in ("1", "true", "on"):
    return True
  return default


def parse_side_right(text) -> bool:
  return False if text is None else str(text).strip().lower() == "right"


def circle_scanlines(radius: float = RADIUS):
  """Rows of a vertical-gradient disc: (dy from top, half width, gradient fraction 0..1). One entry per pixel row."""
  rows = []
  n = int(2 * radius)
  for i in range(n):
    y = i + 0.5 - radius
    half = max(0.0, radius * radius - y * y) ** 0.5
    rows.append((i, half, (i + 0.5) / (2 * radius)))
  return rows


def lerp_color(top, bottom, f: float):
  return tuple(int(round(t + (b - t) * f)) for t, b in zip(top, bottom, strict=True))


class ConfidenceBallState:
  """Per-frame state: the smoothed confidence, and the two settings re-read every REREAD_S seconds."""

  def __init__(self, read_toggle, read_side, clock, dt: float):
    self._read_toggle = read_toggle
    self._read_side = read_side
    self._clock = clock
    self.filter = FirstOrderFilter(START, RC, dt)
    self.enabled = TOGGLE_DEFAULT
    self.right = False
    self._next_read = -1.0

  def _reread(self):
    now = self._clock()
    if now >= self._next_read:
      self._next_read = now + REREAD_S
      try:
        self.enabled = bool(self._read_toggle())
      except Exception:
        self.enabled = TOGGLE_DEFAULT
      try:
        self.right = bool(self._read_side())
      except Exception:
        self.right = False

  def update(self, started: bool, status_name: str, brake_probs, steer_probs):
    """One UI frame. Returns True when the ball should be drawn: toggle on and started, in EVERY status (always shown).
    The height always follows the model, engaged or not; status only picks the colour (ball_colors)."""
    self._reread()
    self.filter.update(model_confidence(brake_probs, steer_probs))
    return bool(self.enabled and started)
