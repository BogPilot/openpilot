"""Tesla Model S / Model X trim profiles: the Vehicle Options "Trim" picker and the CAN drive-layout detection.

Scope: AP1 Model S, AP1 Model X and Pre-AP Model S. Comfort and display layers only (the regen-aware stop shaper, comfort
regen, the onroad pedal gauge). CarParams, the panda and every safety limit are the same for every trim.

What comes from where
  * From CAN, every drive (DriveDetector): the motor layout (0x186 front drive inverter torque frame present, with
    0x398 GTW_fourWheelDrive as a supporting signal), the Performance (large) rear motor on a dual-motor car (rear / front
    rpm per m/s ratio, about 1.026 on a P car against about 1.001 on a non-P dual), and the live rpm per m/s of each motor
    (replaces the fixed 9.73 gear ratio and 0.35 m wheel radius).
  * From the driver (Param TeslaTrim, file /data/params_bogpilot/TeslaTrim): only what CAN cannot tell, which is the battery
    size and Ludicrous. "Auto" (the default, also a missing or empty file) keeps the base AP1 Model S / AP1 Model X tune.
  * Mass = Tesla's published curb weight (the later model-year value where Tesla changed it) + CARGO_KG. With Auto, a
    trim that CAN contradicts, or a trim with no published weight, the base platform mass is kept.

Sources (see work notes TESLA_TRIM_PROFILES): T1 Model S manual early 2015, T2 Model S manual MY2016, T3 Model S manual
MY2017, T4 Model S manual mid 2018, T9 Model X manual mid 2018, T5 Tesla 2012 Model S specifications. Curb weights are
copied exactly as Tesla prints them (lb / kg). Nothing in this table is estimated.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

CARGO_KG = 136.0                      # the standard openpilot cargo / occupant allowance
MS_PER_MPH = 0.44704

TRIM_PATH = Path("/data/params_bogpilot/TeslaTrim")
DETECTED_PATH = Path("/data/params_bogpilot/TeslaTrimDetected")
_trim_path = TRIM_PATH
_detected_path = DETECTED_PATH
AUTO = "Auto"

S, X = "S", "X"
AP1_S, AP1_X, PREAP = "TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"

# Drive layout / Performance rear codes (also the bogpilot carState fields ap1DriveLayout / ap1PerfRear)
LAYOUT_UNKNOWN, LAYOUT_SINGLE, LAYOUT_DUAL = 0, 1, 2
PERF_UNKNOWN, PERF_NO, PERF_YES = 0, 1, 2


@dataclass(frozen=True)
class Trim:
  key: str
  chassis: str              # S or X
  label: str
  dual: bool                # front + rear motor
  perf_rear: bool           # large performance rear motor (P trims)
  ludicrous: bool
  curb_lb: int | None       # Tesla's published curb weight; None = Tesla never published one
  curb_kg: int | None
  source: str
  preap: bool = False       # sold before Autopilot hardware (Pre-AP picker)
  ap1: bool = True          # sold with Autopilot 1 hardware (AP1 picker)

  @property
  def mass_kg(self) -> float | None:
    return None if self.curb_kg is None else float(self.curb_kg) + CARGO_KG


_T = Trim
TRIMS: tuple[Trim, ...] = (
  # Model S, single (rear) motor
  _T("S40", S, "40", False, False, False, None, None, "T5 (no curb weight published)", preap=True, ap1=False),
  _T("S60", S, "60 (2013-15)", False, False, False, 4407, 1999, "T1, T2", preap=True),
  _T("S60_2016", S, "60 (2016-17)", False, False, False, 4469, 2027, "T3, T4"),
  _T("S70", S, "70", False, False, False, 4469, 2027, "T3"),
  _T("S75", S, "75", False, False, False, 4469, 2027, "T3, T4"),
  _T("S85", S, "85", False, False, False, 4630, 2100, "T1, T2", preap=True),
  _T("SP85", S, "P85", False, True, False, 4630, 2100, "T1, T2", preap=True),
  _T("SP85PLUS", S, "P85+", False, True, False, 4630, 2100, "T1", preap=True),
  # Model S, dual motor, small rear motor
  _T("S60D", S, "60D", True, False, False, 4647, 2108, "T3"),
  _T("S70D", S, "70D", True, False, False, 4647, 2108, "T3"),
  _T("S75D", S, "75D", True, False, False, 4647, 2108, "T3, T4"),
  _T("S85D", S, "85D", True, False, False, 4848, 2199, "T2"),
  _T("S90D", S, "90D", True, False, False, 4736, 2148, "T3"),
  _T("S100D", S, "100D", True, False, False, 4883, 2215, "T4"),
  # Model S, dual motor, Performance rear motor
  _T("SP85D", S, "P85D", True, True, False, 4963, 2251, "T2"),
  _T("SP85DL", S, "P85D Ludicrous", True, True, True, 4963, 2251, "T2"),
  _T("SP90D", S, "P90D", True, True, False, 4841, 2196, "T3"),
  _T("SP90DL", S, "P90D Ludicrous", True, True, True, 4841, 2196, "T3"),
  _T("SP100DL", S, "P100D Ludicrous", True, True, True, 4941, 2241, "T3, T4"),
  # Model X (always dual motor)
  _T("X60D", X, "60D", True, False, False, 5185, 2352, "T9"),
  _T("X75D", X, "75D", True, False, False, 5185, 2352, "T9"),
  _T("X90D", X, "90D", True, False, False, 5267, 2389, "T9"),
  _T("X100D", X, "100D", True, False, False, 5421, 2459, "T9"),
  _T("XP90D", X, "P90D", True, True, False, 5377, 2439, "T9"),
  _T("XP90DL", X, "P90D Ludicrous", True, True, True, 5377, 2439, "T9"),
  _T("XP100DL", X, "P100D Ludicrous", True, True, True, 5483, 2487, "T9"),
)
TRIM_BY_KEY = {t.key: t for t in TRIMS}

# Base (Auto) mass per platform: exactly the values the shaper used before trim profiles (regen_aware MASS_KG / MODELX_MASS_KG).
BASE_MASS_KG = {AP1_S: 2100.0, PREAP: 2100.0, AP1_X: 2400.0}

# ---- rpm per m/s of each motor (motor rpm / vEgo): seeds and sanity clamps ----
# Measured on real drives (rpm per mph): X P dual rear 111.8 / front 109.1; S non-P dual rear 115.1 / front 114.9; S single 120.1.
# The two classes without a drive are scaled from a measured one by Tesla's gear ratios only (large 9.734, small 9.325, T4/T9):
# S P dual rear = 115.1 x 9.734 / 9.325; X non-P dual rear = 111.8 x 9.325 / 9.734 (same tires as the measured car).
GEAR_LARGE, GEAR_SMALL = 9.734, 9.325
MEASURED_RPM_PER_MPH = {
  (S, LAYOUT_SINGLE, PERF_UNKNOWN): (120.1, None),
  (S, LAYOUT_DUAL, PERF_NO): (115.1, 114.9),
  (X, LAYOUT_DUAL, PERF_YES): (111.8, 109.1),
}
DERIVED_RPM_PER_MPH = {
  (S, LAYOUT_DUAL, PERF_YES): (round(115.1 * GEAR_LARGE / GEAR_SMALL, 1), 114.9),
  (X, LAYOUT_DUAL, PERF_NO): (round(111.8 * GEAR_SMALL / GEAR_LARGE, 1), 109.1),
}
# Before the layout is known: the constants the code used before (S 9.73 / 0.35 m; X 249.9 rpm per m/s measured).
LEGACY_RPM_PER_MS = {S: 9.73 * 60.0 / (2.0 * math.pi * 0.35), X: 249.9}
LEGACY_FRONT_RPM_PER_MPH = {S: 114.9, X: 109.1}
# Physical band: Tesla gear ratios 9.325..9.734 and static tire diameters 703..758 mm (T1, T8, T9), widened by 3 % for the
# rolling radius and speedometer factor (measured 1.0..1.7 %). A learned value is always clamped into it.
RPM_PER_MS_MIN = GEAR_SMALL * 60.0 / (math.pi * 0.758) / 1.03     # about 228
RPM_PER_MS_MAX = GEAR_LARGE * 60.0 / (math.pi * 0.703) * 1.03     # about 272

# ---- regen peak (front + rear shaft power, kW): the pedal gauge full bar, and the shaper's nominal (x 30 / 42 as before) ----
# Measured: S non-P dual 53.1 kW, X P dual 71.6 kW. A single-motor car keeps the existing per-platform value (no change).
# S P dual and X non-P dual have no drive yet: they use their chassis' measured dual value.
DUAL_REGEN_PEAK_KW = {S: 53.1, X: 71.6}
SHAPER_NOMINAL_FRAC = 30.0 / 42.0     # regen_aware: 30 kW nominal against the 42 kW peak on the S


def chassis_of(fingerprint) -> str | None:
  fp = str(fingerprint or "")
  if fp in (AP1_S, PREAP):
    return S
  if fp == AP1_X:
    return X
  return None


def clamp_rpm_per_ms(k) -> float | None:
  try:
    k = float(k)
  except (TypeError, ValueError):
    return None
  if not math.isfinite(k) or k <= 0.0:
    return None
  return min(max(k, RPM_PER_MS_MIN), RPM_PER_MS_MAX)


def seed_rpm_per_ms(chassis: str | None, layout: int, perf: int) -> tuple[float | None, float | None]:
  """(rear, front) rpm per m/s seeds for a detected class; front None on a single-motor car."""
  if chassis is None:
    return None, None
  if layout == LAYOUT_SINGLE:
    rear, front = MEASURED_RPM_PER_MPH[(S, LAYOUT_SINGLE, PERF_UNKNOWN)] if chassis == S else (None, None)
    return (rear / MS_PER_MPH if rear else LEGACY_RPM_PER_MS[chassis]), None
  if layout == LAYOUT_DUAL and perf in (PERF_NO, PERF_YES):
    rear, front = MEASURED_RPM_PER_MPH.get((chassis, layout, perf)) or DERIVED_RPM_PER_MPH[(chassis, layout, perf)]
    return rear / MS_PER_MPH, front / MS_PER_MPH
  front = LEGACY_FRONT_RPM_PER_MPH[chassis] / MS_PER_MPH if layout == LAYOUT_DUAL else None
  return LEGACY_RPM_PER_MS[chassis], front


# ---- the Trim param (file) ----
def read_trim(stored: str | bytes | None = None) -> str:
  """The saved TeslaTrim key; AUTO when missing, empty or unreadable. An unknown key is returned as is (kept, treated as Auto)."""
  if stored is None:
    try:
      stored = _trim_path.read_text(encoding="utf-8", errors="replace") if _trim_path.is_file() else ""
    except OSError:
      stored = ""
  if isinstance(stored, bytes):
    stored = stored.decode("utf-8", "replace")
  text = str(stored).strip()
  return text or AUTO


def write_trim(key: str, path: Path | None = None) -> None:
  if key != AUTO and key not in TRIM_BY_KEY:
    raise KeyError(key)
  target = path if path is not None else _trim_path
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(key)


# ---- the detection the car saw last (written by card once per drive when stable; read offroad and at planner start) ----
@dataclass(frozen=True)
class Detected:
  chassis: str | None = None
  layout: int = LAYOUT_UNKNOWN
  perf: int = PERF_UNKNOWN
  rear_rpm_per_ms: float | None = None      # learned (None = not measured)
  front_rpm_per_ms: float | None = None

  def to_json(self) -> str:
    return json.dumps({"chassis": self.chassis, "layout": self.layout, "perf": self.perf,
                       "rear_rpm_per_ms": self.rear_rpm_per_ms, "front_rpm_per_ms": self.front_rpm_per_ms}, sort_keys=True)


def read_detected(stored: str | None = None, path: Path | None = None) -> Detected:
  if stored is None:
    p = path if path is not None else _detected_path
    try:
      stored = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    except OSError:
      stored = ""
  try:
    d = json.loads(stored or "{}")
    if not isinstance(d, dict):
      return Detected()
    chassis = d.get("chassis") if d.get("chassis") in (S, X) else None
    layout = int(d.get("layout", 0)) if int(d.get("layout", 0)) in (LAYOUT_UNKNOWN, LAYOUT_SINGLE, LAYOUT_DUAL) else LAYOUT_UNKNOWN
    perf = int(d.get("perf", 0)) if int(d.get("perf", 0)) in (PERF_UNKNOWN, PERF_NO, PERF_YES) else PERF_UNKNOWN
    return Detected(chassis, layout, perf, clamp_rpm_per_ms(d.get("rear_rpm_per_ms")), clamp_rpm_per_ms(d.get("front_rpm_per_ms")))
  except (TypeError, ValueError):
    return Detected()


def write_detected(det: Detected, path: Path | None = None) -> bool:
  """Write the detection if it differs from what is saved (at most a few small writes per drive). True when written."""
  p = path if path is not None else _detected_path
  text = det.to_json()
  try:
    if p.is_file() and p.read_text(encoding="utf-8", errors="replace") == text:
      return False
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(p)
    return True
  except OSError:
    return False


def detected_text(det: Detected, fingerprint=None) -> str:
  """The read-only Detected line, e.g. 'Model X, dual motor, Performance rear (from CAN)'."""
  chassis = chassis_of(fingerprint) or det.chassis
  if chassis is None:
    return "Not detected yet"
  parts = [f"Model {chassis}"]
  if det.chassis is not None and det.chassis != chassis:
    return parts[0] + ", drive the car once to detect the motors"
  if det.layout == LAYOUT_SINGLE:
    parts.append("single motor")
  elif det.layout == LAYOUT_DUAL:
    parts.append("dual motor")
    if det.perf == PERF_YES:
      parts.append("Performance rear")
    elif det.perf == PERF_NO:
      parts.append("standard rear")
    else:
      parts.append("rear motor not measured yet")
  else:
    return parts[0] + ", drive the car once to detect the motors"
  return ", ".join(parts) + " (from CAN)"


# ---- picker list ----
def platform_trims(fingerprint) -> list[Trim]:
  chassis = chassis_of(fingerprint)
  if chassis is None:
    return []
  if str(fingerprint) == PREAP:
    return [t for t in TRIMS if t.chassis == S and t.preap]
  return [t for t in TRIMS if t.chassis == chassis and t.ap1]


def consistent(trim: Trim, det: Detected) -> bool:
  """False when the picked trim contradicts what CAN detected (layout, or the Performance rear once it was measured)."""
  if det.layout == LAYOUT_SINGLE and trim.dual:
    return False
  if det.layout == LAYOUT_DUAL and not trim.dual:
    return False
  if trim.dual and det.layout == LAYOUT_DUAL and det.perf != PERF_UNKNOWN and trim.perf_rear != (det.perf == PERF_YES):
    return False
  return True


def picker_keys(fingerprint, det: Detected, saved: str | None = None) -> list[str]:
  """AUTO, then only the trims of this platform that agree with the detection. A saved trim that no longer agrees stays in
  the list (right after AUTO) so it is shown, never silently changed."""
  keys = [AUTO] + [t.key for t in platform_trims(fingerprint) if consistent(t, det)]
  if saved and saved != AUTO and saved in TRIM_BY_KEY and saved not in keys and TRIM_BY_KEY[saved] in platform_trims(fingerprint):
    keys.insert(1, saved)
  return keys


def trim_label(key: str) -> str:
  if key == AUTO or key not in TRIM_BY_KEY:
    return AUTO
  return TRIM_BY_KEY[key].label


# ---- the profile the comfort / display layers use ----
@dataclass(frozen=True)
class Profile:
  fingerprint: str
  trim: str                   # the saved key (AUTO, a trim key, or an unknown text kept as is)
  trim_used: bool             # the trim's mass is in use (picked, known, consistent with CAN, weight published)
  mismatch: bool              # the picked trim contradicts CAN (warning; CAN-derived fields win)
  mass_kg: float
  layout: int
  perf: int
  rear_rpm_per_ms: float      # seed for this drive (learned last drive if any, else the class seed)
  front_rpm_per_ms: float | None
  regen_peak_kw: float | None  # front + rear peak on a dual car; None = keep the platform's single-motor value


def profile_for(fingerprint, trim: str | None = None, det: Detected | None = None) -> Profile:
  fp = str(fingerprint or "")
  chassis = chassis_of(fp)
  trim = read_trim() if trim is None else (trim or AUTO)
  det = read_detected() if det is None else det
  if chassis is None:
    return Profile(fp, trim, False, False, BASE_MASS_KG[AP1_S], LAYOUT_UNKNOWN, PERF_UNKNOWN, LEGACY_RPM_PER_MS[S], None, None)
  if det.chassis is not None and det.chassis != chassis:
    det = Detected(chassis)                        # saved for another car: start over
  if fp == PREAP:
    det = Detected(chassis, LAYOUT_SINGLE, PERF_UNKNOWN, det.rear_rpm_per_ms, None)   # Pre-AP is rear-motor only
  t = TRIM_BY_KEY.get(trim)
  in_platform = t is not None and t in platform_trims(fp)
  mismatch = bool(in_platform and not consistent(t, det))
  use = bool(in_platform and not mismatch and t.mass_kg is not None)
  mass = t.mass_kg if use else BASE_MASS_KG[fp]
  layout, perf = det.layout, det.perf
  if layout == LAYOUT_UNKNOWN and fp == AP1_X:
    layout = LAYOUT_DUAL                           # every Model X is dual motor
  if use and layout == LAYOUT_DUAL and perf == PERF_UNKNOWN:
    perf = PERF_YES if t.perf_rear else PERF_NO    # the picked trim fills in what CAN has not measured yet
  rear_seed, front_seed = seed_rpm_per_ms(chassis, layout, perf)
  rear = det.rear_rpm_per_ms or rear_seed
  front = (det.front_rpm_per_ms or front_seed) if layout == LAYOUT_DUAL else None
  peak = DUAL_REGEN_PEAK_KW[chassis] if layout == LAYOUT_DUAL else None
  return Profile(fp, trim, use, mismatch, float(mass), layout, perf, float(clamp_rpm_per_ms(rear)),
                 clamp_rpm_per_ms(front) if front is not None else None, peak)


# ---- live CAN detection (carstate) ----
PERF_RATIO_SPLIT = 1.012          # rear / front rpm per m/s: S non-P dual 1.001, X P dual 1.026, S P dual about 1.024 (gears x tires)
K_MIN_SPEED = 8.0                 # m/s: learn rpm per m/s only above this (speed and rpm resolution, little slip)
K_TAU_S = 10.0                    # EMA time constant
K_MIN_SAMPLES = 300               # samples before a value counts as measured (3 s at speed at 100 Hz)
K_OUTLIER = 0.08                  # a sample more than 8 % off the running value is ignored (wheel slip, a bad frame)
SINGLE_AFTER_S = 5.0              # no front frame for this long while moving -> single motor
MOVING_SPEED = 3.0
RPM_SNA = -32768.0


class DriveDetector:
  """Per drive. update() once per carstate step; read layout / perf / rear_k / front_k / measured."""

  def __init__(self, fingerprint, dt: float, front_possible: bool = True, seed: Detected | None = None):
    self.chassis = chassis_of(fingerprint)
    self.dt = dt
    self.front_possible = front_possible
    if not front_possible:
      self.layout = LAYOUT_SINGLE
    elif self.chassis == X:
      self.layout = LAYOUT_DUAL       # every Model X has a front motor (no RWD X was sold)
    else:
      self.layout = LAYOUT_UNKNOWN
    self.perf = PERF_UNKNOWN
    self.no_front_s = 0.0
    prof = profile_for(fingerprint, AUTO, seed or Detected(self.chassis))
    self._rear = _Ema(prof.rear_rpm_per_ms)
    self._front = _Ema(prof.front_rpm_per_ms or LEGACY_FRONT_RPM_PER_MPH.get(self.chassis or S, 114.9) / MS_PER_MPH)

  def update(self, v, rear_rpm, front_rpm=None, front_seen: bool = False, four_wheel_drive=None) -> None:
    v = _finite(v)
    if self.front_possible:
      if front_seen or four_wheel_drive == 1:
        self.layout = LAYOUT_DUAL
      elif self.layout == LAYOUT_UNKNOWN and v is not None and v > MOVING_SPEED and four_wheel_drive in (None, 0):
        self.no_front_s += self.dt
        if self.no_front_s >= SINGLE_AFTER_S:
          self.layout = LAYOUT_SINGLE
    if v is None or v < K_MIN_SPEED:
      return
    self._rear.add(_rpm(rear_rpm), v, self.dt)
    if self.layout == LAYOUT_DUAL and front_seen:
      self._front.add(_rpm(front_rpm), v, self.dt)
    if self.layout == LAYOUT_DUAL and self._rear.measured and self._front.measured:
      self.perf = PERF_YES if self._rear.value / self._front.value >= PERF_RATIO_SPLIT else PERF_NO

  @property
  def rear_k(self) -> float:
    return self._rear.value

  @property
  def front_k(self) -> float:
    return self._front.value if self.layout == LAYOUT_DUAL else float("nan")

  @property
  def measured(self) -> bool:
    return self._rear.measured

  def detected(self) -> Detected:
    return Detected(self.chassis, self.layout, self.perf if self.layout == LAYOUT_DUAL else PERF_UNKNOWN,
                    self._rear.value if self._rear.measured else None,
                    self._front.value if (self.layout == LAYOUT_DUAL and self._front.measured) else None)


class _Ema:
  def __init__(self, seed):
    self.value = float(clamp_rpm_per_ms(seed) or LEGACY_RPM_PER_MS[S])
    self.count = 0

  @property
  def measured(self) -> bool:
    return self.count >= K_MIN_SAMPLES

  def add(self, rpm, v, dt) -> None:
    if rpm is None or v <= 0.0:
      return
    k = rpm / v
    if not RPM_PER_MS_MIN <= k <= RPM_PER_MS_MAX:
      return
    if self.count >= K_MIN_SAMPLES and abs(k - self.value) > K_OUTLIER * self.value:
      return
    alpha = 1.0 / (self.count + 1) if self.count < K_MIN_SAMPLES else min(1.0, dt / K_TAU_S)
    self.value += alpha * (k - self.value)
    self.count += 1


def _finite(x) -> float | None:
  try:
    x = float(x)
  except (TypeError, ValueError):
    return None
  return x if math.isfinite(x) else None


def _rpm(x) -> float | None:
  x = _finite(x)
  if x is None or x <= RPM_SNA:
    return None
  return abs(x)
