"""C3X onroad HUD composition (wave-2 w9): draws the component adapters in the right order.

w9 owns this file and the call sites in onroad/augmented_road_view.py. Component modules belong to their owners:
  w1 lead_lockon.make_layer   primary-lead lock-on box (the stock lead chevron is never painted)
  w3 lead_labels.make_layer   lead speed/distance labels and the personality pill (display only, replaces nothing)
  w2 driver_monitor.make_layer relocated stock driver-monitor renderer (replaces the stock DM icon while it is enabled)
  w4 alert_banner.BogPilotAlertRenderer, a drop-in AlertRenderer (native alert source; redesign banner for small and mid)
A missing module is not an error: its slot keeps the stock element. Nothing here invents runtime data. Every frame
field comes from the current drive's messages or from an existing setting resolved by its tuning-level policy.

Order with RedesignUI ON (inside the content scissor):
  model (path, lanes; no stock lead chevron) -> lead lock-on -> HUD cluster
  (speed capsule with LIMIT tile, accel graph, CSC slot, steering arc, pedals, record button) -> labels and
  personality -> driver monitor -> alert LAST.
With RedesignUI OFF the stock order and renderers run unchanged: model -> hud -> alert -> driver_state.
AugmentedRoadView arms each frame with begin_frame(defer_alert=True): the alert (and, with RedesignUI OFF, the stock
driver monitor after it) is then drawn by render_tail() after the status border and the confidence ball, so it is still
the last thing in the frame. render_tail() works from per-frame counters, so it draws exactly one alert even when
render() raised early. Callers that never arm a frame get the order above unchanged.
A stock element is skipped only while its replacing layer is enabled and actually paints in that frame. If a layer
raises, the stock element is painted in the same frame and the layer stays off until the next drive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import time

import pyray as rl
from openpilot.cereal import log, messaging
from openpilot.cereal.services import SERVICE_LIST
from openpilot.common.swaglog import cloudlog
from openpilot.common.traffic_mode_hold import ONROAD_TRAFFIC_HOLD
from openpilot.selfdrive.ui.onroad.alert_renderer import AlertRenderer
from openpilot.selfdrive.ui.onroad.bogpilot import redesign as R
from openpilot.selfdrive.ui.onroad.bogpilot.bogpilot_hud import cluster_layout
from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import toggles
from openpilot.selfdrive.ui.onroad.bogpilot.style import PILL_LABEL_SPACE, CLUSTER_GAP, TRAFFIC_RED
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus

DESIGN_W, DESIGN_H = 2160.0, 1080.0
WIDE_MIN_W = 1800.0          # redesign.alert_banner_rect's wide-layout breakpoint (content-rect pixels)
UI_BORDER = 30               # stock UI_BORDER_SIZE / UI_CONFIG.border_size
DM_BTN = 192                 # stock driver_state.BTN_SIZE
LABEL_CLEAR_MARGIN = 8       # lead_labels.clear() default margin
EXP_BTN = 192                # stock UI_CONFIG.button_size
MAX_AGE = 0.5
MAX_FUTURE = 0.25   # TrafficModeReader: update() stamps recv_time with time.monotonic() AFTER the frame clock was read
FULL = log.SelfdriveState.AlertSize.full
BP = "openpilot.selfdrive.ui.onroad.bogpilot."
# the w2 driver-monitor relocation layer (daily 150 px cluster slot, 150/192 scale) is no longer loaded. The
# driver monitor is ALWAYS the stock 0.11.2 DriverStateRenderer drawn by its own render() at its stock corner and size
# (self.dm below), so face/head pose/arcs/fade are stock code end to end. driver_monitor.py stays in tree, unused.
PEER_LAYERS = (("lead_lockon", BP + "lead_lockon"), ("lead_labels", BP + "lead_labels"))
ALERT_MODULE = BP + "alert_banner"


def fresh(sm, name, started_frame) -> bool:
  """Current-drive, valid and alive (same rule as ClusterState: recv_frame >= started_frame)."""
  try:
    return bool(sm.recv_frame[name] >= started_frame and sm.alive[name] and sm.valid[name])
  except (KeyError, AttributeError, TypeError):
    return False


def design_scale(rect) -> float:
  # Identical to bogpilot_hud.draw_cluster, so every layer shares the cluster's mapping.
  return min(1.0, rect.width / DESIGN_W, rect.height / DESIGN_H)


def to_screen(r, rect, scale):
  """Design rectangle (x, y, w, h tuple or Rectangle) -> screen Rectangle in the content rect."""
  x, y, w, h = (r.x, r.y, r.width, r.height) if hasattr(r, "width") else r
  return rl.Rectangle(rect.x + x * scale, rect.y + y * scale, w * scale, h * scale)


class PolicyToggles:
  """Effective settings, resolved as 367e1fe bogpilot_variables.py does (ParamStore applies the tuning level).

  hide_lead_marker (:768) = longitudinal and AdvancedCustomUI and HideLeadMarker and not DebugMode
  onroad_distance_button (:1110) = longitudinal and ((QOLVisuals and OnroadDistanceButton) or DebugMode)
  adjacent_leads = has_radar and (AdjacentLeadsUI or DebugMode). Daily (367e1fe :908) also required the DeveloperUI /
    DeveloperWidgets parents and drew when human_lane_changes made radard compute the leads. C3X has the human
    lane-change logic, but it only acts after its row is adopted on an AP1 Model S with openpilot longitudinal, and
    C3X has no reachable developer-widget panel, so the UI gate is the user's AdjacentLeadsUI setting
    alone (BogPilot Visuals panel). radard still computes the leads (BSMFlameTracks); the UI decides visibility.
  The longitudinal term is applied by the caller from the real CarParams. A read failure fails closed: the lead
  marker is reported hidden (so no lock-on box is drawn) and there is no personality pill."""

  CLOSED = {"hide_lead_marker": True, "onroad_distance_button": False, "adjacent_leads": False}

  def __init__(self, store=None, clock=time.monotonic, ttl=2.0):
    self._store, self.clock, self.ttl = store, clock, ttl
    self._next = -1.0
    self._value = dict(self.CLOSED)

  def get(self) -> dict:
    now = self.clock()
    if now >= self._next:
      self._next = now + self.ttl
      try:
        if self._store is None:
          from openpilot.common.bogpilot_store import ParamStore
          self._store = ParamStore()
        s = self._store
        level = s.tuning_level()
        debug = bool(s.get_bool("DebugMode", False))
        hide = bool(s.toggle_bool("AdvancedCustomUI", level) and s.toggle_bool("HideLeadMarker", level) and not debug)
        odb = bool((s.toggle_bool("QOLVisuals", level) and s.toggle_bool("OnroadDistanceButton", level)) or debug)
        adj = False
        try:
          from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
          t = onroad_toggles(s, getattr(ui_state, "CP", None))
          adj = bool(t.has_radar and (s.toggle_bool("AdjacentLeadsUI", level) or debug))
        except Exception:
          adj = False   # fail closed: no adjacent boxes
        self._value = {"hide_lead_marker": hide, "onroad_distance_button": odb, "adjacent_leads": adj}
      except Exception:
        self._value = dict(self.CLOSED)
    return self._value


class TrafficModeReader:
  """bogpilotCarState.trafficModeEnabled (card mirrors carState.bogpilot). None when the topic is absent or stale."""

  NAME = "bogpilotCarState"

  def __init__(self, sm=None):
    if sm is not None:
      self._sm = sm
      return
    # Prefer the process-wide UI SubMaster so we do not open a second socket for
    # bogpilotCarState and so recv_time is stamped in ui_state.update (before the frame clock).
    ui_sm = getattr(ui_state, "sm", None)
    if ui_sm is not None and self.NAME in getattr(ui_sm, "data", {}):
      self._sm = ui_sm
      return
    self._sm = messaging.SubMaster([self.NAME]) if self.NAME in SERVICE_LIST else None

  def read(self, now, drive_start):
    if self._sm is None:
      return None
    try:
      # ui_state.sm is already updated at the start of the UI frame; a second
      # update(0) here was both wasted work and the first-drive personality miss
      # (recv_time stamped after the frame clock).
      if self._sm is not getattr(ui_state, "sm", None):
        self._sm.update(0)
      t = self._sm.recv_time[self.NAME]
      if not (self._sm.valid[self.NAME] and self._sm.alive[self.NAME] and t >= drive_start and -MAX_FUTURE <= now - t <= MAX_AGE):
        return None
      return bool(self._sm[self.NAME].trafficModeEnabled)
    except Exception:
      return None


@dataclass
class HudFrame:
  rect: object
  scale: float
  mici: bool
  redesign: bool
  wide: bool
  sm: object
  model_renderer: object
  now: float
  drive_start: float
  started_frame: int
  is_metric: bool
  longitudinal: bool
  engaged: bool
  rhd: bool
  hide_lead_marker: bool
  onroad_distance_button: bool
  lead_info: bool
  traffic_mode: object  # bool or None (unknown)
  alert: object
  full_alert: bool
  layout: object
  adjacent_leads: bool = False
  personality_rect: object = None
  keepouts: list = field(default_factory=list)
  label_keepouts: list = field(default_factory=list)
  lead_keepouts: list = None     # lead / adjacent-lead boxes: keepouts without the alert (drawn under it)
  dm_keepouts: list = field(default_factory=list)
  lead_label_box: object = None
  dm_relocated: bool = False
  dm_personality_visible: bool = False
  base_keepouts: list = field(default_factory=list)
  stock_dm_rect: object = None
  dm_shift: float = 0.0          # px the stock DM moved toward the centre to free its corner for the button


def load_peer_layers(loader=importlib.import_module, mici=False):
  """{name: layer}, plus {name: reason} for the slots that keep stock behaviour (missing module / no adapter)."""
  layers, missing = {}, {}
  for name, module in PEER_LAYERS:
    try:
      mod = loader(module)
    except ModuleNotFoundError as e:
      if e.name != module:
        cloudlog.exception(f"hud_compose: {name} import failed")
      missing[name] = "module not present"
      continue
    except Exception:
      cloudlog.exception(f"hud_compose: {name} import failed")
      missing[name] = "import error"
      continue
    make = getattr(mod, "make_layer", None)
    layer = make(mici=mici) if callable(make) else None
    if layer is None:
      missing[name] = "no make_layer adapter" if not callable(make) else "adapter declined"
    else:
      layers[name] = layer
  return layers, missing


def make_alert_renderer(loader=importlib.import_module):
  """w4's BogPilotAlertRenderer when present (same native alert source), else the stock AlertRenderer."""
  try:
    mod = loader(ALERT_MODULE)
    return mod.BogPilotAlertRenderer(redesign_fn=lambda: toggles.get("RedesignUI"))
  except ModuleNotFoundError as e:
    if e.name != ALERT_MODULE:
      cloudlog.exception("hud_compose: alert banner import failed")
  except Exception:
    cloudlog.exception("hud_compose: alert banner unavailable")
  return AlertRenderer()


class HudComposer:
  # Optional callable(content_rect) -> rects the HUD keeps clear (the confidence ball strip). Class default, so instances
  # built without __init__ (older tests) keep working; None = no change.
  extra_keepouts = None
  # Deferred-tail frame state (begin_frame / render_tail). Class defaults for the same reason. With defer_alert False
  # (every caller except AugmentedRoadView) nothing changes: render() draws the alert itself, exactly as before.
  _armed = False
  _defer = False
  _alert_draws = 0
  _dm_drawn = False
  _redesign_frame = None

  def __init__(self, model, hud, alert, dm, *, layers=None, policy=None, traffic=None, clock=time.monotonic,
               state=None, toggle_get=None):
    self.model, self.hud, self.alert, self.dm = model, hud, alert, dm
    if layers is None:
      layers, self.missing = load_peer_layers()
    else:
      self.missing = {}
    self.layers = layers
    self.policy = policy if policy is not None else PolicyToggles()
    self.traffic = traffic if traffic is not None else TrafficModeReader()
    self.clock = clock
    self.state = state if state is not None else ui_state
    self.toggle_get = toggle_get if toggle_get is not None else toggles.get
    self.disabled: set[str] = set()
    self.frame = None
    self.order: list[str] = []          # what was painted in the last frame (tests and diagnostics)
    self._started = None
    self.drive_start = 0.0
    self._button_press_t0 = None
    self._button_press_pos = None

  # ---- lifecycle ----
  def _lifecycle(self, now):
    sf = self.state.started_frame
    if sf != self._started:
      self._started = sf
      self.drive_start = now
      self._button_press_t0 = None
      self._button_press_pos = None
      self.disabled.clear()
      for name, layer in self.layers.items():
        self._call(name, layer.reset)

  def _call(self, name, fn, *args):
    try:
      return True, fn(*args)
    except Exception:
      cloudlog.exception(f"hud_compose: {name} failed; stock element kept until the next drive")
      self.disabled.add(name)
      return False, None

  def _layer(self, name, frame):
    layer = self.layers.get(name)
    if layer is None or name in self.disabled or not frame.redesign:
      return None
    if (frame.mici or not frame.wide) and not getattr(layer, "supports_compact", False):
      return None
    return layer

  # ---- frame ----
  def build_frame(self, rect, now) -> HudFrame:
    st, sm = self.state, self.state.sm
    sf = st.started_frame
    redesign = bool(self.toggle_get("RedesignUI"))
    pol = self.policy.get()
    longitudinal = bool(st.has_longitudinal_control)
    ss_ok = fresh(sm, "selfdriveState", sf)
    dm_ok = fresh(sm, "driverMonitoringState", sf)
    alert = None
    try:
      alert = self.alert.get_alert(sm)
    except Exception:
      cloudlog.exception("hud_compose: get_alert failed")
    scale = design_scale(rect)
    traffic = self.traffic.read(now, self.drive_start) if redesign else None
    frame = HudFrame(
      rect=rect, scale=scale, mici=False, redesign=redesign, wide=rect.width >= WIDE_MIN_W, sm=sm,
      model_renderer=self.model, now=now, drive_start=self.drive_start, started_frame=sf,
      is_metric=bool(st.is_metric), longitudinal=longitudinal,
      engaged=bool(ss_ok and sm["selfdriveState"].enabled),
      rhd=bool(dm_ok and sm["driverMonitoringState"].isRHD),
      hide_lead_marker=bool(longitudinal and pol["hide_lead_marker"]),
      onroad_distance_button=bool(longitudinal and pol["onroad_distance_button"]),
      adjacent_leads=bool(longitudinal and pol.get("adjacent_leads", False)),
      # Daily 04d560f3e drawLead(): with the redesign the lead labels are always drawn (LeadInfo only drives the
      # legacy chevron metrics), so the redesign path enables them whenever the lock-on itself is allowed.
      lead_info=redesign,
      traffic_mode=traffic, alert=alert, full_alert=bool(alert is not None and alert.size == FULL),
      layout=cluster_layout())
    self._keepouts(frame, ss_ok)
    return frame

  def _keepouts(self, f, ss_ok):
    """Screen-space reservations.
    keepouts        everything incl. the DM and pill reservations
    lead_keepouts   keepouts without the alert: lead boxes are drawn under every alert (the alert paints on top)
    dm_keepouts     everything except the DM's own reservation (kept for the unused w2 relocation API)
    label_keepouts  everything except the pill's own reservation (w3), always including the stock DM corner
    the DM is always the stock corner renderer, so the display-only personality pill sits beside it (driver
    side, CLUSTER_GAP from the stock DM rect) instead of in the old daily slot the stock DM covers."""
    rect, s = f.rect, f.scale
    base = [to_screen(k, rect, s) for k in f.layout.keepouts()]
    # stock experimental-mode button (hud_renderer: top-right, border 30, 192 px)
    base.append(rl.Rectangle(rect.x + rect.width - UI_BORDER - EXP_BTN, rect.y + UI_BORDER, EXP_BTN, EXP_BTN))
    if self.extra_keepouts is not None:
      try:
        base.extend(k for k in (self.extra_keepouts(rect) or ()) if k is not None)
      except Exception:
        cloudlog.exception("hud_compose: extra keepouts failed")
    no_alert = list(base)
    ar = self._alert_rect(f)
    if ar is not None:
      base.append(ar)
    # stock driver monitor corner (driver_state._pre_calculate_drawing_elements)
    off = UI_BORDER + DM_BTN // 2
    px = rect.x + (rect.width - off if f.rhd else off)
    py = rect.y + rect.height - off
    dm = rl.Rectangle(px - DM_BTN / 2, py - DM_BTN / 2, DM_BTN, DM_BTN)
    pill = band = None
    f.dm_shift = 0.0
    if f.wide and f.onroad_distance_button and f.traffic_mode is not None and ss_ok and not f.full_alert:
      # the driving-personality button takes the stock DM corner (daily: button in the corner, DM beside
      # it); the unmodified stock DM keeps its size and moves toward the centre by button + gap.
      p = R.personality_rect(f.rhd, rect.width / s)        # design-space disc; w3 adds its own 40 px label band
      pill = to_screen(p, rect, s)
      gap = CLUSTER_GAP * s + LABEL_CLEAR_MARGIN   # lead_labels.clear() refuses the pill within 8 px of a keepout
      pill.x, pill.y = px - pill.width / 2, py - pill.height / 2
      shift = pill.width / 2 + gap + DM_BTN / 2
      f.dm_shift = shift
      dm = rl.Rectangle(dm.x + (-shift if f.rhd else shift), dm.y, DM_BTN, DM_BTN)
      band = rl.Rectangle(pill.x, pill.y - PILL_LABEL_SPACE, pill.width, pill.height + PILL_LABEL_SPACE)
    extra = [band] if band is not None else []
    f.base_keepouts, f.stock_dm_rect, f.personality_rect = base, dm, pill
    f.keepouts = base + [dm] + extra
    f.lead_keepouts = no_alert + [dm] + extra
    f.dm_keepouts = base + extra
    f.label_keepouts = base + [dm]
    f.dm_personality_visible = pill is not None

  def _alert_rect(self, f):
    if f.alert is None:
      return None
    plan_fn = getattr(self.alert, "current_plan", None)
    if plan_fn is not None:
      try:
        plan = plan_fn(f.rect)
        if getattr(plan, "rect", None) is not None and getattr(plan, "mode", None) != "native":
          x, y, w, h = plan.rect if not hasattr(plan.rect, "width") else (plan.rect.x, plan.rect.y, plan.rect.width, plan.rect.height)
          return rl.Rectangle(x, y, w, h)
      except Exception:
        cloudlog.exception("hud_compose: alert plan failed")
    try:
      return self.alert._get_alert_rect(f.rect, f.alert.size)
    except Exception:
      return rl.Rectangle(f.rect.x, f.rect.y, f.rect.width, f.rect.height)

  # ---- render ----
  # frame arming / deferred tail (AugmentedRoadView: border and confidence ball, then the alert last) ----
  def begin_frame(self, defer_alert=False):
    """Arm one frame. Plain assignments only, so it cannot raise. AugmentedRoadView calls it with defer_alert=True
    before render(); render() then leaves the alert (and, with RedesignUI off, the stock driver monitor after it) to
    render_tail(), which the view runs from a finally after the status border and the confidence ball."""
    self._armed = True
    self._defer = bool(defer_alert)
    self._alert_draws = 0
    self._dm_drawn = False
    self._redesign_frame = None
    self.frame = None
    self.order = []

  def full_alert_pending(self) -> bool:
    """True while the current alert is full-screen, or on any error, so the caller keeps the plain order (alert inside
    the content scissor, then the border) and draws no confidence ball in that frame."""
    try:
      alert = self.alert.get_alert(self.state.sm)
      return bool(alert is not None and alert.size == FULL)
    except Exception:
      return True

  def render_tail(self, rect):
    """Draw what a deferred frame still owes. It does not depend on how far render() got: the counters set by
    begin_frame() say whether the driver monitor and the alert were drawn. Exactly one alert per frame; calling it again,
    or without a deferred frame, does nothing. Order: RedesignUI-on or unknown frame -> driver monitor, then the alert
    last; RedesignUI-off frame -> alert, then driver monitor (the stock order)."""
    if not self._defer:
      return
    self._defer = False
    stock_frame = self._redesign_frame is False
    try:
      if not stock_frame and not self._dm_drawn:
        self._draw_dm(rect, self.frame)
    finally:
      if self._alert_draws == 0:
        self._alert(rect)
    if stock_frame and not self._dm_drawn:
      self._draw_dm(rect, None)

  def _draw_dm(self, rect, f):
    self._dm_drawn = True
    self.dm.render(self.dm_rect(rect, f) if f is not None else rect)   # stock DriverStateRenderer.render()
    self.order.append("stock_dm")

  def render(self, rect):
    if not self._armed:
      self.begin_frame(False)
    self._armed = False
    now = self.clock()
    self._lifecycle(now)
    self._redesign_frame = bool(self.toggle_get("RedesignUI"))
    if not self._redesign_frame:
      self._stock(rect)
      return
    f = self.frame = self.build_frame(rect, now)

    lead = self._layer("lead_lockon", f)
    self.model.bp_pending_primary = None
    self.model.bp_defer_primary_lead = lead is not None
    self.model.bp_traffic_red = self.traffic_red()
    try:
      self.model.render(rect)
    finally:
      self.model.bp_defer_primary_lead = False
    self.order.append("model")

    box = None
    if lead is not None:
      # enabled() already calls update(); a prior update() would recompute the lock twice.
      ok, on = self._call("lead_lockon", lead.enabled, f)
      if ok and on:
        ok, box = self._call("lead_lockon", lead.draw, f)
        box = box if (ok and box is not None and box is not False) else None
    if lead is not None and getattr(getattr(lead, "lock", None), "adjacent_painted", None):
      self.order.append("adjacent_leads")
    if box is not None:
      self.order.append("lead_lockon")
    # The stock lead chevron is never painted (leadOne or leadTwo), including on the
    # first frames, when lock-on has not claimed the slot, and when hide_lead_marker
    # fail-closes. The lock-on box or nothing.
    f.lead_label_box = box

    self.hud.render(rect)
    self.order.append("hud")
    # the steering arc's tap area (daily paintLeadLabels keepout), the pedals and the record button, as painted
    # this frame. Lead labels avoid them; the lock-on box and the DM relocation keep their validated keepouts.
    extra = list(getattr(self.hud, "bp_extra_keepouts", None) or [])
    if extra:
      f.base_keepouts = f.base_keepouts + extra
      f.label_keepouts = f.label_keepouts + extra

    # stock 0.11.2 driver monitor only (no relocation); its stock corner stays reserved for labels/pill.
    f.dm_relocated = False

    labels = self._layer("lead_labels", f)
    if labels is not None:
      ok, _ = self._call("lead_labels", labels.update, f)
      if ok:
        ok, on = self._call("lead_labels", labels.enabled, f)
        if ok and on:
          ok, _ = self._call("lead_labels", labels.draw, f)
          if ok:
            self.order.append("lead_labels")

    self._draw_dm(rect, f)   # stock DriverStateRenderer.render(): stock pose, fade, arcs; position

    if not self._defer:
      self._alert(rect)

  def _alert(self, rect):
    self._alert_draws += 1   # one alert per frame: render_tail() checks this, whatever path drew it
    if "alert" not in self.disabled:
      try:
        self.alert.render(rect)
        self.order.append("alert")
        return
      except Exception:
        cloudlog.exception("hud_compose: alert renderer failed; stock alert painter used")
        self.disabled.add("alert")
    AlertRenderer._render(self.alert, rect)
    self.order.append("stock_alert")

  def _stock(self, rect):
    self.model.bp_pending_primary = None
    self.model.bp_defer_primary_lead = False
    self.model.bp_traffic_red = False
    self.model.render(rect)
    self.hud.render(rect)
    if self._defer:
      self.order = ["model", "hud"]   # alert, then the stock driver monitor: render_tail(), stock order
      return
    self._alert_draws += 1
    self.alert.render(rect)
    self._dm_drawn = True
    self.dm.render(rect)
    self.order = ["model", "hud", "alert", "stock_dm"]

  @staticmethod
  def dm_rect(rect, f):
    """Rect handed to the stock DM renderer. Stock places it at rect.x + offset (LHD) or rect.x + width - offset
    (RHD), so trimming dm_shift from the driver side moves it by exactly dm_shift; size and code are untouched."""
    d = getattr(f, "dm_shift", 0.0) if f is not None else 0.0
    if not d:
      return rect
    return rl.Rectangle(rect.x + (0 if f.rhd else d), rect.y, rect.width - d, rect.height)

  def _personality_hit(self, pos) -> bool:
    """Same box test handle_press uses to decide the tap belongs to the personality button."""
    f = self.frame
    pill = getattr(f, "personality_rect", None) if f is not None else None
    if pill is None or pos is None:
      return False
    x, y = float(pos.x), float(pos.y)
    return pill.x <= x <= pill.x + pill.width and pill.y <= y <= pill.y + pill.height

  def _write_button_pressed(self, value, write_pressed=None) -> None:
    try:
      if write_pressed is None:
        from openpilot.common.params import Params
        Params().put_bool("OnroadDistanceButtonPressed", bool(value))
      else:
        write_pressed(bool(value))
    except Exception:
      cloudlog.exception("hud_compose: OnroadDistanceButtonPressed write failed")

  def handle_button_press(self, pos, now=None, write_pressed=None) -> bool:
    """Start a personality-button press. card watches OnroadDistanceButtonPressed and toggles Traffic Mode
    after ONROAD_TRAFFIC_HOLD. Returns True when the press was on the button (so it does not toggle the sidebar)."""
    if not self._personality_hit(pos):
      return False
    self._button_press_t0 = self.clock() if now is None else now
    self._button_press_pos = pos
    self._write_button_pressed(True, write_pressed)
    return True

  def handle_button_release(self, pos, now=None, write=None, write_pressed=None) -> bool:
    """End a personality-button press. A brief tap calls handle_press (same cycle as today). A hold of
    ONROAD_TRAFFIC_HOLD or longer does not step the personality; Traffic Mode is toggled by card."""
    if getattr(self, "_button_press_t0", None) is None:
      return False
    t0 = self._button_press_t0
    press_pos = self._button_press_pos
    self._button_press_t0 = None
    self._button_press_pos = None
    self._write_button_pressed(False, write_pressed)
    held = (self.clock() if now is None else now) - t0
    if held >= ONROAD_TRAFFIC_HOLD:
      return True
    return self.handle_press(press_pos if press_pos is not None else pos, write=write)

  def handle_press(self, pos, write=None) -> bool:
    """Personality button tap (daily DistanceButton: personality_at steps down like the stalk; ignored in Traffic
    Mode). Writes LongitudinalPersonality, which selfdrived re-reads every 0.1 s (stock params_thread), the same key
    the stock Toggles panel writes. Returns True when the tap was the button's (so it does not toggle the sidebar)."""
    f = self.frame
    if not self._personality_hit(pos):
      return False
    pill = f.personality_rect
    x, y = float(pos.x), float(pos.y)
    if f.traffic_mode:
      return True
    try:
      pers = ui_state.sm["selfdriveState"].personality
      current = int(getattr(pers, "raw", pers))
    except Exception:
      return True
    new = R.personality_at(pill, x, y, current)
    if new < 0:
      return True
    try:
      if write is None:
        from openpilot.common.params import Params
        Params().put("LongitudinalPersonality", int(new))
      else:
        write("LongitudinalPersonality", int(new))
      self.last_personality_write = int(new)
    except Exception:
      cloudlog.exception("hud_compose: personality write failed")
    return True

  BSM_BORDER_RGBA = (0xC9, 0x22, 0x31, 0xF1)   # earlier-build bg_colors[STATUS_TRAFFIC_MODE_ENABLED]

  def bsm_border(self, now=None):
    """(left, right) border halves to paint red, or None. Daily bogpilot_onroad paintTurnSignalBorder: a side with
    carState blindspot paints its half bg_colors[STATUS_TRAFFIC_MODE_ENABLED], steady, when has_bsm and (BlindSpotMetrics
    or DebugMode). The daily build also needed the BorderMetrics parent; here Blind Spot Border alone decides and a stored
    BorderMetrics is left unread. Physical sides (RHD does not swap). Priority: the
    LKAS-fault flash, a full-screen alert and a critical alert keep the whole border (BSM never hides them)."""
    f = self.frame
    if f is None or f.full_alert:
      return None
    a = getattr(f, "alert", None)
    if a is not None and int(getattr(a, "status", 0)) == int(log.SelfdriveState.AlertStatus.critical):
      return None
    if self.border_override() is not None:
      return None
    try:
      from openpilot.selfdrive.ui.onroad.bogpilot.bsm_state import blindspots, has_bsm
      if not has_bsm(getattr(ui_state, "CP", None)) or not self._bsm_border_enabled():
        return None
      left, right = blindspots(ui_state.sm, ui_state.started_frame, time.monotonic() if now is None else now)
    except Exception:
      return None
    return (left, right) if (left or right) else None

  def _bsm_border_enabled(self) -> bool:
    now = self.clock()
    if now >= getattr(self, "_bsm_border_next", -1.0):
      self._bsm_border_next = now + 2.0
      try:
        s = getattr(self, "_bsm_store", None)
        if s is None:
          from openpilot.common.bogpilot_store import ParamStore
          s = self._bsm_store = ParamStore()
        level = s.tuning_level()
        self._bsm_border_on = bool(s.toggle_bool("BlindSpotMetrics", level) or s.get_bool("DebugMode", False))
      except Exception:
        self._bsm_border_on = False
    return bool(getattr(self, "_bsm_border_on", False))

  def traffic_red(self) -> bool:
    """0.9.7 STATUS_TRAFFIC_MODE_ENABLED (ui.cc: traffic_mode_enabled and enabled, after the override check): the
    border and the path take TRAFFIC_RED while engaged with openpilot longitudinal and Traffic Mode on.
    Reads this frame's cached fields only (no allocation, no message reads)."""
    f = self.frame
    return bool(f is not None and f.traffic_mode is True and f.engaged and f.longitudinal and ui_state.status == UIStatus.ENGAGED)

  def border_color(self, base):
    """Onroad border colour: LKAS-fault flash first, then the Traffic Mode red, else the stock status colour."""
    return self.border_override() or (TRAFFIC_RED if self.traffic_red() else base)

  def border_override(self, millis=None):
    """LKAS-fault flashing border (daily onroad_home) from w4's plan of the real alertType; None = stock colour."""
    if self.frame is None or "alert" in self.disabled:
      return None
    state = getattr(self.alert, "hud_state", None)
    try:
      if state is not None and state().lkas_fault:
        return R.lkas_fault_border_color(millis if millis is not None else time.monotonic() * 1000.0)
    except Exception:
      return None
    return None
