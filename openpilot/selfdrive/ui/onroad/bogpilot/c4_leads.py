"""comma 4 lead boxes: the shared lock-on core (lead_lockon.LeadLockOn: validated radar leadOne and
bogpilotRadarState.leadLeft / leadRight, stock calibrated projection, fail closed) with the box scaled to the comma 4,
plus the speed labels (absolute lead speed, no distance). The show / hide gate is the core's (engaged or not,
no alert term; HideLeadMarker, AdjacentLeadsUI and openpilot longitudinal from the caller); the comma 4 layout only
adds its placement and keepouts."""
from __future__ import annotations

from dataclasses import dataclass

from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot import lead_labels as LL
from openpilot.selfdrive.ui.onroad.bogpilot.lead_lockon import LeadLockOn

ADJ_SPEED_MIN = 5          # redesign.ADJ_SPEED_MIN: adjacent speeds below this show the box only


class Comma4LeadStyle:
  """The lock-on core's style hook: comma 4 box geometry; colours and rects from the wide layout."""
  ADJ_SPEED_MIN = ADJ_SPEED_MIN

  def __init__(self):
    self.gauge = None        # gauge rect while it is on screen (boxes keep clear of it)

  @staticmethod
  def rect(x, y, w, h):
    from openpilot.selfdrive.ui.onroad.bogpilot.style import rect
    return rect(x, y, w, h)

  def lead_lock_box(self, cx, cy, d_rel, max_x, max_y, min_x=0.0):
    x0, y0, x1, y1 = C4.lead_box(cx, cy, d_rel, max_x, max_y, min_x, self.gauge)
    return self.rect(x0, y0, x1 - x0, y1 - y0)

  @staticmethod
  def lead_distance_color(d_rel, adjacent, v_ego):
    from openpilot.selfdrive.ui.onroad.bogpilot.redesign import lead_distance_color
    return lead_distance_color(d_rel, adjacent, v_ego)


@dataclass(frozen=True)
class LeadDraw:
  key: str                 # "left", "right" (adjacent) or "primary"
  box: tuple               # (x0, y0, x1, y1) screen px
  d_rel: float
  speed: str               # display text ("" = box only)
  accent: str | None       # primary only: "red" closing fast, "amber" closing


class Comma4Leads:
  def __init__(self, lock=None):
    self.style = Comma4LeadStyle()
    self.lock = lock if lock is not None else LeadLockOn(style=self.style)

  def update(self, model_renderer, sm, started_frame, *, longitudinal, adjacent, hide_marker, metric, gauge):
    """Leads to draw this frame, adjacent left / right first, then the primary. enabled=True: the comma 4 layout is
    always the BogPilot layout (no RedesignUI switch on this device); engagement is left to the core."""
    self.style.gauge = gauge
    target = self.lock.update(model_renderer, sm, started_frame, enabled=True, longitudinal=longitudinal, local=True,
                              hide_marker=hide_marker, adjacent=adjacent, metric=metric)
    out = []
    for a in self.lock.adjacent:
      b = a.box
      out.append(LeadDraw("left" if a.side == 0 else "right", (b.x, b.y, b.x + b.width, b.y + b.height), a.d_rel,
                          a.speed, None))
    if target is not None:
      lbl = LL.lead_labels(sm["radarState"].leadOne, metric)
      b = target.box
      out.append(LeadDraw("primary", (b.x, b.y, b.x + b.width, b.y + b.height), target.d_rel,
                          lbl.speed if lbl is not None else "", lbl.accent if lbl is not None else None))
    return out, (target.v_ego if target is not None else float(sm["carState"].vEgo))
