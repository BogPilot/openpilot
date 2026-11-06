"""Port of frogpilot/ui/qt/onroad/bogpilot_redesign.{h,cc}: speed row, personality button, lead lock-on box and labels,
record / no-GPS buttons, LKAS Fault border flash and the small / mid alert banner.

Everything is in widget space (screen minus the 30 px engage border); pass the content rect origin as ox, oy.
opview (gerrylum, Rick Lan non-commercial licence) was a visual reference only for the Qt original; no code from it is used.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

import pyray as rl

from openpilot.selfdrive.ui.onroad.bogpilot.style import (
  C, W, EDGE, SPEED_ROW_HEIGHT, SPEED_ROW_MIN_RIGHT, SPEED_PANEL, PANEL_DARK, MUTED, TEXT, STROKE, BADGE_GREEN, TRAFFIC_RED,
  REC_CX, REC_CY, REC_HIT, REC_DIAMETER, CLUSTER_LEFT, CLUSTER_CY, CLUSTER_D, CLUSTER_GAP, PILL_W, PILL_LABEL_SPACE,
  STACK_BOTTOM, PEDAL_W, PEDAL_H, PEDAL_GAP, NOGPS_CX, NOGPS_CY, ALERT_GAP, ALERT_RIGHT_MARGIN, LKAS_FAULT_FLASH_MS,
  LKAS_RED, LKAS_ORANGE, GRAPH_WIDTH, GRAPH_HEIGHT, speed_row_top, graph_top, panel, fill_rounded, stroke_rounded,
  fill_circle, stroke_circle, line, polyline, fill_convex, draw_text, draw_text_centred, draw_text_in_rect_centred, text_width,
  cap_height, spaced, rect, rect_lrtb, inflate, intersects, overlap_area, clamp, lerp_color, with_alpha,
)

CAP_RADIUS = 44
COL_MAX, COL_SPEED, COL_LIMIT = 140, 370, 612
DIV_1, DIV_2 = 250, 490
SIDE_PX, BIG_PX, LABEL_PX = 66, 100, 22
TILE_LABEL_PX = 16
SIGN_FILL = C(244, 244, 242, 238)
SIGN_EDGE = C(20, 20, 20)
SIGN_INK = C(14, 14, 14)
SIGN_LABEL = C(55, 55, 55)
CSC_AMBER = C(255, 176, 32)

WHITE_BELOW_V = 3.58   # m/s, 8 mph
ADJ_SPEED_MIN = 5
ADJ_LABEL_MARGIN = 8
ADJ_LABEL_OUTSIDE = 26
ADJ_LABEL_LEADER_MIN = 40
ADJ_LABEL_SLIDE_GAP = 4
ADJ_LABEL_BRACKET = 16


def baseline_y(swap: bool) -> float:
  return speed_row_top(swap) + 114


def label_baseline_y(swap: bool) -> float:
  return baseline_y(swap) + 36


def accel_graph_rect(swap: bool) -> rl.Rectangle:
  return rect(EDGE, graph_top(swap), GRAPH_WIDTH, GRAPH_HEIGHT)


# ---------------- speed row ----------------
@dataclass
class SpeedRowInputs:
  set_speed: str = "–"
  max_label: str = "MAX"
  max_color: rl.Color = field(default_factory=lambda: MUTED)
  set_speed_color: rl.Color = field(default_factory=lambda: TEXT)
  show_max: bool = True
  speed: str = "0"
  show_speed: bool = True
  unit: str = "MPH"
  show_limit: bool = False
  vienna: bool = False
  limit: str = "–"
  limit_label: str = "LIMIT"
  offset: str = ""
  limit_opacity: float = 1.0
  traffic_mode: bool = False
  csc_active: bool = False
  csc_training: bool = False
  csc_left: bool = True
  csc_speed: str = ""
  csc_label: str = ""
  csc_pulse: float = 0.0
  swap: bool = False


@dataclass
class SpeedRowGeometry:
  capsule: rl.Rectangle
  tile: rl.Rectangle | None = None
  badge: rl.Rectangle | None = None


def speed_row_geometry(inp: SpeedRowInputs) -> SpeedRowGeometry:
  y0 = speed_row_top(inp.swap)
  y1 = y0 + SPEED_ROW_HEIGHT
  base = baseline_y(inp.swap)
  x1 = DIV_2 + 14
  tile = badge = None
  if inp.show_limit:
    if inp.vienna:
      d = 128
      tx0, tx1 = COL_LIMIT - d / 2, COL_LIMIT + d / 2
      ty0 = base - 92
      ty1 = ty0 + d
    else:
      nw = text_width(inp.limit, SIDE_PX, W.BOLD)
      lw = text_width(inp.limit_label, TILE_LABEL_PX, W.BOLD)
      half = max(nw, lw) / 2 + 22
      tx0, tx1 = COL_LIMIT - half, COL_LIMIT + half
      ty0, ty1 = base - 92, base + 40
    tile = rect_lrtb(tx0, ty0, tx1, ty1)
    x1 = max(tx1 + 44, SPEED_ROW_MIN_RIGHT)
    if inp.offset:
      bw = text_width(inp.offset, 20, W.BOLD) + 18
      bx, by = tx1 - 4, max(ty0 + 2, y0 + 22)
      badge = rect(bx - bw / 2, by - 15, bw, 30)
  return SpeedRowGeometry(rect_lrtb(EDGE, y0, x1, y1), tile, badge)


def max_slot_rect(swap: bool) -> rl.Rectangle:
  top = speed_row_top(swap)
  return rect_lrtb(EDGE + 6, top + 6, DIV_1 - 6, top + SPEED_ROW_HEIGHT - 6)


def _o(r: rl.Rectangle, ox: float, oy: float) -> rl.Rectangle:
  return rl.Rectangle(r.x + ox, r.y + oy, r.width, r.height)


def paint_curve_glyph(cx: float, cy: float, size: float, color: rl.Color, left: bool, stroke: float) -> None:
  sgn = -1.0 if left else 1.0
  R = size * 0.30
  stem = cx - sgn * size * 0.16
  top = cy + size * 0.06
  pts = [(stem, cy + size * 0.48), (stem, top)]
  ccx = stem + sgn * R
  end = (stem, top)
  for i in range(1, 25):
    a = math.pi / 2 * i / 24
    end = (ccx - sgn * R * math.cos(a), top - R * math.sin(a))
    pts.append(end)
  polyline(pts, stroke, color)
  ah = size * 0.30
  fill_convex([(end[0] + sgn * ah * 0.75, end[1]), (end[0] - sgn * 0.02 * ah, end[1] - ah * 0.55),
               (end[0] - sgn * 0.02 * ah, end[1] + ah * 0.55)], color)


def paint_speed_row(inp: SpeedRowInputs, ox: float, oy: float) -> SpeedRowGeometry:
  g = speed_row_geometry(inp)
  cap = _o(g.capsule, ox, oy)
  y0, y1 = cap.y, cap.y + cap.height
  base = oy + baseline_y(inp.swap)
  lbase = oy + label_baseline_y(inp.swap)
  cmax, cspeed, climit = ox + COL_MAX, ox + COL_SPEED, ox + COL_LIMIT

  if inp.traffic_mode:
    panel(cap, CAP_RADIUS, SPEED_PANEL, TRAFFIC_RED, 5)
  else:
    panel(cap, CAP_RADIUS, SPEED_PANEL)

  if inp.csc_active:
    slot = _o(max_slot_rect(inp.swap), ox, oy)
    fill_rounded(slot, 38, C(255, 176, 32, 46))
    stroke_rounded(slot, 38, 3, C(255, 176, 32, 210))
    if inp.csc_label:
      paint_curve_glyph(cmax, y0 + 42, 42, CSC_AMBER, inp.csc_left, 7)
      draw_text_centred(inp.csc_speed, cmax, base + 8, 64, CSC_AMBER, W.DEMI)
      draw_text_centred(inp.csc_label, cmax, lbase + 8, 26, C(255, 205, 110, 245), W.DEMI)
    else:
      paint_curve_glyph(cmax, y0 + 50, 46, CSC_AMBER, inp.csc_left, 7.5)
      draw_text_centred(inp.csc_speed, cmax, base + 26, 70, CSC_AMBER, W.DEMI)
  else:
    if inp.csc_training:
      k = clamp(inp.csc_pulse, 0.0, 1.0)
      stroke_rounded(_o(max_slot_rect(inp.swap), ox, oy), 38, 2 + k, C(255, 176, 32, int(70 + 140 * k)))
      paint_curve_glyph(cmax, y0 + 42, 38, C(255, 176, 32, 200), inp.csc_left, 6)
    if inp.show_max or inp.csc_training:
      draw_text_centred(inp.set_speed, cmax, base + 8 if inp.csc_training else base, SIDE_PX, inp.set_speed_color, W.DEMI)
      draw_text_centred(inp.csc_label if inp.csc_training else spaced(inp.max_label), cmax,
                        lbase + 8 if inp.csc_training else lbase, 24 if inp.csc_training else LABEL_PX,
                        C(255, 205, 110, 220) if inp.csc_training else inp.max_color, W.DEMI)

  if inp.show_speed:
    draw_text_centred(inp.speed, cspeed, base, BIG_PX, C(255, 255, 255), W.BOLD)
    draw_text_centred(spaced(inp.unit.upper()), cspeed, lbase, LABEL_PX, MUTED, W.DEMI)

  div = C(255, 255, 255, 36)
  line(ox + DIV_1, y0 + 40, ox + DIV_1, y1 - 40, 2, div)
  if inp.show_limit:
    line(ox + DIV_2, y0 + 40, ox + DIV_2, y1 - 40, 2, div)

  if inp.show_limit and g.tile is not None:
    tile = _o(g.tile, ox, oy)
    op = clamp(inp.limit_opacity, 0.0, 1.0)

    def fa(c: rl.Color) -> rl.Color:
      return with_alpha(c, c.a * op)
    if inp.vienna:
      tcx, tcy, tr = tile.x + tile.width / 2, tile.y + tile.height / 2, tile.width / 2
      fill_circle(tcx, tcy, tr, fa(C(255, 255, 255)))
      stroke_circle(tcx, tcy, tr - 9, 13, fa(C(220, 30, 30)))
      draw_text_in_rect_centred(inp.limit, tile, 46 if len(inp.limit) >= 3 else 56, fa(SIGN_INK), W.BOLD)
    else:
      fill_rounded(tile, 20, fa(SIGN_FILL))
      stroke_rounded(tile, 20, 3, fa(SIGN_EDGE))
      # centre the LIMIT + number pair on their cap heights (Qt: tight ink bounds)
      lh, nh, gap = cap_height(TILE_LABEL_PX), cap_height(SIDE_PX), 10
      top = tile.y + tile.height / 2 - (lh + gap + nh) / 2
      draw_text_centred(inp.limit_label, climit, top + lh, TILE_LABEL_PX, fa(SIGN_LABEL), W.BOLD)
      draw_text_centred(inp.limit, climit, top + lh + gap + nh, SIDE_PX, fa(SIGN_INK), W.BOLD)

    if g.badge is not None:
      b = _o(g.badge, ox, oy)
      fill_rounded(b, 15, BADGE_GREEN)
      stroke_rounded(b, 15, 2, C(14, 17, 22))
      draw_text_centred(inp.offset, b.x + b.width / 2, b.y + b.height / 2 + 7, 20, C(255, 255, 255), W.BOLD)
  return g


# ---------------- personality ----------------
def personality_rect(rhd: bool, widget_w: float) -> rl.Rectangle:
  x = CLUSTER_LEFT
  if rhd:
    x = widget_w - CLUSTER_LEFT - PILL_W
  return rect(x, CLUSTER_CY - CLUSTER_D / 2, PILL_W, CLUSTER_D)


def paint_personality(pill: rl.Rectangle, personality: int, traffic_mode: bool, label: str) -> None:
  traffic = C(232, 70, 80)
  d = min(pill.width, pill.height)
  cx, cy = pill.x + pill.width / 2, pill.y + pill.height / 2
  disc = rect(cx - d / 2, cy - d / 2, d, d)
  panel(disc, d / 2, PANEL_DARK, traffic if traffic_mode else C(255, 255, 255, 60), 3)
  draw_text_in_rect_centred(label.upper(), rect(disc.x, disc.y - PILL_LABEL_SPACE, disc.width, PILL_LABEL_SPACE - 4), 20,
                            traffic if traffic_mode else C(255, 255, 255, 200), W.DEMI)
  nb = 1 if traffic_mode else int(clamp(personality, 0, 2)) + 1
  col = traffic if traffic_mode else C(245, 245, 245, 240)
  for k in range(nb):
    yb = cy - (nb - 1) * 15 + k * 30
    fill_rounded(rect(cx - 34, yb - 7.5, 68, 15), 7.5, col)


def personality_at(pill: rl.Rectangle, x: float, y: float, current: int) -> int:
  dx, dy = x - (pill.x + pill.width / 2), y - (pill.y + pill.height / 2)
  if dx * dx + dy * dy > (pill.width / 2) ** 2:
    return -1
  # aggressive=0, standard=1, relaxed=2: step down like the stalk (Relaxed -> Standard -> Aggressive)
  return (int(clamp(current, 0, 2)) + 2) % 3


# ---------------- lead box ----------------
def lead_distance_color(d_rel: float, adjacent: bool, v_ego: float) -> rl.Color:
  v = max(0.0, v_ego)
  far = C(150, 150, 155, 200) if adjacent else C(255, 255, 255, 245)
  if v < WHITE_BELOW_V:
    return far
  FAR, MID, NEAR = max(2.0 * v, 10.0), max(1.0 * v, 5.0), max(0.5 * v, 2.0)
  mid = C(190, 130, 80, 210) if adjacent else C(255, 140, 0, 250)
  near = C(185, 80, 80, 215) if adjacent else C(240, 40, 40, 255)
  if d_rel >= MID:
    return lerp_color(mid, far, (d_rel - MID) / (FAR - MID))
  return lerp_color(near, mid, (d_rel - NEAR) / (MID - NEAR))


def lead_lock_box(cx: float, cy: float, d_rel: float, max_x: float, max_y: float, min_x: float = 0.0) -> rl.Rectangle:
  """Box for a lead whose road contact point is (cx, cy). max_x / max_y are the view's right / bottom edges and
  min_x its left edge (Qt clamps in widget space, where the left edge is 0)."""
  sz = clamp(750.0 / (d_rel / 3.0 + 30.0), 15.0, 30.0) * 2.35
  w = sz * 3.2
  h = w * 0.86
  x = clamp(cx, min_x + w / 2 + 8, max_x - w / 2 - 8)
  bottom = min(cy + h * 0.1, max_y - 8)
  return rect(x - w / 2, bottom - h, w, h)


def paint_lead_lock(box: rl.Rectangle, dist: str, color: rl.Color, scissor_parent: rl.Rectangle | None = None) -> None:
  thick, thin, r, leg = 8.0, 3.5, 9.0, 0.30
  centre = inflate(box, thick / 2)
  cr = r + thick / 2
  lw, lh, o = box.width * leg, box.height * leg, thick * 2
  l, t, rr, b = box.x, box.y, box.x + box.width, box.y + box.height
  corners = [rect_lrtb(l - o, t - o, l + lw, t + lh), rect_lrtb(rr - lw, t - o, rr + o, t + lh),
             rect_lrtb(l - o, b - lh, l + lw, b + o), rect_lrtb(rr - lw, b - lh, rr + o, b + o)]

  def ring(width: float, c: rl.Color, clipped: bool) -> None:
    if not clipped:
      _ring_centre(centre, cr, width, c)
      return
    for k in corners:
      k = _clip_to(k, scissor_parent)
      if k is None:
        continue
      rl.begin_scissor_mode(int(k.x), int(k.y), int(math.ceil(k.width)), int(math.ceil(k.height)))
      _ring_centre(centre, cr, width, c)
      rl.end_scissor_mode()
    if scissor_parent is not None:
      p = scissor_parent
      rl.begin_scissor_mode(int(p.x), int(p.y), int(p.width), int(p.height))

  for grow in (6.0, 3.0):
    sh = C(0, 0, 0, 40 if grow > 4 else 60)
    ring(thin + grow, sh, False)
    ring(thick + grow, sh, True)
  ring(thin, color, False)
  ring(thick, color, True)

  if dist:
    tw = text_width(dist, 38, W.BOLD)
    px, py = box.x + box.width / 2, box.y - thick - 14 - 30
    pill = rect(px - tw / 2 - 22, py - 30, tw + 44, 60)
    fill_rounded(pill, 30, C(20, 22, 26, 205))
    draw_text_in_rect_centred(dist, pill, 38, C(255, 255, 255), W.BOLD)


def _ring_centre(centre: rl.Rectangle, radius: float, width: float, color: rl.Color) -> None:
  """Rounded-rect outline whose pen is centred on `centre`'s edge (Qt QPen semantics)."""
  stroke_rounded(inflate(centre, width / 2), radius + width / 2, width, color)


def _clip_to(k: rl.Rectangle, parent: rl.Rectangle | None) -> rl.Rectangle | None:
  if parent is None:
    return k
  x0, y0 = max(k.x, parent.x), max(k.y, parent.y)
  x1, y1 = min(k.x + k.width, parent.x + parent.width), min(k.y + k.height, parent.y + parent.height)
  if x1 <= x0 or y1 <= y0:
    return None
  return rect_lrtb(x0, y0, x1, y1)


@dataclass
class LeadLabels:
  speed: str = ""
  dist: str = ""
  dist_unit: str = ""
  vision_only: bool = False
  accent: rl.Color | None = None


def lead_tag_hud_overlap(r: rl.Rectangle, swap: bool, ox: float, oy: float) -> float:
  M = 8
  row = inflate(rect(ox + EDGE, oy + speed_row_top(swap), SPEED_ROW_MIN_RIGHT - EDGE, SPEED_ROW_HEIGHT), M)
  graph = inflate(_o(accel_graph_rect(swap), ox, oy), M)
  return overlap_area(r, row) + overlap_area(r, graph)


def _in_box_pill(box: rl.Rectangle, text: str) -> tuple[rl.Rectangle | None, int]:
  BRACKET = 8 + 6
  avail_w, avail_h = box.width - 2 * BRACKET, box.height - 2 * BRACKET
  if avail_w <= 0 or avail_h <= 0 or not text:
    return None, 0
  px = int(clamp(round(box.height * 0.42), 24, 64))
  w = h = 0.0
  for _ in range(8):
    pad = px * 0.32
    w = text_width(text, px, W.BOLD) + 2 * pad
    h = px * 1.28
    k = min(avail_w / w, avail_h / h)
    if k >= 1.0 or px <= 18:
      break
    px = max(18, int(math.floor(px * k)))
  cx, cy = box.x + box.width / 2, box.y + box.height / 2
  return rect(cx - w / 2, cy - h / 2, w, h), px


def _label_pill(cx: float, cy: float, h: float, pad: float, number: str, num_px: int, num_color: rl.Color, unit: str,
                unit_px: int, view: rl.Rectangle, accent: rl.Color | None = None) -> rl.Rectangle:
  u = " " + unit
  nw, uw = text_width(number, num_px, W.BOLD), text_width(u, unit_px, W.DEMI)
  w = nw + uw + 2 * pad
  x0 = cx - w / 2
  x0 = max(x0, view.x + 8)
  x0 = min(x0, view.x + view.width - 8 - w)
  r = rect(x0, cy - h / 2, w, h)
  fill_rounded(r, h / 2, C(20, 22, 26, 205))
  if accent is not None:
    fill_rounded(rect(x0 + pad, r.y + r.height - 7, nw + uw, 4), 2, accent)
  baseline = cy + cap_height(num_px) / 2
  draw_text(number, x0 + pad, baseline, num_px, num_color, W.BOLD)
  draw_text(u, x0 + pad + nw, baseline, unit_px, MUTED, W.DEMI)
  return r


def paint_lead_speed_in_box(box: rl.Rectangle, speed: str, vision_only: bool, accent: rl.Color | None) -> None:
  r, px = _in_box_pill(box, speed)
  if r is None:
    return
  fill_rounded(r, r.height / 2, C(20, 22, 26, 190))
  if accent is not None:
    tw = text_width(speed, px, W.BOLD)
    bar_h = max(3.0, r.height * 0.06)
    fill_rounded(rect(r.x + r.width / 2 - tw / 2, r.y + r.height - max(5.0, r.height * 0.10), tw, bar_h), 2, accent)
  draw_text_in_rect_centred(speed, r, px, C(255, 255, 255, 230) if vision_only else C(255, 255, 255), W.BOLD)


def paint_lead_labels(box: rl.Rectangle, lbl: LeadLabels, view: rl.Rectangle, keepout_top: float, swap: bool,
                      ox: float, oy: float) -> bool:
  GAP, TAG_H = 8 + 14, 46
  paint_lead_speed_in_box(box, lbl.speed, lbl.vision_only, lbl.accent)
  if not lbl.dist:
    return False
  tag_w = text_width(lbl.dist, 30, W.BOLD) + text_width(" " + lbl.dist_unit, 22, W.DEMI) + 2 * 18
  bcx = box.x + box.width / 2
  cx = clamp(bcx, view.x + 8 + tag_w / 2, view.x + view.width - 8 - tag_w / 2)
  below = rect(cx - tag_w / 2, box.y + box.height + GAP, tag_w, TAG_H)
  above = rect(cx - tag_w / 2, box.y - GAP - TAG_H, tag_w, TAG_H)
  below_cost = lead_tag_hud_overlap(below, swap, ox, oy) + max(0.0, below.y + below.height - keepout_top) * tag_w
  above_cost = lead_tag_hud_overlap(above, swap, ox, oy) + max(0.0, view.y + 8 - above.y) * tag_w
  put_above = below_cost > 0 and above_cost < below_cost
  tag = above if put_above else below
  _label_pill(bcx, tag.y + tag.height / 2, TAG_H, 18, lbl.dist, 30, C(255, 255, 255), lbl.dist_unit, 22, view)
  return put_above


def bottom_corner_keepout(widget_w: float, rhd: bool, map_button: bool, pedals: bool,
                          status_icons: list[rl.Rectangle], ox: float, oy: float) -> list[rl.Rectangle]:
  def mirrored(r: rl.Rectangle) -> rl.Rectangle:
    if rhd:
      r = rect(widget_w - r.x - r.width, r.y, r.width, r.height)
    return _o(r, ox, oy)
  k = [mirrored(rect(REC_CX - REC_HIT / 2, REC_CY - REC_HIT / 2, REC_HIT, REC_HIT)),
       mirrored(rect(NOGPS_CX - REC_DIAMETER / 2, NOGPS_CY - REC_DIAMETER / 2, REC_DIAMETER, REC_DIAMETER))]
  cluster_w = PILL_W + CLUSTER_GAP + CLUSTER_D + (CLUSTER_GAP + CLUSTER_D if map_button else 0)
  k.append(mirrored(rect(CLUSTER_LEFT, CLUSTER_CY - CLUSTER_D / 2 - PILL_LABEL_SPACE, cluster_w, CLUSTER_D + PILL_LABEL_SPACE)))
  if pedals:
    k.append(mirrored(rect(EDGE, STACK_BOTTOM + PEDAL_GAP, 2 * PEDAL_W, PEDAL_H)))
  return k + list(status_icons)


@dataclass
class AdjacentSpeedPlacement:
  rect: rl.Rectangle | None = None
  px: int = 0
  outside: bool = False
  leader: tuple[float, float, float, float] | None = None


def place_adjacent_speed(box: rl.Rectangle, speed: str, keepout: list[rl.Rectangle], rhd: bool = False,
                         view: rl.Rectangle | None = None) -> AdjacentSpeedPlacement:
  out = AdjacentSpeedPlacement()
  pr, px = _in_box_pill(box, speed)
  out.rect, out.px = pr, px
  if px == 0 or pr is None or not keepout:
    return out
  m = ADJ_LABEL_MARGIN

  def hits(r: rl.Rectangle) -> list[rl.Rectangle]:
    grown = inflate(r, m)
    return [k for k in keepout if intersects(grown, k)]
  if not hits(pr):
    return out
  w, h = pr.width, pr.height
  cy = box.y + box.height / 2
  r = rect(box.x - ADJ_LABEL_OUTSIDE - w if rhd else box.x + box.width + ADJ_LABEL_OUTSIDE, cy - h / 2, w, h)
  for _ in range(8):
    hs = hits(r)
    if not hs:
      break
    if rhd:
      edge = min(k.x for k in hs)
      r.x = edge - m - ADJ_LABEL_SLIDE_GAP - w
    else:
      edge = max(k.x + k.width for k in hs)
      r.x = edge + m + ADJ_LABEL_SLIDE_GAP
  if view is not None:
    r.x = clamp(r.x, view.x + 8, max(view.x + 8, view.x + view.width - 8 - w))
  out.rect = r
  out.outside = True
  gap = box.x - (r.x + r.width) if rhd else r.x - (box.x + box.width)
  if gap > ADJ_LABEL_LEADER_MIN:
    out.leader = (box.x - ADJ_LABEL_BRACKET, cy, r.x + r.width, cy) if rhd else (box.x + box.width + ADJ_LABEL_BRACKET, cy, r.x, cy)
  return out


def paint_adjacent_speed(box: rl.Rectangle, speed: str, box_color: rl.Color, keepout: list[rl.Rectangle] | None = None,
                         rhd: bool = False, view: rl.Rectangle | None = None) -> None:
  place = place_adjacent_speed(box, speed, keepout or [], rhd, view)
  if place.px == 0 or place.rect is None:
    return
  r = place.rect
  ink = C(min(255, box_color.r + 70), min(255, box_color.g + 70), min(255, box_color.b + 70), 240)
  if place.leader is not None:
    line(*place.leader, 3, with_alpha(box_color, 150), round_cap=True)
  fill_rounded(r, r.height / 2, C(20, 22, 26, 165))
  draw_text_in_rect_centred(speed, r, place.px, ink, W.BOLD)


# ---------------- LKAS Fault border ----------------
def is_lkas_fault_alert(alert_type: str, text1: str, text2: str = "") -> bool:
  return alert_type.startswith("steerUnavailable/") or "lkas fault" in text1.lower() or "lkas fault" in text2.lower()


def lkas_fault_border_color(millis: float) -> rl.Color:
  phase = int(math.floor(max(0.0, millis) / LKAS_FAULT_FLASH_MS))
  return LKAS_RED if phase % 2 == 0 else LKAS_ORANGE


# ---------------- round buttons ----------------
def paint_record_button(hit: rl.Rectangle, recording: bool, pulse: float) -> None:
  cx, cy = hit.x + hit.width / 2, hit.y + hit.height / 2
  d = min(REC_DIAMETER, min(hit.width, hit.height))
  dot, sq = d * 0.19, d * 0.35
  if recording:
    glow = C(225, 60, 60, int(255 * (0.4 + 0.6 * clamp(pulse, 0.0, 1.0))))
    rr = d / 2 - 3
    fill_circle(cx, cy, rr, C(14, 17, 22, 190))
    stroke_circle(cx, cy, rr, 5, glow)
    fill_rounded(rect(cx - sq / 2, cy - sq / 2, sq, sq), 7, C(225, 60, 60, 235))
  else:
    rr = d / 2 - 2
    fill_circle(cx, cy, rr, C(14, 17, 22, 190))
    stroke_circle(cx, cy, rr, 3, C(255, 255, 255, 60))
    fill_circle(cx, cy, dot, C(225, 60, 60, 240))


def paint_icon_button(r: rl.Rectangle, icon: rl.Texture | None, opacity: float) -> None:
  cx, cy = r.x + r.width / 2, r.y + r.height / 2
  fill_circle(cx, cy, min(r.width, r.height) / 2, PANEL_DARK)
  if icon is not None:
    rl.draw_texture_ex(icon, rl.Vector2(cx - icon.width / 2, cy - icon.height / 2), 0.0, 1.0, C(255, 255, 255, int(255 * clamp(opacity, 0, 1))))


def _arc_pts(cx: float, cy: float, rx: float, ry: float, a0_deg: float, span_deg: float, n: int = 24) -> list[tuple[float, float]]:
  # Qt angles: 0 = 3 o'clock, positive = counter-clockwise (screen y up)
  pts = []
  for i in range(n + 1):
    a = math.radians(a0_deg + span_deg * i / n)
    pts.append((cx + rx * math.cos(a), cy - ry * math.sin(a)))
  return pts


def paint_no_gps_indicator(cx: float, cy: float, slash_on: bool) -> None:
  d = REC_DIAMETER
  u = d / 124.0 * 1.18
  fill_circle(cx, cy, d / 2 - 2, C(14, 17, 22, 190))
  stroke_circle(cx, cy, d / 2 - 2, 3, C(255, 255, 255, 60))
  white = C(255, 255, 255)
  sx, sy = cx, cy - 4 * u
  rl.draw_rectangle_rec(rect(sx - 12 * u, sy - 12 * u, 24 * u, 24 * u), white)
  for g in (-1, 1):
    a, b = min(sx + g * 18 * u, sx + g * 44 * u), max(sx + g * 18 * u, sx + g * 44 * u)
    pw = 4 * u
    rl.draw_rectangle_lines_ex(rect(a - pw / 2, sy - 9 * u - pw / 2, b - a + pw, 18 * u + pw), pw, white)
    line(sx + g * 12 * u, sy, sx + g * 18 * u, sy, 4 * u, white)
    line((a + b) / 2, sy - 9 * u, (a + b) / 2, sy + 9 * u, 3 * u, white)
  line(sx, sy + 12 * u, sx, sy + 22 * u, 4 * u, white)
  # dish: QRect(sx-14u, sy+16u, 28u, 20u), start -200 deg, span 140 deg
  polyline(_arc_pts(sx, sy + 26 * u, 14 * u, 10 * u, -200, 140), 4 * u, white, round_cap=False)
  if slash_on:
    rr, w = d * 48.0 / 124.0, d * 9.0 / 124.0
    red = C(225, 60, 60)
    stroke_circle(cx, cy, rr, w, red)
    q = (rr - w / 2) * 0.7071
    line(cx - q, cy - q, cx + q, cy + q, w, red)


# ---------------- alert banner ----------------
def alert_banner_rect(widget_w: float, widget_h: float, mid: bool) -> rl.Rectangle:
  if widget_w >= 1800:
    left = REC_CX + REC_HIT // 2 + ALERT_GAP
    right = int(widget_w) - ALERT_RIGHT_MARGIN
    top = STACK_BOTTOM + ALERT_GAP
    bottom = CLUSTER_CY - CLUSTER_D // 2 - PILL_LABEL_SPACE - ALERT_GAP
    h = bottom - top if mid else min(bottom - top, 170)
    y = top + (bottom - top - h) // 2
    return rect(left, y, right - left, h)
  h = 300 if mid else 170
  return rect(40, widget_h - 230 - h, widget_w - 80, h)


def paint_alert_banner(r: rl.Rectangle, mid: bool, text1: str, text2: str, fill: rl.Color) -> None:
  panel(r, 30, fill, STROKE, 2)
  # 5 % -> 35 % dark vertical gradient over the status colour (clipped to the rounded rect via a scissored copy)
  _rounded_vertical_gradient(r, 30, C(0, 0, 0, int(0.05 * 255)), C(0, 0, 0, int(0.35 * 255)))

  def fitted(text: str, px: int, weight) -> int:
    max_w = r.width - 120
    tw = text_width(text, px, weight)
    if tw > max_w:
      return max(28, int(px * max_w / tw))
    return px

  cx = r.x + r.width / 2
  if mid:
    s1, s2 = fitted(text1, 96, W.BOLD), fitted(text2, 70, W.REGULAR)
    h1, h2, gap = cap_height(s1), cap_height(s2), 56
    y0 = r.y + r.height / 2 - (h1 + gap + h2) / 2
    draw_text_centred(text1, cx, y0 + h1, s1, TEXT, W.BOLD)
    draw_text_centred(text2, cx, y0 + h1 + gap + h2, s2, TEXT, W.REGULAR)
  else:
    draw_text_in_rect_centred(text1, r, fitted(text1, 80, W.DEMI), TEXT, W.DEMI)


def _rounded_vertical_gradient(r: rl.Rectangle, radius: float, top: rl.Color, bottom: rl.Color) -> None:
  """Vertical gradient inside a rounded rect: the straight middle as one gradient quad, the rounded top / bottom bands
  as horizontal strips whose width follows the corner arc."""
  radius = min(radius, r.width / 2, r.height / 2)
  steps = max(4, int(radius / 2))
  x0, x1 = r.x, r.x + r.width
  y_top, y_bot = r.y, r.y + r.height

  def col_at(y: float) -> rl.Color:
    return lerp_color(top, bottom, (y - y_top) / r.height if r.height > 0 else 0)

  def inset(dy: float) -> float:   # horizontal inset at distance dy (0..radius) from the straight section
    return radius - math.sqrt(max(0.0, radius * radius - dy * dy))

  for i in range(steps):
    ya, yb = y_top + radius * i / steps, y_top + radius * (i + 1) / steps
    ins = inset(radius - (ya + yb) / 2 + y_top)
    rl.draw_rectangle_gradient_v(int(x0 + ins), int(ya), int(r.width - 2 * ins), max(1, int(math.ceil(yb - ya))), col_at(ya), col_at(yb))
  mid_h = r.height - 2 * radius
  if mid_h > 0:
    rl.draw_rectangle_gradient_v(int(x0), int(y_top + radius), int(r.width), int(math.ceil(mid_h)), col_at(y_top + radius),
                                 col_at(y_bot - radius))
  for i in range(steps):
    ya, yb = y_bot - radius + radius * i / steps, y_bot - radius + radius * (i + 1) / steps
    ins = inset((ya + yb) / 2 - (y_bot - radius))
    rl.draw_rectangle_gradient_v(int(x0 + ins), int(ya), int(r.width - 2 * ins), max(1, int(math.ceil(yb - ya))), col_at(ya), col_at(yb))
  _ = x1
