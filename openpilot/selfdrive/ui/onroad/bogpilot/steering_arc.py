"""BogPilot steering arc (t913u): pyray port of daily frogpilot/ui/qt/onroad/steering_arc.{h,cc} (bogpilot-tesla 04d560f3e).

The daily arc is itself a QPainter port of upstream openpilot selfdrive/ui/mici/onroad/torque_bar.py (MIT); this port
reuses that file's arc_bar_pts and the shared shader_polygon.draw_polygon. BogPilot changes kept from daily: arc "B"
geometry (1800 px radius, 17 degree span, raised 112 px), purple in Experimental Mode, visible (dimmed) while
disengaged because it is the Experimental Mode tap target, fill grows toward the turn (left fills left), the driver's
own steering while lateral is off or overriding (6-frame source hysteresis) coloured by wheel angle, and a white tick at
openpilot's target during an override.

Signals (0.11.2 names; ordinals verified identical to the 0.9.7 recording for the replay):
  op     angle / curvature lateral control (AP1: angleState): (curvature*v^2 - roll*g*interp(v,[5,15],[0,1])
         + (desired - actual)) / maxLateralAccel from controlsState.curvature / desiredCurvature, carState.vEgo,
         vehicleParameters.roll, CP.maxLateralAccel. controlsState.curvature = -VM.calc_curvature(steeringAngle): a
         RIGHT turn is positive, a left turn negative and fills LEFT (no extra negation, same as upstream).
         Torque control: -carOutput.actuatorsOutput.torque (0.11.2 upstream TorqueBar; daily read actuators.steer).
  human  angleUtilization(curvature, curvature, ...) blended with -carState.steeringAngleDeg/180 below 5..9 m/s
         (steeringAngleDeg is positive to the LEFT, so the minus makes a left wheel fill left).
  latActive carControl.latActive; override / active from ui_state.status; experimental selfdriveState.experimentalMode.
Pure state/geometry is importable without a window; painting needs pyray.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

SPAN_DEG = 17.0
SCALE = 2.6
RADIUS = 1800.0
OFFSET_LO, OFFSET_HI = 112.0, 122.4
THICKNESS_LO, THICKNESS_HI = 22.1, 52.0
DEFAULT_MAX_LAT_ACCEL = 3.0
HUMAN_FULL_ANGLE_DEG = 180.0
HUMAN_ANGLE_SPEED_LO, HUMAN_ANGLE_SPEED_HI = 5.0, 9.0
SOURCE_HYSTERESIS_FRAMES = 6
LOCK_DEG = 430.0
GRAVITY = 9.81
FILTER_K = (0.05 / 0.1) / (1.0 + 0.05 / 0.1)   # daily FirstOrderFilter(rc 0.1 s, dt 1/20 s), applied at 20 Hz
UPDATE_HZ = 20.0
VIEW_W, VIEW_H = 2100.0, 1020.0                # daily widget (screen minus border) == C3X content rect
TAP_HALF_W = 280.0

WHITE = (255, 255, 255)
PURPLE = (150, 100, 255)
YELLOW = (255, 200, 0)
ORANGE = (255, 115, 0)
DOT_GREY = (182, 182, 182)


def interp(x, x0, x1, y0, y1):
  if x <= x0:
    return y0
  if x >= x1:
    return y1
  return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def clamp(v, lo, hi):
  return lo if v < lo else hi if v > hi else v


def angle_utilization(curvature, desired_curvature, v_ego, roll, max_lat_accel):
  actual = curvature * v_ego * v_ego
  desired = desired_curvature * v_ego * v_ego
  roll_comp = roll * GRAVITY * interp(v_ego, 5.0, 15.0, 0.0, 1.0)
  max_lat = max_lat_accel if max_lat_accel > 0.1 else DEFAULT_MAX_LAT_ACCEL
  return clamp((actual - roll_comp + (desired - actual)) / max_lat, -1.0, 1.0)


def human_utilization(curvature, steering_angle_deg, v_ego, roll, max_lat_accel):
  """-> (value, lateral-acceleration weight)."""
  lat = angle_utilization(curvature, curvature, v_ego, roll, max_lat_accel)
  ang = clamp(-steering_angle_deg / HUMAN_FULL_ANGLE_DEG, -1.0, 1.0)
  w = interp(v_ego, HUMAN_ANGLE_SPEED_LO, HUMAN_ANGLE_SPEED_HI, 0.0, 1.0)
  return clamp(w * lat + (1.0 - w) * ang, -1.0, 1.0), w


def _blend(a, b, k):
  k = clamp(k, 0.0, 1.0)
  return tuple(a[i] + (b[i] - a[i]) * k for i in range(len(a)))


def human_angle_color(a):
  blue, orange_a, orange_deep, hot_pink = (90, 205, 255), (255, 140, 0), (255, 80, 0), (255, 20, 147)
  if a <= 120.0:
    return blue
  if a <= 180.0:
    return _blend(blue, orange_a, (a - 120.0) / 60.0)
  if a <= 360.0:
    return _blend(orange_a, orange_deep, (a - 180.0) / 180.0)
  return _blend(orange_deep, hot_pink, min(1.0, (a - 360.0) / (LOCK_DEG - 360.0)))


@dataclass
class ArcInputs:
  op: float = 0.0
  human: float = 0.0
  human_lat_weight: float = 1.0
  lat_active: bool = False
  override: bool = False
  active: bool = False
  engaged_colors: bool = False
  experimental: bool = False
  steering_angle_deg: float = 0.0


def _f(x):
  x = float(x)
  if not math.isfinite(x):
    raise ValueError("non-finite arc input")
  return x


def inputs_from_messages(controls_state, car_state, car_control, car_output, vehicle_parameters, max_lat_accel,
                         status: str, experimental: bool) -> ArcInputs:
  """`status` is "engaged" / "disengaged" / "override" (UIStatus values). vehicle_parameters may be None (roll 0)."""
  roll = _f(vehicle_parameters.roll) if vehicle_parameters is not None else 0.0
  v = _f(car_state.vEgo)
  curv = _f(controls_state.curvature)
  if controls_state.lateralControlState.which() in ("angleState", "curvatureState"):
    op = angle_utilization(curv, _f(controls_state.desiredCurvature), v, roll, max_lat_accel)
  else:
    op = -_f(car_output.actuatorsOutput.torque) if car_output is not None else 0.0
  angle = _f(car_state.steeringAngleDeg)
  human, w = human_utilization(curv, angle, v, roll, max_lat_accel)
  active = status != "disengaged"
  return ArcInputs(op=op, human=human, human_lat_weight=w, lat_active=bool(car_control.latActive),
                   override=status == "override", active=active, engaged_colors=active and status != "override",
                   experimental=bool(experimental), steering_angle_deg=angle)


class ArcState:
  """daily SteeringArc::update. Call at UPDATE_HZ (the daily UI_FREQ) so the filter time constant matches."""

  def __init__(self):
    self.reset()

  def reset(self):
    self.torque = 0.0
    self.op_target = 0.0
    self.alpha = 0.0
    self.human_orange = 1.0
    self.angle = 0.0
    self.human = False
    self.human_frames = 0
    self.show_tick = False
    self.engaged_colors = False
    self.experimental = False

  def update(self, a: ArcInputs):
    want_human = (not a.lat_active) or a.override
    if want_human != self.human:
      self.human_frames += 1
      if self.human_frames >= SOURCE_HYSTERESIS_FRAMES:
        self.human = want_human
        self.human_frames = 0
    else:
      self.human_frames = 0
    target = clamp(a.human, -1.0, 1.0) if self.human else (clamp(a.op, -1.0, 1.0) if a.lat_active else 0.0)
    k = FILTER_K
    self.torque = (1 - k) * self.torque + k * target
    op = clamp(a.op, -1.0, 1.0) if a.lat_active else 0.0
    self.op_target = (1 - k) * self.op_target + k * op
    self.alpha = (1 - k) * self.alpha + k * (1.0 if a.active else 0.55)
    self.human_orange = clamp(a.human_lat_weight, 0.0, 1.0)
    self.angle = (1 - k) * self.angle + k * abs(a.steering_angle_deg)
    self.show_tick = self.human and a.lat_active and a.override
    self.engaged_colors = a.engaged_colors
    self.experimental = a.experimental


def view_scale(rect) -> float:
  return min(1.0, rect.width / VIEW_W, rect.height / VIEW_H)


def tap_rect(rect):
  """(x, y, w, h) screen rect: from 30 px above the full-lock bar top to the view bottom, ~6 px past the arc ends."""
  s = view_scale(rect)
  h = (OFFSET_HI + THICKNESS_HI + 30) * s
  cx = rect.x + rect.width / 2
  bottom = rect.y + rect.height
  top = round(bottom - h)
  return (cx - TAP_HALF_W * s, top, 2 * TAP_HALF_W * s, bottom - top)


def geometry(state: ArcState, rect):
  """Pure arc geometry in screen pixels: dict with centre, radii, angles (for tests and painting)."""
  s = view_scale(rect)
  at = abs(state.torque)
  offset = interp(at, 0.5, 1.0, OFFSET_LO, OFFSET_HI) * s
  thickness = interp(at, 0.5, 1.0, THICKNESS_LO, THICKNESS_HI) * s
  radius = RADIUS * s
  top = -90.0
  return {"s": s, "cx": rect.x + rect.width / 2, "cy": rect.y + rect.height + radius - offset, "radius": radius,
          "thickness": thickness, "mid_r": radius + thickness / 2, "bg": (top - SPAN_DEG / 2, top + SPAN_DEG / 2),
          "fill": (top, top + SPAN_DEG / 2 * state.torque), "at": at}


def paint(state: ArcState, rect) -> None:
  import numpy as np
  import pyray as rl
  from openpilot.selfdrive.ui.mici.onroad.torque_bar import arc_bar_pts
  from openpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient

  g = geometry(state, rect)
  s, at, cx, cy = g["s"], g["at"], g["cx"], g["cy"]
  alpha = max(state.alpha, 0.05)
  base = PURPLE if state.experimental else WHITE
  cap = 7 * SCALE * s
  off = np.array([cx, cy], dtype=np.float32)

  def col(c, a):
    return rl.Color(int(c[0]), int(c[1]), int(c[2]), int(255 * clamp(a, 0.0, 1.0)))

  a0, a1 = g["bg"]
  # soft dark halo (daily: stacked round-joined strokes); approximated with widened, faint dark arcs
  for w in (28, 20, 12, 4):
    ws = w * s
    da = math.degrees(ws / 2 / g["mid_r"])
    draw_polygon(rect, arc_bar_pts(g["mid_r"], g["thickness"] + ws, a0 - da, a1 + da, cap_radius=cap + ws / 2) + off,
                 color=rl.Color(0, 0, 0, int(14 * alpha)))
  bg_alpha = interp(at, 0.5, 1.0, 0.25, 0.5) * alpha
  if not state.engaged_colors and not state.human:
    bg_alpha = 0.15 * alpha
  if state.human and state.alpha < 0.9:
    bg_alpha = 0.15 + 0.1 * max(0.0, at - 0.5) * 2.0
  bg = arc_bar_pts(g["mid_r"], g["thickness"], a0, a1, cap_radius=cap) + off
  draw_polygon(rect, bg, color=col(WHITE, bg_alpha))

  if at > 0.005:
    f0, f1 = g["fill"]
    fill = arc_bar_pts(g["mid_r"], g["thickness"], f0, f1, cap_radius=cap) + off
    if state.human:
      c0 = c1 = col(human_angle_color(state.angle), 0.95)
    elif not state.engaged_colors:
      c0 = c1 = col(WHITE, 0.35 * alpha)
    else:
      k = max(0.0, at - 0.75) * 4.0
      c0 = col(_blend(base + (0.9 * alpha,), (PURPLE if state.experimental else YELLOW) + (alpha,), k)[:3],
               _blend(base + (0.9 * alpha,), (PURPLE if state.experimental else YELLOW) + (alpha,), k)[3])
      c1 = col(_blend(base + (0.9 * alpha,), ORANGE + (alpha,), k)[:3], _blend(base + (0.9 * alpha,), ORANGE + (alpha,), k)[3])
    edge = float(bg[:, 0].min() if state.torque < 0 else bg[:, 0].max())
    start = (cx - rect.x) / rect.width
    end = ((cx + (edge - cx) * 0.65) - rect.x) / rect.width
    draw_polygon(rect, fill, gradient=Gradient(start=(start, 0), end=(end, 0), colors=[c0, c1], stops=[0.0, 1.0]))

  if state.show_tick:
    a = math.radians(-90.0 + SPAN_DEG / 2 * clamp(state.op_target, -1.0, 1.0))
    r0, r1 = g["radius"] - 11 * s, g["radius"] + g["thickness"] + 11 * s
    p0 = rl.Vector2(cx + math.cos(a) * r0, cy + math.sin(a) * r0)
    p1 = rl.Vector2(cx + math.cos(a) * r1, cy + math.sin(a) * r1)
    rl.draw_line_ex(p0, p1, 10 * s, rl.Color(0, 0, 0, 110))
    rl.draw_line_ex(p0, p1, 6 * s, rl.Color(255, 255, 255, 245))

  if at < 0.5:
    dot_y = cy - g["radius"] - g["thickness"] / 2
    rl.draw_circle_v(rl.Vector2(cx, dot_y), 5 * SCALE * s, col(DOT_GREY, 0.9 * alpha))
