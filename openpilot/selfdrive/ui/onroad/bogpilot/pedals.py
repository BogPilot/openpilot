"""BogPilot pedal gauge on the 3X driving screen: the HUD adapter for the 3-bar gauge (pedal_gauge3.py).

Three vertical bars in the old pedals' 120 x 120 footprint (pedal_rect, the same rect bottom_corner_keepout reserves):
LEFT friction brake pedal, CENTER regen power, RIGHT acceleration request; RHD mirrors the position and keeps the order.
Placement: centred on the record / personality column (COLUMN_CX screen px from the driver-side content edge, the
same column style.REC_CX and the stock DM corner use), at the same height as before.

Gate: openpilot longitudinal and CustomUI and PedalsOnUI (policy_from_store). There is one behaviour, the dynamic gauge
below; the old Dynamic / Static mode keys are not read, and nothing here writes Params.

Inputs per bar (pedal_gauge3 has the fill and colour rules):
  LEFT    carState.deprecated.brake, 0..1, set by the car state: AP1 the 0x39D rod-stroke level; Pre-AP 1.0 / 0.0 from the
          brake press, or the iBooster swap pedal position when that toggle is on. Negative = missing -> empty. Colour:
          openpilot's (op) only on AP1 while openpilot applies the iBooster (longActive, DI_brakePedalState ON, no driver
          press); a driver press always wins.
  CENTER  bogpilotCarState.ap1MotorTorqueNm x ap1MotorRpm -> kW (0x108, every legacy platform), smoothed, against the
          model's full scale. Missing / SNA / stale -> empty. Colour: op while carControl.longActive.
  RIGHT   driver pedal carState.deprecated.gas (DI_pedalPos / 100; negative = SNA -> 0) when pressed, else openpilot's
          carControl.actuators.accel / OP_ACCEL_FULL_SCALE while longActive. The driver's pedal wins.
aEgo is not an input to any bar.
Colour-source hysteresis: a change waits SOURCE_HOLD_S of steady request, except a change TO an active driver input
(pedal or brake), which shows at once.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from opendbc.car.interfaces import ACCEL_MAX
from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3

EDGE = 30
STACK_BOTTOM = 468
PEDAL_W, PEDAL_H, PEDAL_GAP = 60, 120, 18
# Record / personality column, screen px from the driver-side content edge (style.REC_CX = style.DM_CORNER_OFF = 126).
COLUMN_CX = 126

# OP accel that fills the accel bar: the controlsd clip (interfaces.ACCEL_MAX via get_pid_accel_limits, clipped in
# longcontrol), which tesla_ap1 does not override, so it is the most OP can command on AP1 AND Pre-AP.
OP_ACCEL_FULL_SCALE = ACCEL_MAX

PREAP = "TESLA_PREAP_MODELS"
AP1 = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX")
DI_BRAKE_STATE_ON = 1             # bogpilotCarState.ap1BrakePedalState ON (tesla_ap1 brake_level.DI_BRAKE_STATE_ON)

PEDAL_ON, PEDAL_OFF = 0.02, 0.01        # pedal 0..1; 2 % = the Pre-AP stock pressed threshold (DI_pedalPos noise)
OP_ACCEL_ON, OP_ACCEL_OFF = 0.10, 0.05  # m/s^2: OP counts as commanding accel
SOURCE_HOLD_S = 0.25                    # steady request needed to change a bar's colour source (not for a new driver input)


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


CLOSED = PedalPolicy()


def policy_from_store(store, longitudinal: bool) -> PedalPolicy:
  """Show the gauge with openpilot longitudinal, Driving Screen Widgets (CustomUI) and Pedals on Screen. A stored
  DynamicPedalsOnUI / StaticPedalsOnUI value from an older build is neither read nor rewritten."""
  level = store.tuning_level()
  show = bool(longitudinal) and bool(store.toggle_bool("CustomUI", level)) and bool(store.toggle_bool("PedalsOnUI", level))
  return PedalPolicy(show=show)


def platform_of(fingerprint) -> str:
  fp = str(fingerprint or "")
  return "preap" if fp == PREAP else "ap1" if fp in AP1 else "other"


def brake_level_of(level) -> float | None:
  """carState.deprecated.brake -> 0..1; None when missing / stale / bad (negative, not finite, not a number)."""
  try:
    x = float(level)
  except (TypeError, ValueError):
    return None
  if not math.isfinite(x) or x < 0.0:
    return None
  return clamp(x, 0.0, 1.0)


def pedal_of(pos) -> float:
  """carState.deprecated.gas -> 0..1; missing (negative: DI_pedalPos SNA), NaN or junk -> 0."""
  try:
    x = float(pos)
  except (TypeError, ValueError):
    return 0.0
  if not math.isfinite(x) or x < 0.0:
    return 0.0
  return clamp(x, 0.0, 1.0)


def op_ibooster_applied(brake_pedal_state, long_active, brake_pressed) -> bool:
  """OP is applying the iBooster: long control active, DI_brakePedalState ON and no driver press. Anything else
  (OFF, INVALID, SNA, stale = None, junk) is False."""
  try:
    on = int(brake_pedal_state) == DI_BRAKE_STATE_ON and float(brake_pedal_state) == DI_BRAKE_STATE_ON
  except (TypeError, ValueError, OverflowError):
    return False
  return bool(long_active) and on and not bool(brake_pressed)


class PedalGauge:
  """Per-frame gauge state with the colour-source hysteresis and the regen smoothing. update() returns G3.Gauge3."""

  def __init__(self):
    self.regen = G3.RegenSmoother()
    self.reset()

  def reset(self):
    self.accel_src, self.brake_src = G3.DRIVER, G3.DRIVER
    self._pedal_on = False
    self._pend = {"a": (None, 0.0), "b": (None, 0.0)}
    self.regen.reset()

  def _settle(self, key, cur, want, now, immediate):
    if want == cur:
      self._pend[key] = (None, 0.0)
      return cur
    if immediate:
      self._pend[key] = (None, 0.0)
      return want
    pend, since = self._pend[key]
    if pend != want:
      self._pend[key] = (want, now)
      return cur
    if now - since >= SOURCE_HOLD_S:
      self._pend[key] = (None, 0.0)
      return want
    return cur

  def update(self, policy: PedalPolicy, fresh: bool, now: float, platform: str, *, brake_pressed: bool, brake_level,
             pedal_pos, op_accel, long_active: bool, motor_torque_nm=None, motor_rpm=None, brake_pedal_state=None,
             fingerprint=None) -> G3.Gauge3:
    """now: monotonic seconds. brake_level: carState.deprecated.brake; pedal_pos: carState.deprecated.gas; op_accel:
    carControl.actuators.accel (used only while long_active); motor_torque_nm / motor_rpm: bogpilotCarState (None when
    stale); brake_pedal_state: bogpilotCarState.ap1BrakePedalState (None when stale, AP1 only); fingerprint selects the
    regen full scale."""
    if not policy.show or not fresh:
      self.reset()
      return G3.EMPTY3
    long_active = bool(long_active)
    pedal = pedal_of(pedal_pos)
    op = finite(op_accel) if long_active else 0.0
    # RIGHT: the driver's pedal wins
    self._pedal_on = pedal > (PEDAL_OFF if self._pedal_on else PEDAL_ON)
    if self._pedal_on:
      want_a = G3.DRIVER
    elif long_active and op > (OP_ACCEL_OFF if self.accel_src == G3.OP else OP_ACCEL_ON):
      want_a = G3.OP
    else:
      want_a = G3.DRIVER
    self.accel_src = self._settle("a", self.accel_src, want_a, now, want_a == G3.DRIVER and self._pedal_on)
    accel = clamp(op / OP_ACCEL_FULL_SCALE, 0.0, 1.0) if self.accel_src == G3.OP else pedal
    # LEFT: openpilot's colour only while it applies the iBooster (AP1); a driver press shows at once
    op_brake = platform == "ap1" and op_ibooster_applied(brake_pedal_state, long_active, brake_pressed)
    want_b = G3.OP if op_brake else G3.DRIVER
    self.brake_src = self._settle("b", self.brake_src, want_b, now, want_b == G3.DRIVER and bool(brake_pressed))
    brake = brake_level_of(brake_level)
    # CENTER: regen power, smoothed; missing -> empty
    kw = self.regen.update(G3.motor_power_kw(motor_torque_nm, motor_rpm), now)
    return G3.gauge_state(brake, kw, accel, long_active, full_scale_kw=G3.regen_full_scale_kw(fingerprint),
                          brake_by_op=self.brake_src == G3.OP, accel_by_op=self.accel_src == G3.OP)


def pedal_rect(widget_w: float, rhd: bool, scale: float = 1.0):
  """(x, y, w, h) of the gauge footprint in widget (design) space, centred on the record / personality column. scale is
  the HUD design scale (the column is a fixed screen-px offset, so its design x depends on it); y and h do not."""
  x = (COLUMN_CX / scale if scale > 0 else COLUMN_CX) - G3.FOOT_W / 2.0
  return (widget_w - x - G3.FOOT_W if rhd else x, STACK_BOTTOM + PEDAL_GAP, G3.FOOT_W, PEDAL_H)


def screen_rect(rect, scale: float, widget_w: float, rhd: bool):
  """The footprint in screen px inside the HUD content rect."""
  x, y, w, h = pedal_rect(widget_w, rhd, scale)
  return (rect.x + x * scale, rect.y + y * scale, w * scale, h * scale)


def paint(rect, scale: float, widget_w: float, rhd: bool, g: G3.Gauge3) -> None:
  """Screen space: rect is the HUD content rect, scale its design scale (as _bp_render_extras)."""
  G3.paint_gauge3(screen_rect(rect, scale, widget_w, rhd), g, scale)
