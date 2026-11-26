"""Non-invasive BSM overlays for both release raylib model renderers.

Projection and all stock paths/leads remain upstream-owned. Flame geometry and
edge-trigger logic are reused from the 19.9 port at 23f47f903.
"""
import numpy as np
import pyray as rl
from openpilot.selfdrive.ui.onroad.model_renderer import ModelRenderer
from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer as MiciModelRenderer
from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import toggles
from openpilot.selfdrive.ui.onroad.bogpilot.flame_tracks import FlameTracks, FlameSideInput
import time
from openpilot.selfdrive.ui.onroad.bogpilot.bsm_state import adjacent_leads, blindspots, BsmPolicy
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.onroad.bogpilot.style import TRAFFIC_PATH_GRADIENT
from openpilot.system.ui.lib.shader_polygon import draw_polygon


class BlindspotOverlay:
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._flames = FlameTracks()
    self._bsm_policy = BsmPolicy()
    self.bp_bsm_shown = (False, False)   # sides whose red lane fill was painted this frame (tests / evidence)
    # Stock lead chevrons (leadOne and leadTwo) are never painted. The lock-on box is the
    # lead indicator when the redesign is on; otherwise there is no stock triangle.
    # bp_defer_primary_lead and bp_flush_primary_lead stay as a no-op API so older callers
    # cannot paint a deferred chevron.
    self.bp_defer_primary_lead = False
    self.bp_pending_primary = None

  def _draw_lead_indicator(self):
    self.bp_pending_primary = None
    return

  def bp_flush_primary_lead(self):
    self.bp_pending_primary = None

  def _overlay_offset(self):
    return np.zeros(2, dtype=np.float32)

  def _draw_lane_lines(self):
    super()._draw_lane_lines()
    sm = ui_state.sm
    empty = np.empty((0, 2), dtype=np.float32)
    lanes, shown = [empty, empty], [False, False]
    now = time.monotonic()
    # Do not paint from the previous drive's or a stale car state.
    fresh = (sm.valid["carState"] and sm.alive["carState"] and
             sm.recv_frame["carState"] > ui_state.started_frame and
             all(sm.valid[name] and sm.alive[name] and sm.recv_frame[name] > ui_state.started_frame
                 for name in ("modelV2", "extrinsicsCalibration")))
    flags = blindspots(sm, ui_state.started_frame, now) if fresh else (False, False)
    if fresh and self._bsm_policy.enabled(bool(toggles.get("BlindSpotPath")), getattr(ui_state, "CP", None)):
      # _map_line_to_polygon is not free; skip it unless a red fill is up, a flame
      # is already burning, or the post-fill arm window is open (so a trigger this
      # frame still has lane geometry to paint).
      trig = self._flames.trigger
      need_lanes = any(flags) or any(s.start_ms >= 0 or s.arm_until_ms >= 0 for s in getattr(trig, "side", ()))
      if need_lanes:
        for side, (outer, inner) in enumerate(((0, 1), (3, 2))):
          a, b = self._lane_lines[outer].raw_points, self._lane_lines[inner].raw_points
          n = min(len(a), len(b))
          if n < 2:
            continue
          width = float(np.median(np.abs(a[:n, 1] - b[:n, 1])))
          if not np.isfinite(width) or not 1.0 < width < 6.0:
            continue
          centre = (a[:n] + b[:n]) / 2.0
          distance = min(100.0, float(centre[-1, 0]))
          idx = self._get_path_length_idx(centre[:, 0], distance)
          poly = self._map_line_to_polygon(centre, width / 2, 0.0, idx, distance)
          if not poly.size or not np.isfinite(poly).all():
            continue
          # Mici stores camera projection in rect-local coordinates; tizi uses
          # screen coordinates. Convert exactly once before BSM or flame paint.
          poly = poly + self._overlay_offset()
          lanes[side] = poly
          if flags[side]:
            bottom = self._rect.y + self._rect.height
            draw_polygon(self._rect, extend_to_bottom(poly, bottom), rl.Color(255, 0, 0, 110))
            shown[side] = True
    self.bp_bsm_shown = (shown[0], shown[1])
    adj = adjacent_leads(sm, ui_state.started_frame, now) if fresh else [(False, 0.0)] * 2
    inputs = [FlameSideInput(shown[i], adj[i][0], adj[i][1]) for i in range(2)]
    # Flame tracks start at the passing car: hand over each side's adjacent lead screen point (None = not cleanly
    # projectable, which makes the flames fall back to the base tracks) and the road view.
    self._flames.targets = self._bp_adjacent_points(sm, adj) if fresh else [None, None]
    r = getattr(self, "_rect", None)
    self._flames.view = None if r is None else (float(r.x), float(r.y), float(r.width), float(r.height))
    if not fresh:
      # Reset animation state across dropped car state / drive transitions.
      self._flames.trigger.update(0, False, inputs)
    self._flames.update_and_paint(inputs, lanes)

  def _bp_adjacent_points(self, sm, adj):
    """(x, y) screen point of each fresh adjacent lead at (dRel, -yRel, path road height), else None. Fails closed.

    Same calibrated projection and checks as LeadLockOn._project_box (lead_lockon.py): only leads that adjacent_leads()
    reports fresh, inside the model path's observed range and in front of the camera."""
    out = [None, None]
    try:
      points = self._path.raw_points
      if len(points) < 2:
        return out
      xs = [float(p[0]) for p in points]
      radar = sm["bogpilotRadarState"]
      for side, lead in enumerate((radar.leadLeft, radar.leadRight)):
        if not adj[side][0]:
          continue
        d, y = float(lead.dRel), float(lead.yRel)
        if not (np.isfinite(d) and np.isfinite(y)) or d <= 0 or not xs[0] <= d <= xs[-1]:
          continue
        idx = max(i for i, x in enumerate(xs) if x <= d)
        z = float(points[idx][2]) + float(self._path_offset_z)
        transform = self._car_space_transform
        depth = sum(float(transform[2][i]) * value for i, value in enumerate((d, -y, z)))
        if not np.isfinite(depth) or depth <= 1e-6:
          continue
        p = self._map_to_screen(d, -y, z)
        if p is None or not all(np.isfinite(float(c)) for c in p):
          continue
        out[side] = np.asarray(p, dtype=np.float32)[:2] + self._overlay_offset()
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OverflowError):
      return [None, None]
    return out


def extend_to_bottom(poly, bottom):
  """Continue the BSM lane fill down to the screen bottom (behind the DM / personality button).

  Stock _map_line_to_polygon drops every point outside the clip region, so the projected lane stops where its
  nearest visible model point is. The road plane is flat near the car, so each lane edge is continued along its
  own nearest projected direction until it meets y = bottom. poly = left edge near->far, then right edge far->near."""
  n = len(poly) // 2
  if n < 2 or len(poly) != 2 * n:
    return poly
  left, right = poly[:n], poly[n:][::-1]
  def ext(edge):
    k = min(3, len(edge) - 1)
    d = edge[0] - edge[k]
    if edge[0, 1] >= bottom or d[1] <= 1e-3:
      return edge[:0]
    t = (bottom - edge[0, 1]) / d[1]
    return (edge[0] + t * d)[None, :].astype(poly.dtype)
  el, er = ext(left), ext(right)
  return np.concatenate((el, left, right[::-1], er), axis=0)


class BogPilotModelRenderer(BlindspotOverlay, ModelRenderer):
  bp_traffic_red = False   # set by HudComposer each frame (engaged, longitudinal, Traffic Mode on)

  def _draw_path(self, sm):
    # 0.9.7 setPathEdgeColors: the path takes the status colour, TRAFFIC_RED in Traffic Mode while engaged.
    # Experimental mode keeps its acceleration gradient. Same polygon, only the constant gradient differs.
    if not self.bp_traffic_red or self._experimental_mode or not self._path.projected_points.size:
      return super()._draw_path(sm)
    self._blend_filter.update(int(sm['longitudinalPlan'].allowThrottle or not self._longitudinal_control))
    draw_polygon(self._rect, self._path.projected_points, gradient=TRAFFIC_PATH_GRADIENT)


class BogPilotMiciModelRenderer(BlindspotOverlay, MiciModelRenderer):
  def _overlay_offset(self):
    return np.array([self._rect.x, self._rect.y], dtype=np.float32)
