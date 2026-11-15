"""BogPilot 3-bar pedal gauge: the shared state function, colours and a rect-based painter.

Pure Python at import (no pyray), so any HUD (3X, comma 4) and the unit tests can use the state part; only
paint_gauge3() imports pyray, when it draws. The 3X HUD adapter is pedals.py (inputs, colour-source hysteresis, Option A
placement); a different screen passes its own rect to paint_gauge3().

Bars, left to right (the order is kept on RHD):
  LEFT    friction brake pedal only, 0..1: AP1 the 0x39D rod-stroke level, Pre-AP binary press or the iBooster swap
          pedal position. Never aEgo, never a residual after subtracting regen.
  CENTER  regen POWER from 0x108: kW = DI_torqueMotor (Nm) * DI_motorRPM * pi / 30000 (the same mechanical power as
          tesla_ap1 regen_aware.regen_power_kw, kept signed here). Regen is negative; the bar fills as kW goes from 0 to
          the per-model full scale (REGEN_FULLSCALE_KW_*, -55 kW). Drive power (kW > 0) and a small deadband read 0.
  RIGHT   acceleration request, 0..1: the driver's accelerator pedal, or openpilot's accel request while openpilot
          controls speed. The driver's pedal wins.
Colours: one per bar and source. "driver" = the driver's input or openpilot not controlling speed; "op" = openpilot.
A filled segment gets a 1 px white outline. Missing or invalid inputs give an empty segment (fail closed).
"""
from __future__ import annotations

from dataclasses import dataclass
import math

DRIVER, OP = "driver", "op"
BRAKE, REGEN, ACCEL = "brake", "regen", "accel"

# Colours (RGB, drawn at FILL_A over the track).
GAUGE3_PALETTE = {
  (BRAKE, DRIVER): (198, 40, 40),     # #C62828 driver brake
  (BRAKE, OP): (181, 131, 141),       # #B5838D openpilot braking (AP1 iBooster applied by openpilot)
  (REGEN, DRIVER): (46, 139, 255),    # #2E8BFF regen, openpilot not controlling speed
  (REGEN, OP): (143, 179, 224),       # #8FB3E0 regen while openpilot controls speed
  (ACCEL, DRIVER): (61, 220, 151),    # #3DDC97 driver accelerator pedal
  (ACCEL, OP): (94, 138, 114),        # #5E8A72 openpilot accel request
}
FILL_A = 191                          # about 75 % opacity
OUTLINE_RGB, OUTLINE_A, OUTLINE_PX = (255, 255, 255), 255, 1.0   # around each filled segment, screen px
TRACK_RGB, TRACK_A = (14, 17, 22), 96
EDGE_RGB, EDGE_A, EDGE_PX = (255, 255, 255), 90, 2.0             # track outline, screen px
INSET, ROUND = 4, 0.28                # fill inset in design px (times the HUD scale), raylib roundness
# Footprint: three 36-wide bars with 6 gaps = 120 design px, the old two-pedal footprint (2 x 60).
BAR_W, BAR_GAP = 36, 6
FOOT_W = 3 * BAR_W + 2 * BAR_GAP

# Regen full scale per model (kW, negative). One named constant per legacy model so each can be tuned on its own.
REGEN_FULLSCALE_KW_AP1_S = -55.0
REGEN_FULLSCALE_KW_AP1_X = -55.0
REGEN_FULLSCALE_KW_PREAP = -55.0
REGEN_FULLSCALE_KW_DEFAULT = -55.0
REGEN_FULLSCALE_KW = {
  "TESLA_AP1_MODELS": REGEN_FULLSCALE_KW_AP1_S,
  "TESLA_AP1_MODELX": REGEN_FULLSCALE_KW_AP1_X,
  "TESLA_PREAP_MODELS": REGEN_FULLSCALE_KW_PREAP,
}
# Proposal (UI only): below 1 kW of regen the bar reads empty. The 0x108 torque decode is within about 1 Nm of the CAN
# frames (about 0.5 kW at highway motor speed), so coasting noise never flickers the bar; 1 kW is under 2 % of full scale.
REGEN_DEADBAND_KW = 1.0
# Proposal (UI only): first-order smoothing of the regen kW, time constant in seconds. Short enough to follow a lift-off
# (the bar reaches 63 % of a step in 0.15 s), long enough to hide frame-to-frame torque jitter.
REGEN_TAU_S = 0.15
REGEN_GAP_RESET_S = 1.0               # a longer gap between samples restarts the filter at the new value

# 0x108 SNA values (tesla_ap1_can.dbc VAL_ 264): DI_torqueMotor -4096 x 0.25 Nm, DI_motorRPM -32768.
MOTOR_TORQUE_SNA_NM = -1024.0
MOTOR_RPM_SNA = -32768.0


def clamp(v, lo, hi):
  return lo if v < lo else hi if v > hi else v


def _num(x) -> float | None:
  try:
    v = float(x)
  except (TypeError, ValueError, OverflowError):
    return None
  return v if math.isfinite(v) else None


def frac01(x) -> float:
  """0..1 fill from a 0..1 input; None, NaN, junk or negative (missing) -> 0."""
  v = _num(x)
  return 0.0 if v is None or v <= 0.0 else min(v, 1.0)


def regen_full_scale_kw(fingerprint) -> float:
  return REGEN_FULLSCALE_KW.get(str(fingerprint or ""), REGEN_FULLSCALE_KW_DEFAULT)


def motor_power_kw(torque_nm, rpm) -> float | None:
  """Signed motor power in kW = Nm * rpm * 2 pi / 60 / 1000 = Nm * rpm * pi / 30000 (negative = regen).
  None when either input is missing, not finite or SNA (fail closed: the regen bar stays empty)."""
  tq, n = _num(torque_nm), _num(rpm)
  if tq is None or n is None or tq <= MOTOR_TORQUE_SNA_NM or n <= MOTOR_RPM_SNA:
    return None
  return tq * n * math.pi / 30000.0


def regen_fill(regen_kw, full_scale_kw: float = REGEN_FULLSCALE_KW_DEFAULT, deadband_kw: float = REGEN_DEADBAND_KW) -> float:
  """0..1: regen_kw / full_scale_kw for regen beyond the deadband. Missing, drive power, or a full scale that is not
  negative -> 0."""
  kw, fs = _num(regen_kw), _num(full_scale_kw)
  if kw is None or fs is None or fs >= 0.0 or kw >= -abs(deadband_kw):
    return 0.0
  return clamp(kw / fs, 0.0, 1.0)


@dataclass(frozen=True)
class Gauge3:
  brake: float = 0.0
  regen: float = 0.0
  accel: float = 0.0
  brake_src: str = DRIVER
  regen_src: str = DRIVER
  accel_src: str = DRIVER

  @property
  def brake_rgb(self):
    return GAUGE3_PALETTE[(BRAKE, self.brake_src)]

  @property
  def regen_rgb(self):
    return GAUGE3_PALETTE[(REGEN, self.regen_src)]

  @property
  def accel_rgb(self):
    return GAUGE3_PALETTE[(ACCEL, self.accel_src)]

  def segments(self):
    """((fill, rgb) for LEFT, CENTER, RIGHT)."""
    return ((self.brake, self.brake_rgb), (self.regen, self.regen_rgb), (self.accel, self.accel_rgb))


EMPTY3 = Gauge3()


def gauge_state(brake_frac, regen_kw, accel_frac, engaged: bool, *, full_scale_kw: float = REGEN_FULLSCALE_KW_DEFAULT,
                brake_by_op: bool = False, accel_by_op: bool = False,
                deadband_kw: float = REGEN_DEADBAND_KW) -> Gauge3:
  """The three segments from already-measured inputs. brake_frac / accel_frac: 0..1 (None or negative = missing ->
  empty). regen_kw: signed motor power in kW (negative = regen; None = missing -> empty). engaged: openpilot controls
  speed (carControl.longActive). brake_by_op / accel_by_op: that bar's input is openpilot's, not the driver's (only
  honoured while engaged)."""
  engaged = bool(engaged)
  return Gauge3(brake=frac01(brake_frac), regen=regen_fill(regen_kw, full_scale_kw, deadband_kw), accel=frac01(accel_frac),
                brake_src=OP if engaged and brake_by_op else DRIVER,
                regen_src=OP if engaged else DRIVER,
                accel_src=OP if engaged and accel_by_op else DRIVER)


class RegenSmoother:
  """First-order low-pass of the regen kW (time constant tau_s). A missing sample resets it (no stale fill)."""

  def __init__(self, tau_s: float = REGEN_TAU_S):
    self.tau_s = float(tau_s)
    self.reset()

  def reset(self):
    self.kw = None
    self.t = None

  def update(self, kw, now: float) -> float | None:
    v, t = _num(kw), _num(now)
    if v is None or t is None:
      self.reset()
      return None
    if self.kw is None or self.t is None or not 0.0 <= t - self.t <= REGEN_GAP_RESET_S or self.tau_s <= 0.0:
      self.kw = v
    else:
      dt = t - self.t
      self.kw += (v - self.kw) * dt / (self.tau_s + dt)
    self.t = t
    return self.kw


# ---- geometry and paint (rect = the whole footprint in screen px) ----

def bar_rects(rect):
  """(x, y, w, h) screen rects of LEFT, CENTER, RIGHT inside rect = (x, y, w, h), in the 36 / 6 proportions."""
  x, y, w, h = rect
  bw, gap = w * BAR_W / FOOT_W, w * BAR_GAP / FOOT_W
  return tuple((x + i * (bw + gap), y, bw, h) for i in range(3))


def corner_radius(w: float, h: float) -> float:
  """Corner radius raylib uses for draw_rectangle_rounded(roundness=ROUND)."""
  return ROUND * min(w, h) / 2.0


def fill_top(inner_y: float, inner_h: float, frac: float) -> float:
  return inner_y + inner_h * (1.0 - clamp(frac, 0.0, 1.0))


def fill_polygon(inner, frac: float, n: int = 6):
  """Convex outline of the filled part: the inner rounded rect cut flat at fill_top (no scissor, so the HUD's content
  scissor is never touched). inner = (x, y, w, h) in screen px. [] when empty."""
  x, y, w, h = inner
  frac = clamp(frac, 0.0, 1.0)
  if frac <= 0 or w <= 0 or h <= 0:
    return []
  r = corner_radius(w, h)
  outline = []
  for cx, cy, a0 in ((x + w - r, y + h - r, 0.0), (x + r, y + h - r, 90.0), (x + r, y + r, 180.0), (x + w - r, y + r, 270.0)):
    for j in range(n + 1):
      a = math.radians(a0 + 90.0 * j / n)
      outline.append((cx + r * math.cos(a), cy + r * math.sin(a)))
  top = fill_top(y, h, frac)
  out = []
  for k in range(len(outline)):   # Sutherland-Hodgman against y >= top
    p, q = outline[k], outline[(k + 1) % len(outline)]
    pin, qin = p[1] >= top, q[1] >= top
    if pin:
      out.append(p)
    if pin != qin:
      t = (top - p[1]) / (q[1] - p[1])
      out.append((p[0] + (q[0] - p[0]) * t, top))
  return out


def inner_rect(bar, scale: float = 1.0):
  x, y, w, h = bar
  i = INSET * scale
  return (x + i, y + i, w - 2 * i, h - 2 * i)


def paint_gauge3(rect, g: Gauge3, scale: float = 1.0) -> None:
  """Draw the gauge in rect = (x, y, w, h) screen px. scale: the HUD design scale (for the fill inset only)."""
  import pyray as rl
  from openpilot.selfdrive.ui.onroad.bogpilot.style import fill_convex

  for bar, (frac, rgb) in zip(bar_rects(rect), g.segments(), strict=True):
    outer = rl.Rectangle(*bar)
    rl.draw_rectangle_rounded(outer, ROUND, 10, rl.Color(*TRACK_RGB, TRACK_A))
    poly = fill_polygon(inner_rect(bar, scale), frac)
    fill_convex(poly, rl.Color(*rgb, FILL_A))
    if len(poly) >= 3:
      line = rl.Color(*OUTLINE_RGB, OUTLINE_A)
      for k in range(len(poly)):
        p, q = poly[k], poly[(k + 1) % len(poly)]
        rl.draw_line_ex(rl.Vector2(*p), rl.Vector2(*q), OUTLINE_PX, line)
    rl.draw_rectangle_rounded_lines_ex(outer, ROUND, 10, EDGE_PX, rl.Color(*EDGE_RGB, EDGE_A))
