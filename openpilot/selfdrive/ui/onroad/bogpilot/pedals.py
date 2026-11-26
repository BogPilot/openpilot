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
  CENTER  bogpilotCarState.ap1MotorTorqueNm (0x108 DI_torqueMotor, every legacy platform), smoothed: regen torque
          -min(0, T) / REGEN_FULLSCALE_NM. Missing / SNA / stale -> empty. Colour: op while carControl.longActive.
  RIGHT   driver pedal carState.deprecated.gas (DI_pedalPos / 100; negative = SNA -> 0) when pressed (the driver's pedal
          wins). Otherwise, while longActive, the measured drive torque max(0, T) / ACCEL_FULLSCALE_NM, smoothed like the
          regen bar; the colour is openpilot's anytime longActive (a driver pedal press wins); OP_ACCEL_ON / OFF only gates the fallback fill. With
          no valid torque (missing / SNA / stale) it falls back to carControl.actuators.accel / OP_ACCEL_FULL_SCALE, shown
          only once that request passes the threshold (the previous behaviour).
Dead torque: 0x108 can read a flat 0.0 Nm at high motor rpm even while openpilot drives (TorqueTrust). The gauge then treats
          the torque as missing: the accel bar shows openpilot's request, the regen bar shows openpilot's decel request.
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

# Fallback only (no valid motor torque): the OP accel that fills the accel bar is the controlsd clip
# (interfaces.ACCEL_MAX via get_pid_accel_limits, clipped in longcontrol), which tesla_ap1 does not override, so it is
# the most OP can command on AP1 AND Pre-AP. With a valid torque the bar uses G3.ACCEL_FULLSCALE_NM instead.
OP_ACCEL_FULL_SCALE = ACCEL_MAX

PREAP = "TESLA_PREAP_MODELS"
AP1 = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX")
DI_BRAKE_STATE_ON = 1             # bogpilotCarState.ap1BrakePedalState ON (tesla_ap1 brake_level.DI_BRAKE_STATE_ON)

PEDAL_ON, PEDAL_OFF = 0.02, 0.01        # pedal 0..1; 2 % = the Pre-AP stock pressed threshold (DI_pedalPos noise)
OP_ACCEL_ON, OP_ACCEL_OFF = 0.10, 0.05  # m/s^2: request gate for the fallback fill only (the colour is OP anytime long is active)
SOURCE_HOLD_S = 0.25                    # steady request needed to change a bar's colour source (not for a new driver input)

# DI_torqueMotor (0x108) reads a flat 0.0 Nm at high motor speed on the AP1 S bench car, even while openpilot accelerates
# or brakes (seen from about 7000 rpm down to about 6300 rpm, three minutes at a time). A torque that stays at zero with the
# motor above TORQUE_DEAD_RPM_ON is a dead signal, not a coasting car: the gauge then ignores it and draws openpilot's
# request instead (the same fallback as a missing torque). It is released below TORQUE_DEAD_RPM_OFF, or when the torque
# is clearly alive again.
TORQUE_DEAD_RPM_ON, TORQUE_DEAD_RPM_OFF = 6000.0, 5000.0
# The AP1 Model X rear drive unit spins slower per mph (rpm per m/s 249.9 vs 265.5 on the S), so its gate is 5500 rpm, about the
# same road speed as 6000 on the S. Release stays 5000. Only used while the gauge is in single-motor mode (no fresh 0x186).
TORQUE_DEAD_RPM_ON_BY_FP = {"TESLA_AP1_MODELX": 5500.0}


def dead_rpm_on(fingerprint) -> float:
  """The dead-torque rpm gate for this car: 5500 on the AP1 Model X, 6000 on every other car (AP1 S, Pre-AP)."""
  return TORQUE_DEAD_RPM_ON_BY_FP.get(str(fingerprint or ""), TORQUE_DEAD_RPM_ON)
TORQUE_DEAD_NM = 0.5                    # |torque| at or below this is a flat zero (the signal steps in 0.25 Nm)
TORQUE_ALIVE_NM = 5.0                   # |torque| above this is a live signal
TORQUE_DEAD_HOLD_S = 0.5                # flat zero this long above the rpm gate before it is called dead
TORQUE_ALIVE_HOLD_S = 0.3               # live torque this long before a dead call is released


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


class TorqueTrust:
  """Calls DI_torqueMotor dead (flat zero at high motor rpm) so the gauge can fall back to openpilot's request."""

  def __init__(self, rpm_on: float = TORQUE_DEAD_RPM_ON):
    self.rpm_on = rpm_on
    self.reset()

  def reset(self):
    self.dead = False
    self._since = None
    self._t = None

  def update(self, torque_nm, rpm, now) -> bool:
    """torque_nm: G3.motor_torque_value() (None = missing); rpm: DI_motorRPM or None. True while the torque is dead."""
    t = G3._num(now)
    tq = G3._num(torque_nm)
    n = G3._num(rpm)
    if n is not None and n <= G3.MOTOR_RPM_SNA:
      n = None
    if t is None or tq is None or n is None or (self._t is not None and not 0.0 <= t - self._t <= G3.REGEN_GAP_RESET_S):
      self.reset()
      self._t = t
      return False
    self._t = t
    if self.dead:
      if n < TORQUE_DEAD_RPM_OFF:
        self.reset()
        self._t = t
      elif abs(tq) > TORQUE_ALIVE_NM:
        self._since = t if self._since is None else self._since
        if t - self._since >= TORQUE_ALIVE_HOLD_S:
          self.reset()
          self._t = t
      else:
        self._since = None
    else:
      if n >= self.rpm_on and abs(tq) <= TORQUE_DEAD_NM:
        self._since = t if self._since is None else self._since
        if t - self._since >= TORQUE_DEAD_HOLD_S:
          self.dead, self._since = True, None
      else:
        self._since = None
    return self.dead


# Dual-motor cars (fresh 0x186): at highway speed one motor can sit at zero while the other carries the whole load (the S and
# the X both cruise on one motor), so a single zero motor is real and the rpm gate above does not apply. The gauge sums both
# motors' power and falls back to openpilot's request only when BOTH read a flat zero for TORQUE_DEAD_HOLD_S while the car is
# moving under openpilot longitudinal with a request past the fill gate; either motor above TORQUE_ALIVE_NM for
# TORQUE_ALIVE_HOLD_S releases it.
DUAL_MOVING_RPM = 300.0                 # motor rpm: about 2.5 mph on either motor


class DualTorqueTrust:
  """Both motors flat zero while openpilot drives the car = a dead signal pair (the dual-motor fallback gate)."""

  def __init__(self):
    self.reset()

  def reset(self):
    self.dead = False
    self._since = None
    self._t = None

  def update(self, rear_nm, front_nm, armed: bool, now) -> bool:
    """rear_nm / front_nm: G3.motor_torque_value() (None = missing). armed: moving, openpilot long active and a request past
    the fill gate. True while both are dead."""
    t = G3._num(now)
    if t is None or (self._t is not None and not 0.0 <= t - self._t <= G3.REGEN_GAP_RESET_S):
      self.reset()
      self._t = t
      return False
    self._t = t
    tqs = [x for x in (G3._num(rear_nm), G3._num(front_nm)) if x is not None]
    if self.dead:
      if not armed or not tqs:
        self.reset()
        self._t = t
      elif any(abs(x) > TORQUE_ALIVE_NM for x in tqs):
        self._since = t if self._since is None else self._since
        if t - self._since >= TORQUE_ALIVE_HOLD_S:
          self.reset()
          self._t = t
      else:
        self._since = None
    else:
      if armed and len(tqs) == 2 and all(abs(x) <= TORQUE_DEAD_NM for x in tqs):
        self._since = t if self._since is None else self._since
        if t - self._since >= TORQUE_DEAD_HOLD_S:
          self.dead, self._since = True, None
      else:
        self._since = None
    return self.dead


def request_regen_kw(op_accel, v, mass_kg=None) -> float | None:
  """Regen power openpilot's decel request needs, P = m x a x v (kW >= 0); None without a speed."""
  vv = G3._num(v)
  if vv is None:
    return None
  m = G3._num(mass_kg)
  m = m if m is not None and m > 0.0 else G3.MASS_KG
  return max(0.0, -finite(op_accel)) * m * abs(vv) / 1000.0


def request_regen_torque_nm(op_accel, rpm_per_ms=None, mass_kg=None) -> float:
  """Regen torque (negative Nm, as if all on the rear motor) that openpilot's decel request would need, the inverse of
  G3.regen_decel_from_torque; 0 for no decel request. rpm_per_ms / mass_kg: the live measured value and the trim mass
  (None = the fixed 9.73 / 0.35 m / 2100 kg constants)."""
  d = max(0.0, -finite(op_accel))
  m = G3._num(mass_kg)
  m = m if m is not None and m > 0.0 else G3.MASS_KG
  return -d * m / (G3._rpm_per_ms(rpm_per_ms) * 2.0 * math.pi / 60.0)


_PROFILE_TTL_S = 10.0
_profile_cache: dict = {}


def trim_mass_kg(fingerprint, now=None) -> float | None:
  """The trim profile mass (opendbc tesla_ap1/trims.py: Tesla curb weight + 136 kg, or the base mass with Auto), re-read at
  most every _PROFILE_TTL_S (a tiny file, never per frame). None for a car without a trim profile or on any error."""
  import time
  fp = str(fingerprint or "")
  t = time.monotonic() if now is None else now
  hit = _profile_cache.get(fp)
  if hit is not None and 0.0 <= t - hit[0] < _PROFILE_TTL_S:
    return hit[1]
  try:
    from opendbc.car.tesla_ap1.trims import chassis_of, profile_for
    mass = profile_for(fp).mass_kg if chassis_of(fp) is not None else None
  except Exception:
    mass = None
  _profile_cache[fp] = (t, mass)
  return mass


def drive_kwargs(bcs, fingerprint=None, now=None) -> dict:
  """PedalGauge.update keyword inputs from a bogpilotCarState: the 0x186 front motor only on a detected dual-motor car
  (ap1DriveLayout 2) with finite values, the live rpm per m/s of each motor, and the trim mass."""
  def num(name):
    v = G3._num(getattr(bcs, name, None))
    return v
  out = {"mass_kg": trim_mass_kg(fingerprint, now)}
  k = num("ap1RearRpmPerMs")
  out["rpm_per_ms"] = k if k is not None and k > 0.0 else None
  if int(getattr(bcs, "ap1DriveLayout", 0) or 0) == 2:
    ftq, frpm, fk = num("ap1FrontMotorTorqueNm"), num("ap1FrontMotorRpm"), num("ap1FrontRpmPerMs")
    if ftq is not None and frpm is not None:
      out["front_torque_nm"], out["front_rpm"] = ftq, frpm
    out["front_rpm_per_ms"] = fk if fk is not None and fk > 0.0 else None
  return out


class PedalGauge:
  """Per-frame gauge state with the colour-source hysteresis and the regen smoothing. update() returns G3.Gauge3."""

  def __init__(self):
    self.torque = G3.RegenSmoother()   # signed DI_torqueMotor in Nm; feeds the regen and the accel (torque) bars
    self.trust = TorqueTrust()         # dead-torque detector (flat zero at high rpm)
    self.req_torque = G3.RegenSmoother()  # regen torque equivalent of openpilot's request, used only while the torque is dead
    self.front_torque = G3.RegenSmoother()  # 0x186 front motor torque (dual-motor cars), summed into both bars
    self.dual_trust = DualTorqueTrust()     # dual-motor fallback gate: both motors flat zero
    self.flash = G3.RegenLimitFlash()  # near-max regen flash (openpilot colour only)
    self.reset()

  def reset(self):
    self.accel_src, self.brake_src = G3.DRIVER, G3.DRIVER
    self._pedal_on = False
    self._req_on = False
    self._pend = {"a": (None, 0.0), "b": (None, 0.0)}
    self.torque.reset()
    self.trust.reset()
    self.req_torque.reset()
    self.front_torque.reset()
    self.dual_trust.reset()
    self._regen_req_on = False
    self.flash.reset()

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
             fingerprint=None, front_torque_nm=None, front_rpm=None, rpm_per_ms=None, front_rpm_per_ms=None,
             mass_kg=None) -> G3.Gauge3:
    """now: monotonic seconds. brake_level: carState.deprecated.brake; pedal_pos: carState.deprecated.gas; op_accel:
    carControl.actuators.accel (colour source, and the fill only without a valid torque); motor_torque_nm:
    bogpilotCarState.ap1MotorTorqueNm (None when stale) drives the regen and the accel bars; motor_rpm (0x108 DI_motorRPM)
    turns torque into shaft power for the log scale (missing / SNA -> torque fill); fingerprint picks the regen peak kW;
    brake_pedal_state: bogpilotCarState.ap1BrakePedalState (None
    when stale, AP1 only)."""
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
    elif long_active:
      want_a = G3.OP                                                     # OP colour anytime long is active, even a tiny request
    else:
      want_a = G3.DRIVER
    self._req_on = long_active and op > (OP_ACCEL_OFF if self._req_on else OP_ACCEL_ON)   # request past the fallback fill gate
    self.accel_src = self._settle("a", self.accel_src, want_a, now, want_a == G3.DRIVER and self._pedal_on)
    # Measured motor torque (None when missing / SNA / stale), smoothed; a missing sample resets the filter.
    tq_raw = G3.motor_torque_value(motor_torque_nm)
    f_raw = G3.motor_torque_value(front_torque_nm) if front_torque_nm is not None else None
    # Dual-motor mode: a fresh 0x186 (torque and rpm valid). A stale 0x186 arrives as NaN -> single-motor mode (rear only and
    # the rpm-gated TorqueTrust), never a stale front value.
    dual = f_raw is not None and G3.motor_rpm_value(front_rpm) is not None
    if dual:
      self.trust.reset()
      rpms = [abs(n) for n in (G3.motor_rpm_value(motor_rpm), G3.motor_rpm_value(front_rpm)) if n is not None]
      moving = bool(rpms) and max(rpms) >= DUAL_MOVING_RPM
      armed = moving and long_active and abs(op) > OP_ACCEL_ON
      dead = self.dual_trust.update(tq_raw, f_raw, armed, now)
      tq = self.torque.update(None if dead else tq_raw, now)
      ftq = self.front_torque.update(None if dead else f_raw, now)
    else:
      self.dual_trust.reset()
      self.front_torque.reset()
      ftq = None
      self.trust.rpm_on = dead_rpm_on(fingerprint)
      dead = self.trust.update(tq_raw, motor_rpm, now)
      tq = self.torque.update(None if dead else tq_raw, now)
    f_rpm = front_rpm if dual else None
    measured = tq is not None or ftq is not None
    if self._pedal_on:
      accel = pedal                                                      # the driver's pedal, as before
    elif long_active and measured:
      # OP's drive power (log; front + rear on a dual car), else torque; hills included
      pf = G3.accel_power_fill(tq, motor_rpm, ftq, f_rpm) if G3.POWER_LOG_SCALE else None
      accel = pf if pf is not None else G3.accel_torque_fill((tq or 0.0) + (ftq or 0.0))
    elif self.accel_src == G3.OP and self._req_on:
      accel = clamp(op / OP_ACCEL_FULL_SCALE, 0.0, 1.0)                  # fallback: OP's request
    else:
      accel = pedal
    # LEFT: openpilot's colour only while it applies the iBooster (AP1); a driver press shows at once
    op_brake = platform == "ap1" and op_ibooster_applied(brake_pedal_state, long_active, brake_pressed)
    want_b = G3.OP if op_brake else G3.DRIVER
    self.brake_src = self._settle("b", self.brake_src, want_b, now, want_b == G3.DRIVER and bool(brake_pressed))
    brake = brake_level_of(brake_level)
    # CENTER: regen power from the smoothed torque and rpm (front + rear power on a dual car); no valid rpm -> regen torque;
    # missing torque -> empty
    rf = G3.regen_power_fill(tq, motor_rpm, fingerprint, ftq, f_rpm) if G3.POWER_LOG_SCALE else None
    flash = self.flash.update(now, long_active, tq, motor_rpm, op, driver_input=self._pedal_on or bool(brake_pressed),
                              front_torque_nm=ftq, front_rpm=f_rpm, rpm_per_ms=rpm_per_ms,
                              front_rpm_per_ms=front_rpm_per_ms, mass_kg=mass_kg)
    regen_nm = None if not measured else (tq or 0.0) + (ftq or 0.0)
    kw = {"regen_frac": rf} if rf is not None else {"regen_nm": regen_nm}
    # Dead torque: the regen bar shows openpilot's decel request, not an empty bar
    req_nm = None
    if dead and long_active and not self._pedal_on:
      want = max(0.0, -op) > (OP_ACCEL_OFF if self._regen_req_on else OP_ACCEL_ON)
      self._regen_req_on = want
      req_nm = self.req_torque.update(request_regen_torque_nm(op, rpm_per_ms, mass_kg), now) if want else None
      if not want:
        self.req_torque.reset()
    else:
      self._regen_req_on = False
      self.req_torque.reset()
    if dead:
      if req_nm is not None and dual:
        # P_req = m x a x v on the combined scale (req_nm is the smoothed request as rear torque: x the rear motor's
        # angular speed at that road speed); v from the rear motor, else the front
        v = G3.speed_from_rpm(motor_rpm, rpm_per_ms) if G3.motor_rpm_value(motor_rpm) is not None else \
            G3.speed_from_rpm(front_rpm, front_rpm_per_ms or rpm_per_ms)
        req_kw = None if v is None else max(0.0, -req_nm) * v * G3._rpm_per_ms(rpm_per_ms) * math.pi / 30000.0
        rf2 = None if req_kw is None else G3.regen_kw_fill(req_kw, fingerprint, dual=True)
      else:
        rf2 = None if req_nm is None else G3.regen_power_fill(req_nm, motor_rpm, fingerprint)
      kw = {"regen_frac": rf2} if rf2 is not None else {"regen_nm": req_nm}
    return G3.gauge_state(brake, None, accel, long_active, brake_by_op=self.brake_src == G3.OP,
                          accel_by_op=self.accel_src == G3.OP, regen_flash=flash, **kw)


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
