"""BogPilot pedal bars (replaces the pedal icons in the same footprint).

Two vertical bars in the old pedals' rect (2 x 60 x 120 under the accel graph on the driver side; pedal_rect, the same
rect bottom_corner_keepout reserves). Decel on the left, accel on the right; RHD mirrors the position and keeps the
order (daily did not swap the pedals for RHD either). Fill alpha FILL_A = 191 (about 75 % opacity).

Gate (UNCHANGED): openpilot longitudinal and CustomUI and PedalsOnUI, then the Dynamic / Static sub-modes; with neither
the widget is hidden (policy_from_store).

Heights (Dynamic):
  accel  max(carState.deprecated.gas, OP carControl.actuators.accel / OP_ACCEL_FULL_SCALE), 0..1. deprecated.gas is
         DI_pedalPos / 100 set by the tesla_ap1 and Pre-AP carstate (no schema change). OP accel counts only while
         carControl.longActive and fresh.
  decel  AP1: total braking decel max(0, -carState.aEgo) (regen + friction) on ONE continuous scale (ap1_decel_height):
         0..AP1_BAR_REGEN_REF fills 0..50 %, AP1_BAR_REGEN_REF..AP1_BAR_TOP fills 50..100 %. The anchor is a FIXED decel
         (peak no-pedal decel measured over all speeds), so weaker regen (high speed, low-speed fade) reads lower and a
         press simply adds on top. Pre-AP / other: as before (decel_fill_legacy: regen half on the regen scale, a brake
         press at least half).
Colours (PEDAL_BAR_PALETTE), one source per bar; the driver wins:
  accel  driver gas pedal pressed -> human green; else longActive and OP accel > 0 -> OP sage; else human green.
  decel  AP1 has NO car-side regen / friction blending: any iBooster application (driver or OP) adds friction at once
         and regen runs in parallel. So friction = max(0, measured decel - regen being applied), and it exists only
         while the iBooster is applied; with no press / command the bar is blue whatever the decel. Regen being applied
         = the live motor regen from DI_torqueMotor (bogpilotCarState.ap1MotorTorqueNm, RA.regen_decel_from_torque),
         else the measured table ap1_regen_capacity(vEgo) (UI only, NOT the control estimate). Share = friction /
         decel. AP1, brakePressed: violet below SHARE_VIOLET_BELOW, red above SHARE_RED_ABOVE, the colour holds in
         between; at a standstill red (friction holds the car); red when the brake level frame is missing / stale
         (carState.deprecated.brake < 0). The colour keys off brakePressed only (the rod stroke lags it). AP1 OP:
         lavender / rose by the same share ONLY while OP is applying the iBooster: longActive AND
         bogpilotCarState.ap1BrakePedalState == ON (DI_brakePedalState) AND NOT brakePressed (a driver press always wins,
         violet / red). Stale or missing state (SNA, stale bogpilotCarState) -> OP dusty blue; being past regen
         capacity never triggers it.
         Else longActive and OP accel < 0 -> OP dusty blue; else human regen blue. Pre-AP / other: brakePressed ->
         red; else OP dusty blue / human blue as before.
  Hysteresis: thresholds have an on / off deadband, and a source change waits SOURCE_HOLD_S of steady request, except a
  change TO an active driver input (pedal or brake), which shows at once; so an alternating input cannot flicker.
  Leaving an OP brake colour (lavender / rose) waits SOURCE_HOLD_S from the first frame the request left it, even if the
  request then moves between the regen colours, so it ends at most SOURCE_HOLD_S plus one frame after OP stops.
Static (on / off, the daily rule): decel bar full when daily_opacity's brake is 1 (standstill, brakeLights or
  aEgo < -0.25), accel bar full when its gas is 1 (aEgo > 0.25); colours as above. brakeLights is never set by the car
  code today, so in practice the Static decel bar lights at standstill or when decelerating.
Stale or missing carState: both bars empty and the colour state resets. NaN / missing inputs read as 0.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from opendbc.car.interfaces import ACCEL_MAX, ACCEL_MIN
from opendbc.car.tesla_ap1 import regen_aware as RA
from opendbc.car.tesla_ap1.preap import vdas_constants as VDAS

REST = 0.25
EDGE = 30
STACK_BOTTOM = 468
PEDAL_W, PEDAL_H, PEDAL_GAP = 60, 120, 18

# OP accel that fills the green bar: the controlsd clip (interfaces.ACCEL_MAX via get_pid_accel_limits, clipped in
# longcontrol), which tesla_ap1 does not override, so it is the most OP can command on AP1 AND Pre-AP. The Pre-AP spec
# value VDAS.ACCEL_MAX (vdas_constants.py, 2.5) is NOT used: OP accel never exceeds the 2.0 clip, so a 2.5 divisor
# would cap OP's bar at 80 %. Change this one name to change the scale.
OP_ACCEL_FULL_SCALE = ACCEL_MAX
PREAP_SPEC_ACCEL_MAX = VDAS.ACCEL_MAX          # documented only (see above)

# Decel bar. Pre-AP / other keep the two-half layout (regen half on regen_scale, brake press from 50 %).
DECEL_FULL_SCALE = -ACCEL_MIN    # 3.5 m/s^2: top of the bar (AP1 and the legacy layout)
REGEN_HALF = 0.5                 # the regen anchor fills this much
# AP1, UI ONLY (measured on the AP1 drive logs; see DIVERGENCES). Controls keep regen_aware.regen_capacity untouched.
AP1_BAR_REGEN_REF = 2.0          # m/s^2 total decel at 50 %: p95 of no-pedal decel over all speeds (1.96)
AP1_BAR_TOP = DECEL_FULL_SCALE   # 3.5 m/s^2 at 100 %: driver-braking total decel p99 is 3.2
# Fallback regen (m/s^2) by speed for the friction share when the live motor torque is missing: p99 of the motor-torque
# regen decel with no pedal (brake and gas released, no OP longitudinal, rod at rest; grade-free), 1 m/s bins below
# 10 m/s, then 5 m/s, over the AP1 drive logs (the 35-40 m/s bin is too thin and is left out).
AP1_REGEN_V = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 12.5, 17.5, 22.5, 27.5, 32.5)
AP1_REGEN_A = (0.24, 0.32, 0.88, 1.38, 1.52, 1.52, 1.52, 1.52, 1.54, 1.50, 1.38, 0.92, 0.80, 0.78, 0.44)
MOTOR_TORQUE_SNA_NM = -1024.0    # DI_torqueMotor raw -4096 x 0.25: signal not available
SHARE_RED_ABOVE = 0.55           # friction share hysteresis: red above, violet below SHARE_VIOLET_BELOW, hold between
SHARE_VIOLET_BELOW = 0.45
DI_BRAKE_STATE_ON = 1             # bogpilotCarState.ap1BrakePedalState ON (tesla_ap1 brake_level.DI_BRAKE_STATE_ON)
STANDSTILL_V = 0.3               # m/s: below this a pressed brake is holding the car (friction)

PREAP = "TESLA_PREAP_MODELS"
AP1 = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX")

# ---- PEDAL_BAR_PALETTE: every bar colour lives here (RGB; drawn at FILL_A) ----
ACCEL_HUMAN, ACCEL_OP = "accel_human", "accel_op"
DECEL_HUMAN_REGEN, DECEL_OP_REGEN, DECEL_HUMAN_BRAKE, DECEL_OP_BRAKE = "decel_human_regen", "decel_op_regen", \
  "decel_human_brake", "decel_op_brake"
DECEL_HUMAN_LIGHT, DECEL_OP_LIGHT = "decel_human_light", "decel_op_light"
PEDAL_BAR_OP_BRAKE_ROSES = {
  "rose_mix": (214, 110, 112),     # between the human red and dusty rose (default)
  "dusty_rose": (201, 169, 166),   # pure dusty rose #C9A9A6
}
PEDAL_BAR_OP_BRAKE_ROSE = "rose_mix"   # flip to "dusty_rose" for the pure shade
PEDAL_BAR_PALETTE = {
  ACCEL_HUMAN: (64, 206, 84),          # driver gas pedal: the old gas pedal green
  ACCEL_OP: (163, 190, 140),           # OP accel request: sage #A3BE8C (a lighter #9CAF88 so it reads on the camera)
  DECEL_HUMAN_REGEN: (90, 205, 255),   # regen with OP not commanding: the old blue
  DECEL_OP_REGEN: (122, 155, 191),     # OP regen decel: dusty blue #7A9BBF
  DECEL_HUMAN_BRAKE: (238, 48, 44),    # brakePressed: the old brake red
  DECEL_HUMAN_LIGHT: (176, 124, 255),  # driver brake, regen has the majority (AP1): bright violet #B07CFF
  DECEL_OP_LIGHT: (154, 134, 184),     # OP past regen, regen has the majority (AP1): muted lavender #9A86B8
  DECEL_OP_BRAKE: None,                # OP past regen, friction has the majority (AP1): PEDAL_BAR_OP_BRAKE_ROSES[...]
}
BRAKING = (DECEL_HUMAN_BRAKE, DECEL_HUMAN_LIGHT, DECEL_OP_LIGHT, DECEL_OP_BRAKE)
HUMAN_BRAKING = (DECEL_HUMAN_BRAKE, DECEL_HUMAN_LIGHT)
OP_BRAKING = (DECEL_OP_LIGHT, DECEL_OP_BRAKE)


def bar_color(source: str):
  if source == DECEL_OP_BRAKE:
    return PEDAL_BAR_OP_BRAKE_ROSES[PEDAL_BAR_OP_BRAKE_ROSE]
  return PEDAL_BAR_PALETTE[source]


# ---- source thresholds and hysteresis ----
PEDAL_ON, PEDAL_OFF = 0.02, 0.01        # pedal 0..1; 2 % = the Pre-AP stock pressed threshold (DI_pedalPos noise)
OP_ACCEL_ON, OP_ACCEL_OFF = 0.10, 0.05  # m/s^2: OP counts as commanding accel (or decel, mirrored)
SOURCE_HOLD_S = 0.25                    # steady request needed to change colour (not for a new driver input); also
                                        # the longest an OP brake colour stays after OP stops braking (plus one frame)

FILL_A = 191                 # about 75 % opacity (25 % transparent)
TRACK_RGB, TRACK_A = (14, 17, 22), 96
EDGE_RGB, EDGE_A = (255, 255, 255), 90
BAR_W, BAR_GAP_X, INSET, ROUND = 52, 16, 4, 0.28


def clamp(v, lo, hi):
  return lo if v < lo else hi if v > hi else v


def finite(x) -> float:
  try:
    x = float(x)
  except (TypeError, ValueError):
    return 0.0
  return x if math.isfinite(x) else 0.0


@dataclass(frozen=True)
class PedalPolicy:
  show: bool = False
  dynamic: bool = False
  static: bool = False


CLOSED = PedalPolicy()


@dataclass(frozen=True)
class Bars:
  decel: float = 0.0
  decel_src: str = DECEL_HUMAN_REGEN
  accel: float = 0.0
  accel_src: str = ACCEL_HUMAN

  @property
  def braking(self) -> bool:
    return self.decel_src in BRAKING


EMPTY = Bars()


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
  """(brake, gas) exactly as daily paintPedalIcons, clamped like QPainter::setOpacity. Static mode uses it on / off."""
  brake = gas = 1.0
  if policy.dynamic:
    brake = 1.0 if standstill else (max(0.25, abs(a_ego)) if a_ego < -0.25 else 0.25)
    gas = max(0.25, a_ego)
  elif policy.static:
    brake = 1.0 if (standstill or brake_lights or a_ego < -0.25) else 0.25
    gas = 1.0 if a_ego > 0.25 else 0.25
  return clamp(brake, 0.0, 1.0), clamp(gas, 0.0, 1.0)


def platform_of(fingerprint) -> str:
  fp = str(fingerprint or "")
  return "preap" if fp == PREAP else "ap1" if fp in AP1 else "other"


def accel_fraction(pedal_pos, op_accel) -> float:
  """max(driver pedal 0..1, OP accel / OP_ACCEL_FULL_SCALE), clamped 0..1."""
  return max(clamp(finite(pedal_pos), 0.0, 1.0), clamp(finite(op_accel) / OP_ACCEL_FULL_SCALE, 0.0, 1.0))


def regen_scale(v_ego, platform: str) -> float:
  """Legacy layout's regen scale (m/s^2, > 0). Pre-AP: |VDAS.REGEN_MAX| (1.5). Otherwise the control regen estimate at
  the nominal power (read only), floored at RA.A_GENTLE_FLOOR. AP1 bars use ap1_regen_capacity instead."""
  if platform == "preap":
    return abs(VDAS.REGEN_MAX)
  return max(RA.A_GENTLE_FLOOR, RA.regen_capacity(max(0.0, finite(v_ego)), RA.P_NOMINAL_KW))


def brake_level_of(level) -> float | None:
  """carState.deprecated.brake -> 0..1; None when missing / stale / bad checksum (negative, not finite, not a number)."""
  try:
    x = float(level)
  except (TypeError, ValueError):
    return None
  if not math.isfinite(x) or x < 0.0:
    return None
  return clamp(x, 0.0, 1.0)


def regen_part(a_ego, v_ego, platform: str) -> float:
  """Legacy bottom half: measured decel on the regen scale, 0..REGEN_HALF."""
  decel = max(0.0, -finite(a_ego))
  return REGEN_HALF * clamp(decel / regen_scale(v_ego, platform), 0.0, 1.0)


def beyond_regen(decel, v_ego, platform: str) -> float:
  """0..1 position of a decel (m/s^2, > 0) between the regen scale and DECEL_FULL_SCALE."""
  cap = regen_scale(v_ego, platform)
  span = DECEL_FULL_SCALE - cap
  if span <= 0:
    return 1.0 if decel > cap else 0.0
  return clamp((decel - cap) / span, 0.0, 1.0)


def top_half(frac) -> float:
  return REGEN_HALF + (1.0 - REGEN_HALF) * clamp(frac, 0.0, 1.0)


def decel_fill_legacy(source: str, a_ego, v_ego, platform: str) -> float:
  """Pre-AP / other: brake press -> 50 % + measured decel past the regen scale; otherwise the regen half."""
  if source in BRAKING:
    return top_half(beyond_regen(max(0.0, -finite(a_ego)), v_ego, platform))
  return regen_part(a_ego, v_ego, platform)


def ap1_regen_capacity(v_ego) -> float:
  """UI-only regen capacity (m/s^2) at speed, linear between the measured bins, flat past the ends."""
  v = max(0.0, finite(v_ego))
  xs, ys = AP1_REGEN_V, AP1_REGEN_A
  if v <= xs[0]:
    return ys[0]
  for i in range(1, len(xs)):
    if v <= xs[i]:
      return ys[i - 1] + (ys[i] - ys[i - 1]) * (v - xs[i - 1]) / (xs[i] - xs[i - 1])
  return ys[-1]


def ap1_decel_height(a_ego) -> float:
  """Total decel on one continuous scale: 0..REF -> 0..50 %, REF..TOP -> 50..100 %."""
  decel = max(0.0, -finite(a_ego))
  if decel <= AP1_BAR_REGEN_REF:
    return REGEN_HALF * decel / AP1_BAR_REGEN_REF
  return top_half((decel - AP1_BAR_REGEN_REF) / (AP1_BAR_TOP - AP1_BAR_REGEN_REF))


def regen_live(motor_torque_nm) -> float | None:
  """Regen decel (m/s^2) the motor is applying now, from DI_torqueMotor (read-only use of the regen_aware helper).
  None when missing, not finite or SNA."""
  try:
    tq = float(motor_torque_nm)
  except (TypeError, ValueError):
    return None
  if not math.isfinite(tq) or tq <= MOTOR_TORQUE_SNA_NM:
    return None
  return RA.regen_decel_from_torque(tq)


def friction_share(decel, v_ego, regen=None) -> float:
  """No blending: friction = max(0, decel - regen being applied); share = friction / decel, 0..1. regen: live regen
  (regen_live) or None for the measured table. 1 at a standstill (friction holds the car); 0 with no decel."""
  v = max(0.0, finite(v_ego))
  if v < STANDSTILL_V:
    return 1.0
  if decel <= 0.0:
    return 0.0
  r = ap1_regen_capacity(v) if regen is None else max(0.0, finite(regen))
  return clamp(max(0.0, decel - r) / decel, 0.0, 1.0)


def op_ibooster_applied(brake_pedal_state, long_active, brake_pressed) -> bool:
  """OP is applying the iBooster: long control active, DI_brakePedalState ON and no driver press. Anything else
  (OFF, INVALID, SNA, stale = None, junk) is False, so OP decel stays dusty blue."""
  try:
    on = int(brake_pedal_state) == DI_BRAKE_STATE_ON and float(brake_pedal_state) == DI_BRAKE_STATE_ON
  except (TypeError, ValueError, OverflowError):
    return False
  return bool(long_active) and on and not bool(brake_pressed)


def _by_share(share, cur, light, heavy):
  if share > SHARE_RED_ABOVE:
    return heavy
  if share < SHARE_VIOLET_BELOW:
    return light
  if cur in (light, heavy):
    return cur                                     # band holds
  return heavy if share >= 0.5 else light


class PedalBars:
  """Per-frame bar state with the colour hysteresis. update() returns Bars."""

  def __init__(self):
    self.reset()

  def reset(self):
    self.accel_src, self.decel_src = ACCEL_HUMAN, DECEL_HUMAN_REGEN
    self._pedal_on = False
    self._pend = {"a": (None, 0.0), "d": (None, 0.0)}

  def _settle(self, key, cur, want, now, immediate):
    if want == cur:
      self._pend[key] = (None, 0.0)
      return cur
    if immediate:
      self._pend[key] = (None, 0.0)
      return want
    pend, since = self._pend[key]
    if pend != want:
      # Leaving an OP brake colour: keep timing from the first frame the request left it while the target only moves
      # between non-OP-brake colours (e.g. OP regen <-> human regen), so that move cannot restart the hold.
      keep = cur in OP_BRAKING and pend is not None and pend not in OP_BRAKING and want not in OP_BRAKING
      if not keep:
        self._pend[key] = (want, now)
        return cur
      self._pend[key] = (want, since)
    if now - since >= SOURCE_HOLD_S:
      self._pend[key] = (None, 0.0)
      return want
    return cur

  def _accel_want(self, pedal, op, long_active):
    self._pedal_on = pedal > (PEDAL_OFF if self._pedal_on else PEDAL_ON)
    if self._pedal_on:
      return ACCEL_HUMAN
    if long_active and op > (OP_ACCEL_OFF if self.accel_src == ACCEL_OP else OP_ACCEL_ON):
      return ACCEL_OP
    return ACCEL_HUMAN

  def _decel_want(self, brake_pressed, op, v_ego, long_active, platform, level, a_ego, regen=None, op_brake=False):
    if platform == "ap1":
      decel = max(0.0, -finite(a_ego))
      if brake_pressed:
        if level is None:
          return DECEL_HUMAN_BRAKE                   # no brake level (missing / stale frame): red
        return _by_share(friction_share(decel, v_ego, regen), self.decel_src, DECEL_HUMAN_LIGHT, DECEL_HUMAN_BRAKE)
      if long_active and op_brake:                   # OP applying the iBooster (DI_brakePedalState ON, no driver press)
        return _by_share(friction_share(decel, v_ego, regen), self.decel_src, DECEL_OP_LIGHT, DECEL_OP_BRAKE)
    elif brake_pressed:
      return DECEL_HUMAN_BRAKE
    if long_active and op < -(OP_ACCEL_OFF if self.decel_src in (DECEL_OP_REGEN,) + OP_BRAKING else OP_ACCEL_ON):
      return DECEL_OP_REGEN
    return DECEL_HUMAN_REGEN

  def update(self, policy: PedalPolicy, fresh: bool, now: float, a_ego, v_ego, standstill: bool, brake_pressed: bool,
             brake_lights: bool, pedal_pos, op_accel, long_active: bool, platform: str, brake_level=None,
             motor_torque_nm=None, op_brake_active: bool = False, brake_pedal_state=None) -> Bars:
    """op_accel: carControl.actuators.accel (used only while long_active). now: monotonic seconds. brake_level:
    carState.deprecated.brake (0..1, negative = missing); motor_torque_nm: bogpilotCarState.ap1MotorTorqueNm (None
    when stale); op_brake_active: OP is applying the iBooster; brake_pedal_state: bogpilotCarState.ap1BrakePedalState
    (None when stale), ON sets op_brake_active. The last four are used on AP1 only."""
    if not policy.show or not fresh:
      self.reset()
      return EMPTY
    pedal, op, v = finite(pedal_pos), finite(op_accel) if long_active else 0.0, finite(v_ego)
    want_a = self._accel_want(pedal, op, bool(long_active))
    self.accel_src = self._settle("a", self.accel_src, want_a, now, want_a == ACCEL_HUMAN and self._pedal_on)
    level = brake_level_of(brake_level) if platform == "ap1" else None
    regen = regen_live(motor_torque_nm) if platform == "ap1" else None
    want_d = self._decel_want(bool(brake_pressed), op, v, bool(long_active), platform, level, a_ego, regen,
                              bool(op_brake_active) or op_ibooster_applied(brake_pedal_state, long_active, brake_pressed))
    # a new driver brake input shows at once; violet <-> red and everything else wait for a steady request
    new_press = want_d in HUMAN_BRAKING and self.decel_src not in HUMAN_BRAKING
    self.decel_src = self._settle("d", self.decel_src, want_d, now, new_press)
    if policy.dynamic:
      fill = ap1_decel_height(a_ego) if platform == "ap1" else decel_fill_legacy(self.decel_src, a_ego, v, platform)
      return Bars(fill, self.decel_src, accel_fraction(pedal, op), self.accel_src)
    brake, gas = daily_opacity(policy, finite(a_ego), bool(standstill), bool(brake_lights))
    return Bars(1.0 if brake >= 1.0 else 0.0, self.decel_src, 1.0 if gas >= 1.0 else 0.0, self.accel_src)


def pedal_rect(widget_w: float, rhd: bool):
  """(x, y, w, h) of the widget footprint in widget (design) space."""
  x = widget_w - EDGE - 2 * PEDAL_W if rhd else EDGE
  return (x, STACK_BOTTOM + PEDAL_GAP, 2 * PEDAL_W, PEDAL_H)


def bar_boxes(widget_w: float, rhd: bool):
  """(decel, accel) boxes in widget space; decel left, accel right on both sides."""
  fx, fy, _fw, fh = pedal_rect(widget_w, rhd)
  return (fx, fy, BAR_W, fh), (fx + BAR_W + BAR_GAP_X, fy, BAR_W, fh)


def fill_top(inner_y: float, inner_h: float, frac: float) -> float:
  return inner_y + inner_h * (1.0 - clamp(frac, 0.0, 1.0))


def corner_radius(w: float, h: float) -> float:
  """Corner radius raylib uses for draw_rectangle_rounded(roundness=ROUND)."""
  return ROUND * min(w, h) / 2.0


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


def paint(rect, scale: float, widget_w: float, rhd: bool, b: Bars) -> None:
  """Screen space: rect is the HUD content rect, scale its design scale (as _bp_render_extras)."""
  import pyray as rl
  from openpilot.selfdrive.ui.onroad.bogpilot.style import fill_convex

  def one(box, frac, rgb):
    x, y = rect.x + box[0] * scale, rect.y + box[1] * scale
    w, h = box[2] * scale, box[3] * scale
    outer = rl.Rectangle(x, y, w, h)
    rl.draw_rectangle_rounded(outer, ROUND, 10, rl.Color(*TRACK_RGB, TRACK_A))
    inner = (x + INSET * scale, y + INSET * scale, w - 2 * INSET * scale, h - 2 * INSET * scale)
    fill_convex(fill_polygon(inner, frac), rl.Color(*rgb, FILL_A))
    rl.draw_rectangle_rounded_lines_ex(outer, ROUND, 10, 2.0, rl.Color(*EDGE_RGB, EDGE_A))

  dbox, abox = bar_boxes(widget_w, rhd)
  one(dbox, b.decel, bar_color(b.decel_src))
  one(abox, b.accel, bar_color(b.accel_src))
