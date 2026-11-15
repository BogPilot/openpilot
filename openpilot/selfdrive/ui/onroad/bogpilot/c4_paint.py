"""comma 4 BogPilot layout painters (pyray). Geometry comes from c4_layout; every colour below is named."""
from __future__ import annotations

from dataclasses import dataclass

import pyray as rl

from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot.style import (C, W, MUTED, ACTUAL_GREEN, draw_text_in_rect_centred, fill_circle,
                                                           fill_rounded, panel, rect_lrtb, stroke_circle, stroke_rounded,
                                                           text_width)

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

# three-bar gauge: translucent track with a 1 px white outline, fill inset 2 px
GAUGE_TRACK, GAUGE_OUTLINE = C(255, 255, 255, 34), C(255, 255, 255, 90)
GAUGE_TRACK_R, GAUGE_FILL_R, GAUGE_INSET = 3, 2, 2

# record button (wide-layout paint_record_button colours)
REC_FILL, REC_RING, REC_DOT = C(14, 17, 22, 190), C(255, 255, 255, 60), C(225, 60, 60, 240)
REC_SQUARE = C(225, 60, 60, 235)

# lead boxes and speed labels
LEAD_SHADOW = C(0, 0, 0, 60)
LABEL_BG_PRIMARY, LABEL_BG_ADJ = C(20, 22, 26, 190), C(20, 22, 26, 165)
LABEL_INK_PRIMARY = C(255, 255, 255, 255)
ACCENTS = {"red": C(255, 0, 0, 255), "amber": C(255, 188, 0, 255)}


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


def gauge_bar_rects(rect, n=3):
  """Split a gauge rect (x0, y0, x1, y1) into n equal bars separated by C4.GAUGE_BAR_GAP."""
  x0, y0, x1, y1 = rect
  gap = C4.GAUGE_BAR_GAP
  bw = (x1 - x0 - gap * (n - 1)) / n
  return tuple((x0 + i * (bw + gap), y0, x0 + i * (bw + gap) + bw, y1) for i in range(n))


def paint_gauge(state, rect, ox: float = 0.0, oy: float = 0.0):
  """Three-bar gauge (brake | regen | accel) from a gauge state (fills + colours) in rect. Returns the bar rects and
  the fill rects drawn."""
  out = {"3-bar gauge": _o(rect, ox, oy)}
  fills = []
  for i, (bar, frac, rgb) in enumerate(zip(gauge_bar_rects(_o(rect, ox, oy)), state.fills, state.colours)):
    bx0, by0, bx1, by1 = bar
    fill_rounded(rect_lrtb(bx0, by0, bx1, by1), GAUGE_TRACK_R, GAUGE_TRACK)
    stroke_rounded(rect_lrtb(bx0, by0, bx1, by1), GAUGE_TRACK_R, 1.0, GAUGE_OUTLINE)
    if frac > 0.0:
      ih = (by1 - by0 - 2 * GAUGE_INSET) * min(1.0, frac)
      f = (bx0 + GAUGE_INSET, by1 - GAUGE_INSET - ih, bx1 - GAUGE_INSET, by1 - GAUGE_INSET)
      fill_rounded(rect_lrtb(*f), GAUGE_FILL_R, C(*rgb, 255))
      fills.append(f)
    else:
      fills.append(None)
  out["gauge fills"] = fills
  return out


def paint_arrow(tex, direction: int, ox: float = 0.0, oy: float = 0.0):
  """Green stock turn-signal arrow at the comma 4 arrow spot (left under the pill, right under the DM icon)."""
  tx, ty = C4.arrow_tex_origin(direction)
  src = rl.Rectangle(0, 0, tex.width if direction < 0 else -tex.width, tex.height)
  rl.draw_texture_pro(tex, src, rl.Rectangle(ox + tx, oy + ty, C4.ARROW_TEX_W, C4.ARROW_TEX_H), rl.Vector2(0, 0), 0.0,
                      rl.WHITE)
  return {f"lane-change arrow ({'left' if direction < 0 else 'right'}, core)": _o(C4.arrow_core_rect(direction), ox, oy)}


def paint_turn_intent(tex_left, tex_right, direction: int, alpha: float, rotation: float, ox: float = 0.0, oy: float = 0.0):
  """Stock TurnIntent arrow over the personality button (stock filter values), rotated about the button centre."""
  if alpha <= 1e-2:
    return {}
  tex = tex_right if direction == 1 else tex_left
  r = C4.turn_intent_rect()
  cx, cy = ox + C4.PERSONALITY_CX, oy + C4.PERSONALITY_CY
  src = rl.Rectangle(0, 0, tex.width, tex.height)
  dest = rl.Rectangle(cx, cy, C4.TURN_INTENT_W, C4.TURN_INTENT_H)
  origin = rl.Vector2(C4.TURN_INTENT_W / 2, C4.PERSONALITY_CY - r[1])
  rl.draw_texture_pro(tex, src, dest, origin, rotation, rl.Color(255, 255, 255, int(255 * min(1.0, alpha))))
  return {"turn intent (over button)": _o(r, ox, oy)}


def paint_record_button(status: str, pulse: float, ox: float = 0.0, oy: float = 0.0):
  """comma 4 record button: paint_record_button scaled to C4.REC_D. status: "idle", "starting", "recording", "error"
  (screen_recorder.status). Returns its rect."""
  cx, cy = ox + C4.REC_CX, oy + C4.REC_CY
  if status == "recording":
    rr, sw, sq, sr = C4.record_ring_recording()
    glow = C(225, 60, 60, int(255 * (0.4 + 0.6 * max(0.0, min(1.0, pulse)))))
    fill_circle(cx, cy, rr, REC_FILL)
    stroke_circle(cx, cy, rr, sw, glow)
    fill_rounded(rl.Rectangle(cx - sq / 2, cy - sq / 2, sq, sq), sr, REC_SQUARE)
  else:
    rr, sw, dot = C4.record_ring()
    fill_circle(cx, cy, rr, REC_FILL)
    stroke_circle(cx, cy, rr, sw, REC_RING)
    fill_circle(cx, cy, dot, REC_DOT)
    r = C4.REC_D / 2
    if status == "starting":
      rl.draw_ring(rl.Vector2(cx, cy), r * 0.62, r * 0.70, 0, 360, 32, rl.Color(225, 60, 60, int(90 + 120 * pulse)))
    elif status == "error":
      rl.draw_ring(rl.Vector2(cx, cy), r * 0.62, r * 0.72, 0, 360, 32, rl.Color(255, 176, 32, 235))
  return {"record button": _o(C4.record_rect(), ox, oy)}


def paint_lead_box(box, color):
  """Thin rounded ring with a soft shadow and thick corner legs (the wide layout's lock box, drawn at comma 4 size)."""
  x0, y0, x1, y1 = box
  w, h = x1 - x0, y1 - y0
  stroke_rounded(rect_lrtb(x0 - 1, y0 - 1, x1 + 1, y1 + 1), 3, 3.0, LEAD_SHADOW)
  stroke_rounded(rect_lrtb(x0, y0, x1, y1), 2, 1.0, color)
  lw, lh = w * 0.30, h * 0.30
  for ax, ay, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
    rl.draw_line_ex(rl.Vector2(ax, ay), rl.Vector2(ax + sx * lw, ay), 2.0, color)
    rl.draw_line_ex(rl.Vector2(ax, ay), rl.Vector2(ax, ay + sy * lh), 2.0, color)


def label_ink(color, adjacent):
  if not adjacent:
    return LABEL_INK_PRIMARY
  return C(min(255, color.r + 70), min(255, color.g + 70), min(255, color.b + 70), 240)


def label_text_width(text, px):
  return text_width(text, px, W.BOLD)


def paint_speed_label(r, text, px, ink, bg, accent=None):
  x0, y0, x1, y1 = r
  fill_rounded(rect_lrtb(x0, y0, x1, y1), (y1 - y0) / 2, bg)
  draw_text_in_rect_centred(text, rect_lrtb(x0, y0, x1, y1), px, ink, W.BOLD)
  if accent in ACCENTS:
    tw = label_text_width(text, px)
    cx = (x0 + x1) / 2
    fill_rounded(rect_lrtb(cx - tw / 2, y1 - 4, cx + tw / 2, y1 - 2), 1, ACCENTS[accent])


def paint_leads(leads, v_ego, keepouts=(), alert_zone=None, side_mode=False, ox=0.0, oy=0.0):
  """Lead boxes (adjacent first, then the primary) and their speed labels. Returns the rects drawn."""
  from openpilot.selfdrive.ui.onroad.bogpilot.c4_leads import Comma4LeadStyle
  out = {}
  for ld in leads:
    adjacent = ld.key != "primary"
    color = Comma4LeadStyle.lead_distance_color(ld.d_rel, adjacent, v_ego)
    paint_lead_box(ld.box, color)
    name = f"lead box (adjacent {ld.key})" if adjacent else "lead box (primary)"
    out[name] = tuple(ld.box)
    if not ld.speed:
      continue
    px = C4.SPEED_PX_ADJ if adjacent else C4.SPEED_PX_PRIMARY
    lw, lh = C4.label_size(label_text_width(ld.speed, px), px)
    local = (ld.box[0] - ox, ld.box[1] - oy, ld.box[2] - ox, ld.box[3] - oy)
    r, where = C4.speed_label_rect(local, lw, lh, keepouts, alert_zone, side_mode, ld.key)
    r = _o(r, ox, oy)
    paint_speed_label(r, ld.speed, px, label_ink(color, adjacent), LABEL_BG_ADJ if adjacent else LABEL_BG_PRIMARY,
                      None if adjacent else ld.accent)
    out[(f"adjacent {ld.key} speed label" if adjacent else "lead speed label") + ("" if where == "above" else f" ({where})")] = r
  return out
