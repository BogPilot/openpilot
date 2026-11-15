"""comma 4 steering arc and status border.

Arc: the BogPilot steering arc (steering_arc.ArcState: OP / driver source, colours, override tick, centre dot) drawn on
the stock comma 4 torque-bar geometry (torque_bar.py: radius 1200, span 12.7 deg, offset 22-26 px, thickness 14-56 px,
centre 8 px right of the view centre, cap radius 7), raised ARC_RAISE_PX.

Border: a thin status border on the camera view edge: engaged / override colours as the 3X status border, Traffic Mode
red while engaged with openpilot longitudinal, and the blind-spot side's half in BSM red with an edge bar."""
from __future__ import annotations

import math

from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot import steering_arc as ARC

RADIUS = 1200.0
SPAN_DEG = 12.7
CAP_R = 7.0
HALO_W = (6, 4, 2)

BORDER_ENGAGED = (0x16, 0x7F, 0x40, 255)
BORDER_OVERRIDE = (0x89, 0x92, 0x8D, 255)
TRAFFIC_RED = (201, 34, 49, 255)
BSM_RED = (0xC9, 0x22, 0x31, 0xF1)
BSM_EDGE_BAR = (255, 30, 30, 220)
BSM_EDGE_W = 5
BORDER_ROUNDNESS = 0.2 * 1.02          # the stock view's rounded corner (augmented_road_view fake border)


def geometry(state, rect, raise_px=C4.ARC_RAISE_PX):
  at = abs(state.torque)
  offset = ARC.interp(at, 0.5, 1.0, 22.0, 26.0) + raise_px
  thickness = ARC.interp(at, 0.5, 1.0, 14.0, 56.0)
  cx = rect.x + rect.width / 2 + 8
  cy = rect.y + rect.height + RADIUS - offset
  top = -90.0
  return {"cx": cx, "cy": cy, "radius": RADIUS, "thickness": thickness, "mid_r": RADIUS + thickness / 2,
          "offset": offset, "bg": (top - SPAN_DEG / 2, top + SPAN_DEG / 2), "fill": (top, top + SPAN_DEG / 2 * state.torque),
          "at": at}


def band_bbox(g):
  hw = math.sin(math.radians(SPAN_DEG / 2)) * (g["radius"] + g["thickness"])
  y1 = g["cy"] - g["radius"]
  return (g["cx"] - hw - CAP_R, y1 - g["thickness"] - 2, g["cx"] + hw + CAP_R, y1 + 2)


def fill_colours(state):
  """(start, end) RGBA 0..1 alpha of the fill, the same rules as steering_arc.paint."""
  alpha = max(state.alpha, 0.05)
  base = ARC.PURPLE if state.experimental else ARC.WHITE
  if state.human:
    c = ARC.human_angle_color(state.angle) + (0.95,)
    return c, c
  if not state.engaged_colors:
    c = ARC.WHITE + (0.35 * alpha,)
    return c, c
  k = max(0.0, abs(state.torque) - 0.75) * 4.0
  c0 = ARC._blend(base + (0.9 * alpha,), (ARC.PURPLE if state.experimental else ARC.YELLOW) + (alpha,), k)
  c1 = ARC._blend(base + (0.9 * alpha,), ARC.ORANGE + (alpha,), k)
  return c0, c1


def bg_alpha(state):
  alpha = max(state.alpha, 0.05)
  at = abs(state.torque)
  a = ARC.interp(at, 0.5, 1.0, 0.25, 0.5) * alpha
  if not state.engaged_colors and not state.human:
    a = 0.15 * alpha
  if state.human and state.alpha < 0.9:
    a = 0.15 + 0.1 * max(0.0, at - 0.5) * 2.0
  return a


def paint(state, rect, raise_px=C4.ARC_RAISE_PX):
  import numpy as np
  import pyray as rl
  from openpilot.selfdrive.ui.mici.onroad.torque_bar import arc_bar_pts
  from openpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient

  g = geometry(state, rect, raise_px)
  cx, cy, at = g["cx"], g["cy"], g["at"]
  alpha = max(state.alpha, 0.05)
  off = np.array([cx, cy], dtype=np.float32)

  def col(c, a):
    return rl.Color(int(c[0]), int(c[1]), int(c[2]), int(255 * ARC.clamp(a, 0.0, 1.0)))

  a0, a1 = g["bg"]
  for w in HALO_W:
    da = math.degrees(w / 2 / g["mid_r"])
    draw_polygon(rect, arc_bar_pts(g["mid_r"], g["thickness"] + w, a0 - da, a1 + da, cap_radius=CAP_R + w / 2) + off,
                 color=rl.Color(0, 0, 0, int(14 * alpha)))
  bg = arc_bar_pts(g["mid_r"], g["thickness"], a0, a1, cap_radius=CAP_R) + off
  draw_polygon(rect, bg, color=col(ARC.WHITE, bg_alpha(state)))
  if at > 0.005:
    f0, f1 = g["fill"]
    fill = arc_bar_pts(g["mid_r"], g["thickness"], f0, f1, cap_radius=CAP_R) + off
    c0, c1 = fill_colours(state)
    edge = float(bg[:, 0].min() if state.torque < 0 else bg[:, 0].max())
    start = (cx - rect.x) / rect.width
    end = ((cx + (edge - cx) * 0.65) - rect.x) / rect.width
    draw_polygon(rect, fill, gradient=Gradient(start=(start, 0), end=(end, 0), colors=[col(c0, c0[3]), col(c1, c1[3])],
                                               stops=[0.0, 1.0]))
  if state.show_tick:
    a = math.radians(-90.0 + SPAN_DEG / 2 * ARC.clamp(state.op_target, -1.0, 1.0))
    r0, r1 = g["radius"] - 3, g["radius"] + g["thickness"] + 3
    p0 = rl.Vector2(cx + math.cos(a) * r0, cy + math.sin(a) * r0)
    p1 = rl.Vector2(cx + math.cos(a) * r1, cy + math.sin(a) * r1)
    rl.draw_line_ex(p0, p1, 4, rl.Color(0, 0, 0, 110))
    rl.draw_line_ex(p0, p1, 2, rl.Color(255, 255, 255, 245))
  if at < 0.5:
    dot_y = cy - g["radius"] - g["thickness"] / 2
    rl.draw_circle_v(rl.Vector2(cx, dot_y), 5, col(ARC.DOT_GREY, 0.9 * alpha))
  return {"steering arc": band_bbox(g)}


def border_colour(status: str, traffic_red: bool):
  """status: UIStatus value ("engaged" / "override" / "disengaged"). None = no border."""
  if status == "engaged":
    return TRAFFIC_RED if traffic_red else BORDER_ENGAGED
  if status == "override":
    return BORDER_OVERRIDE
  return None


def bsm_halves(left: bool, right: bool, has_bsm: bool, enabled: bool, full_alert: bool, critical_alert: bool):
  """(left, right) halves to paint BSM red, or None (same rule as the 3X: full-screen and critical alerts keep the
  whole border)."""
  if not (has_bsm and enabled) or full_alert or critical_alert or not (left or right):
    return None
  return bool(left), bool(right)


def paint_border(rect, colour, bsm):
  """Status border BORDER_W px inside the camera view edge, then the BSM halves and edge bars. rect = the view
  (the caller's scissor). Returns the rects drawn."""
  import pyray as rl
  from openpilot.selfdrive.ui.onroad.bogpilot.style import C, stroke_rounded, rect_lrtb
  out = {}
  w = C4.BORDER_W
  radius = BORDER_ROUNDNESS * min(rect.width, rect.height) / 2
  ring = rect_lrtb(rect.x + w / 2, rect.y + w / 2, rect.x + rect.width - w / 2, rect.y + rect.height - w / 2)
  if colour is not None:
    stroke_rounded(ring, radius - w / 2, w, C(*colour))
    out["status border"] = (rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
  if bsm is not None:
    half = rect.width / 2
    for i, on in enumerate(bsm):
      if not on:
        continue
      x0 = rect.x + (0 if i == 0 else half)
      bx0 = rect.x if i == 0 else rect.x + rect.width - BSM_EDGE_W
      rl.draw_rectangle_rec(rl.Rectangle(bx0, rect.y, BSM_EDGE_W, rect.height), C(*BSM_EDGE_BAR))   # under the border
      rl.begin_scissor_mode(int(x0), int(rect.y), int(math.ceil(half)), int(rect.height))
      stroke_rounded(ring, radius - w / 2, w, C(*BSM_RED))
      rl.end_scissor_mode()
      out[f"BSM border ({'left' if i == 0 else 'right'} half)"] = (x0, rect.y, x0 + half, rect.y + rect.height)
      out[f"BSM edge bar ({'left' if i == 0 else 'right'})"] = (bx0, rect.y, bx0 + BSM_EDGE_W, rect.y + rect.height)
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))   # the view's own clip
  return out
