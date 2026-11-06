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
from openpilot.selfdrive.ui.onroad.bogpilot.bsm_state import adjacent_leads
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.shader_polygon import draw_polygon


class BlindspotOverlay:
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._flames = FlameTracks()

  def _overlay_offset(self):
    return np.zeros(2, dtype=np.float32)

  def _draw_lane_lines(self):
    super()._draw_lane_lines()
    sm = ui_state.sm
    empty = np.empty((0, 2), dtype=np.float32)
    lanes, shown = [empty, empty], [False, False]
    # Do not paint from the previous drive's car state.
    fresh = (sm.valid["carState"] and sm.alive["carState"] and
             sm.recv_frame["carState"] > ui_state.started_frame and
             all(sm.valid[name] and sm.alive[name] and sm.recv_frame[name] > ui_state.started_frame
                 for name in ("modelV2", "extrinsicsCalibration")))
    if fresh and toggles.get("BlindSpotPath"):
      cs = sm["carState"]
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
        if (cs.leftBlindspot, cs.rightBlindspot)[side]:
          draw_polygon(self._rect, poly, rl.Color(255, 0, 0, 110))
          shown[side] = True
    adj = adjacent_leads(sm, ui_state.started_frame) if fresh else [(False, 0.0)] * 2
    inputs = [FlameSideInput(shown[i], adj[i][0], adj[i][1]) for i in range(2)]
    if not fresh:
      # Reset animation state across dropped car state / drive transitions.
      self._flames.trigger.update(0, False, inputs)
    self._flames.update_and_paint(inputs, lanes)


class BogPilotModelRenderer(BlindspotOverlay, ModelRenderer):
  pass


class BogPilotMiciModelRenderer(BlindspotOverlay, MiciModelRenderer):
  def _overlay_offset(self):
    return np.array([self._rect.x, self._rect.y], dtype=np.float32)
