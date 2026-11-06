"""Release-tizi redesign adapter, retaining the upstream HUD state and controls.

Stream 8 owns the cluster composition below: speed capsule, accel graph (SwapSpeedGraph order), HideAccelGraph
(graph hidden, capsule kept in the lower slot) and the CSC MAX slot from a validated planner report only. There are
deliberately no uploads, streaming, custom planner imports or unknown Params deps.
"""
import time
import pyray as rl
from openpilot.cereal import messaging
from openpilot.cereal.services import SERVICE_LIST
from openpilot.selfdrive.ui.onroad.hud_renderer import HudRenderer, COLORS
from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer as MiciHudRenderer
from openpilot.selfdrive.ui.onroad.bogpilot import redesign as R
from openpilot.selfdrive.ui.onroad.bogpilot import cluster_layout as L
from openpilot.selfdrive.ui.onroad.bogpilot.accel_graph import AccelGraph
from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import toggles
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus

GRAPH_HZ = 20          # AccelGraph(hz=20, seconds=10): one sample per 50 ms regardless of the UI frame rate
MS_TO_KPH, MS_TO_MPH = 3.6, 2.23694


def cluster_layout():
  return L.layout_from_toggles(toggles.get)


def display_set_speed(hud, mici=False):
  # C3X upstream converts set speed to display units; mici keeps it in km/h.
  return hud.set_speed * (0.621371 if mici and not ui_state.is_metric else 1.0)


def csc_slot(hud, mici=False):
  ctx = L.CscContext(redesign=True, cruise_set=bool(hud.is_cruise_set), set_speed_display=display_set_speed(hud, mici),
                     display_conv=MS_TO_KPH if ui_state.is_metric else MS_TO_MPH, t=time.monotonic())
  return L.csc_slot(getattr(hud, "bp_csc", L.INVALID_CSC), ctx)


def speed_row_inputs(hud, mici=False, layout=None, slot=None):
  layout = layout if layout is not None else cluster_layout()
  speed = display_set_speed(hud, mici)
  color = COLORS.ENGAGED if ui_state.status == UIStatus.ENGAGED else COLORS.DISENGAGED
  kw = dict(set_speed=str(round(speed)) if hud.is_cruise_set else "–",
            speed=str(round(hud.speed)), unit="km/h" if ui_state.is_metric else "mph",
            max_color=color, swap=layout.redesign_swap)
  if slot is not None:
    kw.update(L.csc_fields(slot))
  return R.SpeedRowInputs(**kw)


def draw_cluster(hud, rect, mici=False):
  # Design coordinates are 2160x1080. Fit both hardware viewports without
  # changing camera transforms or touching the system UI's font scaling.
  layout = cluster_layout()
  scale = min(1.0, rect.width / 2160.0, rect.height / 1080.0)
  rl.rl_push_matrix()
  rl.rl_translatef(rect.x, rect.y, 0)
  rl.rl_scalef(scale, scale, 1)
  try:
    R.paint_speed_row(speed_row_inputs(hud, mici, layout, csc_slot(hud, mici)), 0, 0)
    graph = getattr(hud, "bp_graph", None)
    if graph is not None and layout.graph_visible:
      # HideAccelGraph: graph skipped, capsule already moved to the lower slot via layout.redesign_swap.
      graph.paint(R.accel_graph_rect(layout.swap))
  finally:
    rl.rl_pop_matrix()


class ClusterState:
  """Accel graph samples and the validated CSC report, shared by the C3X and C4 renderers."""

  def _bp_init(self):
    self.bp_graph = AccelGraph(hz=GRAPH_HZ)
    self.bp_csc = L.INVALID_CSC
    self._bp_graph_t = -1.0
    self._bp_started = None
    self._bp_drive_start = 0.0
    # Stream-6 optional contract: subscribe only when the service exists (never on stock release-tizi).
    self._bp_plan_sm = messaging.SubMaster(["frogpilotPlan"]) if "frogpilotPlan" in SERVICE_LIST else None

  def _bp_update(self):
    sm = ui_state.sm
    now = time.monotonic()
    if self._bp_started != ui_state.started_frame:
      self._bp_started = ui_state.started_frame
      self._bp_drive_start = now
      self.bp_graph.clear()
      self.bp_csc = L.INVALID_CSC
    fresh = sm.recv_frame["carState"] >= ui_state.started_frame and sm.alive["carState"] and sm.valid["carState"]
    if not fresh:
      self.bp_graph.clear()
      self.bp_csc = L.INVALID_CSC
      return
    if now - self._bp_graph_t >= 1.0 / GRAPH_HZ and sm.alive["carControl"] and sm.valid["carControl"]:
      self._bp_graph_t = now
      self.bp_graph.push(float(sm["carControl"].actuators.accel), float(sm["carState"].aEgo))
    if self._bp_plan_sm is not None:
      self._bp_plan_sm.update(0)
      self.bp_csc = L.read_csc_status(self._bp_plan_sm, now, self._bp_drive_start)


class BogPilotHudRenderer(ClusterState, HudRenderer):
  def __init__(self):
    super().__init__()
    self._bp_init()

  def _update_state(self):
    super()._update_state()
    self._bp_update()

  def _draw_set_speed(self, rect):
    if not toggles.get("RedesignUI"):
      super()._draw_set_speed(rect)

  def _draw_current_speed(self, rect):
    if not toggles.get("RedesignUI"):
      return super()._draw_current_speed(rect)
    draw_cluster(self, rect)


class BogPilotMiciHudRenderer(ClusterState, MiciHudRenderer):
  def __init__(self):
    super().__init__()
    self._bp_init()

  def _update_state(self):
    super()._update_state()
    self._bp_update()

  def _draw_set_speed(self, rect):
    if not toggles.get("RedesignUI"):
      super()._draw_set_speed(rect)

  def _render(self, rect):
    # Preserve torque bar, model-source warnings, steer-required icon and turn
    # intent. Do not paint the redesign over the stock alert's reserved space.
    super()._render(rect)
    if toggles.get("RedesignUI") and self._can_draw_top_icons:
      draw_cluster(self, rect, mici=True)
