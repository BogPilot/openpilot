"""Camera-layer adapter for the ported BogPilot lock painter; never a lead source.

Caller owns composition: update after current camera transforms, paint before HUD
and safety alerts. No smoothing: a lost/switched lead cannot retain old geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class LockTarget:
  box: object
  view: object
  d_rel: float
  v_rel: float
  v_ego: float
  drive: int
  expires: float


def _finite(*values):
  return all(math.isfinite(float(v)) for v in values)


def _bounds(r):
  return r.x, r.y, r.x + r.width, r.y + r.height


def _inside(box, view, margin=0):
  x, y, right, bottom = _bounds(box)
  l, t, r, b = _bounds(view)
  return (_finite(x, y, right, bottom, l, t, r, b) and box.width > 0 and box.height > 0
          and l + margin <= x and t + margin <= y and right <= r - margin and bottom <= b - margin)


def _overlaps(a, b):
  l, t, r, bottom = _bounds(a)
  x, y, right, bot = _bounds(b)
  return l < right and x < r and t < bot and y < bottom


class LeadLockOn:
  """Only latest validated radar leadOne; fail closed on missing data or geometry.

  ``local`` distinguishes mici's camera-local projection from tizi's screen
  projection. No default dimensions or guessed camera coordinates are used.
  ``style`` exists for headless tests; production uses the already ported painter.
  """
  def __init__(self, clock=time.monotonic, style=None):
    self.clock = clock
    self._style = style
    self.target = None

  @property
  def style(self):
    if self._style is None:
      from openpilot.selfdrive.ui.onroad.bogpilot import redesign
      self._style = redesign
    return self._style

  def update(self, renderer, sm, started_frame, *, enabled, engaged, longitudinal, local=False, hide_marker=False):
    self.target = None
    if hide_marker or not (enabled and engaged and longitudinal):
      return None
    try:
      now = self.clock()
      # Calibration is a low-rate service; model/radar/carState must be recent.
      for service, max_age in (("radarState", 0.5), ("modelV2", 0.5),
                               ("carState", 0.5), ("selfdriveState", 0.5), ("extrinsicsCalibration", 5.0)):
        age = now - sm.recv_time[service]
        if not (sm.valid[service] and sm.alive[service] and sm.recv_frame[service] > started_frame
                and math.isfinite(age) and 0 <= age <= max_age):
          return None
      lead = sm["radarState"].leadOne
      d, y, v, ego = float(lead.dRel), float(lead.yRel), float(lead.vRel), float(sm["carState"].vEgo)
      if not lead.present or not _finite(d, y, v, ego) or d <= 0 or ego < 0:
        return None
      points = renderer._path.raw_points
      if len(points) < 2:
        return None
      # Match upstream lead projection's road height, without a fabricated z=0
      # fallback or extrapolation beyond this model's observed road shape.
      xs = [float(p[0]) for p in points]
      if not _finite(*xs) or any(a >= b for a, b in zip(xs, xs[1:])) or not xs[0] <= d <= xs[-1]:
        return None
      idx = max(i for i, x in enumerate(xs) if x <= d)
      z = float(points[idx][2]) + float(renderer._path_offset_z)
      if not _finite(z):
        return None
      # Stock _map_to_screen accepts negative homogeneous depth. Reject points
      # behind the camera here, before calling its actual calibrated projection.
      transform = renderer._car_space_transform
      depth = sum(float(transform[2][i]) * value for i, value in enumerate((d, -y, z)))
      if not math.isfinite(depth) or depth <= 1e-6:
        return None
      point = renderer._map_to_screen(d, -y, z)
      if point is None or not _finite(*point):
        return None
      view = renderer._rect
      if not _finite(view.x, view.y, view.width, view.height) or min(view.width, view.height) <= 0:
        return None
      cx, cy = point
      if local:
        cx, cy = cx + view.x, cy + view.y
      if not (view.x <= cx <= view.x + view.width and view.y <= cy <= view.y + view.height):
        return None
      box = self.style.lead_lock_box(cx, cy, d, view.x + view.width, view.y + view.height, view.x)
      # Painter's outline/glow extends past its nominal box; never clamp a lead
      # from outside the view onto a visible edge. Reserve its full footprint.
      if not _inside(box, view, 24):
        return None
      self.target = LockTarget(box, self.style.rect(view.x, view.y, view.width, view.height), d, v, ego, started_frame, now + 0.5)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OverflowError):
      return None
    return self.target

  def paint(self, renderer, target, *, keepouts=()):
    """Returns painted box for label adapter, or None. Never call above alerts.

    keepouts are screen-space reserved rectangles (DM/alert/HUD). Suppression,
    not movement, preserves the lock's real projected road contact location.
    """
    if (target is None or target is not self.target or self.clock() > target.expires
        or _bounds(renderer._rect) != _bounds(target.view)):
      return None
    R = self.style
    footprint = R.rect(target.box.x - 24, target.box.y - 24, target.box.width + 48, target.box.height + 48)
    if any(_overlaps(footprint, k) for k in keepouts):
      return None
    # Explicit scissor: painter restores its parent after per-corner scissors.
    import pyray as rl
    view = target.view
    rl.begin_scissor_mode(int(view.x), int(view.y), int(view.width), int(view.height))
    try:
      R.paint_lead_lock(target.box, "", R.lead_distance_color(target.d_rel, False, target.v_ego), view)
    finally:
      rl.end_scissor_mode()
    return target.box


class LeadLockOnLayer:
  """w9 composer adapter. Raw current renderer and SubMaster are required.

  enabled() validates placement before claiming the stock lead-chevron slot.
  C4 projection is supported by the core, but compact integration stays opt-in.
  """
  name = "lead_lockon"
  replaces = frozenset({"lead_chevron"})
  supports_compact = False

  def __init__(self):
    self.lock = LeadLockOn()

  def reset(self):
    self.lock.target = None

  def update(self, frame):
    self.reset()
    if getattr(frame, "full_alert", False) or getattr(frame, "mici", False):
      return
    renderer, sm = getattr(frame, "model_renderer", None), getattr(frame, "sm", None)
    if renderer is None or sm is None:
      return
    self.lock.update(renderer, sm, frame.started_frame,
                     enabled=bool(frame.redesign), engaged=bool(getattr(frame, "engaged", False)),
                     longitudinal=bool(frame.longitudinal),
                     hide_marker=bool(getattr(frame, "hide_lead_marker", True)))

  def enabled(self, frame):
    self.update(frame)
    target = self.lock.target
    if target is None:
      return False
    box = target.box
    footprint = self.lock.style.rect(box.x - 24, box.y - 24, box.width + 48, box.height + 48)
    return not any(_overlaps(footprint, k) for k in getattr(frame, "keepouts", ()))

  def draw(self, frame):
    return self.lock.paint(frame.model_renderer, self.lock.target, keepouts=getattr(frame, "keepouts", ()))


def make_layer(mici=False):
  return None if mici else LeadLockOnLayer()
