"""comma 4 BogPilot layout painters (pyray). Geometry comes from c4_layout; every colour below is named."""
from __future__ import annotations

from dataclasses import dataclass

import pyray as rl

from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot.style import (C, W, MUTED, ACTUAL_GREEN, draw_text_in_rect_centred, fill_circle,
                                                           fill_rounded, panel, rect_lrtb, stroke_circle)

PILL_FILL = C(14, 17, 22, 190)            # wide-layout record / panel fill
PILL_STROKE = C(255, 255, 255, 40)
PILL_TEXT = C(255, 255, 255, 245)
PILL_DIVIDER = C(255, 255, 255, 40)
LIMIT_FILL, LIMIT_STROKE = C(244, 244, 242, 238), C(20, 20, 20, 255)
LIMIT_LABEL, LIMIT_INK = C(55, 55, 55, 255), C(14, 14, 14, 255)
SET_PX, SPEED_PX, LABEL_PX, LIMIT_LABEL_PX, LIMIT_PX = 24, 34, 10, 8, 20

BUTTON_FILL, BUTTON_RIM = C(14, 17, 22, 200), C(255, 255, 255, 60)
STRIPE = C(245, 245, 245, 240)
TRAFFIC = C(232, 70, 80)                  # redesign.paint_personality Traffic Mode colour
# take control: the stock wheel_critical.png colours (top -> bottom), white stripes, red '!' with a white border
CRIT_TOP, CRIT_BOTTOM = (255, 200, 1), (255, 114, 0)
CRIT_RIM, CRIT_STRIPE = C(255, 255, 255, 120), C(255, 255, 255, 255)
EXCL_RED, EXCL_BORDER = C(224, 32, 42, 255), C(255, 255, 255, 255)


@dataclass(frozen=True)
class PillInputs:
  set_speed: str            # "70" or the cruise-off dash
  speed: str
  unit: str
  engaged: bool
  show_limit: bool
  limit: str


def _o(r, ox, oy):
  return (r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)


def _centred(text, cx, cy, px, color, weight):
  draw_text_in_rect_centred(text, rl.Rectangle(cx - 60, cy - px, 120, 2 * px), px, color, weight)


def paint_pill(inp: PillInputs, ox: float = 0.0, oy: float = 0.0):
  """MAX (set speed) | current speed + unit | LIMIT tile in one capsule. Returns the rects drawn."""
  x0, y0, x1, y1 = _o(C4.PILL, ox, oy)
  panel(rect_lrtb(x0, y0, x1, y1), C4.PILL_RADIUS, PILL_FILL, PILL_STROKE, 1.0)
  _centred(inp.set_speed, ox + C4.PILL_SET_CX, oy + 27, SET_PX, PILL_TEXT, W.BOLD)
  _centred("MAX", ox + C4.PILL_SET_CX, oy + 47, LABEL_PX, ACTUAL_GREEN if inp.engaged else MUTED, W.DEMI)
  dx = ox + C4.PILL_DIVIDER_X
  rl.draw_line_ex(rl.Vector2(dx + 0.5, oy + 14), rl.Vector2(dx + 0.5, oy + 50), 1.0, PILL_DIVIDER)
  _centred(inp.speed, ox + C4.PILL_SPEED_CX, oy + 27, SPEED_PX, PILL_TEXT, W.BOLD)
  _centred(inp.unit, ox + C4.PILL_SPEED_CX, oy + 49, LABEL_PX, MUTED, W.DEMI)
  out = {"speed pill": (x0, y0, x1, y1)}
  if inp.show_limit:
    lx0, ly0, lx1, ly1 = _o(C4.PILL_LIMIT, ox, oy)
    panel(rect_lrtb(lx0, ly0, lx1, ly1), 6, LIMIT_FILL, LIMIT_STROKE, 1.0)
    _centred("LIMIT", (lx0 + lx1) / 2, oy + 18, LIMIT_LABEL_PX, LIMIT_LABEL, W.BOLD)
    _centred(inp.limit, (lx0 + lx1) / 2, oy + 37, LIMIT_PX, LIMIT_INK, W.BOLD)
    out["limit tile"] = (lx0, ly0, lx1, ly1)
  return out


def _gradient_disc(cx, cy, r, top, bottom):
  """Vertical top -> bottom gradient disc, one 1 px row at a time (no shader)."""
  y = cy - r
  while y < cy + r:
    yc = y + 0.5
    dy = yc - cy
    half = (r * r - dy * dy) ** 0.5 if abs(dy) < r else 0.0
    t = (yc - (cy - r)) / (2 * r)
    col = C(*(int(round(top[i] + (bottom[i] - top[i]) * t)) for i in range(3)))
    if half > 0:
      rl.draw_rectangle_rec(rl.Rectangle(cx - half, y, 2 * half, 1.0), col)
    y += 1.0


def paint_personality_button(personality: int | None, traffic_mode: bool, take_control: bool,
                             ox: float = 0.0, oy: float = 0.0):
  """The lower-left personality button, which is also the personality indicator: 1 / 2 / 3 stripes for aggressive /
  standard / relaxed, one red stripe in Traffic Mode. Take control: orange disc, white stripes, red '!'."""
  cx, cy, r = ox + C4.PERSONALITY_CX, oy + C4.PERSONALITY_CY, C4.PERSONALITY_D / 2
  out = {"personality button": (cx - r, cy - r, cx + r, cy + r)}
  if take_control:
    _gradient_disc(cx, cy, r, CRIT_TOP, CRIT_BOTTOM)
    stroke_circle(cx, cy, r - 0.5, 1.0, CRIT_RIM)
    stripe = CRIT_STRIPE
  else:
    fill_circle(cx, cy, r, BUTTON_FILL)
    stroke_circle(cx, cy, r - 0.5, 1.0, TRAFFIC if traffic_mode else BUTTON_RIM)
    stripe = TRAFFIC if traffic_mode else STRIPE
  if traffic_mode:
    nb = 1
  elif personality is None:
    nb = 0
  else:
    nb = int(min(2, max(0, personality))) + 1
  sw, sh, pitch = C4.PERSONALITY_STRIPE_W, C4.PERSONALITY_STRIPE_H, C4.PERSONALITY_STRIPE_PITCH
  for k in range(nb):
    yb = cy - (nb - 1) * pitch / 2 + k * pitch
    fill_rounded(rl.Rectangle(cx - sw / 2, yb - sh / 2, sw, sh), sh / 2, stripe)
  if take_control:
    ex, ey0 = cx + r - 3, cy - r - 9
    bar, dot = (ex - 3, ey0, ex + 3, ey0 + 19), (ex - 3, ey0 + 22, ex + 3, ey0 + 28)
    for b in (bar, dot):
      fill_rounded(rect_lrtb(b[0] - 2, b[1] - 2, b[2] + 2, b[3] + 2), 4, EXCL_BORDER)
    for b in (bar, dot):
      fill_rounded(rect_lrtb(*b), 3, EXCL_RED)
    out["take-control !"] = (ex - 5, ey0 - 2, ex + 5, ey0 + 30)
  return out
