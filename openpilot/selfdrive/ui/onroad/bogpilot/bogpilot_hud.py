"""Release-tizi redesign adapter, retaining the upstream HUD state and controls.

Stream 8 owns the cluster composition below: speed capsule, accel graph (SwapSpeedGraph order), HideAccelGraph
(graph hidden, capsule kept in the lower slot) and the CSC MAX slot from a validated planner report only
(plannerd's frogpilotPlan, AP1 CSC). The slot also needs CurveSpeedController and ShowCSCStatus on. There are
deliberately no uploads, streaming, custom planner imports or unknown Params deps.
"""
import math
import time
import pyray as rl
from openpilot.cereal import messaging
from openpilot.common.swaglog import cloudlog
from openpilot.cereal.services import SERVICE_LIST
from openpilot.selfdrive.ui.onroad.hud_renderer import HudRenderer, COLORS, UI_CONFIG
from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer as MiciHudRenderer
from openpilot.selfdrive.ui.onroad.bogpilot import redesign as R
from openpilot.selfdrive.ui.onroad.bogpilot import cluster_layout as L
from openpilot.selfdrive.ui.onroad.bogpilot.accel_graph import AccelGraph
from openpilot.selfdrive.ui.onroad.bogpilot import speed_limit_display as SL
from openpilot.selfdrive.ui.onroad.bogpilot import steering_arc as ARC
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED
from openpilot.selfdrive.ui.onroad.bogpilot.style import REC_CX, REC_CY, REC_HIT
from openpilot.selfdrive.ui.onroad.exp_button import ExpButton
from openpilot.system.ui.widgets import Widget
from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import toggles
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus

WIDE_MIN_W = 1800.0    # hud_compose.WIDE_MIN_W: the arc, pedals and record button are wide-layout only
GRAPH_HZ = 20          # AccelGraph(hz=20, seconds=10): one sample per 50 ms regardless of the UI frame rate
MS_TO_KPH, MS_TO_MPH = 3.6, 2.23694


UI_CONFIG_BUTTON, UI_CONFIG_ICON = UI_CONFIG.button_size, UI_CONFIG.wheel_icon_size


def cluster_layout():
  return L.layout_from_toggles(toggles.get)


def display_set_speed(hud, mici=False):
  # C3X upstream converts set speed to display units; mici keeps it in km/h.
  return hud.set_speed * (0.621371 if mici and not ui_state.is_metric else 1.0)


class CscStatusToggle:
  """Daily csc_status: CurveSpeedController and ShowCSCStatus (367e1fe tuning-level rule), cached.

  Display only: ShowCSCStatus never changes what the planner does. Any read failure hides the slot."""

  def __init__(self, store=None, clock=time.monotonic, ttl=2.0):
    self._store = store
    self.clock = clock
    self.ttl = ttl
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
        self._value = bool(self._store.toggle_bool("CurveSpeedController") and self._store.toggle_bool("ShowCSCStatus"))
      except Exception:
        self._value = False
    return self._value


csc_status_toggle = CscStatusToggle()


def csc_slot(hud, mici=False):
  ctx = L.CscContext(redesign=True, show_status=csc_status_toggle.get(), cruise_set=bool(hud.is_cruise_set),
                     set_speed_display=display_set_speed(hud, mici),
                     display_conv=MS_TO_KPH if ui_state.is_metric else MS_TO_MPH, t=time.monotonic())
  return L.csc_slot(getattr(hud, "bp_csc", L.INVALID_CSC), ctx)


def speed_row_inputs(hud, mici=False, layout=None, slot=None):
  layout = layout if layout is not None else cluster_layout()
  speed = display_set_speed(hud, mici)
  color = COLORS.ENGAGED if ui_state.status == UIStatus.ENGAGED else COLORS.DISENGAGED
  kw = dict(set_speed=str(round(speed)) if hud.is_cruise_set else "–",
            speed=str(round(hud.speed)), unit="km/h" if ui_state.is_metric else "mph",
            max_color=color, swap=layout.redesign_swap)
  limit = getattr(hud, "bp_limit", SL.HIDDEN)
  if not mici:
    # t913u LIMIT tile / SLC offset badge and the daily set-speed colour (compact mici layout keeps the stock row)
    kw.update(limit.fields())
    rgba = SL.set_speed_rgba(bool(hud.is_cruise_set), ui_state.status == UIStatus.ENGAGED, speed, limit.color_limit)
    kw["set_speed_color"] = rl.Color(*rgba)
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
    services = [s for s in ("frogpilotPlan", "frogpilotCarState") if s in SERVICE_LIST]
    self._bp_plan_sm = messaging.SubMaster(services) if services else None
    self.bp_limit = SL.HIDDEN
    self._bp_limit_policy = SL.LimitPolicyReader(cp_fn=lambda: ui_state.CP)

  def _bp_update(self):
    sm = ui_state.sm
    now = time.monotonic()
    if self._bp_started != ui_state.started_frame:
      self._bp_started = ui_state.started_frame
      self._bp_drive_start = now
      self.bp_graph.clear()
      self.bp_csc = L.INVALID_CSC
      self.bp_limit = SL.HIDDEN
    fresh = sm.recv_frame["carState"] >= ui_state.started_frame and sm.alive["carState"] and sm.valid["carState"]
    if not fresh:
      self.bp_graph.clear()
      self.bp_csc = L.INVALID_CSC
      self.bp_limit = SL.HIDDEN
      return
    if now - self._bp_graph_t >= 1.0 / GRAPH_HZ and sm.alive["carControl"] and sm.valid["carControl"]:
      self._bp_graph_t = now
      self.bp_graph.push(float(sm["carControl"].actuators.accel), float(sm["carState"].aEgo))
    if self._bp_plan_sm is not None:
      self._bp_plan_sm.update(0)
      self.bp_csc = L.read_csc_status(self._bp_plan_sm, now, self._bp_drive_start)
    dashboard = SL.read_dashboard_limit(self._bp_plan_sm, now, self._bp_drive_start)
    self.bp_limit = SL.speed_limit_view(self._bp_limit_policy.get(), dashboard, self.bp_csc,
                                        MS_TO_KPH if ui_state.is_metric else MS_TO_MPH)


def _fresh(sm, name) -> bool:
  try:
    return bool(sm.recv_frame[name] >= ui_state.started_frame and sm.alive[name] and sm.valid[name])
  except (KeyError, AttributeError, TypeError):
    return False


class ArcTapButton(ExpButton):
  """Daily redesign: the steering arc (+ its surroundings) is the Experimental Mode button. Same toggle rules as the
  stock ExpButton (ExperimentalModeConfirmed and longitudinal control); paints nothing, the arc shows the state."""

  def set_rect(self, rect) -> None:
    Widget.set_rect(self, rect)

  def _render(self, rect) -> None:
    pass


class RecordButton(Widget):
  def __init__(self, recorder_fn):
    super().__init__()
    self._recorder_fn = recorder_fn

  def _handle_mouse_release(self, _):
    super()._handle_mouse_release(_)
    try:
      self._recorder_fn().toggle()
    except Exception:
      cloudlog.exception("screen recorder toggle failed")

  def _render(self, rect) -> None:
    rec = self._recorder_fn()
    pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 3.14159)
    R.paint_record_button(rect, rec.recording, pulse)


class ExtrasPolicy:
  """Cached (2 s): pedals (367e1fe :877-879) and screen_recorder (:1120). Read failures fail closed (hidden)."""

  def __init__(self, store=None, clock=time.monotonic, ttl=2.0):
    self._store, self.clock, self.ttl = store, clock, ttl
    self._next = -1.0
    self._value = (PED.CLOSED, False)

  def get(self, longitudinal: bool):
    now = self.clock()
    if now >= self._next:
      self._next = now + self.ttl
      try:
        if self._store is None:
          from openpilot.common.bogpilot_store import ParamStore
          self._store = ParamStore()
        s = self._store
        level = s.tuning_level()
        rec = bool((s.toggle_bool("ScreenManagement", level) and s.toggle_bool("ScreenRecorder", level))
                   or s.get_bool("DebugMode", False))
        self._value = (PED.policy_from_store(s, longitudinal), rec)
      except Exception:
        self._value = (PED.CLOSED, False)
    return self._value


def _recorder():
  from openpilot.selfdrive.ui.onroad.bogpilot.screen_recorder import recorder
  return recorder()


class BogPilotHudRenderer(ClusterState, HudRenderer):
  def __init__(self):
    super().__init__()
    self._bp_init()
    self.bp_arc = ARC.ArcState()
    self.bp_arc_live = False
    self.bp_arc_failed = False
    self.bp_arc_tap = None            # screen (x, y, w, h) while the arc owns the Experimental Mode tap
    self._bp_arc_t = -1.0
    self._bp_arc_btn = ArcTapButton(UI_CONFIG_BUTTON, UI_CONFIG_ICON)
    self._bp_rec_btn = RecordButton(_recorder)
    self._bp_extras = ExtrasPolicy()
    self.bp_pedals = None             # (brake_opacity, gas_opacity) daily response, or None when hidden
    self.bp_extra_keepouts: list = []  # screen rects of the arc tap area, pedals and record button (lead labels avoid)
    self.bp_rhd = False
    self._bp_started_arc = None

  def _update_state(self):
    super()._update_state()
    self._bp_update()
    self._bp_update_features()

  def _bp_update_features(self):
    sm = ui_state.sm
    now = time.monotonic()
    if self._bp_started_arc != ui_state.started_frame:
      self._bp_started_arc = ui_state.started_frame
      self.bp_arc.reset()
      self.bp_arc_failed = False
    self.bp_rhd = bool(_fresh(sm, "driverMonitoringState") and sm["driverMonitoringState"].isRHD)
    live = bool(toggles.get("RedesignUI")) and all(_fresh(sm, n) for n in ("controlsState", "carState", "carControl"))
    if not live:
      self.bp_arc_live = False
      self.bp_arc.reset()
    elif now - self._bp_arc_t >= 1.0 / ARC.UPDATE_HZ:
      self._bp_arc_t = now
      try:
        vp = sm["vehicleParameters"] if _fresh(sm, "vehicleParameters") else None
        co = sm["carOutput"] if _fresh(sm, "carOutput") else None
        cp = ui_state.CP
        max_lat = float(cp.maxLateralAccel) if cp is not None else ARC.DEFAULT_MAX_LAT_ACCEL
        exp = bool(_fresh(sm, "selfdriveState") and sm["selfdriveState"].experimentalMode)
        self.bp_arc.update(ARC.inputs_from_messages(sm["controlsState"], sm["carState"], sm["carControl"], co, vp, max_lat,
                                                    ui_state.status.value, exp))
        self.bp_arc_live = True
      except Exception:
        cloudlog.exception("steering arc inputs failed; stock Experimental Mode button kept until the next drive")
        self.bp_arc_live = False
        self.bp_arc_failed = True
    # pedals: daily response on measured carState.aEgo / standstill and frogpilotCarState.brakeLights
    self.bp_pedals = None
    pol, _rec = self._bp_extras.get(bool(getattr(ui_state, "has_longitudinal_control", False)))
    if pol.show:
      cs = sm["carState"]
      lights = False
      psm = self._bp_plan_sm
      try:
        if psm is not None and "frogpilotCarState" in psm.data and psm.valid["frogpilotCarState"] and \
           psm.alive["frogpilotCarState"] and 0.0 <= now - psm.recv_time["frogpilotCarState"] <= SL.LIMIT_STALE_S and \
           psm.recv_time["frogpilotCarState"] >= self._bp_drive_start:
          lights = bool(psm["frogpilotCarState"].brakeLights)
      except (KeyError, AttributeError, TypeError):
        lights = False
      self.bp_pedals = PED.daily_opacity(pol, float(cs.aEgo), bool(cs.standstill), lights)

  def user_interacting(self) -> bool:
    return super().user_interacting() or self._bp_arc_btn.is_pressed or self._bp_rec_btn.is_pressed

  def _render(self, rect):
    redesign = bool(toggles.get("RedesignUI"))
    wide = rect.width >= WIDE_MIN_W
    self.bp_extra_keepouts = []
    self.bp_arc_tap = None
    if not (redesign and wide and self.bp_arc_live and not self.bp_arc_failed):
      super()._render(rect)
    else:
      rl.draw_rectangle_gradient_v(int(rect.x), int(rect.y), int(rect.width), 300, COLORS.HEADER_GRADIENT_START,
                                   COLORS.HEADER_GRADIENT_END)
      if self.is_cruise_available:
        self._draw_set_speed(rect)
      self._draw_current_speed(rect)
      try:
        ARC.paint(self.bp_arc, rect)
        tap = ARC.tap_rect(rect)
        self._bp_arc_btn.render(rl.Rectangle(*tap))
        self.bp_arc_tap = tap
        self.bp_extra_keepouts.append(rl.Rectangle(*tap))
      except Exception:
        cloudlog.exception("steering arc paint failed; stock Experimental Mode button kept until the next drive")
        self.bp_arc_failed = True
        button_x = rect.x + rect.width - 30 - UI_CONFIG_BUTTON
        self._exp_button.render(rl.Rectangle(button_x, rect.y + 30, UI_CONFIG_BUTTON, UI_CONFIG_BUTTON))
    if redesign and wide:
      self._bp_render_extras(rect)

  def _bp_render_extras(self, rect):
    scale = min(1.0, rect.width / 2160.0, rect.height / 1080.0)
    widget_w = rect.width / scale
    if self.bp_pedals is not None:
      try:
        rl.rl_push_matrix()
        rl.rl_translatef(rect.x, rect.y, 0)
        rl.rl_scalef(scale, scale, 1)
        try:
          PED.paint(widget_w, self.bp_rhd, *self.bp_pedals)
        finally:
          rl.rl_pop_matrix()
        x, y, w, h = PED.pedal_rect(widget_w, self.bp_rhd)
        self.bp_extra_keepouts.append(rl.Rectangle(rect.x + x * scale, rect.y + y * scale, w * scale, h * scale))
      except Exception:
        cloudlog.exception("pedal paint failed")
        self.bp_pedals = None
    _pol, rec = self._bp_extras.get(bool(getattr(ui_state, "has_longitudinal_control", False)))
    if rec:
      cx = widget_w - REC_CX if self.bp_rhd else REC_CX
      hit = rl.Rectangle(rect.x + (cx - REC_HIT / 2) * scale, rect.y + (REC_CY - REC_HIT / 2) * scale, REC_HIT * scale,
                         REC_HIT * scale)
      try:
        self._bp_rec_btn.render(hit)
        self.bp_extra_keepouts.append(hit)
      except Exception:
        cloudlog.exception("record button failed")

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
