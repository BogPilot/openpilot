"""comma 4 BogPilot onroad layout: geometry, the device gate and the per-frame visibility rules (no drawing here).

The comma 4 is device type "mici" (536 x 240 px at 300 PPI; the camera view is 476 px wide, the 60 px side panel
holds the confidence ball). The layout is used ONLY when the device type is "mici", and only from the mici onroad
renderers, so the comma 3X path (tici / tizi, big UI) never reaches this code.

All rects are (x0, y0, x1, y1) in screen pixels with x1 / y1 exclusive.
"""
from __future__ import annotations

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

# Driver-monitor icon, top right of the camera view.
DM_ICON = (414, 8, 470, 64)

# Personality button (also the personality indicator): 40 px disc, far lower left, 48 x 48 tap target.
PERSONALITY_CX, PERSONALITY_CY = 28, 212
PERSONALITY_D = 40
PERSONALITY_TAP = 48
PERSONALITY_STRIPE_W, PERSONALITY_STRIPE_H, PERSONALITY_STRIPE_PITCH = 18, 4, 8

# Three-bar pedal gauge, hard left directly above the personality button: brake | regen | accel.
GAUGE_X0, GAUGE_Y0 = 8, 112
GAUGE_BAR_W, GAUGE_BAR_GAP, GAUGE_H = 12, 2, 76
REGEN_FULL_SCALE_KW = 55.0

# Record button: the wide-layout paint_record_button look scaled to a 40 px disc, lower right in the side panel
# (same inset from the right and bottom as the personality button has from the left and bottom).
REC_CX, REC_CY = SCREEN_W - 28, 212
REC_D = 40
REC_SRC_D = 124                              # style.REC_DIAMETER (wide layout)

# Lane-change arrows (green, during preLaneChange / laneChange only): visible core rects under the pill (left) and
# centred under the driver-monitor icon (right), the rows the lead speed labels use.
ARROW_CORE_W, ARROW_CORE_H = 46, 39
ARROW_Y0 = 68
ARROW_LEFT_X0 = 8
ARROW_RIGHT_CX = (DM_ICON[0] + DM_ICON[2]) / 2
# Stock icons_mici/onroad/turn_signal_left.png (104 x 96) drawn at 0.7: 73 x 67, visible core offset (14, 14).
ARROW_TEX_SCALE = 0.7
ARROW_TEX_W, ARROW_TEX_H = 73, 67
ARROW_CORE_OFFSET = (14, 14)
# What our arrows do while the stock lane-change alert (which draws its own arrow and text) is on screen:
#   "overlap"  keep them at the owner's position (they sit inside the alert's text area)
#   "hide"     hide them while the stock lane-change alert shows
# Moving them clear of the alert needs a new position from the owner, so it is not offered here.
ARROWS_WITH_STOCK_LC_ALERT = "overlap"
ARROW_MODES = ("overlap", "hide")

# Stock turn intent (white, from the same lane-change events) drawn over the personality button the way stock draws it
# over the wheel: centred on the button, bottom 5 px above it, rotated about the button centre, at 44 x 18.
TURN_INTENT_W, TURN_INTENT_H, TURN_INTENT_GAP = 44, 18, 5

# Engagement border on the camera view edge; the blind-spot side's half turns red.
BORDER_W = 3
ARC_RAISE_PX = 10

# What a take-control alert hides. One constant so the rule is easy to change. The lead boxes stay on (always on,
# engaged or not, through every alert), as in the approved mockup's pixels.
TAKE_CONTROL_HIDES = frozenset({"pill", "gauge", "dm"})
# Any other on-screen alert covers the top of the view: the pill, gauge and driver-monitor icon step aside.
OTHER_ALERT_HIDES = frozenset({"pill", "gauge", "dm"})


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


def arrow_tex_origin(direction: int):
  """Top-left of the 73 x 67 texture so its visible core lands on arrow_core_rect (the right arrow is the left one
  mirrored, so its core offset is measured from the texture's right edge)."""
  core = arrow_core_rect(direction)
  ox = core[0] - (ARROW_CORE_OFFSET[0] if direction < 0 else ARROW_TEX_W - ARROW_CORE_OFFSET[0] - ARROW_CORE_W)
  return ox, core[1] - ARROW_CORE_OFFSET[1]


def arrow_visible(direction: int, stock_lc_alert_shown: bool, mode: str = None) -> bool:
  mode = ARROWS_WITH_STOCK_LC_ALERT if mode is None else mode
  if direction == 0:
    return False
  return not (mode == "hide" and stock_lc_alert_shown)


def turn_intent_rect():
  """Unrotated stock turn-intent rect over the personality button."""
  r = PERSONALITY_D / 2
  x0 = PERSONALITY_CX - TURN_INTENT_W / 2
  y1 = PERSONALITY_CY - r - TURN_INTENT_GAP
  return (x0, y1 - TURN_INTENT_H, x0 + TURN_INTENT_W, y1)


def arrow_core_rect(direction: int):
  """direction -1 left, +1 right."""
  x0 = ARROW_LEFT_X0 if direction < 0 else ARROW_RIGHT_CX - ARROW_CORE_W / 2
  return (x0, ARROW_Y0, x0 + ARROW_CORE_W, ARROW_Y0 + ARROW_CORE_H)


class LaneChangeArrow:
  """Arrow direction from the lane-change events only (the blinkers are NOT read), like the stock turn intent:
  preLaneChangeLeft / preLaneChangeRight set the direction; laneChange keeps the last pre direction; anything else
  clears it. Returns -1, +1 or 0 (hidden)."""

  def __init__(self):
    self.direction = 0

  def update(self, event_names, model_direction=None) -> int:
    """event_names: onroadEvents names this frame. model_direction: modelV2.meta.laneChangeDirection ("left" /
    "right" / "none"), used only when laneChange arrives without a pre frame."""
    names = {str(n) for n in event_names}
    left, right = "preLaneChangeLeft" in names, "preLaneChangeRight" in names
    if left or right:
      self.direction = -1 if left else 1
    elif "laneChange" in names:
      if self.direction == 0:
        md = str(model_direction)
        self.direction = -1 if md == "left" else 1 if md == "right" else 0
    else:
      self.direction = 0
    return self.direction


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
