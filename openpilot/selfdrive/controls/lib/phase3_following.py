"""Phase 3: Driving Personalities, Human-Like Following, Lead Detection Confidence Threshold and the
AP1 stalk -> LongitudinalPersonality sync, ported from own 0.9.7 bogpilot-tesla 04d560f3.

Sources (04d560f3):
  bogpilot/common/bogpilot_variables.py:849-869, 1001-1004   toggle formulas (tuning level, clip, defaults)
  bogpilot/controls/lib/bogpilot_following.py                BogPilotFollowing.update / update_follow_values
  bogpilot/controls/bogpilot_planner.py:110-129, 136-141     tracking_lead filter, bogpilotPlan jerk scaling
  selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:65-107, 346-351  get_jerk_factor / get_T_FOLLOW / set_weights
  bogpilot/controls/bogpilot_card.py:12-13, 124-176          _apply_ap1_stalk / _sync_ap1_personality
  selfdrive/controls/radard.py:219, 227, 350                   lead_detection_probability gate

Activation (same rule as phase3_long_accel): a group is consumed only after the user changes one of
its rows in the new panel (configure()/reset_personality() write an adoption marker). Without the marker
every consumer returns None and the caller keeps the exact current stock path, so deploying this module
does not wake dormant stored tuning (e.g. the AP1 profile's CustomPersonalities=1 / RelaxedFollow=2.0).
Nothing here writes defaults, CAN, safety, ACCEL_MIN/MAX, FCW or MPC constraints.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# 04d560f3 bogpilot_variables.py:37-45 and long_mpc.py:59-60 / 39-41
CITY_SPEED_LIMIT = 25        # m/s
CRUISING_SPEED = 5           # m/s
MAX_T_FOLLOW = 3.0
THRESHOLD = 0.63
PLANNER_TIME = 10.0          # ModelConstants.T_IDXS[-1]
STOP_DISTANCE = 6.0
COMFORT_BRAKE = 2.5
A_CHANGE_COST = 200.
DANGER_ZONE_COST = 100.
J_EGO_COST = 5.0

# bogpilot_following.py:10-16
TRAFFIC_JERK_BP = [0.0, CITY_SPEED_LIMIT]
TRAFFIC_ACCELERATION_JERK = [0.50, 0.50]
TRAFFIC_DANGER_JERK = [0.50, 0.50]
TRAFFIC_SPEED_JERK = [0.50, 0.50]
TRAFFIC_FOLLOW_BP = [0.0, CRUISING_SPEED]
TRAFFIC_FOLLOW = [0.50, 1.00]

# cereal LongitudinalPersonality raw values
AGGRESSIVE, STANDARD, RELAXED = 0, 1, 2
PROFILES = ("Aggressive", "Standard", "Relaxed")
PROFILE_SUFFIXES = ("Follow", "JerkAcceleration", "JerkDeceleration", "JerkDanger", "JerkSpeed", "JerkSpeedDecrease")

PERSONALITY_ACK = "Phase3PersonalitiesEnabled"
HUMAN_FOLLOWING_ACK = "Phase3HumanFollowingEnabled"
LEAD_DETECTION_ACK = "Phase3LeadDetectionEnabled"
PERSONALITY_KEYS = ("CustomPersonalities", *(f"{p}PersonalityProfile" for p in PROFILES),
                    *(f"{p}{s}" for p in PROFILES for s in PROFILE_SUFFIXES))
HUMAN_FOLLOWING_KEYS = ("HumanFollowing",)
LEAD_DETECTION_KEYS = ("LeadDetectionThreshold",)
STOCK_LEAD_PROB = 0.5        # current radard literal (selfdrive/controls/radard.py get_lead)

# card runs at 100 Hz (bogpilot_card.py:12-13)
# ACTIVATION: "default_on" = the stored/AP1-profile/registry values apply exactly as in
# 0.9.7 (Driving Personalities, Human Following, Lead Detection read their saved values from the first drive; saved prefs are never
# rewritten). "adoption" = the earlier stock-equivalent mode (dormant until the user changes a row, marker file written by configure()).
ACTIVATION_POLICY = "default_on"
AP1_PERSONALITY_RETRY_FRAMES = 10
AP1_PERSONALITY_MAX_FRAMES = 300


def human_following_default_on(CP) -> bool:
  """Human-Like Following needs the radar. On a Pre-AP Model S that is the Bosch retrofit as it was at car start
  (preap_radar_on_at_start), so with the retrofit off it is effectively off and the row reads Off; with it on, the
  saved value applies (registry default On, an explicit Off is kept). Every other car is unchanged (True here)."""
  from openpilot.selfdrive.controls.lib.phase3_lanechange import PREAP_FINGERPRINT, preap_radar_on_at_start
  if CP is not None and str(getattr(CP, "carFingerprint", "") or "") == PREAP_FINGERPRINT:
    return preap_radar_on_at_start(CP)
  return True


def _ack_for(key):
  for keys, ack in ((PERSONALITY_KEYS, PERSONALITY_ACK), (HUMAN_FOLLOWING_KEYS, HUMAN_FOLLOWING_ACK),
                    (LEAD_DETECTION_KEYS, LEAD_DETECTION_ACK)):
    if key in keys:
      return ack
  raise ValueError(key)


def personality_adopted(store=None):
  """True once the user changed a Driving Personalities row (adoption marker). Fail closed (False) on any read problem.
  card.py gates the AP1 stalk -> LongitudinalPersonality sync on this so a fresh install keeps stock behaviour."""
  try:
    if store is None:
      from openpilot.common.bogpilot_store import ParamStore
      store = ParamStore()
    return _group_on(store, PERSONALITY_ACK)
  except Exception:
    return False


def _group_on(store, ack):
  return ACTIVATION_POLICY == "default_on" or bool(store.get_bool(ack, False))


def group_adopted(store, key):
  """Adoption state of the group that owns `key` (False on any read problem)."""
  try:
    return _group_on(store, _ack_for(key))
  except Exception:
    return False


def _put(store, method, key, value):
  """Blocking write so a read right after the tap sees the new value (the panels rebuild their child rows from it);
  small injected test stores without the keyword keep their plain write."""
  try:
    getattr(store, method)(key, value, block=True)
  except TypeError:
    getattr(store, method)(key, value)


def configure(store, key, value):
  """Only from an explicit panel action: write the user's value and adopt its group."""
  ack = _ack_for(key)
  _put(store, "put", key, value)
  _put(store, "put_bool", ack, True)
  store.invalidate()


def reset_personality(store, profile):
  """04d560f3 longitudinal_settings.cc:689-764: Reset to Defaults writes params_default (registry column 2)
  for the profile's Follow + 5 Jerk keys. Profile toggle and CustomPersonalities are not touched."""
  if profile not in PROFILES:
    raise ValueError(profile)
  for s in PROFILE_SUFFIXES:
    _put(store, "put", f"{profile}{s}", float(store.default(f"{profile}{s}")))
  _put(store, "put_bool", PERSONALITY_ACK, True)
  store.invalidate()


def _num(store, key, getter):
  """Finite stored number when honoured, else the registry default (stored NaN/Inf/garbage -> default)."""
  default = float(store.default(key))
  if not store.honoured(key):
    return default
  try:
    v = float(getattr(store, getter)(key))
  except (TypeError, ValueError, OverflowError):
    return default
  return v if math.isfinite(v) else default


@dataclass(frozen=True)
class FollowingToggles:
  custom_personalities: bool = False
  aggressive_follow: float = 1.25
  standard_follow: float = 1.45
  relaxed_follow: float = 1.75
  # (acceleration, deceleration, danger, speed, speed_decrease) per profile, 04d560f3 defaults
  aggressive_jerk: tuple = (0.5, 0.5, 1.0, 0.5, 0.5)
  standard_jerk: tuple = (1.0, 1.0, 1.0, 1.0, 1.0)
  relaxed_jerk: tuple = (1.0, 1.0, 1.0, 1.0, 1.0)
  human_following: bool = False
  lead_detection_probability: float | None = None   # None = stock radard gate
  has_radar: bool = False

  @classmethod
  def read(cls, store, CP, openpilot_longitudinal=None):
    """bogpilot_variables.py:849-869 / 1001-1004 with the adoption markers applied."""
    op_long = bool(CP.openpilotLongitudinalControl) if openpilot_longitudinal is None else bool(openpilot_longitudinal)
    out = {"has_radar": not bool(CP.radarUnavailable)}

    if _group_on(store, PERSONALITY_ACK):
      # :849 parses as (op_long and CustomPersonalities) if honoured else default
      out["custom_personalities"] = (op_long and store.get_bool("CustomPersonalities")) \
        if store.honoured("CustomPersonalities") else store.default("CustomPersonalities") == "1"
      for p in PROFILES:
        prof = out["custom_personalities"] and store.toggle_bool(f"{p}PersonalityProfile")
        def val(s, lo, hi, scale):
          key = f"{p}{s}"
          if prof and store.honoured(key):
            return float(np.clip(_num(store, key, "get_float") / scale, lo, hi))
          return float(store.default(key)) / scale
        jerks = tuple(val(s, 0.25, 2.0, 100.) for s in ("JerkAcceleration", "JerkDeceleration", "JerkDanger",
                                                         "JerkSpeed", "JerkSpeedDecrease"))
        out[f"{p.lower()}_jerk"] = jerks
        out[f"{p.lower()}_follow"] = val("Follow", 1.0, MAX_T_FOLLOW, 1.)

    longitudinal_tuning = op_long and store.toggle_bool("LongitudinalTune")
    if _group_on(store, HUMAN_FOLLOWING_ACK):
      out["human_following"] = bool(longitudinal_tuning and store.toggle_bool("HumanFollowing") and human_following_default_on(CP))
    if _group_on(store, LEAD_DETECTION_ACK):
      key = "LeadDetectionThreshold"
      if longitudinal_tuning and store.honoured(key):
        out["lead_detection_probability"] = float(np.clip(_num(store, key, "get_float") / 100., 0.25, 0.50))
      else:
        out["lead_detection_probability"] = float(store.default(key)) / 100.
    return cls(**out)


def lead_detection_threshold(toggles):
  """radard get_lead / AP1 lead-filter threshold. Stock literal unless the user adopted the row."""
  p = toggles.lead_detection_probability
  return STOCK_LEAD_PROB if p is None else p


_NAMES = {"aggressive": AGGRESSIVE, "standard": STANDARD, "relaxed": RELAXED}


def personality_int(p):
  """capnp enum / str / int -> 0, 1, 2 (unknown raises like long_mpc)."""
  raw = getattr(p, "raw", p)
  if isinstance(raw, str):
    if raw in _NAMES:
      return _NAMES[raw]
    raise NotImplementedError("Longitudinal personality not supported")
  if isinstance(raw, bool) or int(raw) not in (0, 1, 2):
    raise NotImplementedError("Longitudinal personality not supported")
  return int(raw)


def get_jerk_factor(toggles, personality, accelerating):
  """long_mpc.py:65-87 custom branch; accelerating picks Acceleration/Speed vs Deceleration/SpeedDecrease
  (bogpilot_following.py:37-50). Returns (acceleration, danger, speed)."""
  j = {AGGRESSIVE: toggles.aggressive_jerk, STANDARD: toggles.standard_jerk, RELAXED: toggles.relaxed_jerk}.get(personality_int(personality))
  if j is None:
    raise NotImplementedError("Longitudinal personality not supported")
  return (j[0], j[2], j[3]) if accelerating else (j[1], j[2], j[4])


def get_T_FOLLOW(toggles, personality):
  t = {AGGRESSIVE: toggles.aggressive_follow, STANDARD: toggles.standard_follow,
       RELAXED: toggles.relaxed_follow}.get(personality_int(personality))
  if t is None:
    raise NotImplementedError("Longitudinal personality not supported")
  return t


def live_stalk_seconds(seconds, toggles):
  """opendbc tesla_ap1/stalk_follow.live_follow_seconds with the restored profile values (custom off ->
  identity, the stock times the personalities use then). The stalk publishes the stock detent seconds; detent 1
  (traffic) stays 1.0."""
  try:
    from opendbc.car.tesla_ap1.stalk_follow import live_follow_seconds
  except ImportError:  # pragma: no cover
    return seconds
  return live_follow_seconds(seconds, toggles)


@dataclass(frozen=True)
class FollowPlan:
  t_follow: float
  acceleration_jerk: float   # unscaled factors; mpc_weights() applies 04d560f3 bogpilot_planner.py:136-139
  danger_jerk: float
  speed_jerk: float

  def mpc_weights(self):
    return A_CHANGE_COST * self.acceleration_jerk, DANGER_ZONE_COST * self.danger_jerk, J_EGO_COST * self.speed_jerk


class TrackingLead:
  """bogpilot_planner.py:110-129 (FirstOrderFilter(0, 0.5, DT_MDL), updated only while not standstill)."""

  def __init__(self, dt=0.05):
    self.alpha = dt / (0.5 + dt)
    self.x = 0.0
    self.tracking = False

  def update(self, lead, model_length, standstill):
    if standstill:
      return self.tracking
    present = bool(getattr(lead, "present", getattr(lead, "status", False)))
    closing = present and lead.vRel < 0 and lead.dRel + lead.vRel * PLANNER_TIME < model_length + STOP_DISTANCE
    following = present and lead.dRel < model_length + STOP_DISTANCE
    self.x = (1. - self.alpha) * self.x + self.alpha * float(following)
    self.tracking = bool(closing or self.x >= THRESHOLD)
    return self.tracking


def human_follow_values(t_follow, acceleration_jerk, speed_jerk, lead_distance, v_ego, v_lead):
  """frogpilot_following.py:86-105 verbatim (FrogAi offsets)."""
  if v_lead > v_ego:
    distance_factor = max(lead_distance - (v_ego * t_follow), 1)
    accelerating_offset = float(np.clip(STOP_DISTANCE - v_ego, 1, distance_factor))
    acceleration_jerk /= accelerating_offset
    speed_jerk /= accelerating_offset
    t_follow /= accelerating_offset
  if v_lead < v_ego:
    distance_factor = max(lead_distance - (v_lead * t_follow), 1)
    braking_offset = float(np.clip(min(v_ego - v_lead, v_lead) - COMFORT_BRAKE, 1, distance_factor))
    if lead_distance >= 100:
      braking_offset += max(lead_distance - (v_ego * t_follow) - STOP_DISTANCE, 0)
    t_follow /= braking_offset
  return t_follow, acceleration_jerk, speed_jerk


class FollowingPlanner:
  """BogPilotFollowing.update for the 0.11 planner. update() returns None whenever the result would be the
  current stock path (no adopted group active), so stock personality/jerk/AP1 t_follow stay byte-identical."""

  def __init__(self, CP, toggles=None, store=None, dt=0.05, model_version=None):
    if toggles is None:
      try:
        if store is None:
          from openpilot.common.bogpilot_store import ParamStore
          store = ParamStore()
        toggles = FollowingToggles.read(store, CP)
      except Exception:
        toggles = FollowingToggles()  # fail closed -> stock
    self.toggles = toggles
    self.model_version = model_version  # 04d560f3 gate is model_version != "v9"; 0.11.2 bundle has none
    self.lead = TrackingLead(dt)
    self.plan: FollowPlan | None = None

  @property
  def active(self):
    return self.toggles.custom_personalities or self.toggles.human_following

  def update(self, *, enabled, v_ego, a_ego, personality, lead, model_length, standstill,
             traffic_mode=False, stalk_t_follow=None, weather_following_s=0.0):
    """stalk_t_follow: current Ap1Planning.t_follow() (None when not AP1/not ready/not enabled).
    weather_following_s: weather_offsets().following_seconds (0 when no real weather source)."""
    tracking = self.lead.update(lead, model_length, standstill)
    tg = self.toggles
    if not enabled or not (self.active or weather_following_s > 0):
      self.plan = None
      return None

    # bogpilot_following.py:31-57 precedence: Traffic -> personality (custom or stock factors)
    if traffic_mode:
      acc = float(np.interp(v_ego, TRAFFIC_JERK_BP, TRAFFIC_ACCELERATION_JERK))
      dan = float(np.interp(v_ego, TRAFFIC_JERK_BP, TRAFFIC_DANGER_JERK))
      spd = float(np.interp(v_ego, TRAFFIC_JERK_BP, TRAFFIC_SPEED_JERK))
      t = float(np.interp(v_ego, TRAFFIC_FOLLOW_BP, TRAFFIC_FOLLOW))
    elif tg.custom_personalities:
      acc, dan, spd = get_jerk_factor(tg, personality, a_ego >= 0)
      t = get_T_FOLLOW(tg, personality)
    else:
      # stock 0.11 weighting (current long_mpc.get_jerk_factor/get_T_FOLLOW, danger unscaled)
      pi = personality_int(personality)
      f = 0.5 if pi == AGGRESSIVE else 1.0
      acc, dan, spd = f, 1.0, f
      t = {AGGRESSIVE: 1.25, STANDARD: 1.45, RELAXED: 1.75}[pi]

    # :64-71 physical AP1 stalk replaces the follow time (mapped to the live profile seconds)
    # (identity unless custom profiles changed the follow seconds; Ap1Planning's detent-1 traffic curve and any
    # non-table value pass through unchanged)
    if stalk_t_follow is not None:
      t = float(live_stalk_seconds(float(stalk_t_follow), tg))

    # :75-76 weather add-on, capped, before human following
    if weather_following_s > 0:
      t = min(t + float(weather_following_s), MAX_T_FOLLOW)

    # :78-80
    if tracking and not traffic_mode and tg.human_following and tg.has_radar and self.model_version != "v9":
      t, acc, spd = human_follow_values(t, acc, spd, float(lead.dRel), float(v_ego), float(lead.vLead))

    self.plan = FollowPlan(float(t), float(acc), float(dan), float(spd))
    return self.plan


class Ap1PersonalitySync:
  """bogpilot_card.py:124-176 verbatim: AP1 stalk named detents (3/5/7) write LongitudinalPersonality, a
  quick twist over a named detent applies the last one crossed, the stored value is read back every 10 frames
  and rewritten until it matches, and retries stop after 300 frames so a later screen tap is never fought.
  Returns the traffic flag from ap1_stalk_commands (None = not ready / leave alone)."""

  def __init__(self, params):
    self.params = params
    self._personality = None
    self._detent = None
    self._target = None
    self._frames = 0

  def update(self, decision):
    from opendbc.car.tesla_ap1.stalk_follow import ap1_stalk_commands, crossed_personality
    traffic, personality = ap1_stalk_commands(decision)
    if traffic is None:
      return None
    detent = getattr(decision, "detent", None)
    if personality is None:
      personality = crossed_personality(self._detent, detent)
    if personality is not None and (personality != self._personality or detent != self._detent):
      self._target = personality
      self._frames = 0
    self._detent = detent
    self._sync()
    return traffic

  def _put(self, value):
    self.params.put("LongitudinalPersonality", int(value))  # 0.11 Params.put is non-blocking by default

  def _sync(self):
    target = self._target
    if target is None:
      return
    frames = self._frames
    self._frames += 1
    if frames == 0:
      self._put(target)
      self._personality = target
      return
    if frames % AP1_PERSONALITY_RETRY_FRAMES:
      return
    try:
      stored = int(self.params.get("LongitudinalPersonality"))
    except (TypeError, ValueError):
      stored = None
    if stored == target or frames >= AP1_PERSONALITY_MAX_FRAMES:
      self._target = None
      return
    self._put(target)
