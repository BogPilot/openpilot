"""Observational port of own 0.9.7 stop/lead alerts; never controls the car.

Source: 04d560f3 frogpilot_events.py, frogpilot_planner.py and
conditional_experimental_mode.py. Green means model-predicted release, NOT
traffic-light recognition. Current model position/velocity support that source.
"""
from dataclasses import dataclass
import math

HISTORICAL_REVISION = "04d560f3ece97797b8f1ee2f714e682e6d0ef40e"
ACTIVE_ALERT_ROWS = (
  ("GreenLightAlert", "Green Light Alert", "Alert when the model predicts release from a stop. This is not traffic-light detection and may be incorrect. Always check the road."),
  ("LeadDepartingAlert", "Lead Departed Alert", "Alert when the tracked lead moves more than 1 m from its stopped distance at over 1 m/s while your car remains stopped."),
)
ACTIVE_ALERT_KEYS = tuple(row[0] for row in ACTIVE_ALERT_ROWS)
FRESH_DEFAULTS = {key: True for key in ACTIVE_ALERT_KEYS}
OMITTED_ALERT_KEYS = ("GoatScream", "LoudBlindspotAlert", "SpeedLimitChangedAlert")


def read_enabled(store, key):
  # Explicit default overrides the legacy registry default, never stored OFF.
  return store.get_bool(key, default=True)


@dataclass(frozen=True)
class AlertInput:
  now: float
  standstill: bool
  gear: str
  v_ego: float
  model_x: tuple
  model_v: tuple
  model_t: tuple
  lead_status: bool
  d_rel: float
  v_rel: float
  v_lead: float
  valid: bool = True
  model_age: float = 0.
  radar_age: float = 0.
  lead_id: int = -1
  traffic_mode: bool = False
  traffic_valid: bool = True


class Phase2Alerts:
  """20 Hz observational producer. Invalid data discards all prior evidence.

  Historical lead tracking is low-pass filtered while moving and held at stop.
  Stop hints use the historical 0.5 s filter/0.63 threshold, 5 m/s cruising
  threshold, half-speed future-velocity hint and horizon-minus-2 time window.
  One notification per uninterrupted stop prevents repeats after model jitter.
  """
  def __init__(self):
    self.reset()

  def reset(self):
    self.last_time = None
    self.lead_filter = 0.
    self.stop_filter = 0.
    self.tracking = False
    self.stopped_for_light = False
    self.lead_distance = None
    self.fired = set()
    self.last_lead_id = None
    self.last_lead_distance = None
    self.release_time = 0.

  @staticmethod
  def usable(s):
    arrays = (s.model_x, s.model_v, s.model_t)
    return (s.valid and s.traffic_valid and s.gear in ("drive", "low", "sport", "eco", "manumatic")
            and all(len(a) >= 2 for a in arrays) and len(s.model_t) == len(s.model_v)
            and all(math.isfinite(v) for a in arrays for v in a)
            and all(math.isfinite(v) for v in (s.now, s.v_ego, s.d_rel, s.v_rel, s.v_lead, s.model_age, s.radar_age))
            and 0 <= s.model_age <= .25 and 0 <= s.radar_age <= .25
            and s.v_ego >= 0 and s.model_x[-1] >= 0 and s.model_t[-1] > 2
            and all(b > a for a, b in zip(s.model_t, s.model_t[1:]))
            and (not s.lead_status or s.d_rel > 0))

  def update(self, s, green=True, lead=True):
    if not self.usable(s):
      self.reset()
      return ()
    if self.last_time is not None and (s.now <= self.last_time or s.now - self.last_time > .25):
      self.reset()
      self.last_time = s.now
      return ()
    dt = .05 if self.last_time is None else s.now - self.last_time
    self.last_time = s.now
    alpha = dt / (.5 + dt)
    horizon = s.model_t[-1]
    model_length = s.model_x[-1]
    model_stopped = model_length < 5 * horizon
    if not s.standstill:
      # STOP_DISTANCE is 6 m in the historical long_mpc.
      following = s.lead_status and s.d_rel < model_length + 6
      closing = s.lead_status and s.v_rel < 0 and s.d_rel + s.v_rel * horizon < model_length + 6
      self.lead_filter = (1 - alpha) * self.lead_filter + alpha * following
      self.tracking = closing or self.lead_filter >= .63
      self.stopped_for_light = False
      self.lead_distance = None
      self.fired.clear()
    # Unlike the old latch, never retain a vanished lead as usable evidence.
    tracking = self.tracking and s.lead_status
    model_time = horizon - 2
    stop_hint = (model_stopped or model_length < s.v_ego * model_time or
                 any(v <= .5 * s.v_ego for t, v in zip(s.model_t, s.model_v) if t > model_time))
    self.stop_filter = 0. if s.traffic_mode else (1 - alpha) * self.stop_filter + alpha * stop_hint
    stop_light_detected = self.stop_filter >= .63 and not tracking and not s.traffic_mode
    out = []
    if s.standstill and not tracking and not s.lead_status and not s.traffic_mode:
      releasing = not model_stopped and self.stopped_for_light
      self.release_time = self.release_time + dt if releasing else 0.
      # Confirm three normal 20 Hz model frames; a single noisy release is not a cue.
      if green and self.release_time >= .15 - 1e-6 and "GreenLightAlert" not in self.fired:
        out.append("GreenLightAlert")
      self.stopped_for_light = stop_light_detected
    else:
      self.stopped_for_light = False
      self.release_time = 0.
    if s.standstill and tracking and lead:
      identity_changed = self.last_lead_id is not None and s.lead_id != self.last_lead_id
      jumped = (self.last_lead_distance is not None and
                abs(s.d_rel - self.last_lead_distance) > max(1., abs(s.v_rel) * dt + .5))
      if identity_changed or jumped:
        self.lead_distance = None
      if self.lead_distance is None:
        self.lead_distance = s.d_rel
      if s.d_rel - self.lead_distance > 1 and s.v_lead > 1 and "LeadDepartingAlert" not in self.fired:
        out.append("LeadDepartingAlert")
    else:
      self.lead_distance = None
    self.last_lead_id = s.lead_id if tracking else None
    self.last_lead_distance = s.d_rel if tracking else None
    self.fired.update(out)
    return tuple(out)


def make_alert(key, event_api=None):
  """Use the current AlertManager + existing prompt audio, no schema changes.

  Lowest priority intentionally keeps ALL stock safety and DM alerts ahead.
  """
  if event_api is None:
    from openpilot.selfdrive.selfdrived import events as event_api
  Alert, AlertStatus, AlertSize = event_api.Alert, event_api.AlertStatus, event_api.AlertSize
  Priority, VisualAlert, AudibleAlert, ET = event_api.Priority, event_api.VisualAlert, event_api.AudibleAlert, event_api.ET
  text = {"GreenLightAlert": "Light turned green", "LeadDepartingAlert": "Lead departed"}[key]
  a = Alert(text, "", AlertStatus.normal, AlertSize.small, Priority.LOWEST, VisualAlert.none, AudibleAlert.prompt, 3.)
  a.alert_type = f"bogpilot{key}/permanent"
  a.event_type = ET.PERMANENT
  return a


class Phase2AlertRuntime:
  """SelfdriveD adapter: call every frame before AM.add_many; samples at model cadence.

  Radar/model validity AND alive/frequency/age are mandatory. No subscriptions,
  CEM mode changes or writes. No traffic mode exists in current candidate; caller
  must pass its validity if a future traffic-mode provider is introduced.
  """
  def __init__(self, store=None):
    if store is None:
      from openpilot.common.bogpilot_store import ParamStore
      store = ParamStore(cache_ttl=1.)
    self.store = store
    self.producer = Phase2Alerts()

  def update(self, cs, sm, now, traffic_mode=False, traffic_valid=True):
    if not sm.updated["modelV2"]:
      return ()
    try:
      model, lead = sm["modelV2"], sm["radarState"].leadOne
      s = AlertInput(now, cs.standstill, str(cs.gearShifter), cs.vEgo,
                     tuple(model.position.x), tuple(model.velocity.x), tuple(model.velocity.t),
                     lead.present, lead.dRel, lead.vRel, lead.vLead,
                     valid=bool(cs.canValid and sm.all_checks(["modelV2", "radarState"])),
                     model_age=now - sm.recv_time["modelV2"], radar_age=now - sm.recv_time["radarState"],
                     lead_id=lead.radarTrackId, traffic_mode=traffic_mode, traffic_valid=traffic_valid)
      return self.producer.update(s, read_enabled(self.store, "GreenLightAlert"), read_enabled(self.store, "LeadDepartingAlert"))
    except (AttributeError, KeyError, TypeError, ValueError):
      self.producer.reset()
      return ()


def add_to_alert_manager(am, frame, keys, enabled_keys=ACTIVE_ALERT_KEYS, eligible=True, event_api=None):
  """Never mask or queue behind a live stock alert, even at equal LOWEST priority.

  Discard optional notifications during stock alerts rather than replaying a
  stale green/lead cue later. Only this module's own entries may be removed.
  """
  prefix = "bogpilot"
  owned = {f"{prefix}{key}/permanent" for key in ACTIVE_ALERT_KEYS}
  stock_active = any(entry.active(frame) and entry.alert is not None and
                     (entry.alert.alert_text_1 or entry.alert.alert_text_2 or int(entry.alert.audible_alert) != 0)
                     for name, entry in am.alerts.items() if name not in owned)
  allowed = set(enabled_keys) if eligible and not stock_active else set()
  for key in ACTIVE_ALERT_KEYS:
    if key not in allowed:
      am.alerts.pop(f"{prefix}{key}/permanent", None)
  am.add_many(frame, [make_alert(key, event_api) for key in keys if key in allowed])


def create_alerts_layout(store=None):
  """Lazy raylib layout; sound lane owns the sibling Alert Volume Controller."""
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import toggle_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.system.ui.lib.multilang import tr
  if store is None:
    from openpilot.common.bogpilot_store import ParamStore
    store = ParamStore()

  class BogPilotAlertsLayout(Widget):
    def __init__(self):
      super().__init__()
      self.items = {}
      for key, title, description in ACTIVE_ALERT_ROWS:
        self.items[key] = toggle_item(lambda t=title: tr(t), lambda d=description: tr(d), read_enabled(store, key),
                                      callback=lambda state, k=key: self.write(k, state))
      self.scroller = Scroller(list(self.items.values()), line_separator=True, spacing=0)

    def write(self, key, state):
      store.put_bool(key, bool(state))
      store.invalidate(key)

    def show_event(self):
      super().show_event()
      self.scroller.show_event()
      for key, item in self.items.items():
        item.action_item.set_state(read_enabled(store, key))

    def _render(self, rect):
      self.scroller.render(rect)

  return BogPilotAlertsLayout()
