"""BogPilot: the onroad toggles the publishers need, computed as 367e1fe frogpilot_variables.py did.

Only the subset used by radard (adjacent leads), plannerd (frogpilotPlan: speed limit, follow distance,
lane widths) and soundd. Every formula below names its 367e1fe source line in a comment; the tuning-level
rule (a key above the user's level reads as its default) comes from ParamStore.toggle_*.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

CV_MPH_TO_MS = 0.44704
CV_KPH_TO_MS = 1 / 3.6
CV_FOOT_TO_METER = 0.3048
MAX_T_FOLLOW = 3.0  # frogpilot_variables.py
THRESHOLD = 0.63    # frogpilot_variables.py: requires the condition to be true for ~1 second
AP1_FINGERPRINT = "TESLA_AP1_MODELS"

# keys whose change means "toggles updated" (frogpilotPlan.togglesUpdated)
WATCHED_KEYS = (
  "TuningLevel", "TuningLevelConfirmed", "IsMetric", "DebugMode", "DisableOpenpilotLongitudinal",
  "DeveloperUI", "DeveloperWidgets", "AdjacentLeadsUI", "LongitudinalTune", "HumanLaneChanges",
  "NavigationUI", "ShowSpeedLimits", "SpeedLimitController", "ShowSLCOffset", "SLCFallback", "SLCOverride",
  "SLCConfirmation", "SLCConfirmationHigher", "SLCConfirmationLower", "SLCPriority1", "SLCPriority2",
  "SLCPriority3", "SLCLookaheadHigher", "SLCLookaheadLower", "Offset1", "Offset2", "Offset3", "Offset4",
  "Offset5", "Offset6", "Offset7", "CustomPersonalities", "AggressivePersonalityProfile", "AggressiveFollow",
  "StandardPersonalityProfile", "StandardFollow", "RelaxedPersonalityProfile", "RelaxedFollow",
  "AlertVolumeControl", "EngageVolume", "DisengageVolume", "RefuseVolume", "PromptVolume",
  "PromptDistractedVolume", "WarningSoftVolume", "WarningImmediateVolume", "HolidayThemes",
  "PersonalizeOpenpilot", "CustomColors", "CustomDistanceIcons", "CustomIcons", "CustomSignals", "CustomSounds",
  "WheelIcon", "CustomUI", "AdjacentPath", "BlindSpotPath", "DeveloperMetrics", "AdjacentPathMetrics",
  "LaneChanges", "LaneDetectionWidth", "MinimumLaneChangeSpeed",
)


def toggles_signature(store) -> tuple:
  return tuple(store.raw(k) for k in WATCHED_KEYS)


def _gated_and(store, gate: bool, key: str, level: int) -> bool:
  """367e1fe `x = gate and params.get_bool(K) if level ok else default.get_bool(K)` (Python precedence)."""
  if store.honoured(key, level):
    return gate and store.get_bool(key)
  return store.toggle_bool(key, -1)


def onroad_toggles(store, CP=None) -> SimpleNamespace:
  t = SimpleNamespace()
  level = store.tuning_level()
  t.tuning_level = level
  b = lambda k: store.toggle_bool(k, level)  # noqa: E731

  t.debug_mode = store.get_bool("DebugMode", False)                                # :689
  t.is_metric = store.get_bool("IsMetric", False)                                  # :695
  speed_conversion = CV_KPH_TO_MS if t.is_metric else CV_MPH_TO_MS                 # :698
  distance_conversion = 1.0 if t.is_metric else CV_FOOT_TO_METER

  fingerprint = str(getattr(CP, "carFingerprint", "") or "")
  t.car_model = fingerprint
  t.is_ap1 = fingerprint == AP1_FINGERPRINT
  t.has_radar = not bool(getattr(CP, "radarUnavailable", True))                    # :735
  t.has_bsm = bool(getattr(CP, "enableBsm", False))
  t.openpilot_longitudinal = bool(getattr(CP, "openpilotLongitudinalControl", False)) and not b("DisableOpenpilotLongitudinal")  # :744

  # :849-870 custom personalities
  t.custom_personalities = _gated_and(store, t.openpilot_longitudinal, "CustomPersonalities", level)
  for name in ("Aggressive", "Standard", "Relaxed"):
    profile = t.custom_personalities and b(f"{name}PersonalityProfile")
    key = f"{name}Follow"
    if profile and store.honoured(key, level):
      val = float(np.clip(store.get_float(key), 1, MAX_T_FOLLOW))
    else:
      val = store.toggle_float(key, -1)
    setattr(t, f"{name.lower()}_follow", val)

  # :882 / :908 / :909 developer widgets and adjacent leads
  t.developer_ui = b("DeveloperUI")
  developer_widgets = _gated_and(store, t.developer_ui, "DeveloperWidgets", level)
  t.adjacent_lead_tracking = t.has_radar and (_gated_and(store, developer_widgets, "AdjacentLeadsUI", level) or t.debug_mode)

  # :998 / :1003 human lane changes
  longitudinal_tuning = t.openpilot_longitudinal and b("LongitudinalTune")
  t.human_lane_changes = longitudinal_tuning and t.has_radar and b("HumanLaneChanges")

  # :874 / :875 / :889 / :974-975 lane widths (frogpilot_planner.py check_lane_width)
  custom_ui = b("CustomUI")
  t.adjacent_paths = custom_ui and b("AdjacentPath")
  t.blind_spot_path = t.has_bsm and ((custom_ui and b("BlindSpotPath")) or t.debug_mode)
  developer_metrics = b("DeveloperMetrics")
  t.adjacent_path_metrics = _gated_and(store, developer_metrics, "AdjacentPathMetrics", level) or t.debug_mode
  t.lane_changes = b("LaneChanges")
  if t.lane_changes and store.honoured("LaneDetectionWidth", level):
    t.lane_detection_width = store.get_float("LaneDetectionWidth") * distance_conversion
  else:
    t.lane_detection_width = store.toggle_float("LaneDetectionWidth", -1) * CV_FOOT_TO_METER
  t.lane_detection = t.lane_detection_width > 0
  if t.lane_changes and store.honoured("MinimumLaneChangeSpeed", level):
    t.minimum_lane_change_speed = store.get_float("MinimumLaneChangeSpeed") * speed_conversion
  else:
    t.minimum_lane_change_speed = store.toggle_float("MinimumLaneChangeSpeed", -1) * CV_MPH_TO_MS

  # :1051 / :1056 speed limit display
  t.navigation_ui = b("NavigationUI")
  t.show_speed_limits = t.navigation_ui and b("ShowSpeedLimits")

  # :1127-1156 speed limit controller
  slc = t.openpilot_longitudinal and b("SpeedLimitController")
  t.speed_limit_controller = slc
  gated_int = lambda k: store.get_int(k) if slc and store.honoured(k, level) else store.toggle_int(k, -1)  # noqa: E731
  gated_str = lambda k: store.get(k) if slc and store.honoured(k, level) else store.toggle_str(k, -1)  # noqa: E731
  gated_bool = lambda gate, k: gate and (store.get_bool(k) if store.honoured(k, level) else store.toggle_bool(k, -1))  # noqa: E731
  t.map_speed_lookahead_higher = gated_int("SLCLookaheadHigher")
  t.map_speed_lookahead_lower = gated_int("SLCLookaheadLower")
  t.show_speed_limit_offset = gated_bool(slc, "ShowSLCOffset") or t.debug_mode
  fallback = gated_int("SLCFallback")
  t.slc_fallback_experimental_mode = fallback == 1
  t.slc_fallback_previous_speed_limit = fallback == 2
  t.slc_fallback_set_speed = fallback == 0
  t.slc_mapbox_filler = False  # BogPilot: no Mapbox filler on 0.11.2 yet
  t.speed_limit_confirmation = gated_bool(slc, "SLCConfirmation")
  t.speed_limit_confirmation_higher = gated_bool(t.speed_limit_confirmation, "SLCConfirmationHigher")
  t.speed_limit_confirmation_lower = gated_bool(t.speed_limit_confirmation, "SLCConfirmationLower")
  override = gated_int("SLCOverride")
  t.speed_limit_controller_override_manual = override == 1
  t.speed_limit_controller_override_set_speed = override == 2
  for i in range(1, 8):
    key = f"Offset{i}"
    if not slc:
      val = 0.0
    elif store.honoured(key, level):
      val = store.get_int(key) * speed_conversion
    else:
      val = store.toggle_int(key, -1) * CV_MPH_TO_MS
    setattr(t, f"speed_limit_offset{i}", val)
  t.speed_limit_priority1 = gated_str("SLCPriority1")
  t.speed_limit_priority2 = gated_str("SLCPriority2")
  t.speed_limit_priority3 = gated_str("SLCPriority3")
  t.speed_limit_priority_highest = t.speed_limit_priority1 == "Highest"
  t.speed_limit_priority_lowest = t.speed_limit_priority1 == "Lowest"
  return t
