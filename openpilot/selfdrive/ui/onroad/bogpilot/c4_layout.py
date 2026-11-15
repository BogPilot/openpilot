"""comma 4 BogPilot onroad layout: geometry, the device gate and the per-frame visibility rules (no drawing here).

The comma 4 is device type "mici" (536 x 240 px at 300 PPI; the camera view is 476 px wide, the 60 px side panel
holds the confidence ball). The layout is used ONLY when the device type is "mici", and only from the mici onroad
renderers, so the comma 3X path (tici / tizi, big UI) never reaches this code.

All rects are (x0, y0, x1, y1) in screen pixels with x1 / y1 exclusive.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

COMMA4_DEVICE_TYPES = frozenset({"mici"})

SCREEN_W, SCREEN_H = 536, 240
SIDE_PANEL_W = 60
VIEW_W = SCREEN_W - SIDE_PANEL_W            # 476: camera / content rect width

# Speed pill: MAX (set speed) | current speed + unit | LIMIT tile, one rounded capsule at the top left.
PILL = (6, 6, 174, 58)
PILL_RADIUS = 12
PILL_DIVIDER_X = 54
PILL_SET_CX, PILL_SPEED_CX = 30, 92
PILL_LIMIT = (134, 10, 168, 54)

# Driver-monitor icon, top right of the camera view. The stock DriverStateRenderer (60 px) is centred on this 56 px spot.
DM_ICON = (414, 8, 470, 64)
DM_STOCK_SIZE = 60

# Lead boxes: the wide layout's lock box scaled from its 2100 px design width to the camera view; speed labels above
# the box (24 px primary, 20 px adjacent), no distance label.
LEAD_SCALE = VIEW_W / 2100.0
LEAD_EDGE = 8
SPEED_PX_PRIMARY, SPEED_PX_ADJ = 24, 20
LABEL_GAP, LABEL_SLIDE_MARGIN = 3, 2
# Area the stock (non-full) alert text can cover; a label that would land in it moves below its box, or beside it
# during take-control style (userPrompt) alerts.
ALERT_TEXT_ZONE = (4, 0, 472, 118)

# Personality button (also the personality indicator): 40 px disc, far lower left, 48 x 48 tap target.
PERSONALITY_CX, PERSONALITY_CY = 28, 212
PERSONALITY_D = 40
PERSONALITY_TAP = 48
PERSONALITY_STRIPE_W, PERSONALITY_STRIPE_H, PERSONALITY_STRIPE_PITCH = 18, 4, 8

# Three-bar pedal gauge, hard left directly above the personality button: brake | regen | accel.
GAUGE_X0, GAUGE_Y0 = 8, 112
GAUGE_BAR_W, GAUGE_BAR_GAP, GAUGE_H = 12, 2, 76   # pedal_gauge3 36 / 6 proportions at 40 px wide
GAUGE_SCALE = 0.5                                  # pedal_gauge3 design scale here: fill inset 4 * 0.5 = 2 px

# Record button: the wide-layout paint_record_button look scaled to a 40 px disc, lower right in the side panel
# (same inset from the right and bottom as the personality button has from the left and bottom).
REC_CX, REC_CY = SCREEN_W - 28, 212
REC_D = 40
REC_SRC_D = 124                              # style.REC_DIAMETER (wide layout)

# Lane changes: no custom arrows; the stock lane-change alert draws its own turn-signal arrows.

# Stock turn intent (white, from the same lane-change events) drawn over the personality button the way stock draws it
# over the wheel: centred on the button, bottom 5 px above it, rotated about the button centre, at 44 x 18.
TURN_INTENT_W, TURN_INTENT_H, TURN_INTENT_GAP = 44, 18, 5

# Engagement border on the camera view edge; the blind-spot side's half turns red.
BORDER_W = 3
ARC_RAISE_PX = 10

# What a take-control alert hides. One constant so the rule is easy to change. On this small screen the alert takes
# over: the pill, gauge, driver-monitor icon and the lead / adjacent-lead boxes with their speeds step aside, and the
# take-control personality button is left on its own.
TAKE_CONTROL_HIDES = frozenset({"pill", "gauge", "dm", "leads"})
# Any other on-screen alert (the same stock alert-shown condition) hides the same set.
OTHER_ALERT_HIDES = frozenset({"pill", "gauge", "dm", "leads"})


def is_comma4(device_type) -> bool:
  """True for the comma 4. Accepts the cereal enum, its name, or anything else (False)."""
  try:
    name = str(device_type)
  except Exception:
    return False
  return name in COMMA4_DEVICE_TYPES


def comma4_device(sm, fallback_device_type=None) -> bool:
  """Device gate from deviceState.deviceType once it has arrived, else the hardware's own device type."""
  try:
    if sm.seen["deviceState"]:
      return is_comma4(sm["deviceState"].deviceType)
  except (KeyError, AttributeError, TypeError):
    pass
  if fallback_device_type is None:
    from openpilot.common.hardware import HARDWARE
    fallback_device_type = HARDWARE.get_device_type()
  return is_comma4(fallback_device_type)


def gauge_rect():
  w = 3 * GAUGE_BAR_W + 2 * GAUGE_BAR_GAP
  return (GAUGE_X0, GAUGE_Y0, GAUGE_X0 + w, GAUGE_Y0 + GAUGE_H)


def gauge_xywh():
  """gauge_rect() as (x, y, w, h), the pedal_gauge3 painter's rect."""
  x0, y0, x1, y1 = gauge_rect()
  return (x0, y0, x1 - x0, y1 - y0)


def gauge_bar_rects():
  """(brake, regen, accel) bar rects, left to right."""
  out = []
  for i in range(3):
    x = GAUGE_X0 + i * (GAUGE_BAR_W + GAUGE_BAR_GAP)
    out.append((x, GAUGE_Y0, x + GAUGE_BAR_W, GAUGE_Y0 + GAUGE_H))
  return tuple(out)


def personality_rect():
  r = PERSONALITY_D / 2
  return (PERSONALITY_CX - r, PERSONALITY_CY - r, PERSONALITY_CX + r, PERSONALITY_CY + r)


def personality_tap_rect():
  r = PERSONALITY_TAP / 2
  return (PERSONALITY_CX - r, PERSONALITY_CY - r, PERSONALITY_CX + r, PERSONALITY_CY + r)


def record_rect():
  r = REC_D / 2
  return (REC_CX - r, REC_CY - r, REC_CX + r, REC_CY + r)


def record_ring():
  """(ring radius, ring stroke width, dot radius): paint_record_button idle (rr = d / 2 - 2, stroke 3, dot d * 0.19)
  with the pixel constants scaled by REC_D / REC_SRC_D. The dark fill has radius rr."""
  k = REC_D / REC_SRC_D
  return REC_D / 2 - 2 * k, 3 * k, REC_D * 0.19


def record_ring_recording():
  """(ring radius, glow stroke width, square side, square corner radius): paint_record_button recording branch
  (rr = d / 2 - 3, stroke 5, square d * 0.35 with radius 7), scaled the same way."""
  k = REC_D / REC_SRC_D
  return REC_D / 2 - 3 * k, 5 * k, REC_D * 0.35, 7 * k


def in_rect(r, x, y) -> bool:
  return r[0] <= x < r[2] and r[1] <= y < r[3]


def turn_intent_rect():
  """Unrotated stock turn-intent rect over the personality button."""
  r = PERSONALITY_D / 2
  x0 = PERSONALITY_CX - TURN_INTENT_W / 2
  y1 = PERSONALITY_CY - r - TURN_INTENT_GAP
  return (x0, y1 - TURN_INTENT_H, x0 + TURN_INTENT_W, y1)


@dataclass(frozen=True)
class Visibility:
  pill: bool
  gauge: bool
  dm: bool
  leads: bool
  take_control: bool


def visibility(alert_shown: bool, take_control: bool) -> Visibility:
  hidden = TAKE_CONTROL_HIDES if take_control else (OTHER_ALERT_HIDES if alert_shown else frozenset())
  return Visibility("pill" not in hidden, "gauge" not in hidden, "dm" not in hidden, "leads" not in hidden,
                    bool(take_control))


def dm_position():
  """Top-left for the stock 60 px DriverStateRenderer so it is centred on DM_ICON."""
  cx, cy = (DM_ICON[0] + DM_ICON[2]) / 2, (DM_ICON[1] + DM_ICON[3]) / 2
  return cx - DM_STOCK_SIZE / 2, cy - DM_STOCK_SIZE / 2


def lead_box(cx, cy, d_rel, max_x=VIEW_W, max_y=SCREEN_H, min_x=0.0, gauge=None):
  """Lead lock box (x0, y0, x1, y1) for a lead whose road contact point is (cx, cy): the wide layout's lead_lock_box
  scaled by LEAD_SCALE. With the gauge on screen the box never covers the gauge column."""
  sz = min(30.0, max(15.0, 750.0 / (d_rel / 3.0 + 30.0))) * 2.35 * LEAD_SCALE
  w = sz * 3.2
  h = w * 0.86
  bottom = min(cy + h * 0.1, max_y - LEAD_EDGE)
  if gauge is not None and bottom - h < gauge[3] and gauge[1] < bottom:
    min_x = max(min_x, gauge[2] + 1 - LEAD_EDGE)   # box edge 1 px clear of the gauge's last column
  lo, hi = min_x + w / 2 + LEAD_EDGE, max_x - w / 2 - LEAD_EDGE
  x = min(max(cx, lo), hi) if lo <= hi else (lo + hi) / 2
  return (x - w / 2, bottom - h, x + w / 2, bottom)


def label_size(text_w, px):
  """(width, height) of a speed label with its padding."""
  pad = int(math.floor(px * 0.32 + 0.5))
  return text_w + 2 * pad, int(math.floor(px * 1.15 + 0.5))


def _hits(r, rects, m=0.0):
  return [k for k in rects if r[0] - m < k[2] and k[0] < r[2] + m and r[1] - m < k[3] and k[1] < r[3] + m]


def speed_label_rect(box, lw, lh, keepouts=(), alert_zone=None, side_mode=False, side="primary", view_w=VIEW_W):
  """Where a lead speed label goes: centred above its box (sliding right past keepouts); if that lands in the alert
  zone, below the box, or beside it (outer side; the primary to the right) during userPrompt alerts."""
  cx = (box[0] + box[2]) / 2
  hi = max(LEAD_EDGE, view_w - LEAD_EDGE - lw)

  def above_or_below(y1):
    x0 = min(max(cx - lw / 2, LEAD_EDGE), view_w - LEAD_EDGE - lw)
    for _ in range(8):
      hs = _hits((x0, y1 - lh, x0 + lw, y1), keepouts, LABEL_SLIDE_MARGIN)
      if not hs:
        break
      x0 = max(k[2] for k in hs) + LABEL_SLIDE_MARGIN + 1
    x0 = min(max(x0, LEAD_EDGE), hi)
    return (x0, y1 - lh, x0 + lw, y1)

  r = above_or_below(box[1] - LABEL_GAP)
  if alert_zone is None or not _hits(r, (alert_zone,)):
    return r, "above"
  if side_mode:
    cy = max((box[1] + box[3]) / 2, alert_zone[3] + 2 + lh / 2)
    lx = box[0] - LABEL_GAP - lw / 2 if side == "left" else box[2] + LABEL_GAP + lw / 2
    x0 = min(max(lx - lw / 2, LEAD_EDGE), hi)
    return (x0, cy - lh / 2, x0 + lw, cy + lh / 2), "beside"
  return above_or_below(box[3] + LABEL_GAP + lh), "below"


def _offset(r, ox, oy):
  return (r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)


def turn_intent_bbox(rotation_deg: float):
  """Screen bbox of the stock turn intent over the personality button after its rotation about the button centre
  (raylib: positive = clockwise on screen). Speed labels keep clear of it."""
  x0, y0, x1, y1 = turn_intent_rect()
  a = math.radians(rotation_deg)
  ca, sa = math.cos(a), math.sin(a)
  xs, ys = [], []
  for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
    dx, dy = x - PERSONALITY_CX, y - PERSONALITY_CY
    xs.append(PERSONALITY_CX + dx * ca - dy * sa)
    ys.append(PERSONALITY_CY + dx * sa + dy * ca)
  return (min(xs), min(ys), max(xs), max(ys))
