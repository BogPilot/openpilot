"""BogPilot pedal icons (t913u; design approved by the owner t916s3369 / t917u).

Response (UNCHANGED from daily bogpilot-tesla 04d560f3e FrogPilotAnnotatedCameraWidget::paintPedalIcons):
  gate     pedals_on_ui = openpilot_longitudinal and CustomUI and PedalsOnUI (367e1fe :877-879, tuning-level rule);
           Dynamic / Static sub-modes; with neither, the overlay is hidden (not drawn at full strength).
  Dynamic  brake = 1 at standstill, else max(0.25, |aEgo|) when aEgo < -0.25, else 0.25;  gas = max(0.25, aEgo)
  Static   brake = 1 if standstill or brakeLights or aEgo < -0.25 else 0.25;               gas = 1 if aEgo > 0.25 else 0.25
  Signals  carState.aEgo (MEASURED vehicle acceleration, m/s^2), carState.standstill, frogpilotCarState.brakeLights.
           Not pedal position, not commanded accel and no brake force (AP1 has no brake force/pressure signal wired;
           none is invented). Opacities are clamped to [0.25, 1] as Qt's setOpacity did.
Visual (new, approved mockup): strength k = (opacity - 0.25) / 0.75 in [0, 1]. At k = 0 the pedals are a nearly
transparent ghost; the red brake / green gas overlay's opacity and brightness rise linearly with k. Shape: Model S
performance-style pedals (wide slotted brake, tall tapered slotted gas) with a subtle silver edge / mixed highlight.
Footprint and placement are daily's: 2 x 60 x 120 under the accel graph on the driver side (PEDAL_W/H, PEDAL_GAP),
the same rect bottom_corner_keepout reserves; brake left, gas right (daily does not swap them for RHD).
"""
from __future__ import annotations

from dataclasses import dataclass
import math

REST = 0.25
EDGE = 30
STACK_BOTTOM = 468
PEDAL_W, PEDAL_H, PEDAL_GAP = 60, 120, 18


def clamp(v, lo, hi):
  return lo if v < lo else hi if v > hi else v


@dataclass(frozen=True)
class PedalPolicy:
  show: bool = False
  dynamic: bool = False
  static: bool = False


CLOSED = PedalPolicy()


def policy_from_store(store, longitudinal: bool) -> PedalPolicy:
  """Show the overlay only when a mode is selected. Dynamic off + Static off hides it."""
  level = store.tuning_level()
  b = lambda k: bool(store.toggle_bool(k, level))  # noqa: E731
  parent = bool(longitudinal) and b("CustomUI") and b("PedalsOnUI")
  dynamic = parent and b("DynamicPedalsOnUI")
  static = parent and b("StaticPedalsOnUI")
  # Neither mode used to draw both pedals at full strength; that left no way to hide them
  # from the Dynamic Pedals toggle. Hide unless Dynamic or Static is on.
  show = dynamic or static
  return PedalPolicy(show=show, dynamic=dynamic, static=static)


def daily_opacity(policy: PedalPolicy, a_ego: float, standstill: bool, brake_lights: bool) -> tuple[float, float]:
  """(brake, gas) exactly as daily paintPedalIcons, clamped like QPainter::setOpacity."""
  brake = gas = 1.0
  if policy.dynamic:
    brake = 1.0 if standstill else (max(0.25, abs(a_ego)) if a_ego < -0.25 else 0.25)
    gas = max(0.25, a_ego)
  elif policy.static:
    brake = 1.0 if (standstill or brake_lights or a_ego < -0.25) else 0.25
    gas = 1.0 if a_ego > 0.25 else 0.25
  return clamp(brake, 0.0, 1.0), clamp(gas, 0.0, 1.0)


def strength(opacity: float) -> float:
  return clamp((opacity - REST) / (1.0 - REST), 0.0, 1.0)


def pedal_rect(widget_w: float, rhd: bool):
  """(x, y, w, h) of the two-pedal footprint in widget (design) space."""
  x = widget_w - EDGE - 2 * PEDAL_W if rhd else EDGE
  return (x, STACK_BOTTOM + PEDAL_GAP, 2 * PEDAL_W, PEDAL_H)


# ---- shape (design px, relative to the footprint) ----
BRAKE_BOX = (2, 58, 64, 56)      # wide brake pad in the lower part of the left 60 px slot (+6 px into the gap)
GAS_BOX = (74, 0, 44, 120)       # tall gas pedal, tapered toward the floor hinge
BRAKE_TAPER, GAS_TAPER = 5.0, 5.0
RADIUS = 9.0

BRAKE_DIM, BRAKE_BRIGHT = (120, 22, 24), (238, 48, 44)
GAS_DIM, GAS_BRIGHT = (26, 104, 40), (64, 206, 84)
SILVER_HI, SILVER_LO = (226, 230, 236), (128, 134, 142)


def rounded_trapezoid(box, taper, r, n=5):
  """Convex outline: top full width, bottom inset by `taper` on each side, corner radius r."""
  x, y, w, h = box
  corners = [(x, y), (x + w, y), (x + w - taper, y + h), (x + taper, y + h)]
  pts = []
  for i, (cx, cy) in enumerate(corners):
    px, py = corners[i - 1]
    nx, ny = corners[(i + 1) % 4]
    v1 = (px - cx, py - cy)
    v2 = (nx - cx, ny - cy)
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    a = (cx + v1[0] / l1 * r, cy + v1[1] / l1 * r)
    b = (cx + v2[0] / l2 * r, cy + v2[1] / l2 * r)
    for j in range(n + 1):   # quadratic Bezier through the corner: a smooth rounded corner on a convex polygon
      t = j / n
      pts.append(((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * cx + t * t * b[0],
                  (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * cy + t * t * b[1]))
  return pts


def visual(k: float, dim, bright):
  """Overlay colour/alpha and edge alpha for strength k (pure; tested)."""
  k = clamp(k, 0.0, 1.0)
  rgb = tuple(int(round(dim[i] + (bright[i] - dim[i]) * k)) for i in range(3))
  return {"fill_rgb": rgb, "fill_a": int(round(255 * (0.06 + 0.84 * k))), "ghost_a": 26,
          "edge_a": int(round(255 * (0.16 + 0.34 * k))), "groove_a": int(round(255 * (0.10 + 0.25 * k)))}


def paint(widget_w: float, rhd: bool, brake_opacity: float, gas_opacity: float, ox: float = 0.0, oy: float = 0.0) -> None:
  from openpilot.selfdrive.ui.onroad.bogpilot.style import C, fill_convex, polyline, line

  fx, fy, _, _ = pedal_rect(widget_w, rhd)
  fx, fy = fx + ox, fy + oy

  def one(box, taper, k, dim, bright, grooves, vertical_full):
    x, y, w, h = box
    box_s = (fx + x, fy + y, w, h)
    pts = rounded_trapezoid(box_s, taper, RADIUS)
    v = visual(k, dim, bright)
    fill_convex(pts, C(20, 22, 26, v["ghost_a"]))                       # ghost body, nearly transparent at rest
    fill_convex(pts, C(*v["fill_rgb"], v["fill_a"]))                    # red / green overlay rising with input
    # mixed silver edge: lighter on the upper half, darker below (subtle, not an opaque metal plate)
    closed = pts + [pts[0]]
    mid_y = box_s[1] + h * 0.5
    upper = [p for p in closed if p[1] <= mid_y]
    polyline(closed, 2.0, C(*SILVER_LO, v["edge_a"]), round_cap=False)
    if len(upper) >= 2:
      polyline(sorted(upper, key=lambda p: p[0]), 1.6, C(*SILVER_HI, int(v["edge_a"] * 0.9)), round_cap=False)
    # rubber grooves (Model S performance pattern), slightly darker than the pad
    gx0, gx1 = box_s[0] + taper + 8, box_s[0] + w - taper - 8
    for i in range(grooves):
      gx = gx0 + (gx1 - gx0) * (i + 0.5) / grooves
      inset = 9 if vertical_full else 12
      line(gx, box_s[1] + inset, gx, box_s[1] + h - inset, 3.0, C(0, 0, 0, v["groove_a"]))
      line(gx + 1.5, box_s[1] + inset, gx + 1.5, box_s[1] + h - inset, 1.0, C(*SILVER_HI, int(v["groove_a"] * 0.35)))

  one(BRAKE_BOX, BRAKE_TAPER, strength(brake_opacity), BRAKE_DIM, BRAKE_BRIGHT, 7, False)
  one(GAS_BOX, GAS_TAPER, strength(gas_opacity), GAS_DIM, GAS_BRIGHT, 3, True)
