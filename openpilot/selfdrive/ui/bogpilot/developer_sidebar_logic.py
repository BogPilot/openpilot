"""Developer Sidebar: the metric table and the per-drive tracker (display only, no pyray).

Ported from the 0.9.7 BogPilot Developer Sidebar (seven slots, each showing one chosen metric). Metric numbers and labels are the
0.9.7 ones, so a stored choice keeps its meaning. The three longitudinal MPC jerk metrics (13 to 15) are not offered: nothing in
this build publishes those values. A value with no live source shows "-", never an invented zero. Nothing here writes a param, a
file or a message.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

SLOTS = 7
SIDEBAR_WIDTH = 300

# metric number -> (label shown on the sidebar, name in the picker, needs torque steering)
METRICS: dict[int, tuple[str, str, bool]] = {
  1: ("ACCEL", "Acceleration: Current", False),
  2: ("MAX ACCEL", "Acceleration: Max", False),
  3: ("STEER DELAY", "Auto Tune: Actuator Delay", False),
  4: ("FRICTION", "Auto Tune: Friction", True),
  5: ("LAT ACCEL", "Auto Tune: Lateral Acceleration", True),
  6: ("STEER RATIO", "Auto Tune: Steer Ratio", False),
  7: ("STEER STIFF", "Auto Tune: Stiffness Factor", False),
  8: ("LATERAL %", "Engagement %: Lateral", False),
  9: ("LONG %", "Engagement %: Longitudinal", False),
  10: ("STEER ANGLE", "Lateral Control: Steering Angle", False),
  11: ("TORQUE %", "Lateral Control: Torque % Used", True),
  12: ("ACT ACCEL", "Longitudinal Control: Actuator Acceleration Output", False),
}
ACCEL_UNIT = " m/s\u00b2"
TORQUE_HOLD_PERCENT = 50
TORQUE_HOLD_S = 10.0


def metric_keys() -> tuple[str, ...]:
  return tuple(f"DeveloperSidebarMetric{i}" for i in range(1, SLOTS + 1))


def available_metrics(torque: bool | None) -> dict[int, tuple[str, str, bool]]:
  """Metrics the picker offers. The torque ones are left out only when the car is known to steer by angle."""
  return {n: m for n, m in METRICS.items() if torque is not False or not m[2]}


def torque_steering(cp) -> bool | None:
  """True / False once the car's steering type is known, None before."""
  if cp is None:
    return None
  try:
    return str(cp.steerControlType) == "torque"
  except (AttributeError, TypeError):
    return None


def slot_assignments(values, torque: bool | None = None) -> list[int]:
  """Stored choice per slot -> the metrics to draw, in slot order. 0 (none), unknown numbers and the torque metrics on a car
  known to steer by angle are skipped, so the tiles that are left are spaced evenly."""
  offered = available_metrics(torque)
  out = []
  for v in values:
    try:
      n = int(v)
    except (TypeError, ValueError):
      continue
    if n in offered:
      out.append(n)
  return out


@dataclass(frozen=True)
class SidebarInputs:
  a_ego: float = 0.0
  gas_pressed: bool = False
  standstill: bool = False
  reverse: bool = False
  steering_angle_deg: float = 0.0
  lat_active: bool = False
  long_active: bool = False
  actuator_accel: float | None = None
  actuator_torque: float | None = None     # torque-steering cars only; None -> "-"
  lateral_delay: float | None = None
  friction: float | None = None
  lat_accel_factor: float | None = None
  steer_ratio: float | None = None
  stiffness_factor: float | None = None


def _num(x, decimals: int) -> str:
  if x is None or not math.isfinite(x):
    return "-"
  text = f"{x:.{decimals}f}"
  return text[1:] if text.startswith("-") and float(text) == 0 else text


class Tracker:
  """Running values for the current drive (maximum acceleration, engagement shares, torque hold). reset() starts a drive."""

  def __init__(self, clock=time.monotonic):
    self.clock = clock
    self.reset()

  def reset(self):
    self.lateral_time = 0
    self.longitudinal_time = 0
    self.total_time = 0
    self.max_accel = 0.0
    self.max_angle = 0
    self.max_torque = 0
    self._hold_until = None

  def update(self, i: SidebarInputs) -> dict[int, str]:
    """Advance one UI frame and return the text for every metric (number -> "value")."""
    now = self.clock()
    if not i.gas_pressed:
      self.max_accel = max(self.max_accel, i.a_ego)
    moving = not (i.reverse or i.standstill)
    self.lateral_time += 1 if i.lat_active and moving else 0
    self.longitudinal_time += 1 if i.long_active and moving else 0
    self.total_time += 1 if moving or self.total_time == 0 else 0

    angle = int(abs(i.steering_angle_deg)) if math.isfinite(i.steering_angle_deg) else 0
    torque = int(abs(i.actuator_torque) * 100) if i.actuator_torque is not None and math.isfinite(i.actuator_torque) else None
    angle_text = f"{angle}\u00b0"
    torque_text = "-" if torque is None else f"{torque}%"
    if torque is not None:
      if torque >= TORQUE_HOLD_PERCENT:
        self.max_angle = max(self.max_angle, angle)
        self.max_torque = max(self.max_torque, torque)
        self._hold_until = now + TORQUE_HOLD_S
      elif self._hold_until is not None and now >= self._hold_until:
        self.max_angle = self.max_torque = 0
        self._hold_until = None
      if torque >= TORQUE_HOLD_PERCENT or self._hold_until is not None:
        angle_text += f" - ({self.max_angle}\u00b0)"
        torque_text += f" - ({self.max_torque}%)"

    share = lambda t: _num(t / self.total_time * 100.0, 2) + "%"   # noqa: E731  (total_time is at least 1 after the first frame)
    return {
      1: _num(i.a_ego, 2) + ACCEL_UNIT,
      2: _num(self.max_accel, 2) + ACCEL_UNIT,
      3: _num(i.lateral_delay, 5),
      4: _num(i.friction, 5),
      5: _num(i.lat_accel_factor, 5),
      6: _num(i.steer_ratio, 5),
      7: _num(i.stiffness_factor, 5),
      8: share(self.lateral_time),
      9: share(self.longitudinal_time),
      10: angle_text,
      11: torque_text,
      12: "-" if i.actuator_accel is None else _num(i.actuator_accel, 2) + ACCEL_UNIT,
    }


def _finite(x, default=None):
  try:
    x = float(x)
  except (TypeError, ValueError):
    return default
  return x if math.isfinite(x) else default


def inputs_from_messages(sm, started_frame: int, cp=None) -> SidebarInputs | None:
  """SidebarInputs from a SubMaster-like object, or None while carState is not fresh for this drive. Each optional source
  degrades to "-" on its own."""
  def fresh(name) -> bool:
    try:
      return bool(sm.recv_frame[name] >= started_frame and sm.alive[name] and sm.valid[name])
    except (KeyError, AttributeError, TypeError):
      return False

  if not fresh("carState"):
    return None
  cs = sm["carState"]
  torque = torque_steering(cp)
  kw: dict = dict(a_ego=_finite(cs.aEgo, 0.0), gas_pressed=bool(cs.gasPressed), standstill=bool(cs.standstill),
                  reverse=str(cs.gearShifter) == "reverse", steering_angle_deg=_finite(cs.steeringAngleDeg, 0.0))
  if fresh("carControl"):
    cc = sm["carControl"]
    kw.update(lat_active=bool(cc.latActive), long_active=bool(cc.longActive), actuator_accel=_finite(cc.actuators.accel))
    if torque:
      kw["actuator_torque"] = _finite(cc.actuators.torque)
  if fresh("lateralDelay"):
    kw["lateral_delay"] = _finite(sm["lateralDelay"].lateralDelay)
  if fresh("lateralTorqueParameters") and torque:
    p = sm["lateralTorqueParameters"]
    kw.update(friction=_finite(p.frictionCoefficientFiltered), lat_accel_factor=_finite(p.latAccelFactorFiltered))
  if fresh("vehicleParameters"):
    vp = sm["vehicleParameters"]
    kw.update(steer_ratio=_finite(vp.steerRatio), stiffness_factor=_finite(vp.stiffnessFactor))
  return SidebarInputs(**kw)


def split_rect(x: float, y: float, w: float, h: float, visible: bool):
  """(content, sidebar): the 300 px sidebar takes the right edge and the content keeps the rest. sidebar is None when hidden
  or when the screen is too narrow to leave room for the road view."""
  if not visible or w < SIDEBAR_WIDTH * 2:
    return (x, y, w, h), None
  return (x, y, w - SIDEBAR_WIDTH, h), (x + w - SIDEBAR_WIDTH, y, SIDEBAR_WIDTH, h)


def layout_slots(count: int, height: float, tile_h: float = 126.0) -> list[float]:
  """Top edge of each tile: equal gaps above, between and below (0.9.7)."""
  if count <= 0:
    return []
  gap = (height - count * tile_h) / (count + 1)
  return [gap + k * (tile_h + gap) for k in range(count)]
