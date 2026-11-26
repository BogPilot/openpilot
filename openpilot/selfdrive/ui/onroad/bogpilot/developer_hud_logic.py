"""Developer HUD: the live data panel on the driving screen (display only, no pyray).

Ported from the 0.9.7 BogPilot Developer HUD: ten cells in two columns, the same formulas and colour thresholds.
Metric choice and thresholds follow sunnypilot's Developer UI (MIT License, Copyright (c) 2021-, Haibin Wen, sunnypilot,
and a number of other contributors); the two-column layout and the angle-steering substitute are BogPilot's own.

Every cell comes from the current drive's messages. A missing or stale source shows "-", never an invented zero.
Nothing here writes a param, a file or a message.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

MS_TO_KPH = 3.6
MS_TO_MPH = 2.23694
METER_TO_FOOT = 3.28084
GRAVITY = 9.81

WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
ORANGE = (255, 188, 0)
RED = (255, 0, 0)
OVERRIDE_GREY = (145, 155, 149)

CLOSING_FAST_MS = -4.4704   # closing faster than 10 mph
MEM_WARN_PERCENT = 85
MAX_AGE_S = 0.5


@dataclass(frozen=True)
class HudInputs:
  is_metric: bool = False
  a_ego: float = 0.0
  v_ego: float = 0.0
  steering_angle_deg: float = 0.0
  steering_pressed: bool = False
  lat_active: bool = False
  lead_present: bool = False
  lead_d_rel: float = 0.0
  lead_v_rel: float = 0.0
  desired_curvature: float = 0.0
  curvature: float = 0.0
  roll: float = 0.0
  steer_angle_desired: float | None = None   # angle / PID lateral control only; None -> "-"
  torque_control: bool = False
  friction: float = 0.0
  gps_valid: bool = False
  altitude: float = 0.0
  memory_usage_percent: int | None = None   # None -> "-"


@dataclass(frozen=True)
class Cell:
  value: str
  label: str
  unit: str
  color: tuple


def num(value: float, decimals: int) -> str:
  if not math.isfinite(value):
    return "-"
  text = f"{value:.{decimals}f}"
  return text[1:] if text.startswith("-") and float(text) == 0 else text


def _lat_color(i: HudInputs):
  if not i.lat_active:
    return WHITE
  return OVERRIDE_GREY if i.steering_pressed else GREEN


def _angle_color(i: HudInputs, angle: float, base):
  if abs(angle) > 180:
    return RED
  if abs(angle) > 90:
    return ORANGE
  return base


def _lead_speed_color(i: HudInputs):
  if not i.lead_present:
    return WHITE
  if i.lead_v_rel < CLOSING_FAST_MS:
    return RED
  if i.lead_v_rel < 0:
    return ORANGE
  return WHITE


def cells(i: HudInputs) -> list[Cell]:
  speed_conv = MS_TO_KPH if i.is_metric else MS_TO_MPH
  speed_unit = "km/h" if i.is_metric else "mph"
  dist_conv = 1.0 if i.is_metric else METER_TO_FOOT
  dist_unit = "m" if i.is_metric else "ft"
  accel_unit = "m/s\u00b2"
  out: list[Cell] = []

  # Row 1: ACCEL | REL DIST
  out.append(Cell(num(i.a_ego, 1), "ACCEL", accel_unit, WHITE))
  dist_color = WHITE
  if i.lead_present:
    dist_color = RED if i.lead_d_rel < 5 else ORANGE if i.lead_d_rel < 15 else WHITE
  out.append(Cell(num(i.lead_d_rel * dist_conv, 0) if i.lead_present else "-", "REL DIST", dist_unit, dist_color))

  # Row 2: LEAD SPD | REL SPEED
  lead_color = _lead_speed_color(i)
  out.append(Cell(num((i.v_ego + i.lead_v_rel) * speed_conv, 0) if i.lead_present else "-", "LEAD SPD", speed_unit, lead_color))
  out.append(Cell(num(i.lead_v_rel * speed_conv, 0) if i.lead_present else "-", "REL SPEED", speed_unit, lead_color))

  # Row 3: LAT ACCEL (desired, roll compensated) | REAL STEER
  lat = _lat_color(i)
  desired_lat = i.desired_curvature * i.v_ego * i.v_ego - i.roll * GRAVITY
  out.append(Cell(num(desired_lat, 2) if i.lat_active else "-", "LAT ACCEL", accel_unit, lat))
  out.append(Cell(num(i.steering_angle_deg, 1) + "\u00b0", "REAL STEER", "", _angle_color(i, i.steering_angle_deg, lat)))

  # Row 4: FRICTION (torque cars) or DESIRED STEER (angle / PID cars) | ACTUAL LAT
  if i.torque_control:
    out.append(Cell(num(i.friction, 3), "FRICTION", "", WHITE))
  else:
    shown = i.lat_active and i.steer_angle_desired is not None and math.isfinite(i.steer_angle_desired)
    color = _angle_color(i, i.steer_angle_desired, GREEN) if shown else WHITE
    out.append(Cell(num(i.steer_angle_desired, 1) + "\u00b0" if shown else "-", "DESIRED STEER", "", color))
  actual_lat = i.curvature * i.v_ego * i.v_ego - i.roll * GRAVITY
  out.append(Cell(num(actual_lat, 2), "ACTUAL LAT", accel_unit, lat))

  # Row 5: ALTITUDE | MEM %
  out.append(Cell(num(i.altitude * dist_conv, 1 if i.is_metric else 0) if i.gps_valid else "-", "ALTITUDE", dist_unit, WHITE))
  mem = i.memory_usage_percent
  out.append(Cell("-" if mem is None else f"{int(mem)}%", "MEM %", "",
                  ORANGE if mem is not None and mem > MEM_WARN_PERCENT else WHITE))
  return out


def display_cell(c: Cell) -> Cell:
  """Redesign panel: short labels, and the trailing degree / percent sign moves into the unit slot."""
  label = {"DESIRED STEER": "DES STEER", "MEM %": "MEM"}.get(c.label, c.label)
  value, unit = c.value, c.unit
  if not unit and value and value[-1] in "\u00b0%":
    value, unit = value[:-1], value[-1]
  return Cell(value, label, unit, c.color)


def _finite(x, default=0.0):
  try:
    x = float(x)
  except (TypeError, ValueError):
    return default
  return x if math.isfinite(x) else default


def inputs_from_messages(sm, started_frame: int, is_metric: bool, cp=None, now=None) -> HudInputs | None:
  """Build HudInputs from a SubMaster-like object, or None while carState is not fresh for this drive.

  Optional sources (radar, controls, vehicle parameters, carControl, GPS, deviceState) degrade to "-" on their own;
  only a stale carState (no live car data at all) hides the panel."""
  def fresh(name) -> bool:
    try:
      return bool(sm.recv_frame[name] >= started_frame and sm.alive[name] and sm.valid[name])
    except (KeyError, AttributeError, TypeError):
      return False

  if not fresh("carState"):
    return None
  cs = sm["carState"]
  kw: dict = dict(is_metric=bool(is_metric), a_ego=_finite(cs.aEgo), v_ego=_finite(cs.vEgo),
                  steering_angle_deg=_finite(cs.steeringAngleDeg), steering_pressed=bool(cs.steeringPressed))
  if fresh("carControl"):
    kw["lat_active"] = bool(sm["carControl"].latActive)
  if fresh("radarState"):
    lead = sm["radarState"].leadOne
    if bool(lead.present):
      kw.update(lead_present=True, lead_d_rel=_finite(lead.dRel), lead_v_rel=_finite(lead.vRel))
  if fresh("controlsState"):
    ctl = sm["controlsState"]
    kw.update(desired_curvature=_finite(ctl.desiredCurvature), curvature=_finite(ctl.curvature))
    try:
      state = ctl.lateralControlState
      if state.which() in ("angleState", "pidState"):
        kw["steer_angle_desired"] = _finite(getattr(state, state.which()).steeringAngleDesiredDeg, None)
    except (AttributeError, TypeError, ValueError):
      pass
  if fresh("vehicleParameters"):
    kw["roll"] = _finite(sm["vehicleParameters"].roll)
  if fresh("gpsLocationExternal"):
    gps = sm["gpsLocationExternal"]
    if bool(gps.hasFix):
      kw.update(gps_valid=True, altitude=_finite(gps.altitude))
  if fresh("deviceState"):
    kw["memory_usage_percent"] = int(_finite(sm["deviceState"].memoryUsagePercent))
  if cp is not None:
    try:
      if str(cp.steerControlType) == "torque" and cp.lateralTuning.which() == "torque":
        kw.update(torque_control=True, friction=_finite(cp.lateralTuning.torque.friction))
    except (AttributeError, TypeError, ValueError):
      pass
  return HudInputs(**kw)


# ---- placement (design space of the redesign cluster, see style.py HUD_W / HUD_H) ----
HUD_W, HUD_H = 400, 430
MIN_SCALE = 0.5


def panel_rect(view_w: float, view_h: float, edge: float, top: float) -> tuple[float, float, float, float]:
  """(x, y, w, h) in screen pixels: top-right corner, scaled to fit the narrower of width / remaining height."""
  scale = max(MIN_SCALE, min(1.0, (view_w * 0.25) / HUD_W, max(0.0, view_h - top - edge) / HUD_H))
  w, h = HUD_W * scale, HUD_H * scale
  return (view_w - edge - w, top, w, h)


class DeveloperHudPolicy:
  """Cached (2 s) DeveloperHUD file toggle read through the store (default off). Read failure: off."""

  def __init__(self, store=None, clock=time.monotonic, ttl=2.0):
    self._store, self.clock, self.ttl = store, clock, ttl
    self._next = -1.0
    self._value = False

  def get(self) -> bool:
    now = self.clock()
    if now >= self._next:
      self._next = now + self.ttl
      try:
        if self._store is None:
          from openpilot.common.bogpilot_store import ParamStore
          self._store = ParamStore()
        self._value = bool(self._store.toggle_bool("DeveloperHUD", self._store.tuning_level()))
      except Exception:
        self._value = False
    return self._value
