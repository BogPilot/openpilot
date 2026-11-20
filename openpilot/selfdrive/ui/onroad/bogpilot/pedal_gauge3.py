"""BogPilot 3-bar pedal gauge: the shared state function, colours and a rect-based painter.

Pure Python at import (no pyray), so any HUD (3X, comma 4) and the unit tests can use the state part; only
paint_gauge3() imports pyray, when it draws. The 3X HUD adapter is pedals.py (inputs, colour-source hysteresis, column
placement); a different screen passes its own rect to paint_gauge3().

Bars, left to right (the order is kept on RHD):
  LEFT    friction brake pedal only, 0..1: AP1 the 0x39D rod-stroke level, Pre-AP binary press or the iBooster swap
          pedal position. Never aEgo, never a residual after subtracting regen.
  CENTER  regen TORQUE from 0x108: fill = -min(0, DI_torqueMotor) / REGEN_FULLSCALE_NM (116 Nm, the regen torque
          ceiling seen on AP1 logs). Torque, not kW: kW = Nm * rpm is small at the low speeds where regen happens, so a
          kW bar never filled (full-torque regen read 40-50 %). Drive torque (> 0) and a small deadband read 0. The old
          kW path (motor_power_kw / regen_fill / REGEN_FULLSCALE_KW_*, -55 kW) stays for gauge_state(regen_kw=...) callers.
  RIGHT   acceleration, 0..1: the driver's accelerator pedal (always wins), or, while openpilot controls speed, the
          measured motor drive torque max(0, DI_torqueMotor) / ACCEL_FULLSCALE_NM (200 Nm), the same unit as the foot and
          including the grade term the request leaves out. Without a valid torque it falls back to openpilot's request.
Power log scale (POWER_LOG_SCALE, default on): with a valid DI_motorRPM the CENTER and the openpilot RIGHT bar show motor
  shaft power P = |T * rpm| * pi / 30000 kW on a log scale, fill = ln(1 + P / P0) / ln(1 + Pmax / P0): drive Pmax 320 kW
  (the top mark of the Model S power meter), P0 10 kW; regen Pmax REGEN_PEAK_KW (60 kW), P0 5 kW. Without a valid rpm the
  torque fills above are used (fail soft). The driver's pedal on the RIGHT bar is unchanged (pedal position, linear).
Near-max regen flash: while openpilot controls speed and the regen is at or near the most the car gives (regen torque at
  REGEN_FLASH_ON_FRAC of the DI regen torque ceiling, or openpilot asking for more regen decel than the motor delivers),
  the CENTER fill alternates between REGEN_FLASH_RGB and the openpilot regen blue every REGEN_FLASH_MS (see RegenLimitFlash).
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

# Torque bars (UI only). Regen full scale: the regen torque ceiling seen on every AP1 drive of Nov 19 (peaks -110 to -116 Nm,
# cold and warm alike). Accel full scale: p99 of the motor drive torque on the same drives (p99.9 233 Nm, max 270 Nm).
REGEN_FULLSCALE_NM = 116.0
ACCEL_FULLSCALE_NM = 200.0
# Below this much torque a torque bar reads empty: the 0x108 decode is within about 1 Nm of the CAN frames, so coasting
# noise never flickers a bar (under 1 % of either full scale).
TORQUE_DEADBAND_NM = 1.0

# Power log scale (UI only). fill = ln(1 + P / P0) / ln(1 + Pmax / P0), P in kW of motor shaft power from 0x108 torque and rpm.
POWER_LOG_SCALE = True
ACCEL_FULLSCALE_KW = 320.0            # drive: the top mark of the Model S power meter (20 / 40 / 80 / 160 / 320 kW)
ACCEL_LOG_P0_KW = 10.0
REGEN_PEAK_KW_AP1_S = 60.0            # regen: physical peak regen power per model (proposal, tune per car)
REGEN_PEAK_KW_AP1_X = 60.0
REGEN_PEAK_KW_PREAP = 60.0
REGEN_PEAK_KW_DEFAULT = 60.0
REGEN_PEAK_KW = {
  "TESLA_AP1_MODELS": REGEN_PEAK_KW_AP1_S,
  "TESLA_AP1_MODELX": REGEN_PEAK_KW_AP1_X,
  "TESLA_PREAP_MODELS": REGEN_PEAK_KW_PREAP,
}
REGEN_LOG_P0_KW = 5.0
POWER_DEADBAND_KW = 1.0               # below this a power bar reads empty (coasting noise)

# Near-max regen flash (UI only, openpilot regen colour only).
REGEN_FLASH_RGB = (214, 234, 255)     # #D6EAFF very light blue, alternates with GAUGE3_PALETTE[(REGEN, OP)]
REGEN_FLASH_MS = 400                  # phase length: 400 ms light / 400 ms normal (1.25 Hz), slower than the 200 ms LKAS fault
REGEN_FLASH_ON_FRAC = 0.90            # regen torque >= 90 % of REGEN_FULLSCALE_NM ...
REGEN_FLASH_OFF_FRAC = 0.80           # ... and stays on until it drops under 80 %
REGEN_FLASH_ON_HOLD_S = 0.25          # steady near-max needed before the flash starts
REGEN_FLASH_MIN_SHOW_S = 1.0          # once started it shows at least this long (no flicker)
# Power-limited regen (high speed, cold or full battery): openpilot asks for more regen decel than the motor delivers.
GEAR_RATIO, WHEEL_RADIUS_M, MASS_KG = 9.73, 0.35, 2100.0   # as opendbc tesla_ap1/regen_aware.py
LIMIT_MIN_SPEED_MS = 4.7              # above the low-speed regen fade (regen_aware.LIMIT_MIN_SPEED)
LIMIT_MIN_REQ_DECEL = 0.3             # m/s^2
LIMIT_MARGIN = 0.2                    # m/s^2 request beyond the measured regen decel
LIMIT_HOLD_S = 0.5

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


def motor_torque_value(torque_nm) -> float | None:
  """DI_torqueMotor in Nm as a float; None when missing, not finite or SNA (-1024 Nm). Fail closed: the caller then falls
  back to the previous behaviour (regen bar empty, accel bar from openpilot's request)."""
  tq = _num(torque_nm)
  return None if tq is None or tq <= MOTOR_TORQUE_SNA_NM else tq


def regen_torque_fill(torque_nm, full_scale_nm: float = REGEN_FULLSCALE_NM, deadband_nm: float = TORQUE_DEADBAND_NM) -> float:
  """0..1: -min(0, torque) / full_scale for regen beyond the deadband. Missing, SNA, drive torque, or a full scale that is
  not positive -> 0."""
  tq, fs = motor_torque_value(torque_nm), _num(full_scale_nm)
  if tq is None or fs is None or fs <= 0.0 or tq >= -abs(deadband_nm):
    return 0.0
  return clamp(-tq / fs, 0.0, 1.0)


def accel_torque_fill(torque_nm, full_scale_nm: float = ACCEL_FULLSCALE_NM, deadband_nm: float = TORQUE_DEADBAND_NM) -> float:
  """0..1: max(0, torque) / full_scale for drive torque beyond the deadband. Missing, SNA, regen or coasting, or a full
  scale that is not positive -> 0."""
  tq, fs = motor_torque_value(torque_nm), _num(full_scale_nm)
  if tq is None or fs is None or fs <= 0.0 or tq <= abs(deadband_nm):
    return 0.0
  return clamp(tq / fs, 0.0, 1.0)


def regen_fill(regen_kw, full_scale_kw: float = REGEN_FULLSCALE_KW_DEFAULT, deadband_kw: float = REGEN_DEADBAND_KW) -> float:
  """0..1: regen_kw / full_scale_kw for regen beyond the deadband. Missing, drive power, or a full scale that is not
  negative -> 0."""
  kw, fs = _num(regen_kw), _num(full_scale_kw)
  if kw is None or fs is None or fs >= 0.0 or kw >= -abs(deadband_kw):
    return 0.0
  return clamp(kw / fs, 0.0, 1.0)


def regen_peak_kw(fingerprint) -> float:
  return REGEN_PEAK_KW.get(str(fingerprint or ""), REGEN_PEAK_KW_DEFAULT)


def motor_rpm_value(rpm) -> float | None:
  """DI_motorRPM as a float; None when missing, not finite or SNA."""
  n = _num(rpm)
  return None if n is None or n <= MOTOR_RPM_SNA else n


def log_power_fill(kw, full_kw: float, p0_kw: float, deadband_kw: float = POWER_DEADBAND_KW) -> float:
  """0..1 = ln(1 + P / P0) / ln(1 + Pmax / P0) for P (kW, >= 0) beyond the deadband. Monotonic, 0 -> 0, Pmax -> 1, clamped.
  Missing / junk / bad scale -> 0."""
  p, fs, p0 = _num(kw), _num(full_kw), _num(p0_kw)
  if p is None or fs is None or p0 is None or fs <= 0.0 or p0 <= 0.0 or p <= abs(deadband_kw):
    return 0.0
  return clamp(math.log1p(p / p0) / math.log1p(fs / p0), 0.0, 1.0)


def drive_power_kw(torque_nm, rpm) -> float | None:
  """Drive shaft power, kW >= 0 (regen -> 0). None when torque or rpm is missing / SNA."""
  tq, n = motor_torque_value(torque_nm), motor_rpm_value(rpm)
  if tq is None or n is None:
    return None
  return max(0.0, tq) * abs(n) * math.pi / 30000.0


def regen_power_kw(torque_nm, rpm) -> float | None:
  """Regen shaft power, kW >= 0 (drive -> 0). None when torque or rpm is missing / SNA."""
  tq, n = motor_torque_value(torque_nm), motor_rpm_value(rpm)
  if tq is None or n is None:
    return None
  return max(0.0, -tq) * abs(n) * math.pi / 30000.0


def accel_power_fill(torque_nm, rpm) -> float | None:
  """Log drive-power fill, or None when rpm / torque is missing (the caller then uses the torque fill)."""
  kw = drive_power_kw(torque_nm, rpm)
  return None if kw is None else log_power_fill(kw, ACCEL_FULLSCALE_KW, ACCEL_LOG_P0_KW)


def regen_power_fill(torque_nm, rpm, fingerprint=None) -> float | None:
  """Log regen-power fill, or None when rpm / torque is missing (the caller then uses the torque fill)."""
  kw = regen_power_kw(torque_nm, rpm)
  return None if kw is None else log_power_fill(kw, regen_peak_kw(fingerprint), REGEN_LOG_P0_KW)


def speed_from_rpm(rpm) -> float | None:
  n = motor_rpm_value(rpm)
  return None if n is None else abs(n) / GEAR_RATIO * 2.0 * math.pi * WHEEL_RADIUS_M / 60.0


def regen_decel_from_torque(torque_nm) -> float:
  """Positive decel (m/s^2) the regen torque gives (regen_aware.regen_decel_from_torque)."""
  tq = motor_torque_value(torque_nm)
  return 0.0 if tq is None else max(0.0, -tq) * GEAR_RATIO / WHEEL_RADIUS_M / MASS_KG


class RegenLimitFlash:
  """Near-max regen with hysteresis. update() -> True while the CENTER bar should flash.

  Near max when, with openpilot controlling speed and a valid regen torque:
    torque rule: regen torque >= REGEN_FLASH_ON_FRAC * REGEN_FULLSCALE_NM (the DI regen torque ceiling, low / mid speed),
                 released under REGEN_FLASH_OFF_FRAC;
    power rule:  above LIMIT_MIN_SPEED_MS, openpilot asks for more than LIMIT_MIN_REQ_DECEL and more than the measured regen
                 decel + LIMIT_MARGIN for LIMIT_HOLD_S (regen is power-limited: cold or full battery, high speed).
  Starts after REGEN_FLASH_ON_HOLD_S steady, then shows at least REGEN_FLASH_MIN_SHOW_S. Not long active, a missing torque, a
  driver brake / pedal or a time jump clears it at once."""

  def __init__(self):
    self.reset()

  def reset(self):
    self.on = False
    self.near = False
    self.near_since = None
    self.on_since = None
    self.limit_since = None
    self.t = None

  def update(self, now, long_active, torque_nm, rpm=None, op_accel=0.0, driver_input=False) -> bool:
    t = _num(now)
    tq = motor_torque_value(torque_nm)
    if t is None or not long_active or tq is None or driver_input or (self.t is not None and not 0.0 <= t - self.t <= REGEN_GAP_RESET_S):
      self.reset()
      self.t = t
      return False
    self.t = t
    regen_nm = max(0.0, -tq)
    frac = regen_nm / REGEN_FULLSCALE_NM
    torque_near = frac >= (REGEN_FLASH_OFF_FRAC if self.near else REGEN_FLASH_ON_FRAC)
    # power rule
    v = speed_from_rpm(rpm)
    req = _num(op_accel)
    req_decel = -req if req is not None else 0.0
    plateau = (v is not None and v > LIMIT_MIN_SPEED_MS and regen_nm > 0.0 and req_decel > LIMIT_MIN_REQ_DECEL and
               req_decel > regen_decel_from_torque(tq) + LIMIT_MARGIN)
    if plateau:
      self.limit_since = t if self.limit_since is None else self.limit_since
    else:
      self.limit_since = None
    power_near = self.limit_since is not None and t - self.limit_since >= LIMIT_HOLD_S
    self.near = torque_near or power_near
    if self.near:
      self.near_since = t if self.near_since is None else self.near_since
    else:
      self.near_since = None
    if not self.on and self.near and t - self.near_since >= REGEN_FLASH_ON_HOLD_S:
      self.on, self.on_since = True, t
    elif self.on and not self.near and t - self.on_since >= REGEN_FLASH_MIN_SHOW_S:
      self.on, self.on_since = False, None
    return self.on


def flash_light_phase(millis) -> bool:
  """True in the light half of the flash cycle (REGEN_FLASH_MS light, REGEN_FLASH_MS normal)."""
  m = _num(millis)
  return m is not None and int(math.floor(max(0.0, m) / REGEN_FLASH_MS)) % 2 == 0


@dataclass(frozen=True)
class Gauge3:
  brake: float = 0.0
  regen: float = 0.0
  accel: float = 0.0
  brake_src: str = DRIVER
  regen_src: str = DRIVER
  accel_src: str = DRIVER
  regen_flash: bool = False           # near-max regen: the CENTER fill flashes (openpilot colour only)

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

  def regen_rgb_at(self, millis):
    """CENTER colour at time millis: REGEN_FLASH_RGB in the light phase while flashing (openpilot colour only)."""
    if self.regen_flash and self.regen_src == OP and self.regen > 0.0 and flash_light_phase(millis):
      return REGEN_FLASH_RGB
    return self.regen_rgb

  def segments_at(self, millis):
    """segments() with the near-max regen flash applied at time millis (ms)."""
    return ((self.brake, self.brake_rgb), (self.regen, self.regen_rgb_at(millis)), (self.accel, self.accel_rgb))


EMPTY3 = Gauge3()


_UNSET = object()


def gauge_state(brake_frac, regen_kw, accel_frac, engaged: bool, *, full_scale_kw: float = REGEN_FULLSCALE_KW_DEFAULT,
                brake_by_op: bool = False, accel_by_op: bool = False,
                deadband_kw: float = REGEN_DEADBAND_KW, regen_nm=_UNSET, regen_frac=_UNSET,
                regen_flash: bool = False) -> Gauge3:
  """The three segments from already-measured inputs. brake_frac / accel_frac: 0..1 (None or negative = missing ->
  empty). regen_kw: signed motor power in kW (negative = regen; None = missing -> empty). engaged: openpilot controls
  speed (carControl.longActive). brake_by_op / accel_by_op: that bar's input is openpilot's, not the driver's (only
  honoured while engaged). regen_nm: when given (even None = missing) the regen segment is the torque fill
  (regen_torque_fill of the signed motor torque in Nm) and regen_kw is ignored. regen_frac: when given, the 0..1 regen fill
  as is (the power log fill), overriding both. regen_flash: near-max regen flash (honoured only while engaged)."""
  engaged = bool(engaged)
  if regen_frac is not _UNSET:
    regen = frac01(regen_frac)
  elif regen_nm is not _UNSET:
    regen = regen_torque_fill(regen_nm)
  else:
    regen = regen_fill(regen_kw, full_scale_kw, deadband_kw)
  return Gauge3(brake=frac01(brake_frac), regen=regen, accel=frac01(accel_frac), regen_flash=bool(regen_flash) and engaged,
                brake_src=OP if engaged and brake_by_op else DRIVER,
                regen_src=OP if engaged else DRIVER,
                accel_src=OP if engaged and accel_by_op else DRIVER)


class RegenSmoother:
  """First-order low-pass of a signed regen value (kW, or the motor torque in Nm; time constant tau_s). A missing sample
  resets it (no stale fill)."""

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


def outline_points(poly):
  """The fill outline snapped to pixel centres (floor + 0.5), so a 1 px line always lights one pixel column / row. At a
  fractional x (for example 103.1 on 3X) an unsnapped vertical 1 px line can miss every pixel centre and vanish."""
  return [(math.floor(x) + 0.5, math.floor(y) + 0.5) for x, y in poly]


def inner_rect(bar, scale: float = 1.0):
  x, y, w, h = bar
  i = INSET * scale
  return (x + i, y + i, w - 2 * i, h - 2 * i)


def paint_gauge3(rect, g: Gauge3, scale: float = 1.0, millis=None) -> None:
  """Draw the gauge in rect = (x, y, w, h) screen px. scale: the HUD design scale (for the fill inset only). millis: clock
  for the near-max regen flash (None = monotonic now)."""
  import time
  import pyray as rl
  from openpilot.selfdrive.ui.onroad.bogpilot.style import fill_convex

  if millis is None:
    millis = time.monotonic() * 1000.0
  for bar, (frac, rgb) in zip(bar_rects(rect), g.segments_at(millis), strict=True):
    outer = rl.Rectangle(*bar)
    rl.draw_rectangle_rounded(outer, ROUND, 10, rl.Color(*TRACK_RGB, TRACK_A))
    poly = fill_polygon(inner_rect(bar, scale), frac)
    fill_convex(poly, rl.Color(*rgb, FILL_A))
    if len(poly) >= 3:
      line = rl.Color(*OUTLINE_RGB, OUTLINE_A)
      pts = outline_points(poly)
      for k in range(len(pts)):
        p, q = pts[k], pts[(k + 1) % len(pts)]
        rl.draw_line_ex(rl.Vector2(*p), rl.Vector2(*q), OUTLINE_PX, line)
    rl.draw_rectangle_rounded_lines_ex(outer, ROUND, 10, EDGE_PX, rl.Color(*EDGE_RGB, EDGE_A))
