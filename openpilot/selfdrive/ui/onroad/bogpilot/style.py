"""Shared BogPilot redesign style: colours, layout constants and small raylib drawing helpers.

Font sizes are Qt pixel sizes: the raylib text functions are patched to scale by FONT_SCALE, which makes a raylib
size N match Qt's InterFont(N) glyphs. Qt draws text from a baseline, so the helpers here take a baseline y.
"""
from __future__ import annotations
import math
import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.text_measure import measure_text_cached


def C(r: int, g: int, b: int, a: int = 255) -> rl.Color:
  return rl.Color(int(r), int(g), int(b), int(max(0, min(255, a))))


def with_alpha(c: rl.Color, a: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(max(0, min(255, a))))


def scale_alpha(c: rl.Color, k: float) -> rl.Color:
  return rl.Color(c.r, c.g, c.b, int(max(0, min(255, c.a * k))))


def lerp_color(a: rl.Color, b: rl.Color, t: float) -> rl.Color:
  t = max(0.0, min(1.0, t))
  return rl.Color(int(a.r + (b.r - a.r) * t), int(a.g + (b.g - a.g) * t),
                  int(a.b + (b.b - a.b) * t), int(a.a + (b.a - a.a) * t))


# ---- shared style (bogpilot_redesign.h) ----
PANEL = C(14, 17, 22, 168)
PANEL_DARK = C(14, 17, 22, 200)
SPEED_PANEL = C(14, 17, 22, 130)
STROKE = C(255, 255, 255, 30)
MUTED = C(255, 255, 255, 150)
TEXT = C(255, 255, 255, 240)
WHITE = C(255, 255, 255)
ACTUAL_GREEN = C(61, 220, 151)
ARC_PURPLE = C(150, 100, 255)
ARC_YELLOW = C(255, 200, 0)
ARC_ORANGE = C(255, 115, 0)
BADGE_GREEN = C(31, 150, 80)
TRAFFIC_RED = C(201, 34, 49)

# ---- layout (widget space = content rect) ----
EDGE = 30
SPEED_ROW_TOP = 24
SPEED_ROW_HEIGHT = 176
SPEED_ROW_MIN_RIGHT = 740
REC_DIAMETER = 124
REC_HIT = 174
CLUSTER_LEFT = 20
REC_CX, REC_CY = CLUSTER_LEFT + 75, 696
GRAPH_TOP = 228
GRAPH_WIDTH = 560
GRAPH_HEIGHT = 240
PEDAL_W, PEDAL_H = 60, 120
PEDAL_GAP = 18
STATUS_ICON = 132
STATUS_X, STATUS_Y, STATUS_STEP = 196, 642, 150
CLUSTER_CY = 900
CLUSTER_D = 150
CLUSTER_GAP = 6
PILL_W = 150
PILL_H = 150
PILL_LABEL_SPACE = 40
HUD_W = 400
HUD_H = 430
STACK_BOTTOM = GRAPH_TOP + GRAPH_HEIGHT        # 468 in both orders
SWAP_GRAPH_TOP = SPEED_ROW_TOP                  # 24
SWAP_SPEED_ROW_TOP = STACK_BOTTOM - SPEED_ROW_HEIGHT   # 292
NOGPS_CX, NOGPS_CY = 251, 696
NOGPS_DEBOUNCE_S = 5.0
ALERT_GAP = 36
ALERT_RIGHT_MARGIN = 150
LKAS_FAULT_FLASH_MS = 200
LKAS_RED = C(0xE0, 0x1B, 0x24)
LKAS_ORANGE = C(0xFF, 0x8C, 0x00)


def speed_row_top(swap: bool) -> int:
  return SWAP_SPEED_ROW_TOP if swap else SPEED_ROW_TOP


def graph_top(swap: bool) -> int:
  return SWAP_GRAPH_TOP if swap else GRAPH_TOP


# ---- fonts / text ----
# Inter: hhea ascender 1984, descender -495 (units per em 2048). raylib places glyphs from the line top, the line
# being (ascender - descender) tall at size * FONT_SCALE, so the baseline sits ASCENT * size below the text top.
ASCENT = 1984 / (1984 + 495) * FONT_SCALE
CAP_HEIGHT = 1490 / (1984 + 495) * FONT_SCALE   # Inter cap height 1490 units


class W:
  REGULAR = FontWeight.NORMAL
  MEDIUM = FontWeight.MEDIUM
  DEMI = FontWeight.SEMI_BOLD
  BOLD = FontWeight.BOLD


def font(weight=FontWeight.NORMAL) -> rl.Font:
  return gui_app.font(weight)


# The UI fonts are loaded with ASCII plus application.EXTRA_FONT_CHARS only (system/ui is not ours to change), so the few
# glyphs the Qt HUD used outside that set are drawn by hand: superscript two, middle dot, up arrow; em dash -> en dash.
_SPECIAL = "\u00b2\u00b7\u2191"
_REPLACE = {"\u2014": "\u2013"}


def _runs(text: str) -> list[str]:
  for a, b in _REPLACE.items():
    text = text.replace(a, b)
  out, cur = [], ""
  for ch in text:
    if ch in _SPECIAL:
      if cur:
        out.append(cur)
      out.append(ch)
      cur = ""
    else:
      cur += ch
  if cur:
    out.append(cur)
  return out


def _plain_width(text: str, size: int, weight) -> float:
  return measure_text_cached(font(weight), text, size).x if text else 0.0


def _special_width(ch: str, size: int, weight) -> float:
  if ch == "\u00b2":
    return _plain_width("2", max(1, int(size * 0.62)), weight)
  if ch == "\u00b7":
    return size * 0.32
  return size * 0.62   # arrow


def text_width(text: str, size: float, weight=FontWeight.NORMAL) -> float:
  if not text:
    return 0.0
  size = int(round(size))
  return sum(_special_width(r, size, weight) if r in _SPECIAL else _plain_width(r, size, weight) for r in _runs(text))


def _draw_special(ch: str, x: float, baseline: float, size: int, color: rl.Color, weight) -> float:
  w = _special_width(ch, size, weight)
  cap = CAP_HEIGHT * size
  if ch == "\u00b2":
    sub = max(1, int(size * 0.62))
    rl.draw_text_ex(font(weight), "2", rl.Vector2(x, baseline - cap - ASCENT * sub + CAP_HEIGHT * sub), sub, 0, color)
  elif ch == "\u00b7":
    rl.draw_circle_v(rl.Vector2(x + w / 2, baseline - cap * 0.42), max(1.5, size * 0.06), color)
  else:
    cx, top, bot = x + w / 2, baseline - cap, baseline
    head = cap * 0.5
    t = max(2.0, size * 0.11)
    rl.draw_triangle(rl.Vector2(cx, top), rl.Vector2(cx - w * 0.42, top + head), rl.Vector2(cx + w * 0.42, top + head), color)
    rl.draw_rectangle_rec(rl.Rectangle(cx - t / 2, top + head - 1, t, bot - top - head + 1), color)
  return w


def draw_text(text: str, x: float, baseline: float, size: float, color: rl.Color, weight=FontWeight.NORMAL) -> float:
  """Draw text with its left edge at x and its baseline at `baseline`. Returns the advance width."""
  if not text:
    return 0.0
  size = int(round(size))
  x0 = x
  for r in _runs(text):
    if r in _SPECIAL:
      x += _draw_special(r, x, baseline, size, color, weight)
    else:
      rl.draw_text_ex(font(weight), r, rl.Vector2(x, baseline - ASCENT * size), size, 0, color)
      x += _plain_width(r, size, weight)
  return x - x0


def cap_height(size: float) -> float:
  return CAP_HEIGHT * size


def draw_text_centred(text: str, cx: float, baseline: float, size: float, color: rl.Color, weight=FontWeight.NORMAL) -> None:
  w = text_width(text, size, weight)
  draw_text(text, cx - w / 2, baseline, size, color, weight)


def draw_text_in_rect_centred(text: str, r: rl.Rectangle, size: float, color: rl.Color, weight=FontWeight.NORMAL) -> None:
  """Qt AlignCenter for a single line: vertically centred on the cap height (close to Qt's ascent/descent centring)."""
  baseline = r.y + r.height / 2 + cap_height(size) / 2
  draw_text_centred(text, r.x + r.width / 2, baseline, size, color, weight)


def spaced(s: str) -> str:
  return " ".join(s)


# ---- shapes ----
def _roundness(w: float, h: float, radius: float) -> float:
  m = min(w, h)
  if m <= 0:
    return 0.0
  return max(0.0, min(1.0, 2.0 * radius / m))


def fill_rounded(r: rl.Rectangle, radius: float, color: rl.Color) -> None:
  if color.a == 0 or r.width <= 0 or r.height <= 0:
    return
  rl.draw_rectangle_rounded(r, _roundness(r.width, r.height, radius), 24, color)


def stroke_rounded(r: rl.Rectangle, radius: float, width: float, color: rl.Color) -> None:
  """Qt-style pen (centred on the outline). raylib strokes outward, so shrink by half the pen width."""
  if color.a == 0 or width <= 0:
    return
  h = width / 2
  inner = rl.Rectangle(r.x + h, r.y + h, r.width - width, r.height - width)
  if inner.width <= 0 or inner.height <= 0:
    return
  rl.draw_rectangle_rounded_lines_ex(inner, _roundness(inner.width, inner.height, max(0.0, radius - h)), 24, width, color)


def panel(r: rl.Rectangle, radius: float, fill: rl.Color = PANEL, stroke: rl.Color | None = STROKE, stroke_w: float = 2.0) -> None:
  fill_rounded(r, radius, fill)
  if stroke is not None and stroke.a > 0:
    stroke_rounded(r, radius, stroke_w, stroke)


def fill_circle(cx: float, cy: float, radius: float, color: rl.Color) -> None:
  if color.a == 0 or radius <= 0:
    return
  rl.draw_circle_sector(rl.Vector2(cx, cy), radius, 0, 360, max(24, int(radius)), color)


def stroke_circle(cx: float, cy: float, radius: float, width: float, color: rl.Color) -> None:
  if color.a == 0 or width <= 0:
    return
  rl.draw_ring(rl.Vector2(cx, cy), max(0.0, radius - width / 2), radius + width / 2, 0, 360, max(32, int(radius)), color)


def line(x0: float, y0: float, x1: float, y1: float, width: float, color: rl.Color, round_cap: bool = False) -> None:
  rl.draw_line_ex(rl.Vector2(x0, y0), rl.Vector2(x1, y1), width, color)
  if round_cap and width > 2:
    fill_circle(x0, y0, width / 2, color)
    fill_circle(x1, y1, width / 2, color)


def polyline(pts: list[tuple[float, float]], width: float, color: rl.Color, round_cap: bool = True) -> None:
  """Thick open polyline with round joins (a filled circle on every vertex)."""
  if len(pts) < 2 or color.a == 0:
    return
  for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:], strict=True):
    rl.draw_line_ex(rl.Vector2(x0, y0), rl.Vector2(x1, y1), width, color)
  if width > 2:
    verts = pts if round_cap else pts[1:-1]
    for x, y in verts:
      fill_circle(x, y, width / 2, color)


def fill_convex(pts: list[tuple[float, float]], color: rl.Color) -> None:
  """Fill a convex polygon (any winding)."""
  if len(pts) < 3 or color.a == 0:
    return
  cx = sum(p[0] for p in pts) / len(pts)
  cy = sum(p[1] for p in pts) / len(pts)
  # raylib triangle fans want counter-clockwise order in screen space
  ordered = sorted(pts, key=lambda p: -math.atan2(p[1] - cy, p[0] - cx))
  fan = [rl.Vector2(cx, cy)] + [rl.Vector2(*p) for p in ordered] + [rl.Vector2(*ordered[0])]
  rl.draw_triangle_fan(fan, len(fan), color)


def rect(x: float, y: float, w: float, h: float) -> rl.Rectangle:
  return rl.Rectangle(float(x), float(y), float(w), float(h))


def rect_lrtb(x0: float, y0: float, x1: float, y1: float) -> rl.Rectangle:
  return rl.Rectangle(float(x0), float(y0), float(x1 - x0), float(y1 - y0))


def offset_rect(r: rl.Rectangle, ox: float, oy: float) -> rl.Rectangle:
  return rl.Rectangle(r.x + ox, r.y + oy, r.width, r.height)


def inflate(r: rl.Rectangle, d: float) -> rl.Rectangle:
  return rl.Rectangle(r.x - d, r.y - d, r.width + 2 * d, r.height + 2 * d)


def intersects(a: rl.Rectangle, b: rl.Rectangle) -> bool:
  return a.x < b.x + b.width and b.x < a.x + a.width and a.y < b.y + b.height and b.y < a.y + a.height


def contains(r: rl.Rectangle, x: float, y: float) -> bool:
  return r.x <= x <= r.x + r.width and r.y <= y <= r.y + r.height


def overlap_area(a: rl.Rectangle, b: rl.Rectangle) -> float:
  w = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
  h = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
  return w * h if w > 0 and h > 0 else 0.0


def interp(x: float, xp: list[float], fp: list[float]) -> float:
  if x <= xp[0]:
    return fp[0]
  if x >= xp[-1]:
    return fp[-1]
  for i in range(len(xp) - 1):
    if xp[i] <= x <= xp[i + 1]:
      t = (x - xp[i]) / (xp[i + 1] - xp[i]) if xp[i + 1] != xp[i] else 0.0
      return fp[i] + (fp[i + 1] - fp[i]) * t
  return fp[-1]


def clamp(v: float, lo: float, hi: float) -> float:
  return lo if v < lo else hi if v > hi else v
