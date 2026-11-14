"""Driver-feedback alerts restored from own 0.9.7 (04d560f3 events.py, controlsd.py and the 0.9.7 events module).

Nine alerts, all observational: the original five (force-stop, AP1 follow-distance, Traffic Mode,
Speed Limit Changed, loud blind-spot) plus turning left/right, no lane available, a core-process
crash warning, and the custom startup message. This module never writes a param, never changes a
CAN or planner value and never publishes a message. It turns facts the car, planner, manager and
desire helper already produce into AlertManager entries.

  force stop      bogpilotPlan.forcingStop / forcingStopLength (planner), WARNING, priority MID
  follow distance carState.bogpilot.ap1StalkFollowS changes while it stays > 0 (AP1 stalk), PERMANENT, LOW
  Traffic Mode    carState.bogpilot.trafficModeEnabled edge, PERMANENT (shown engaged or not), LOW, prompt sound
  SL changed      bogpilotPlan.speedLimitChanged rising edge, PERMANENT, LOW, prompt sound
  loud blindspot  lane change blocked by a blind-spot car, WARNING, LOW, warningSoft sound
  turning left/right  TurnDesires is on, one signal, below the minimum lane-change speed, not stopped
                  (same conditions DesireHelper already uses), WARNING, LOWEST, silent
  no lane         pre-lane-change and the adjacent lane is narrower than LaneDetectionWidth,
                  WARNING, LOWEST, silent; replaces the stock preLaneChange left/right event
  crash           /data/error_logs/error.txt exists, or a should-be-running core process is down,
                  IMMEDIATE_DISABLE, HIGHEST, prompt sound
  startup         saved StartupMessageTop / StartupMessageBottom (old third-party defaults migrated
                  on read, custom text kept), PERMANENT, LOWER, silent, 5 s

Toggles 0.9.7 had: LoudBlindspotAlert and SpeedLimitChangedAlert (0.9.7 shipped them OFF; here a fresh
install is ON, a saved choice always wins). TurnDesires (default OFF) and LaneDetectionWidth (default 0,
off) already exist and already have consumers; they gate the turn and no-lane alerts and are not
duplicated here. The force-stop, follow-distance, Traffic Mode, crash and startup alerts had no
toggle in 0.9.7 and have none here. The CustomAlerts master gate is not used (same decision as
Green Light / Lead Departed).

Audio contract (no schema change): prompt -> warning.wav once, warningSoft -> critical.wav while the
alert stays up, both through the existing Alert Volume Controller keys (PromptVolume, WarningSoftVolume).
"""
from dataclasses import dataclass
import math

HISTORICAL_REVISION = "04d560f3ece97797b8f1ee2f714e682e6d0ef40e"

DRIVER_ALERT_ROWS = (
  ("LoudBlindspotAlert", "Loud Car in Blindspot Alert",
   "Play a louder alert if a vehicle is in the blind spot when you try to change lanes. Only for cars that report blind spot monitoring."),
  ("SpeedLimitChangedAlert", "Speed Limit Changed Alert",
   "Play an alert when the posted speed limit changes. Needs the Speed Limit Controller."),
)
DRIVER_ALERT_KEYS = tuple(row[0] for row in DRIVER_ALERT_ROWS)
# Fresh install ON (maintainer choice, same as Green Light / Lead Departed). A saved OFF is never overwritten:
# nothing in the profile, defaults table or migration writes these keys.
DRIVER_ALERT_DEFAULTS = dict.fromkeys(DRIVER_ALERT_KEYS, True)

FOLLOW_ALERT_SECONDS = 1.0
FOLLOW_CHANGE_EPSILON = 1e-3
PLAN_MAX_AGE = .5            # bogpilotPlan publishes at 20 Hz
STAMP = "bogpilot"
OWNED_ALERT_TYPES = (
  f"{STAMP}ForcingStop/warning",
  f"{STAMP}AP1FollowDistance/permanent",
  f"{STAMP}TrafficModeOn/permanent",
  f"{STAMP}TrafficModeOff/permanent",
  f"{STAMP}SpeedLimitChanged/permanent",
  f"{STAMP}LoudBlindspot/warning",
  f"{STAMP}TurningLeft/warning",
  f"{STAMP}TurningRight/warning",
  f"{STAMP}NoLaneAvailable/warning",
  f"{STAMP}OpenpilotCrashed/immediateDisable",
  f"{STAMP}CustomStartup/permanent",
)
METER_TO_FOOT = 3.28084
STOCK_MIN_LANE_CHANGE_SPEED = 20 * 0.44704

# 0.9.7 variables module: StartupMessageTop / StartupMessageBottom. The infinity sign is the
# official default (U+221E); a custom saved string always wins. Old third-party defaults are treated
# as unset.
STARTUP_MESSAGE_TOP = "Your m\u221ev"
STARTUP_MESSAGE_BOTTOM = "Hands present, mind at ease"
OLD_STARTUP_MESSAGES_TOP = frozenset({"Hop in and buckle up!"})
OLD_STARTUP_MESSAGES_BOTTOM = frozenset({
  "Human-tested, frog-approved \U0001f438",
  "Human-tested, frog-approved",
})


def resolve_startup_message(value, old_values, new_value):
  if value is None or str(value).strip() == "" or str(value).strip() in old_values:
    return new_value
  return value


def read_startup_messages(top=None, bottom=None):
  return (
    resolve_startup_message(top, OLD_STARTUP_MESSAGES_TOP, STARTUP_MESSAGE_TOP),
    resolve_startup_message(bottom, OLD_STARTUP_MESSAGES_BOTTOM, STARTUP_MESSAGE_BOTTOM),
  )


def read_enabled(store, key):
  """Saved choice, else ON (fresh install). Never gated by CustomAlerts. A store failure reads as OFF."""
  try:
    return bool(store.get_bool(key, default=DRIVER_ALERT_DEFAULTS[key]))
  except Exception:
    return False


@dataclass(frozen=True)
class DriverInput:
  now: float
  can_valid: bool = True
  warning_ok: bool = False       # ET.WARNING is a live alert type, i.e. openpilot is engaged and active
  follow_s: float = 0.            # carState.bogpilot.ap1StalkFollowS, 0 = no detent
  live_follow_s: float = 0.       # the same detent mapped to the user's live follow times (0 = unknown)
  traffic_mode: bool = False
  plan_valid: bool = False        # bogpilotPlan alive, valid and fresh
  plan_updated: bool = False      # a new bogpilotPlan arrived since the last call
  forcing_stop: bool = False
  forcing_length: float = 0.
  slc_changed: bool = False
  blindspot_blocked: bool = False
  loud_blindspot: bool = False    # LoudBlindspotAlert saved ON
  slc_alert: bool = False         # SpeedLimitChangedAlert saved ON
  left_blinker: bool = False
  right_blinker: bool = False
  v_ego: float = 0.
  standstill: bool = False
  turn_desires: bool = False      # TurnDesires adopted and ON; DesireHelper already consumes this
  min_lane_change_speed: float = STOCK_MIN_LANE_CHANGE_SPEED
  pre_lane_change: bool = False
  lane_change_left: bool = False
  lane_width: float | None = None  # metres; None = geometry unavailable
  min_lane_width: float = 0.       # metres; 0 means the width gate is off
  error_log: bool = False
  core_process_down: bool = False
  startup: bool = False
  startup_top: str = STARTUP_MESSAGE_TOP
  startup_bottom: str = STARTUP_MESSAGE_BOTTOM


def _finite(*values):
  return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def turning_active(s):
  """Same gates DesireHelper uses for turnLeft/turnRight: one signal, moving, below the LC speed floor."""
  one = bool(s.left_blinker) != bool(s.right_blinker)
  return bool(
    s.turn_desires and s.warning_ok and s.can_valid and one and not s.standstill
    and _finite(s.v_ego, s.min_lane_change_speed) and s.v_ego > 0 and s.v_ego < s.min_lane_change_speed
  )


def no_lane_blocked(s):
  """preLaneChange and the adjacent lane is narrower than the saved minimum (or the width is unknown)."""
  if not s.pre_lane_change or s.blindspot_blocked or not s.warning_ok:
    return False
  if not _finite(s.min_lane_width) or s.min_lane_width <= 0:
    return False
  return s.lane_width is None or ( _finite(s.lane_width) and s.lane_width < s.min_lane_width)


class DriverAlerts:
  """Edge/level detectors, one call per selfdrived frame. Returns a tuple of (name, arg) requests.

  Invalid data never produces an alert and never counts as a transition: an edge is only taken
  between two valid samples, so a restart, a stale plan or a CAN dropout cannot replay a cue.
  """

  def __init__(self):
    self.reset()

  def reset(self):
    self.prev_follow = 0.
    self.follow_until = None
    self.prev_traffic = None
    self.prev_slc = False

  def update(self, s):
    out = []
    if not _finite(s.now):
      self.reset()
      return ()

    # --- crash: level, while the error marker is present or a core process is down ----------------------
    if s.error_log or s.core_process_down:
      out.append(("OpenpilotCrashed", None))

    # --- startup: one-shot; AlertManager holds the 5 s duration ----------------------------------------
    if s.startup:
      out.append(("CustomStartup", read_startup_messages(s.startup_top, s.startup_bottom)))

    # --- force stop: level, shown for as long as the planner says it is forcing the stop -----------------
    if s.plan_valid and s.warning_ok and s.forcing_stop and _finite(s.forcing_length) and s.forcing_length >= 0:
      out.append(("ForcingStop", float(s.forcing_length)))

    # --- speed limit changed: rising edge of the planner flag between two valid plan messages -----------
    if s.plan_updated or not s.plan_valid:
      if s.plan_valid:
        if s.slc_changed and not self.prev_slc and s.slc_alert:
          out.append(("SpeedLimitChanged", None))
        self.prev_slc = bool(s.slc_changed)
      else:
        self.prev_slc = False

    if s.can_valid:
      # --- follow distance: a changed detent while one was already ready; hold for ~1 s -----------------
      f = s.follow_s if _finite(s.follow_s) else 0.
      if f > 0:
        if self.prev_follow > 0 and abs(f - self.prev_follow) > FOLLOW_CHANGE_EPSILON:
          self.follow_until = s.now + FOLLOW_ALERT_SECONDS
        self.prev_follow = f
      if self.follow_until is not None:
        if s.now < self.follow_until:
          live = s.live_follow_s if _finite(s.live_follow_s) and s.live_follow_s > 0 else self.prev_follow
          out.append(("AP1FollowDistance", float(live)))
        else:
          self.follow_until = None

      # --- Traffic Mode: edge only; the first sample after (re)start just records the state -------------
      traffic = bool(s.traffic_mode)
      if self.prev_traffic is not None and traffic != self.prev_traffic:
        out.append(("TrafficModeOn" if traffic else "TrafficModeOff", None))
      self.prev_traffic = traffic

    # --- loud blind spot: level, replaces the quiet stock "Car Detected in Blindspot" ---------------------
    if s.blindspot_blocked and s.loud_blindspot and s.warning_ok:
      out.append(("LoudBlindspot", None))

    # --- no lane: level, replaces preLaneChange left/right when the adjacent lane is too narrow ----------
    if no_lane_blocked(s):
      width = 0. if s.lane_width is None or not _finite(s.lane_width) else float(s.lane_width)
      out.append(("NoLaneAvailable", width))

    # --- turning: level, only while DesireHelper would publish a turn desire -----------------------------
    elif turning_active(s):
      out.append(("TurningLeft" if s.left_blinker else "TurningRight", None))

    return tuple(out)


def _length_text(meters, metric):
  return f"{meters:.1f} meters" if metric else f"{meters * METER_TO_FOOT:.1f} feet"


def make_alert(name, arg=None, metric=False, event_api=None):
  """AlertManager entry for one request. Priorities and sounds follow 0.9.7 events.py.

  event_api is optional so Mac-native tests can AST-load the real Alert classes without msgq.
  Startup default text keeps the official infinity sign (U+221E); other texts are ASCII.
  """
  if event_api is None:
    from openpilot.selfdrive.selfdrived import events as event_api
  Alert, AlertStatus, AlertSize = event_api.Alert, event_api.AlertStatus, event_api.AlertSize
  Priority, VisualAlert, AudibleAlert, ET = event_api.Priority, event_api.VisualAlert, event_api.AudibleAlert, event_api.ET
  none = VisualAlert.none
  if name == "ForcingStop":
    a = Alert(f"Forcing the car to stop in {_length_text(arg, metric)}", "Press the gas pedal or 'Resume' button to override",
              AlertStatus.userPrompt, AlertSize.mid, Priority.MID, none, AudibleAlert.prompt, 1.)
    et = ET.WARNING
  elif name == "AP1FollowDistance":
    label = " (traffic)" if 0 < arg <= 1.0 + 1e-6 else ""
    a = Alert(f"Follow distance: {arg:.2f} s{label}", "", AlertStatus.normal, AlertSize.small,
              Priority.LOW, none, AudibleAlert.none, FOLLOW_ALERT_SECONDS)
    et = ET.PERMANENT
  elif name == "TrafficModeOn":
    a = Alert("Traffic Mode enabled", "", AlertStatus.normal, AlertSize.small, Priority.LOW, none, AudibleAlert.prompt, 3.)
    et = ET.PERMANENT
  elif name == "TrafficModeOff":
    a = Alert("Traffic Mode Disabled", "", AlertStatus.normal, AlertSize.small, Priority.LOW, none, AudibleAlert.prompt, 3.)
    et = ET.PERMANENT
  elif name == "SpeedLimitChanged":
    a = Alert("Speed limit changed", "", AlertStatus.normal, AlertSize.small, Priority.LOW, none, AudibleAlert.prompt, 3.)
    et = ET.PERMANENT
  elif name == "LoudBlindspot":
    a = Alert("Car Detected in Blindspot", "", AlertStatus.userPrompt, AlertSize.small, Priority.LOW, none,
              AudibleAlert.warningSoft, .1)
    et = ET.WARNING
  elif name == "TurningLeft":
    a = Alert("Turning left", "", AlertStatus.normal, AlertSize.small, Priority.LOWEST, none, AudibleAlert.none, .1)
    et = ET.WARNING
  elif name == "TurningRight":
    a = Alert("Turning right", "", AlertStatus.normal, AlertSize.small, Priority.LOWEST, none, AudibleAlert.none, .1)
    et = ET.WARNING
  elif name == "NoLaneAvailable":
    a = Alert("No lane available", f"Detected lane width is only {_length_text(arg, metric)}",
              AlertStatus.normal, AlertSize.mid, Priority.LOWEST, none, AudibleAlert.none, .2)
    et = ET.WARNING
  elif name == "OpenpilotCrashed":
    a = Alert("openpilot crashed", "Post the 'Error Log' at github.com/BogPilot/openpilot/issues",
              AlertStatus.critical, AlertSize.mid, Priority.HIGHEST, none, AudibleAlert.prompt, .1)
    et = ET.IMMEDIATE_DISABLE
  elif name == "CustomStartup":
    top, bottom = arg
    a = Alert(top, bottom, AlertStatus.normal, AlertSize.mid, Priority.LOWER, none, AudibleAlert.none, 5.)
    et = ET.PERMANENT
  else:
    raise ValueError(name)
  a.alert_type = f"{STAMP}{name}/{et}"
  a.event_type = et
  return a


def add_to_alert_manager(am, frame, requests, metric=False, event_api=None):
  """Add this frame's requests. Entries are not removed here: each one ends on its own duration, and a
  WARNING entry also ends the moment openpilot stops being engaged (AlertManager clear_event_types)."""
  am.add_many(frame, [make_alert(name, arg, metric, event_api) for name, arg in requests])


def _optional_failure():
  # Best-effort LOCAL diagnostic only; optional alerts must never become a fault.
  try:
    from openpilot.common.swaglog import cloudlog
    cloudlog.exception("BogPilot driver alerts disabled until selfdrived restart")
  except Exception:
    pass


def _read_text(store, key):
  try:
    if hasattr(store, "get"):
      value = store.get(key)
    elif hasattr(store, "raw"):
      value = store.raw(key)
    else:
      value = None
    if value is None:
      return None
    if isinstance(value, bytes):
      return value.decode("utf-8")
    return str(value)
  except Exception:
    return None


class DriverAlertRuntime:
  """SelfdriveD adapter. Own SubMaster for bogpilotPlan (selfdrived's main one stays untouched, so a missing
  planner can never raise commIssue). Every input is optional: a missing field means no alert, never a fault."""

  def __init__(self, CP=None, store=None, plan_sm=None):
    if store is None:
      from openpilot.common.bogpilot_store import ParamStore
      store = ParamStore(cache_ttl=1.)
    if plan_sm is None:
      import openpilot.cereal.messaging as messaging
      plan_sm = messaging.SubMaster(["bogpilotPlan"])
    self.CP = CP
    self.store = store
    self.plan_sm = plan_sm
    self.detect = DriverAlerts()
    self._follow_toggles = None
    self._follow_toggles_t = -1e9
    self._lane_settings = None
    self._lane_settings_t = -1e9
    self.injected_settings = None  # tests only

  # -- toggles --------------------------------------------------------------------------------------------
  def loud_blindspot_enabled(self):
    return read_enabled(self.store, "LoudBlindspotAlert")

  def _settings(self, now):
    if self.injected_settings is not None:
      return self.injected_settings
    if now - self._lane_settings_t > 2.:
      self._lane_settings_t = now
      try:
        from openpilot.selfdrive.controls.lib.phase3_lanechange import read_settings
        self._lane_settings = read_settings(self.store, self.CP)
      except Exception:
        self._lane_settings = None
    return self._lane_settings

  def no_lane_available(self, cs, sm, direction, now=None):
    """Used from selfdrived.update_events: whether to suppress the stock preLaneChange left/right event.

    Returns (blocked, width_m). width is 0.0 when geometry is unavailable. Fail open (no suppress)
    if settings or model geometry cannot be read, so stock behaviour is unchanged. Blind-spot
    blocking is decided by the caller, which keeps the stock/loud blind-spot path in charge.
    """
    try:
      from openpilot.selfdrive.controls.lib.phase3_lanechange import adjacent_lane_width
      from openpilot.cereal import log
      settings = self._settings(time_now(now))
      if settings is None or settings.minimum_width <= 0:
        return False, 0.
      left = direction == log.LaneChangeDirection.left
      model = sm["modelV2"] if sm is not None else None
      model_valid = False
      try:
        model_valid = bool(sm.alive["modelV2"] and sm.valid["modelV2"])
      except (AttributeError, KeyError, TypeError):
        model_valid = model is not None
      width = adjacent_lane_width(model, left) if model_valid else None
      blocked = width is None or width < float(settings.minimum_width)
      return bool(blocked), 0. if width is None else float(width)
    except Exception:
      return False, 0.

  def startup_texts(self):
    return read_startup_messages(_read_text(self.store, "StartupMessageTop"),
                                 _read_text(self.store, "StartupMessageBottom"))

  # -- live follow seconds for the detent, as the planner uses them (custom profile values, else defaults) --
  def _live_follow(self, follow_s, now):
    if not follow_s > 0:
      return 0.
    if now - self._follow_toggles_t > 1.:
      self._follow_toggles_t = now
      try:
        from openpilot.selfdrive.controls.lib.phase3_following import FollowingToggles
        self._follow_toggles = FollowingToggles.read(self.store, self.CP)
      except Exception:
        self._follow_toggles = None     # default follow times: the stalk seconds as published
    try:
      from openpilot.selfdrive.controls.lib.phase3_following import live_stalk_seconds
      return float(live_stalk_seconds(follow_s, self._follow_toggles))
    except Exception:
      return float(follow_s)

  # -- one frame --------------------------------------------------------------------------------------------
  def update(self, cs, now, warning_ok, blindspot_blocked=False, not_running=None, startup=False,
             no_lane=None, error_log=None):
    sm = self.plan_sm
    sm.update(0)
    plan_ok = False
    plan_updated = False
    forcing, length, slc = False, 0., False
    try:
      plan_updated = bool(sm.updated["bogpilotPlan"])
      plan_ok = bool(sm.alive["bogpilotPlan"] and sm.valid["bogpilotPlan"] and 0 <= now - sm.recv_time["bogpilotPlan"] <= PLAN_MAX_AGE)
      if plan_ok:
        plan = sm["bogpilotPlan"]
        forcing, length, slc = bool(plan.forcingStop), float(plan.forcingStopLength), bool(plan.speedLimitChanged)
    except (AttributeError, KeyError, TypeError, ValueError):
      plan_ok = False
    bp = getattr(cs, "bogpilot", None)
    follow = float(getattr(bp, "ap1StalkFollowS", 0.) or 0.)
    settings = self._settings(now)
    turn_desires = bool(getattr(settings, "turn_desires", False)) if settings is not None else False
    min_speed = float(getattr(settings, "minimum_speed", STOCK_MIN_LANE_CHANGE_SPEED)) if settings is not None else STOCK_MIN_LANE_CHANGE_SPEED
    pre_lane_change = False
    lane_change_left = False
    lane_width = None
    min_width = 0.
    if no_lane is not None:
      pre_lane_change, lane_width = bool(no_lane[0]), no_lane[1]
      lane_change_left = bool(no_lane[2]) if len(no_lane) > 2 else False
      min_width = float(getattr(settings, "minimum_width", 0.) or 0.) if settings is not None else 0.
    if error_log is None:
      try:
        from openpilot.system.bogpilot.crash_log import error_log_present
        error_log = error_log_present()
      except Exception:
        error_log = False
    top, bottom = self.startup_texts()
    s = DriverInput(
      now=now, can_valid=bool(cs.canValid), warning_ok=bool(warning_ok),
      follow_s=follow, live_follow_s=self._live_follow(follow, now),
      traffic_mode=bool(getattr(bp, "trafficModeEnabled", False)),
      plan_valid=plan_ok, plan_updated=plan_updated, forcing_stop=forcing, forcing_length=length, slc_changed=slc,
      blindspot_blocked=bool(blindspot_blocked), loud_blindspot=self.loud_blindspot_enabled(),
      slc_alert=read_enabled(self.store, "SpeedLimitChangedAlert"),
      left_blinker=bool(getattr(cs, "leftBlinker", False)),
      right_blinker=bool(getattr(cs, "rightBlinker", False)),
      v_ego=float(getattr(cs, "vEgo", 0.) or 0.),
      standstill=bool(getattr(cs, "standstill", False)),
      turn_desires=turn_desires,
      min_lane_change_speed=min_speed,
      pre_lane_change=pre_lane_change,
      lane_change_left=lane_change_left,
      lane_width=lane_width,
      min_lane_width=min_width,
      error_log=bool(error_log),
      core_process_down=bool(not_running),
      startup=bool(startup),
      startup_top=top,
      startup_bottom=bottom)
    return self.detect.update(s)


def time_now(now):
  if now is not None:
    return now
  import time
  return time.monotonic()


def dispatch_driver_alerts(runtime, am, frame, cs, now, warning_ok, metric, blindspot_blocked=False, event_api=None,
                           not_running=None, startup=False, no_lane=None, error_log=None):
  """Only optional work is guarded; stock creation/add/process stay outside. False means: disable this
  runtime until selfdrived restarts (and the caller falls back to the stock quiet blind-spot alert)."""
  try:
    requests = runtime.update(cs, now, warning_ok, blindspot_blocked, not_running=not_running,
                              startup=startup, no_lane=no_lane, error_log=error_log)
    add_to_alert_manager(am, frame, requests, metric, event_api)
    return True
  except Exception:
    for alert_type in OWNED_ALERT_TYPES:
      try:
        am.alerts.pop(alert_type, None)
      except Exception:
        pass
    _optional_failure()
    return False


def create_driver_alert_runtime(CP=None):
  try:
    return DriverAlertRuntime(CP)
  except Exception:
    _optional_failure()
    return None
