"""Release-tizi redesign adapter, retaining the upstream HUD state and controls.

Layout stream owns SpeedRowInputs/paint_speed_row and draw_cluster below. There
are deliberately no uploads, streaming, custom planner or unknown Params deps.
"""
import pyray as rl
from openpilot.selfdrive.ui.onroad.hud_renderer import HudRenderer, COLORS
from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer as MiciHudRenderer
from openpilot.selfdrive.ui.onroad.bogpilot import redesign as R
from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import toggles
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus


def speed_row_inputs(hud, mici=False):
  # C3X upstream converts set speed to display units; mici keeps it in km/h.
  speed = hud.set_speed * (0.621371 if mici and not ui_state.is_metric else 1.0)
  color = COLORS.ENGAGED if ui_state.status == UIStatus.ENGAGED else COLORS.DISENGAGED
  return R.SpeedRowInputs(set_speed=str(round(speed)) if hud.is_cruise_set else "–",
                          speed=str(round(hud.speed)), unit="km/h" if ui_state.is_metric else "mph",
                          max_color=color, swap=toggles.get("SwapSpeedGraph"))


def draw_cluster(hud, rect, mici=False):
  # Design coordinates are 2160x1080. Fit both hardware viewports without
  # changing camera transforms or touching the system UI's font scaling.
  scale = min(1.0, rect.width / 2160.0, rect.height / 1080.0)
  rl.rl_push_matrix()
  rl.rl_translatef(rect.x, rect.y, 0)
  rl.rl_scalef(scale, scale, 1)
  try:
    R.paint_speed_row(speed_row_inputs(hud, mici), 0, 0)
  finally:
    rl.rl_pop_matrix()


class BogPilotHudRenderer(HudRenderer):
  def _draw_set_speed(self, rect):
    if not toggles.get("RedesignUI"):
      super()._draw_set_speed(rect)

  def _draw_current_speed(self, rect):
    if not toggles.get("RedesignUI"):
      return super()._draw_current_speed(rect)
    draw_cluster(self, rect)


class BogPilotMiciHudRenderer(MiciHudRenderer):
  def _draw_set_speed(self, rect):
    if not toggles.get("RedesignUI"):
      super()._draw_set_speed(rect)

  def _render(self, rect):
    # Preserve torque bar, model-source warnings, steer-required icon and turn
    # intent. Do not paint the redesign over the stock alert's reserved space.
    super()._render(rect)
    if toggles.get("RedesignUI") and self._can_draw_top_icons:
      draw_cluster(self, rect, mici=True)
