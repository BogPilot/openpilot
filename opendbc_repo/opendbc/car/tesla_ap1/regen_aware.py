"""AP1 regen-aware early stop braking (prototype).

Goal: when a stop is known early (stopped/slow lead from radarState, or the
model's predicted stop in experimental mode), begin a gentle, regen-only
deceleration earlier instead of coasting and then braking late and hard,
which pushes the last part of the stop onto the friction brakes.

Safety rule: the output is always min(plan, early), so this module can only
ADD earlier gentle braking. It never caps, delays or reduces braking that the
planner asks for (FCW / cut-in / hard stops keep the full ACCEL_MIN path).

The real BMS max-regen limit (CAN3 0x232) is not on the comma's buses, so the
available regen power is estimated:
  * nominal 30 kW (logged regen shaft power peaked at -24..-36 kW, never limited)
  * 18 kW ceiling when the outside air (0x208 GTW_ambientTemperature) is <= 5 C
  * lowered to the measured power when DI_torqueMotor (0x108) regen plateaus
    below the request for > 0.5 s above the low-speed fade band
  * recovers toward the ceiling at 0.5 kW/s
Regen decel capacity = fade(v) * P*0.9/(m*v), m = 2100 kg. The fade comes from
a logged drive: regen torque fell from -113 Nm at 10.5 mph to -43 Nm at
5 mph and 0 at 2 mph.

References: Tinkla/Unity PCC_module.py hard-codes REGEN_DECEL_V; this replaces
the constant with a power-based estimate. File toggle (default on for AP1 Model S
and AP1 Model X; it only runs with openpilot longitudinal, on the X that is the
AP1XOpenpilotLong opt-in):
  echo 0 > /data/params_bogpilot/RegenAwareStop   # off

Per-car physics (RegenCar below). The module-level constants are the AP1 Model S
values and stay exactly as tuned on the S (MODEL_S). The AP1 Model X has its own
values (MODEL_X), taken only from a real Model X drive and public specs:
  * mass 2400 kg: Model X curb weight (public spec range for the AP1-era Model X).
  * gear ratio 9.734: the X rear drive unit (the X is dual motor; the front
    unit is 9.325). With trim profiles the live rpm per m/s of each motor is
    used instead (below); these constants are the fallback.
  * wheel radius 0.372 m: the X rear motor turned 249.9 rpm per m/s on the
    drive (111.8 rpm per mph; the S constants give 265.5 per m/s), so
    r = 9.734 * 60 / (2 pi * 249.9) = 0.372 m.
    The X motor turns about 6 % slower per mph than the S.
  * nominal regen power 51.1 kW: peak front + rear regen shaft power on the drive was
    71.6 kW (rear only 49 kW). The S uses 30 kW against its 42 kW peak (0.71); the
    same fraction of 71.6 kW is 51.1 kW.
  * cold ceiling 18 kW: the S value, kept. The X drive was 25-29 C only, so there
    is no X cold-weather data; 18 kW is lower than the X nominal (safe side).
  * low-speed fade: X pedal-off regen torque relative to its -124 Nm plateau was
    0.07 at 0.5-1.0 m/s, 0.43 at 2.0-2.5 m/s, 0.90 at 3.5-4.0 m/s and 1.0 from
    4.5 m/s: FADE 0.6 / 2.25 / 4.5 m/s -> 0 / 0.43 / 1.0 (at or below the data).
  * decel cap 1.35 m/s^2: the -124 Nm rear regen torque ceiling * 9.734 / 0.372 m /
    2400 kg. DI_torqueMotor (0x108) is the rear drive unit only (the front
    unit carries roughly 20-34 % of X regen and is not read); the X drive's measured
    pedal-off decel (up to about 2.0 m/s^2) was higher than that, so the cap and
    the torque-based limit check sit on the safe side (they assume less regen).
  * limit check only above 4.5 m/s, the top of the X fade band (S: 4.7).
Trim profiles (trims.py, built by regen_car(fingerprint, profile)): the mass is the
picked trim's Tesla curb weight + 136 kg (Auto keeps 2100 kg S / 2400 kg X), the
regen decel uses the live rpm per m/s of each motor (G / r = k * 2 pi / 60) instead of
the fixed ratio and radius, and on a dual-motor car the front motor (0x186) is summed
into the decel, the regen power and the limit check. A dual-motor S uses 53.1 kW
front + rear (measured) x 30 / 42 = 37.9 kW nominal; a single-motor S keeps 30 kW.
The X values are provisional: no X drive with openpilot longitudinal engaged
exists yet (both X drives were stock cruise or manual). A second X drive
(stock cruise, up to 35 mph) agrees: 250.3 rpm per m/s (r = 0.371 m), regen
torque floor -126 Nm, regen peak 43 kW at those lower speeds. Retune from the
first X drive with openpilot longitudinal engaged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from opendbc.car.tesla_ap1 import tesla_tuning as _tt   # Settings > Vehicle > Tesla Tuning (shipped value unless saved)

MASS_KG = 2100.0
ETA = 0.9
GEAR_RATIO = 9.73
WHEEL_RADIUS_M = 0.35

P_NOMINAL_KW = 30.0
P_COLD_KW = 18.0
P_MIN_KW = 10.0
COLD_AMBIENT_C = 5.0
P_RECOVER_KW_S = 0.5

# Low-speed regen fade (m/s -> fraction of capacity).
FADE_BP = [0.9, 2.2, 4.7]
FADE_V = [0.0, 0.38, 1.0]
A_CAP_MAX = 1.6           # never assume more regen decel than seen (~1.5 m/s^2)

# Gentle target band (m/s^2, positive = decel).
A_GENTLE_MIN = 0.6
A_GENTLE_MAX = 1.0
A_GENTLE_FLOOR = 0.3      # at highway speed 30 kW is only ~0.5 m/s^2
GENTLE_FRAC = _tt.get("StopShaperGentleFrac", 0.9)         # stay a bit below estimated capacity
ONSET_FRAC = _tt.get("StopShaperOnsetFrac", 0.85)         # start when the required constant decel reaches this x gentle
RELEASE_FRAC = 0.4        # hysteresis
MIN_SPEED = 1.0           # m/s, below this the planner's stopping logic owns it
ONSET_JERK = _tt.get("StopShaperOnsetJerk", 0.6)          # m/s^3, ramp the added braking in smoothly
RELEASE_JERK = _tt.get("StopShaperReleaseJerk", 1.5)
STOP_LOST_HOLD_S = 0.5

LIMIT_MIN_SPEED = 4.7     # only judge limiting above the fade band
LIMIT_MARGIN = 0.2        # m/s^2
LIMIT_TIME_S = 0.5

LEAD_STOPPED_SPEED = 1.5  # m/s, lead counts as a stop target below this
MODEL_STOP_SPEED = 0.5

_TOGGLE_PATH = Path("/data/params_bogpilot/RegenAwareStop")


@dataclass(frozen=True)
class RegenCar:
  """Car physics for the regen estimate (see the module doc for where each value comes from)."""
  mass_kg: float
  gear_ratio: float
  wheel_radius_m: float
  p_nominal_kw: float
  p_cold_kw: float
  fade_bp: tuple[float, ...]
  fade_v: tuple[float, ...]
  a_cap_max: float
  limit_min_speed: float
  # Trim profiles (trims.py): measured motor rpm per m/s replaces gear_ratio / wheel_radius_m when set (G / r = k * 2 pi / 60),
  # and the front motor (0x186) adds its share on a dual-motor car. None keeps the fixed constants above.
  rpm_per_ms: float | None = None
  front_rpm_per_ms: float | None = None


# AP1 Model S: exactly the module constants above (unchanged).
MODEL_S = RegenCar(MASS_KG, GEAR_RATIO, WHEEL_RADIUS_M, P_NOMINAL_KW, P_COLD_KW, tuple(FADE_BP), tuple(FADE_V), A_CAP_MAX,
                   LIMIT_MIN_SPEED)

# AP1 Model X: from a real Model X drive and public specs only (module doc).
MODELX_MASS_KG = 2400.0
MODELX_GEAR_RATIO = 9.734                     # X rear drive unit (front 9.325 is not used: 0x108 is the rear motor)
MODELX_RPM_PER_MS = 249.9                     # measured DI_motorRPM / vEgo on the X drive (p5 249.0, p95 251.8)
MODELX_WHEEL_RADIUS_M = round(MODELX_GEAR_RATIO * 60.0 / (2.0 * math.pi * MODELX_RPM_PER_MS), 3)   # 0.372
MODELX_REAR_REGEN_PEAK_KW = 49.0              # measured peak REAR motor (0x108) regen shaft power on the X drive
# Front + rear (0x186 + 0x108): the X is always dual motor, and the shaper now sums both motors (trims.DUAL_REGEN_PEAK_KW, 71.6 kW
# measured on the X drive). This supersedes the rear-only 49 kW. The nominal keeps the S fraction (30 of 42).
MODELX_REGEN_PEAK_KW = 71.6
MODELX_P_NOMINAL_KW = round(MODELX_REGEN_PEAK_KW * P_NOMINAL_KW / 42.0, 1)                              # 51.1
MODELX_REGEN_TORQUE_NM = 124.0                # measured regen torque ceiling on the X drive
MODELX_A_CAP_MAX = round(MODELX_REGEN_TORQUE_NM * MODELX_GEAR_RATIO / MODELX_WHEEL_RADIUS_M / MODELX_MASS_KG, 2)   # 1.35
MODEL_X = RegenCar(MODELX_MASS_KG, MODELX_GEAR_RATIO, MODELX_WHEEL_RADIUS_M, MODELX_P_NOMINAL_KW, P_COLD_KW,
                   (0.6, 2.25, 4.5), (0.0, 0.43, 1.0), MODELX_A_CAP_MAX, 4.5)


def regen_car(fingerprint, profile=None) -> RegenCar:
  """MODEL_X for the AP1 Model X, MODEL_S for everything else (only the S and the X ever run the shaper).

  With a trims.Profile: the trim mass (Tesla curb weight + 136 kg, or the base mass with Auto), the rpm per m/s seeds of
  each motor, and on a dual-motor S the front + rear nominal regen (the measured dual peak x 30 / 42). A single-motor S
  keeps the 30 kW nominal."""
  base = MODEL_X if str(fingerprint) == "TESLA_AP1_MODELX" else MODEL_S
  if profile is None:
    return base
  p_nominal = base.p_nominal_kw
  if base is MODEL_S and getattr(profile, "regen_peak_kw", None):
    p_nominal = round(float(profile.regen_peak_kw) * P_NOMINAL_KW / 42.0, 1)
  rear_k = _pos(getattr(profile, "rear_rpm_per_ms", None))
  front_k = _pos(getattr(profile, "front_rpm_per_ms", None))
  legacy_k = base.gear_ratio * 60.0 / (2.0 * math.pi * base.wheel_radius_m)
  if (float(profile.mass_kg) == base.mass_kg and p_nominal == base.p_nominal_kw and front_k is None
      and (rear_k is None or abs(rear_k - legacy_k) < 1e-6)):
    return base                       # nothing new known (Auto, layout not detected yet): exactly the old car
  return replace(base, mass_kg=float(profile.mass_kg), p_nominal_kw=p_nominal, rpm_per_ms=rear_k, front_rpm_per_ms=front_k)


def _pos(x) -> float | None:
  try:
    x = float(x)
  except (TypeError, ValueError):
    return None
  return x if math.isfinite(x) and x > 0.0 else None


def _torque(x) -> float | None:
  """A usable motor torque (Nm): finite and not the 0x108 / 0x186 SNA (-1024 Nm)."""
  try:
    x = float(x)
  except (TypeError, ValueError):
    return None
  return x if math.isfinite(x) and x > -1024.0 else None


def wheel_factor(car: RegenCar, rpm_per_ms=None, front: bool = False) -> float:
  """G / r (1/m) of a motor: the live rpm per m/s when given, else the car's seed, else the fixed gear ratio / radius."""
  k = _pos(rpm_per_ms)
  if k is None:
    k = car.front_rpm_per_ms if front else car.rpm_per_ms
  if k is None:
    return car.gear_ratio / car.wheel_radius_m
  return k * 2.0 * math.pi / 60.0


def regen_aware_enabled(fingerprint, stored: str | None = None) -> bool:
  """AP1 Model S and AP1 Model X: on unless the file (or `stored`) says 0/false/off. Every other car is off.
  The planner (ap1_planning.py) additionally needs openpilot longitudinal."""
  from opendbc.car.tesla_ap1.values import CAR
  if fingerprint not in (CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX):
    return False
  if stored is None:
    try:
      stored = _TOGGLE_PATH.read_text().strip() if _TOGGLE_PATH.is_file() else ""
    except OSError:
      stored = ""
  return stored.strip().lower() not in ("0", "false", "off")


def fade(v: float, car: RegenCar = MODEL_S) -> float:
  return float(np.interp(v, car.fade_bp, car.fade_v))


def regen_capacity(v: float, p_kw: float, car: RegenCar = MODEL_S) -> float:
  """Estimated regen-only decel (m/s^2, positive) at speed v."""
  power = p_kw * 1000.0 * ETA / (car.mass_kg * max(v, 0.5))
  return fade(v, car) * min(car.a_cap_max, power)


def regen_decel_from_torque(motor_torque_nm: float, car: RegenCar = MODEL_S, front_torque_nm=None, rpm_per_ms=None,
                            front_rpm_per_ms=None) -> float:
  """Positive decel produced by negative motor torque: the rear motor, plus the front motor (0x186) when given."""
  rear = _torque(motor_torque_nm)
  decel = 0.0 if rear is None else max(0.0, -rear) * wheel_factor(car, rpm_per_ms)
  front = _torque(front_torque_nm)
  if front is not None:
    decel += max(0.0, -front) * wheel_factor(car, front_rpm_per_ms, front=True)
  return decel / car.mass_kg


def regen_power_kw(motor_torque_nm: float, motor_rpm: float, front_torque_nm=None, front_rpm=None) -> float:
  """Positive regen shaft power (kW): rear, plus the front motor when given (each motor's torque x its own rpm)."""
  total = 0.0
  for tq, rpm in ((motor_torque_nm, motor_rpm), (front_torque_nm, front_rpm)):
    tq, rpm = _torque(tq), _finite_rpm(rpm)
    if tq is None or rpm is None:
      continue
    total += max(0.0, -(tq * rpm * 2.0 * math.pi / 60.0 / 1000.0))
  return total


def _finite_rpm(x) -> float | None:
  try:
    x = float(x)
  except (TypeError, ValueError):
    return None
  return x if math.isfinite(x) and x > -32768.0 else None


class RegenPowerEstimator:
  def __init__(self, p_kw: float | None = None, car: RegenCar = MODEL_S):
    self.car = car
    self.p_kw = car.p_nominal_kw if p_kw is None else p_kw
    self.limit_t = 0.0
    self.limited = False

  def ceiling(self, ambient_c) -> float:
    if ambient_c is not None and ambient_c <= COLD_AMBIENT_C:
      return self.car.p_cold_kw
    return self.car.p_nominal_kw

  def update(self, v, req_accel, motor_torque_nm, motor_rpm, ambient_c, dt, front_torque_nm=None, front_rpm=None,
             rpm_per_ms=None, front_rpm_per_ms=None):
    """front_*: the 0x186 front motor on a dual-motor car (None or NaN = single motor); rpm_per_ms: live rpm per m/s."""
    ceil = self.ceiling(ambient_c)
    req_decel = -req_accel
    front_tq = _torque(front_torque_nm)
    a_meas = regen_decel_from_torque(motor_torque_nm, self.car, front_tq, rpm_per_ms, front_rpm_per_ms)
    rear_tq = _torque(motor_torque_nm)
    regen_now = (rear_tq is not None and rear_tq < 0) or (front_tq is not None and front_tq < 0)
    plateau = (v > self.car.limit_min_speed and req_decel > 0.3 and req_decel > a_meas + LIMIT_MARGIN
               and regen_now)
    self.limit_t = self.limit_t + dt if plateau else 0.0
    self.limited = self.limit_t > LIMIT_TIME_S
    if self.limited:
      measured = regen_power_kw(motor_torque_nm, motor_rpm, front_tq, front_rpm) / ETA
      self.p_kw = max(P_MIN_KW, min(self.p_kw, measured))
    else:
      self.p_kw = min(ceil, self.p_kw + P_RECOVER_KW_S * dt)
    self.p_kw = min(self.p_kw, ceil)
    return self.p_kw


def lead_stop_distance(lead_status, d_rel, v_lead, stop_gap):
  """Distance (m) to where ego should stop behind a stopped/slow lead, else None."""
  if not lead_status or v_lead > LEAD_STOPPED_SPEED:
    return None
  return max(0.0, d_rel - stop_gap)


def model_stop_distance(positions_x, velocities_x):
  """First predicted position where model speed falls below MODEL_STOP_SPEED."""
  if positions_x is None or len(positions_x) < 2 or len(velocities_x) != len(positions_x):
    return None
  for x, vv in zip(positions_x, velocities_x, strict=False):
    if vv < MODEL_STOP_SPEED:
      return max(0.0, float(x))
  return None


def gentle_target(v: float, p_kw: float, car: RegenCar = MODEL_S) -> float:
  cap = regen_capacity(v, p_kw, car)
  g = min(A_GENTLE_MAX, GENTLE_FRAC * cap)
  if cap >= A_GENTLE_MIN / GENTLE_FRAC:
    g = max(g, A_GENTLE_MIN)
  return max(A_GENTLE_FLOOR, g)


A_TAIL = 0.5              # m/s^2, gentle tail inside the regen fade band


def profile_decel(v: float, p_kw: float, car: RegenCar = MODEL_S) -> float:
  """Regen-shaped decel for speed v: follow the gentle regen-only target above the
  fade band, ease to A_TAIL inside it (where regen fades and friction would take over)."""
  bp = car.fade_bp
  if v >= bp[-1]:
    return gentle_target(v, p_kw, car)
  frac = (v - bp[0]) / (bp[-1] - bp[0])
  return float(np.interp(frac, [0.0, 1.0], [A_TAIL, gentle_target(bp[-1], p_kw, car)]))


def profile_distance(v: float, p_kw: float, n: int = 24, car: RegenCar = MODEL_S) -> float:
  """Distance to stop from v following profile_decel (integral of u/a(u) du)."""
  if v <= 0.0:
    return 0.0
  us = np.linspace(0.0, v, n + 1)
  integrand = [u / max(profile_decel(u, p_kw, car), 0.05) for u in us]
  du = v / n
  return float(du * (sum(integrand) - 0.5 * (integrand[0] + integrand[-1])))


class RegenStopShaper:
  """Adds a regen-shaped stop profile that starts as soon as the stop is known
  and the profile needs the remaining distance. Output = min(plan, early)."""
  def __init__(self, car: RegenCar = MODEL_S):
    self.car = car
    self.active = False
    self.a_added = 0.0      # current extra-braking command (<= 0)
    self.lost_t = 0.0
    self.last_req = 0.0

  def reset(self):
    self.active = False
    self.a_added = 0.0
    self.lost_t = 0.0

  def update(self, v, a_plan, stop_dist, p_kw, dt):
    """Return (a_out, a_early). a_out = min(a_plan, a_early) always."""
    target = 0.0
    if v > MIN_SPEED and stop_dist is not None:
      self.lost_t = 0.0
      d = max(stop_dist, 0.5)
      d_prof = profile_distance(v, p_kw, car=self.car)
      self.last_req = d_prof / d
      if not self.active and d_prof >= ONSET_FRAC * d:
        self.active = True
      elif self.active and d_prof < RELEASE_FRAC * d:
        self.active = False
      if self.active:
        # Scale the profile so it lands on the stop point (ratio > 1 means behind schedule).
        target = -profile_decel(v, p_kw, self.car) * max(d_prof / d, 0.0)
    else:
      self.lost_t += dt
      if self.lost_t > STOP_LOST_HOLD_S or v <= MIN_SPEED:
        self.active = False
      elif self.active:
        target = self.a_added

    # Smooth onset / release of the ADDED braking only.
    if target < self.a_added:
      self.a_added = max(target, self.a_added - ONSET_JERK * dt)
    else:
      self.a_added = min(target, self.a_added + RELEASE_JERK * dt)

    a_early = self.a_added if self.a_added < 0.0 else 0.0
    if a_early >= 0.0:
      return a_plan, 0.0
    return min(a_plan, a_early), a_early
