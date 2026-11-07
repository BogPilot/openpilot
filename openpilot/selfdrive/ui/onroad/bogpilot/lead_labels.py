"""BogPilot runtime lead/personality adapters. Display only; no Params writes.

Source behavior: BogPilot annotated_camera.cc / frogpilot_buttons.cc. Absolute
vLead, NOT ego speed or experimental speed predictions. Geometry is in painter
coordinates (screen pixels); design constants are used only by personality.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

STALE_S = 0.5


def fresh(sm, topic, now, drive_start, started_frame):
  try:
    t = sm.recv_time[topic]
    return (sm.alive[topic] and sm.valid[topic] and math.isfinite(t)
            and drive_start <= t <= now and now - t <= STALE_S
            and sm.recv_frame[topic] > started_frame)
  except (AttributeError, KeyError, TypeError, ValueError):
    return False


def qround(value):
  """Qt qRound for nonnegative display quantities (Python round is ties-even)."""
  return int(math.floor(value + 0.5))


@dataclass(frozen=True)
class LabelData:
  speed: str
  dist: str
  dist_unit: str
  vision_only: bool
  accent: str | None = None


def lead_labels(lead, metric=True, adjacent=False):
  """Validated radarState.LeadData. Zero speed is valid; zero distance is not."""
  try:
    if not lead.present:
      return None
    d, v, vr = float(lead.dRel), float(lead.vLead), float(lead.vRel)
    if not all(math.isfinite(x) for x in (d, v, vr)) or d <= 0:
      return None
    n = qround(max(0.0, v) * (3.6 if metric else 2.2369362920544))
    vision = not bool(lead.radar)
    if adjacent:
      return LabelData(str(n), "", "", vision) if n >= 5 else None
    return LabelData(("~" if vision else "") + str(n),
                     str(qround(d * (1.0 if metric else 3.280839895))),
                     "m" if metric else "ft", vision,
                     "red" if vr < -4.4704 else "amber" if vr < 0 else None)
  except (AttributeError, TypeError, ValueError, OverflowError):
    return None


def read_lead_labels(sm, now, drive_start, started_frame, metric=True, index=0):
  if index not in (0, 1) or not fresh(sm, "radarState", now, drive_start, started_frame):
    return None
  try:
    return lead_labels(getattr(sm["radarState"], ("leadOne", "leadTwo")[index]), metric)
  except (AttributeError, KeyError):
    return None


@dataclass(frozen=True)
class PersonalityData:
  personality: int
  traffic_mode: bool
  label: str


def personality_data(value, traffic_mode):
  # cereal LongitudinalPersonality: aggressive=0, standard=1, relaxed=2.
  # Never use the daily UI's one-based icon index as the runtime value.
  # pycapnp DynamicEnum compares equal to integers but does NOT support int().
  # Its raw property is the schema ordinal; unknown ordinals still fail closed.
  try:
    value = getattr(value, "raw", value)
  except (AttributeError, TypeError, ValueError, RuntimeError):
    return None
  if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1, 2) or not isinstance(traffic_mode, bool):
    return None
  return PersonalityData(int(value), traffic_mode,
                         "Traffic" if traffic_mode else ("Aggressive", "Standard", "Relaxed")[int(value)])


def read_personality(sm, now, drive_start, started_frame, traffic_mode):
  if not fresh(sm, "selfdriveState", now, drive_start, started_frame):
    return None
  try:
    return personality_data(sm["selfdriveState"].personality, traffic_mode)
  except (AttributeError, KeyError):
    return None


def _tuple(r):
  return tuple(r) if isinstance(r, (tuple, list)) else (r.x, r.y, r.width, r.height)


def clear(r, view, keepouts=(), margin=8):
  """Fail closed, including invalid geometry. Touching is allowed at margin."""
  try:
    x, y, w, h = _tuple(r)
    vx, vy, vw, vh = _tuple(view)
    if not all(math.isfinite(a) for a in (x,y,w,h,vx,vy,vw,vh)) or min(w,h,vw,vh) <= 0:
      return False
    if x < vx + margin or y < vy + margin or x+w > vx+vw-margin or y+h > vy+vh-margin:
      return False
    for k in keepouts:
      kx, ky, kw, kh = _tuple(k)
      if not all(math.isfinite(a) for a in (kx,ky,kw,kh)) or kw < 0 or kh < 0:
        return False
      if x < kx+kw+margin and x+w > kx-margin and y < ky+kh+margin and y+h > ky-margin:
        return False
    return True
  except (TypeError, ValueError, AttributeError):
    return False


def distance_tag(box, width, view, keepouts=()):
  """Existing below/above preference; suppress instead of painting over safety HUD."""
  x,y,w,h = _tuple(box)
  vx,vy,vw,vh = _tuple(view)
  if not math.isfinite(width) or width <= 0 or width > vw-16:
    return None
  cx = min(max(x+w/2, vx+8+width/2), vx+vw-8-width/2)
  for ty in (y+h+22, y-22-46):
    candidate = (cx-width/2, ty, width, 46)
    if clear(candidate, view, (*keepouts, box)):
      return candidate
  return None


def paint_labels(box, data, view, keepouts=()):
  """Connect existing painters; caller supplies w1's CURRENT box, never stale anchors.

  Units/box/view/keepouts are all screen pixels, so C4/resize never rescales a
  screen anchor twice. Compact composition remains disabled (stock fallback).
  """
  from openpilot.selfdrive.ui.onroad.bogpilot import redesign as r
  from openpilot.selfdrive.ui.onroad.bogpilot.style import C, W, text_width
  if data is None:
    return
  accent = C(255,0,0) if data.accent == "red" else C(255,188,0) if data.accent == "amber" else None
  speed_rect, _ = r._in_box_pill(box, data.speed)
  if speed_rect is not None and clear(speed_rect, view, keepouts):
    r.paint_lead_speed_in_box(box, data.speed, data.vision_only, accent)
  if data.dist:
    width = text_width(data.dist,30,W.BOLD) + text_width(" "+data.dist_unit,22,W.DEMI) + 36
    tag = distance_tag(box, width, view, keepouts)
    if tag is not None:
      x,y,w,h = tag
      r._label_pill(x+w/2,y+h/2,h,18,data.dist,30,C(255,255,255),data.dist_unit,22,view)


class LabelLayer:
  name = "lead_labels"
  replaces = frozenset()
  supports_compact = False

  def __init__(self):
    self.reset()

  def reset(self):
    self.lead = None
    self.personality = None

  def enabled(self, frame):
    return bool(frame.redesign and not frame.mici and not frame.full_alert)

  def update(self, frame):
    # Stateless replacement every frame: no stale labels survive a disabled gate.
    self.reset()
    if not self.enabled(frame):
      return
    sm = getattr(frame, "sm", None)
    now = getattr(frame, "now", math.nan)
    start = getattr(frame, "drive_start", math.inf)
    if getattr(frame, "lead_info", False):
      self.lead = read_lead_labels(sm, now, start, frame.started_frame, frame.is_metric)
    if frame.longitudinal and getattr(frame, "onroad_distance_button", False):
      self.personality = read_personality(sm, now, start, frame.started_frame,
                                          getattr(frame, "traffic_mode", None))

  def draw(self, frame):
    from openpilot.selfdrive.ui.onroad.bogpilot import redesign as r
    # Dedicated keepouts exclude the personality's OWN reservation; callers must
    # include DM/alert plus the actual cluster graph/capsule and other controls.
    keepouts = getattr(frame, "label_keepouts", frame.keepouts)
    box = getattr(frame, "lead_label_box", None)
    if box is not None and self.lead is not None:
      paint_labels(box, self.lead, frame.rect, keepouts)
    pill = getattr(frame, "personality_rect", None)
    if pill is not None and self.personality is not None:
      # Include label band, not just the 150px circle.
      x,y,w,h = _tuple(pill)
      if clear((x,y-40,w,h+40), frame.rect, keepouts):
        p = self.personality
        r.paint_personality(pill,p.personality,p.traffic_mode,p.label)


def make_layer(mici=False):
  return None if mici else LabelLayer()
