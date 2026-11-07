"""C3X onroad HUD composition (wave-2 w9): draws the component adapters in the right order.

w9 owns this file and the call sites in onroad/augmented_road_view.py. Component modules belong to their owners:
  w1 lead_lockon.make_layer   primary-lead lock-on box (replaces only the stock leadOne chevron)
  w3 lead_labels.make_layer   lead speed/distance labels and the personality pill (display only, replaces nothing)
  w2 driver_monitor.make_layer relocated stock driver-monitor renderer (replaces the stock DM icon while it is enabled)
  w4 alert_banner.BogPilotAlertRenderer, a drop-in AlertRenderer (native alert source; redesign banner for small and mid)
A missing module is not an error: its slot keeps the stock element. Nothing here invents runtime data. Every frame
field comes from the current drive's messages or from an existing setting resolved by its tuning-level policy.

Order with RedesignUI ON (inside the content scissor):
  model (path, lanes, stock leadTwo) -> lead lock-on (or the deferred stock leadOne chevron) -> HUD cluster
  (speed capsule with LIMIT tile, accel graph, CSC slot, steering arc, pedals, record button) -> labels and
  personality -> driver monitor -> alert LAST.
With RedesignUI OFF the stock order and renderers run unchanged: model -> hud -> alert -> driver_state.
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
from openpilot.selfdrive.ui.onroad.alert_renderer import AlertRenderer
from openpilot.selfdrive.ui.onroad.bogpilot import redesign as R
from openpilot.selfdrive.ui.onroad.bogpilot.bogpilot_hud import cluster_layout
from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import toggles
from openpilot.selfdrive.ui.onroad.bogpilot.style import PILL_LABEL_SPACE, CLUSTER_GAP
from openpilot.selfdrive.ui.ui_state import ui_state

DESIGN_W, DESIGN_H = 2160.0, 1080.0
WIDE_MIN_W = 1800.0          # redesign.alert_banner_rect's wide-layout breakpoint (content-rect pixels)
UI_BORDER = 30               # stock UI_BORDER_SIZE / UI_CONFIG.border_size
DM_BTN = 192                 # stock driver_state.BTN_SIZE
EXP_BTN = 192                # stock UI_CONFIG.button_size
MAX_AGE = 0.5
FULL = log.SelfdriveState.AlertSize.full
BP = "openpilot.selfdrive.ui.onroad.bogpilot."
# t920u: the w2 driver-monitor relocation layer (daily 150 px cluster slot, 150/192 scale) is no longer loaded. The
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
  """Effective settings, resolved as 367e1fe frogpilot_variables.py does (ParamStore applies the tuning level).

  hide_lead_marker (:768) = longitudinal and AdvancedCustomUI and HideLeadMarker and not DebugMode
  onroad_distance_button (:1110) = longitudinal and ((QOLVisuals and OnroadDistanceButton) or DebugMode)
  adjacent_leads = adjacent_lead_tracking or human_lane_changes (bogpilot_onroad_toggles, 367e1fe :908 / :1003): the
    daily radard computed frogpilotRadarState.leadLeft/Right exactly then, and daily drawLead drew every status=true
    adjacent lead. Here radard also computes them for BSMFlameTracks, so the UI applies the daily gate itself.
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
          adj = bool(t.adjacent_lead_tracking or t.human_lane_changes)
        except Exception:
          adj = False   # fail closed: no adjacent boxes
        self._value = {"hide_lead_marker": hide, "onroad_distance_button": odb, "adjacent_leads": adj}
      except Exception:
        self._value = dict(self.CLOSED)
    return self._value


class TrafficModeReader:
  """frogpilotCarState.trafficModeEnabled (card mirrors carState.bogpilot). None when the topic is absent or stale."""

  NAME = "frogpilotCarState"

  def __init__(self, sm=None):
    self._sm = sm if sm is not None else (messaging.SubMaster([self.NAME]) if self.NAME in SERVICE_LIST else None)

  def read(self, now, drive_start):
    if self._sm is None:
      return None
    try:
      self._sm.update(0)
      t = self._sm.recv_time[self.NAME]
      if not (self._sm.valid[self.NAME] and self._sm.alive[self.NAME] and t >= drive_start and 0.0 <= now - t <= MAX_AGE):
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
  dm_keepouts: list = field(default_factory=list)
  lead_label_box: object = None
  dm_relocated: bool = False
  dm_personality_visible: bool = False
  base_keepouts: list = field(default_factory=list)
  stock_dm_rect: object = None


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

  # ---- lifecycle ----
  def _lifecycle(self, now):
    sf = self.state.started_frame
    if sf != self._started:
      self._started = sf
      self.drive_start = now
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
    keepouts        everything incl. the DM and pill reservations (lead lock-on)
    dm_keepouts     everything except the DM's own reservation (kept for the unused w2 relocation API)
    label_keepouts  everything except the pill's own reservation (w3), always including the stock DM corner
    t920u: the DM is always the stock corner renderer, so the display-only personality pill sits beside it (driver
    side, CLUSTER_GAP from the stock DM rect) instead of in the old daily slot the stock DM covers."""
    rect, s = f.rect, f.scale
    base = [to_screen(k, rect, s) for k in f.layout.keepouts()]
    # stock experimental-mode button (hud_renderer: top-right, border 30, 192 px)
    base.append(rl.Rectangle(rect.x + rect.width - UI_BORDER - EXP_BTN, rect.y + UI_BORDER, EXP_BTN, EXP_BTN))
    ar = self._alert_rect(f)
    if ar is not None:
      base.append(ar)
    # stock driver monitor corner (driver_state._pre_calculate_drawing_elements)
    off = UI_BORDER + DM_BTN // 2
    px = rect.x + (rect.width - off if f.rhd else off)
    py = rect.y + rect.height - off
    dm = rl.Rectangle(px - DM_BTN / 2, py - DM_BTN / 2, DM_BTN, DM_BTN)
    pill = band = None
    if f.wide and f.onroad_distance_button and f.traffic_mode is not None and ss_ok and not f.full_alert:
      p = R.personality_rect(f.rhd, rect.width / s)        # design-space disc; w3 adds its own 40 px label band
      pill = to_screen(p, rect, s)
      gap = CLUSTER_GAP * s
      pill.x = dm.x - gap - pill.width if f.rhd else dm.x + dm.width + gap
      band = rl.Rectangle(pill.x, pill.y - PILL_LABEL_SPACE, pill.width, pill.height + PILL_LABEL_SPACE)
    extra = [band] if band is not None else []
    f.base_keepouts, f.stock_dm_rect, f.personality_rect = base, dm, pill
    f.keepouts = base + [dm] + extra
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
  def render(self, rect):
    now = self.clock()
    self._lifecycle(now)
    self.order = []
    if not self.toggle_get("RedesignUI"):
      self.frame = None
      self._stock(rect)
      return
    f = self.frame = self.build_frame(rect, now)

    lead = self._layer("lead_lockon", f)
    self.model.bp_pending_primary = None
    self.model.bp_defer_primary_lead = lead is not None
    try:
      self.model.render(rect)
    finally:
      self.model.bp_defer_primary_lead = False
    self.order.append("model")

    box = None
    if lead is not None:
      ok, _ = self._call("lead_lockon", lead.update, f)
      ok, on = self._call("lead_lockon", lead.enabled, f) if ok else (False, False)
      if ok and on:
        ok, box = self._call("lead_lockon", lead.draw, f)
        box = box if (ok and box is not None and box is not False) else None
    if lead is not None and getattr(getattr(lead, "lock", None), "adjacent_painted", None):
      self.order.append("adjacent_leads")
    if box is not None:
      self.order.append("lead_lockon")
    elif getattr(self.model, "bp_pending_primary", None) is not None:
      self.model.bp_flush_primary_lead()
      self.order.append("stock_lead")
    f.lead_label_box = box

    self.hud.render(rect)
    self.order.append("hud")
    # t913u: the steering arc's tap area (daily paintLeadLabels keepout), the pedals and the record button, as painted
    # this frame. Lead labels avoid them; the lock-on box and the DM relocation keep their validated keepouts.
    extra = list(getattr(self.hud, "bp_extra_keepouts", None) or [])
    if extra:
      f.base_keepouts = f.base_keepouts + extra
      f.label_keepouts = f.label_keepouts + extra

    # t920u: stock 0.11.2 driver monitor only (no relocation); its stock corner stays reserved for labels/pill.
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

    self.dm.render(rect)            # stock DriverStateRenderer.render(): stock visibility, pose, fade, arcs, corner
    self.order.append("stock_dm")

    self._alert(rect)

  def _alert(self, rect):
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
    self.model.render(rect)
    self.hud.render(rect)
    self.alert.render(rect)
    self.dm.render(rect)
    self.order = ["model", "hud", "alert", "stock_dm"]

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
