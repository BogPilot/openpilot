"""Release-tizi redesign adapter, retaining the upstream HUD state and controls.

The cluster layout owns the cluster composition below: speed capsule, optional accel graph (ShowAccelGraph, off by
default), LowerSpeedLimitsBox (capsule in the lower slot when the rear-view mirror covers the top) and the CSC MAX slot from a validated planner report only
(plannerd's bogpilotPlan, AP1 CSC). The slot also needs CurveSpeedController and ShowCSCStatus on. There are
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
from openpilot.selfdrive.ui.onroad.bogpilot import phase3_cem_status as CEM
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED
from openpilot.selfdrive.ui.onroad.bogpilot import c4_layout as C4
from openpilot.selfdrive.ui.onroad.bogpilot import c4_paint as C4P
from openpilot.selfdrive.ui.onroad.bogpilot import lead_labels as LL
from openpilot.selfdrive.ui.onroad.bogpilot import developer_hud_logic as DEV
from openpilot.selfdrive.ui.onroad.bogpilot import developer_hud as DEVP
from openpilot.selfdrive.ui.onroad.bogpilot import fps_counter as FPS
from openpilot.selfdrive.ui.onroad.bogpilot import overlay_gate as OVG
from openpilot.selfdrive.ui.onroad.bogpilot.style import record_hit_rect
from openpilot.selfdrive.ui.onroad.exp_button import ExpButton
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
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
    # LIMIT tile / SLC offset badge and the daily set-speed colour (compact mici layout keeps the stock row)
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
      # ShowAccelGraph off: graph skipped. Capsule slot follows layout.redesign_swap (LowerSpeedLimitsBox).
      graph.paint(R.accel_graph_rect(layout.swap))
  finally:
    rl.rl_pop_matrix()


def draw_cem_status(hud, rect):
  if not getattr(hud, "bp_cem", CEM.HIDDEN).visible:
    return
  try:
    scale = min(1.0, rect.width / 2160.0, rect.height / 1080.0)
    box = rl.Rectangle(rect.x + 30 * scale, rect.y + 470 * scale, 280 * scale, 54 * scale)
    CEM.paint_status(hud.bp_cem, box)
    if hasattr(hud, "bp_extra_keepouts"):
      hud.bp_extra_keepouts.append(box)
  except Exception:
    cloudlog.exception("cem status badge failed")


class ClusterState:
  """Accel graph samples and the validated CSC report, shared by the C3X and C4 renderers."""

  def _bp_init(self):
    self.bp_graph = AccelGraph(hz=GRAPH_HZ)
    self.bp_csc = L.INVALID_CSC
    self.bp_cem = CEM.HIDDEN
    from openpilot.common.bogpilot_store import ParamStore
    self._bp_cem_store = ParamStore(cache_ttl=2.0)
    self._bp_graph_t = -1.0
    self._bp_started = None
    self._bp_drive_start = 0.0
    # Optional contract: subscribe only when the service exists (never on stock release-tizi).
    # Reuse ui_state.sm when it already owns these topics so we do not poll a second socket.
    have = set(getattr(getattr(ui_state, "sm", None), "data", {}) or [])
    services = [s for s in ("bogpilotPlan", "bogpilotCarState") if s in SERVICE_LIST and s not in have]
    self._bp_plan_sm = messaging.SubMaster(services) if services else None
    self.bp_limit = SL.HIDDEN
    self._bp_limit_policy = SL.LimitPolicyReader(cp_fn=lambda: ui_state.CP)

  def _plan_sm(self):
    """bogpilotPlan / bogpilotCarState: prefer the shared UI SubMaster, else the fallback socket."""
    if self._bp_plan_sm is not None:
      return self._bp_plan_sm
    sm = getattr(ui_state, "sm", None)
    if sm is not None and any(s in getattr(sm, "data", {}) for s in ("bogpilotPlan", "bogpilotCarState")):
      return sm
    return None

  def _bp_update(self):
    self.bp_cem = CEM.HIDDEN
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
    if cluster_layout().graph_visible:
      if now - self._bp_graph_t >= 1.0 / GRAPH_HZ and sm.alive["carControl"] and sm.valid["carControl"]:
        self._bp_graph_t = now
        self.bp_graph.push(float(sm["carControl"].actuators.accel), float(sm["carState"].aEgo))
    psm = self._plan_sm()
    if psm is not None:
      if psm is self._bp_plan_sm:
        psm.update(0)
      self.bp_csc = L.read_csc_status(psm, now, self._bp_drive_start)
      try:  # display-only badge must never break the onroad HUD
        self.bp_cem = CEM.read_status(self._bp_cem_store, psm, now, self._bp_drive_start,
                                      bool(_fresh(sm, "selfdriveState") and sm["selfdriveState"].enabled))
      except Exception:
        self.bp_cem = CEM.HIDDEN
    dashboard = SL.read_dashboard_limit(psm, now, self._bp_drive_start)
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

  @property
  def enabled(self) -> bool:
    # ExpButton is disabled (hidden and inert); the arc's tap target must keep working.
    return True

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
    """Truthful indicator: `status` from the engine (recording only once the encoder is alive and has a frame).
    starting = dim pulse ring around the idle dot; error = amber ring + "!" until the next start (last_error logged)."""
    rec = self._recorder_fn()
    status = rec.status
    error = rec.last_error if status == "error" else None
    pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 3.14159)
    R.paint_record_button(rect, status == "recording", pulse)
    cx, cy = rect.x + rect.width / 2, rect.y + rect.height / 2
    r = min(rect.width, rect.height) / 2
    if status == "starting":
      rl.draw_ring(rl.Vector2(cx, cy), r * 0.62, r * 0.70, 0, 360, 32, rl.Color(225, 60, 60, int(90 + 120 * pulse)))
    elif error:
      rl.draw_ring(rl.Vector2(cx, cy), r * 0.62, r * 0.72, 0, 360, 32, rl.Color(255, 176, 32, 235))
      bx, by = cx + r * 0.52, cy - r * 0.52
      rl.draw_circle_v(rl.Vector2(bx, by), r * 0.24, rl.Color(255, 176, 32, 245))
      rl.draw_rectangle_rec(rl.Rectangle(bx - r * 0.035, by - r * 0.15, r * 0.07, r * 0.17), rl.Color(14, 17, 22, 255))
      rl.draw_circle_v(rl.Vector2(bx, by + r * 0.10), r * 0.04, rl.Color(14, 17, 22, 255))


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
    self.bp_pedals = None             # pedal_gauge3.Gauge3 to draw, or None when hidden
    self.bp_pedal_bars = PED.PedalGauge()
    self.bp_extra_keepouts: list = []  # screen rects of the arc tap area, pedals and record button (lead labels avoid)
    self.bp_rhd = False
    self._bp_started_arc = None
    self._bp_dev_policy = DEV.DeveloperHudPolicy()
    self.bp_dev_cells = None          # Developer HUD cells (DeveloperHUD on and live car data), or None when hidden
    self._bp_fps_gate = OVG.OverlayGate("FPSCounter", stored_only=True)
    self._bp_fps = FPS.FpsTracker()
    self._bp_fps_drive = None

  def _update_state(self):
    super()._update_state()
    self._bp_update()
    self._bp_update_features()
    self._bp_update_developer()

  def _bp_update_developer(self):
    self.bp_dev_cells = None
    try:
      if self._bp_dev_policy.get():
        inputs = DEV.inputs_from_messages(ui_state.sm, ui_state.started_frame, ui_state.is_metric, ui_state.CP)
        if inputs is not None:
          self.bp_dev_cells = DEV.cells(inputs)
    except Exception:  # display-only panel must never break the onroad HUD
      cloudlog.exception("developer HUD inputs failed")
      self.bp_dev_cells = None

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
    # 3-bar pedal gauge (pedals.py / pedal_gauge3.py): carState (brakePressed, deprecated.brake = brake level,
    # deprecated.gas = DI_pedalPos / 100), carControl accel while longActive, bogpilotCarState motor torque and RPM (regen
    # kW, every legacy platform) and DI_brakePedalState (AP1, openpilot braking colour). aEgo is not an input.
    self.bp_pedals = None
    pol, _rec = self._bp_extras.get(bool(getattr(ui_state, "has_longitudinal_control", False)))
    if pol.show:
      cs = sm["carState"]
      motor_tq = None
      motor_rpm = None
      brake_state = None
      psm = self._plan_sm()
      try:
        if psm is not None and "bogpilotCarState" in getattr(psm, "data", psm) and psm.valid["bogpilotCarState"] and \
           psm.alive["bogpilotCarState"] and now - psm.recv_time["bogpilotCarState"] <= SL.LIMIT_STALE_S and \
           psm.recv_time["bogpilotCarState"] >= self._bp_drive_start:
          motor_tq = float(psm["bogpilotCarState"].ap1MotorTorqueNm)      # 0x108 DI_torqueMotor, Nm
          motor_rpm = float(psm["bogpilotCarState"].ap1MotorRpm)          # 0x108 DI_motorRPM
          brake_state = int(psm["bogpilotCarState"].ap1BrakePedalState)   # iBooster applied (AP1), bar colour only
      except (KeyError, AttributeError, TypeError, ValueError):
        motor_tq = None
        motor_rpm = None
        brake_state = None
      long_active = bool(_fresh(sm, "carControl") and sm["carControl"].longActive)
      op_accel = float(sm["carControl"].actuators.accel) if long_active else 0.0
      cp = ui_state.CP
      fp = getattr(cp, "carFingerprint", "") if cp is not None else ""
      self.bp_pedals = self.bp_pedal_bars.update(pol, _fresh(sm, "carState"), now, PED.platform_of(fp),
                                                 brake_pressed=bool(cs.brakePressed), brake_level=cs.deprecated.brake,
                                                 pedal_pos=cs.deprecated.gas, op_accel=op_accel, long_active=long_active,
                                                 motor_torque_nm=motor_tq, motor_rpm=motor_rpm,
                                                 brake_pedal_state=brake_state, fingerprint=fp)

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
    if wide:
      self._bp_render_developer(rect, redesign and self.bp_arc_live and not self.bp_arc_failed)
      self._bp_render_fps(rect)
    draw_cem_status(self, rect)

  def _bp_render_developer(self, rect, arc_layout):
    """Developer HUD, top right. With the redesign arc the corner is free; with the stock Experimental Mode button in
    that corner the panel sits under it. Display only (no tap), and a paint failure only drops the panel."""
    if self.bp_dev_cells is None:
      return
    try:
      top = 30 if arc_layout else 30 + UI_CONFIG_BUTTON + 18
      x, y, w, h = DEV.panel_rect(rect.width, rect.height, 30, top)
      DEVP.paint(self.bp_dev_cells, (rect.x + x, rect.y + y, w, h))
      self.bp_extra_keepouts.append(rl.Rectangle(rect.x + x, rect.y + y, w, h))
    except Exception:
      cloudlog.exception("developer HUD paint failed")
      self.bp_dev_cells = None

  def _bp_render_fps(self, rect):
    """FPS counter along the bottom edge (FPSCounter). Display only; min and max restart with each drive."""
    try:
      if not self._bp_fps_gate.get():
        self._bp_fps_drive = None
        return
      if self._bp_fps_drive != ui_state.started_frame:
        self._bp_fps_drive = ui_state.started_frame
        self._bp_fps.reset()
      self._bp_fps.frame(time.monotonic())
      FPS.paint(self._bp_fps.text(), rect)
    except Exception:
      cloudlog.exception("FPS counter failed")

  def _bp_render_extras(self, rect):
    scale = min(1.0, rect.width / 2160.0, rect.height / 1080.0)
    widget_w = rect.width / scale
    if self.bp_pedals is not None:
      try:
        PED.paint(rect, scale, widget_w, self.bp_rhd, self.bp_pedals)
        self.bp_extra_keepouts.append(rl.Rectangle(*PED.screen_rect(rect, scale, widget_w, self.bp_rhd)))
      except Exception:
        cloudlog.exception("pedal paint failed")
        self.bp_pedals = None
    _pol, rec = self._bp_extras.get(bool(getattr(ui_state, "has_longitudinal_control", False)))
    if rec:
      # one fixed spot halfway between the pedal bars' rect and the personality label; tap area = drawn button
      hit = record_hit_rect(rect, scale, widget_w, self.bp_rhd)
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
    self.bp_c4 = False
    self.bp_c4_layout = {}
    self.bp_c4_personality = None
    self._bp_traffic = None
    self._bp_c4_extras = ExtrasPolicy()
    self._bp_c4_arrow = None         # c4_layout.LaneChangeArrow, made on the first comma 4 frame
    self._bp_c4_arrow_tex = None
    self.bp_c4_gauge = None          # pedal_gauge3.Gauge3 to draw, or None when the pedal display is off
    self._bp_c4_pedals = None        # pedals.PedalGauge (shared inputs, colour-source hysteresis, regen smoothing)
    self.bp_c4_arrow_dir = 0
    self.bp_c4_lc_alert = False      # the stock lane-change alert is on screen
    self.bp_c4_rec = False           # record button shown (ScreenRecorder toggle, same rule as the wide layout)
    self._bp_c4_leads = None         # c4_leads.Comma4Leads, made on the first comma 4 frame
    self._bp_c4_lead_policy = None   # hud_compose.PolicyToggles (HideLeadMarker, AdjacentLeadsUI)
    self._bp_c4_arc = None           # steering_arc.ArcState for the comma 4 arc, made on the first comma 4 frame
    self._bp_c4_arc_t = -1.0
    self._bp_c4_arc_started = None
    self.bp_c4_arc_ok = False        # False: the stock torque bar is drawn instead
    self.bp_c4_bsm = None            # (left, right) border halves in BSM red, or None
    self._bp_c4_bsm_next = -1.0
    self._bp_c4_bsm_on = False

  def _update_state(self):
    super()._update_state()
    self._bp_update()
    self.bp_c4 = C4.comma4_device(ui_state.sm)
    if self.bp_c4:
      try:
        self._bp_c4_update()
      except Exception:
        cloudlog.exception("comma 4 layout inputs failed")
        self.bp_c4_gauge = None
        self.bp_c4_arrow_dir = 0
      self._bp_c4_update_arc()
      self._bp_c4_update_bsm()

  def _bp_c4_update_arc(self):
    """BogPilot steering arc state (same inputs and 20 Hz rate as the wide arc). Any failure keeps the stock torque bar
    until the next drive."""
    sm, now = ui_state.sm, time.monotonic()
    if self._bp_c4_arc is None:
      self._bp_c4_arc = ARC.ArcState()
    if self._bp_c4_arc_started != ui_state.started_frame:
      self._bp_c4_arc_started = ui_state.started_frame
      self._bp_c4_arc.reset()
      self._bp_c4_arc_failed = False
    if getattr(self, "_bp_c4_arc_failed", False):
      self.bp_c4_arc_ok = False
      return
    if not all(_fresh(sm, n) for n in ("controlsState", "carState", "carControl")):
      self.bp_c4_arc_ok = False
      self._bp_c4_arc.reset()
      return
    if now - self._bp_c4_arc_t < 1.0 / ARC.UPDATE_HZ:
      return
    self._bp_c4_arc_t = now
    try:
      vp = sm["vehicleParameters"] if _fresh(sm, "vehicleParameters") else None
      co = sm["carOutput"] if _fresh(sm, "carOutput") else None
      cp = ui_state.CP
      max_lat = float(cp.maxLateralAccel) if cp is not None else ARC.DEFAULT_MAX_LAT_ACCEL
      exp = bool(_fresh(sm, "selfdriveState") and sm["selfdriveState"].experimentalMode)
      self._bp_c4_arc.update(ARC.inputs_from_messages(sm["controlsState"], sm["carState"], sm["carControl"], co, vp,
                                                      max_lat, ui_state.status.value, exp))
      self.bp_c4_arc_ok = True
    except Exception:
      cloudlog.exception("comma 4 steering arc inputs failed; stock torque bar kept until the next drive")
      self.bp_c4_arc_ok = False
      self._bp_c4_arc_failed = True

  def _bp_c4_update_bsm(self):
    """Blind-spot border halves: same rule as the wide layout (has_bsm and (BlindSpotMetrics or DebugMode); a
    full-screen or critical alert keeps the whole border)."""
    self.bp_c4_bsm = None
    try:
      from openpilot.selfdrive.ui.onroad.bogpilot.bsm_state import blindspots, has_bsm
      from openpilot.selfdrive.ui.onroad.bogpilot import c4_arc as C4A
      now = time.monotonic()
      if now >= self._bp_c4_bsm_next:
        self._bp_c4_bsm_next = now + 2.0
        try:
          s = getattr(self, "_bp_c4_bsm_store", None)
          if s is None:
            from openpilot.common.bogpilot_store import ParamStore
            s = self._bp_c4_bsm_store = ParamStore()
          level = s.tuning_level()
          self._bp_c4_bsm_on = bool(s.toggle_bool("BlindSpotMetrics", level) or s.get_bool("DebugMode", False))
        except Exception:
          self._bp_c4_bsm_on = False
      sm = ui_state.sm
      ss = sm["selfdriveState"] if _fresh(sm, "selfdriveState") else None
      left, right = blindspots(sm, ui_state.started_frame, now)
      self.bp_c4_bsm = C4A.bsm_halves(left, right, has_bsm(getattr(ui_state, "CP", None)), self._bp_c4_bsm_on,
                                      ss is not None and str(ss.alertSize) == "full",
                                      ss is not None and str(ss.alertStatus) == "critical")
    except Exception:
      cloudlog.exception("comma 4 BSM border inputs failed")
      self.bp_c4_bsm = None

  def _bp_c4_update(self):
    sm = ui_state.sm
    now = time.monotonic()
    # lane-change arrows and the stock turn intent: onroadEvents only (the blinkers are not read)
    names = [str(e.name) for e in sm["onroadEvents"]] if _fresh(sm, "onroadEvents") else []
    md = sm["modelV2"].meta.laneChangeDirection if _fresh(sm, "modelV2") else None
    if self._bp_c4_arrow is None:
      self._bp_c4_arrow = C4.LaneChangeArrow()
    self.bp_c4_arrow_dir = self._bp_c4_arrow.update(names, md)
    self._turn_intent._update_state()   # stock filters; its render moved over the personality button
    ss = sm["selfdriveState"] if _fresh(sm, "selfdriveState") else None
    alert_type = str(ss.alertType) if ss is not None else ""
    self.bp_c4_lc_alert = alert_type.startswith(("preLaneChange", "laneChange"))
    # three-bar gauge, shown under the same pedal display toggles as the wide layout's pedal bars
    pol, rec = self._bp_c4_extras.get(bool(getattr(ui_state, "has_longitudinal_control", False)))
    self.bp_c4_rec = bool(rec)
    self.bp_c4_gauge = None
    if self._bp_c4_pedals is None:
      self._bp_c4_pedals = PED.PedalGauge()
    if not pol.show:
      self._bp_c4_pedals.reset()
    else:
      cs = sm["carState"]
      motor_tq = motor_rpm = brake_state = None
      psm = self._plan_sm()
      try:
        if psm is not None and "bogpilotCarState" in getattr(psm, "data", psm) and psm.valid["bogpilotCarState"] and \
           psm.alive["bogpilotCarState"] and now - psm.recv_time["bogpilotCarState"] <= SL.LIMIT_STALE_S and \
           psm.recv_time["bogpilotCarState"] >= self._bp_drive_start:
          bcs = psm["bogpilotCarState"]
          motor_tq, motor_rpm = float(bcs.ap1MotorTorqueNm), float(bcs.ap1MotorRpm)
          brake_state = int(bcs.ap1BrakePedalState)
      except (KeyError, AttributeError, TypeError, ValueError):
        motor_tq = motor_rpm = brake_state = None
      long_active = bool(_fresh(sm, "carControl") and sm["carControl"].longActive)
      cp = ui_state.CP
      fp = getattr(cp, "carFingerprint", "") if cp is not None else ""
      # same inputs as the wide layout's gauge (bogpilot_hud BogPilotHudRenderer._bp_update_features)
      self.bp_c4_gauge = self._bp_c4_pedals.update(pol, _fresh(sm, "carState"), now, PED.platform_of(fp),
                                                   brake_pressed=bool(cs.brakePressed), brake_level=cs.deprecated.brake,
                                                   pedal_pos=cs.deprecated.gas,
                                                   op_accel=float(sm["carControl"].actuators.accel) if long_active else 0.0,
                                                   long_active=long_active, motor_torque_nm=motor_tq, motor_rpm=motor_rpm,
                                                   brake_pedal_state=brake_state, fingerprint=fp)

  def _draw_set_speed(self, rect):
    if not toggles.get("RedesignUI") and not self.bp_c4:
      super()._draw_set_speed(rect)

  def _draw_steering_wheel(self, rect):
    # comma 4 layout: no stock wheel icon (its turn-intent arrows are replaced by the lane-change arrows)
    if not self.bp_c4:
      super()._draw_steering_wheel(rect)

  def _render(self, rect):
    # Preserve torque bar, model-source warnings, steer-required icon and turn
    # intent. Do not paint the redesign over the stock alert's reserved space.
    self.bp_c4_layout = dict(getattr(self, "bp_c4_lead_layout", {}) or {})
    if self.bp_c4:
      self.bp_c4_layout["dm icon"] = C4.DM_ICON if getattr(self, "bp_c4_dm_drawn", False) else None
      self._bp_render_c4_stock(rect)
      self._bp_render_c4(rect)
      return
    super()._render(rect)
    if toggles.get("RedesignUI") and self._can_draw_top_icons:
      draw_cluster(self, rect, mici=True)
    if self._can_draw_top_icons:
      draw_cem_status(self, rect)

  def _bp_c4_personality(self):
    sm, now = ui_state.sm, time.monotonic()
    if self._bp_traffic is None:
      from openpilot.selfdrive.ui.onroad.bogpilot.hud_compose import TrafficModeReader
      self._bp_traffic = TrafficModeReader()
    traffic = self._bp_traffic.read(now, self._bp_drive_start)
    data = LL.read_personality(sm, now, self._bp_drive_start, ui_state.started_frame, bool(traffic))
    return data, bool(traffic)

  def _bp_c4_pill_inputs(self):
    speed_set = display_set_speed(self, mici=True)
    lim = getattr(self, "bp_limit", SL.HIDDEN)
    return C4P.PillInputs(set_speed=str(round(speed_set)) if self.is_cruise_set else "\u2013", speed=str(round(self.speed)),
                          unit="KM/H" if ui_state.is_metric else "MPH", engaged=bool(self._engaged),
                          show_limit=bool(lim.show_limit), limit=str(lim.limit))

  def _bp_render_c4_stock(self, rect):
    """The stock mici HUD order with the comma 4 changes: the BogPilot arc on the stock torque-bar geometry (raised)
    instead of the torque bar, the model-source warnings kept, no set-speed box and no wheel icon."""
    from openpilot.selfdrive.ui.onroad.bogpilot import c4_arc as C4A
    drawn = False
    if self.bp_c4_arc_ok and self._bp_c4_arc is not None:
      try:
        self.bp_c4_layout.update(C4A.paint(self._bp_c4_arc, rect))
        drawn = True
      except Exception:
        cloudlog.exception("comma 4 steering arc paint failed; stock torque bar kept until the next drive")
        self.bp_c4_arc_ok = False
        self._bp_c4_arc_failed = True
    if not drawn:
      self._torque_bar.render(rect)
    self.bp_c4_layout["arc"] = "bogpilot" if drawn else "stock"
    self._draw_model_source(rect)

  def _bp_c4_border(self, rect, traffic):
    from openpilot.selfdrive.ui.onroad.bogpilot import c4_arc as C4A
    longitudinal = bool(getattr(ui_state, "has_longitudinal_control", False))
    colour = C4A.border_colour(ui_state.status.value, bool(traffic) and bool(self._engaged) and longitudinal)
    self.bp_c4_layout["border_colour"] = colour
    self.bp_c4_layout["bsm"] = self.bp_c4_bsm
    self.bp_c4_layout.update(C4A.paint_border(rect, colour, self.bp_c4_bsm))

  def _bp_render_c4(self, rect):
    """comma 4 BogPilot layout (device type mici only). Screen = the content rect's origin; positions from c4_layout."""
    ox, oy = rect.x, rect.y
    lay = self.bp_c4_layout
    lay["content_rect"] = (rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
    vis = C4.visibility(alert_shown=not self._can_draw_top_icons, take_control=bool(self._show_wheel_critical))
    lay["visibility"] = {k: getattr(vis, k) for k in ("pill", "gauge", "dm", "leads", "take_control")}
    data, traffic = self._bp_c4_personality()
    self._bp_c4_border(rect, traffic)
    if vis.pill:
      lay.update(C4P.paint_pill(self._bp_c4_pill_inputs(), ox, oy))
    self.bp_c4_personality = None if data is None else data.personality
    lay["personality"] = self.bp_c4_personality
    if vis.gauge and self.bp_c4_gauge is not None:
      lay.update(C4P.paint_gauge(self.bp_c4_gauge, ox, oy))
    lay["arrow_dir"] = self.bp_c4_arrow_dir
    lay["stock_lc_alert"] = self.bp_c4_lc_alert
    if C4.arrow_visible(self.bp_c4_arrow_dir, self.bp_c4_lc_alert and not self._can_draw_top_icons):
      if self._bp_c4_arrow_tex is None:
        self._bp_c4_arrow_tex = gui_app.texture("icons_mici/onroad/turn_signal_left.png", C4.ARROW_TEX_W, C4.ARROW_TEX_H)
      lay.update(C4P.paint_arrow(self._bp_c4_arrow_tex, self.bp_c4_arrow_dir, ox, oy))
    lay.update(C4P.paint_personality_button(self.bp_c4_personality, traffic, vis.take_control, ox, oy))
    ti = self._turn_intent
    lay.update(C4P.paint_turn_intent(ti._txt_turn_intent_left, ti._txt_turn_intent_right, ti._turn_intent_direction,
                                     ti._turn_intent_alpha_filter.x, ti._turn_intent_rotation_filter.x, ox, oy))

  def _bp_c4_alert(self, alert_shown):
    """(alert zone or None, userPrompt) for the stock alert on screen this frame (full-screen alerts cover everything
    and move nothing)."""
    if not alert_shown:
      return None, False
    sm = ui_state.sm
    ss = sm["selfdriveState"] if _fresh(sm, "selfdriveState") else None
    size = str(ss.alertSize) if ss is not None else ""
    status = str(ss.alertStatus) if ss is not None else ""
    return (None if size == "full" else C4.ALERT_TEXT_ZONE), status == "userPrompt"

  def bp_c4_render_leads(self, model_renderer, alert_shown):
    """Lead and adjacent-lead boxes with their speeds (comma 4 only), engaged or not. Drawn in the camera view under
    the alerts and the HUD."""
    if not self.bp_c4:
      return
    try:
      from openpilot.selfdrive.ui.onroad.bogpilot.c4_leads import Comma4Leads
      from openpilot.selfdrive.ui.onroad.bogpilot.hud_compose import PolicyToggles
      if self._bp_c4_leads is None:
        self._bp_c4_leads = Comma4Leads()
        self._bp_c4_lead_policy = PolicyToggles()
      pol = self._bp_c4_lead_policy.get()
      longitudinal = bool(getattr(ui_state, "has_longitudinal_control", False))
      vis = C4.visibility(alert_shown=alert_shown, take_control=False)
      gauge_on = vis.gauge and self.bp_c4_gauge is not None
      rect = model_renderer._rect
      ox, oy = rect.x, rect.y
      gauge = C4._offset(C4.gauge_rect(), ox, oy) if gauge_on else None
      leads, v_ego = self._bp_c4_leads.update(model_renderer, ui_state.sm, ui_state.started_frame,
                                              longitudinal=longitudinal,
                                              adjacent=bool(longitudinal and pol.get("adjacent_leads", False)),
                                              hide_marker=bool(pol.get("hide_lead_marker", True)),
                                              metric=bool(ui_state.is_metric), gauge=gauge)
      keepouts = []
      if not alert_shown:
        keepouts += ([C4.gauge_rect()] if gauge_on else []) + [C4.PILL, C4.DM_ICON]
      if C4.arrow_visible(self.bp_c4_arrow_dir, self.bp_c4_lc_alert and alert_shown):
        keepouts.append(C4.arrow_core_rect(self.bp_c4_arrow_dir))
      ti = self._turn_intent
      if ti._turn_intent_alpha_filter.x > 1e-2:
        keepouts.append(C4.turn_intent_bbox(ti._turn_intent_rotation_filter.x))
      zone, side_mode = self._bp_c4_alert(alert_shown)
      self.bp_c4_lead_layout = C4P.paint_leads(leads, v_ego, keepouts, zone, side_mode, ox, oy)
    except Exception:
      cloudlog.exception("comma 4 lead boxes failed")
      self.bp_c4_lead_layout = {}

  def bp_c4_dm(self, should_draw, alert_shown, screen_rect):
    """Driver-monitor icon on the comma 4: the stock rule for when it shows, moved to the top right, and stepping
    aside during alerts with the pill and gauge. Returns (should_draw, x, y)."""
    vis = C4.visibility(alert_shown=alert_shown, take_control=False)
    x, y = C4.dm_position()
    self.bp_c4_dm_drawn = bool(should_draw and vis.dm)
    return self.bp_c4_dm_drawn, screen_rect.x + x, screen_rect.y + y

  def bp_c4_render_side(self, screen_rect):
    """Side-panel part of the comma 4 layout (outside the camera view's clip): the record button."""
    if not self.bp_c4 or not self.bp_c4_rec:
      return
    try:
      rec = _recorder()
      status = rec.status if rec.status in ("recording", "starting", "error") else "idle"
      pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 3.14159)
      self.bp_c4_layout.update(C4P.paint_record_button(status, pulse, screen_rect.x, screen_rect.y))
      self.bp_c4_layout["record_status"] = status
    except Exception:
      cloudlog.exception("comma 4 record button failed")

  def bp_c4_handle_tap(self, x, y, write=None) -> bool:
    """Personality button tap on the comma 4 (same step as the wide layout: Relaxed -> Standard -> Aggressive ->
    Relaxed, ignored in Traffic Mode). Returns True when the tap was the button's."""
    if not self.bp_c4:
      return False
    if self.bp_c4_rec and C4.in_rect(C4.record_rect(), x, y):
      try:
        (write or (lambda *_: _recorder().toggle()))("ScreenRecorderToggle", None)
      except Exception:
        cloudlog.exception("screen recorder toggle failed")
      return True
    t = C4.personality_tap_rect()
    if not (t[0] <= x < t[2] and t[1] <= y < t[3]):
      return False
    data, traffic = self._bp_c4_personality()
    if traffic or data is None:
      return True
    new = (int(data.personality) + 2) % 3
    try:
      if write is None:
        from openpilot.common.params import Params
        Params().put("LongitudinalPersonality", int(new))
      else:
        write("LongitudinalPersonality", int(new))
    except Exception:
      cloudlog.exception("comma 4 personality write failed")
    return True
