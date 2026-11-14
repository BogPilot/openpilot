"""One-time BogPilot toggle profile for the Tesla AP1 Model S (ported from 367e1fe selfdrive/car/tesla/ap1_defaults.py).

0.11.2 port, shared by the manager boot hook (system/manager/bogpilot_init.py, AP1_DEFAULTS_MODULES) and
the offroad UI (ui/bogpilot/ap1_profile.py re-exports this module). The profile tables, the "only if still
default / file absent" rules, the markers (/data/params_bogpilot/AP1DefaultsApplied and AP1ThemeBogPilot2)
and the unit handling are unchanged from 367e1fe. Values go through the shared store
(openpilot/common/bogpilot_store.py): real Params for keys the params library knows, /data/params_bogpilot
files for the rest; the default table is the params registry (openpilot/common/bogpilot_params.py).
Whoever runs first (boot or the UI) applies it; the marker makes every later call a no-op.

Original notes:
One-time BogPilot toggle profile for the Tesla AP1 Model S.

AP1 is never auto-fingerprinted: owners pick "Tesla AP1 Model S" under
Vehicle Settings, which stores CarModel=TESLA_AP1_MODELS. Model X
(CarModel=TESLA_AP1_MODELX) must not receive this Model S profile. The first time
BogPilot sees Model S (at boot, or offroad when settings close), it applies the
maintainer's recommended toggles below, once:

  - a Params key is written only if its current value still equals the
    bogpilot_default_params table default, so anything the owner already
    changed stays put
  - a /data/params_bogpilot file toggle is written only if the file is absent
  - then /data/params_bogpilot/AP1DefaultsApplied is written so it never runs
    again. "Reset toggles to default" (DoToggleReset) deletes that marker, so
    a reset re-applies the AP1 profile. "Reset to stock" leaves it alone.

No new Params keys (the prebuilt params_pyx.so raises on unknown keys): the
marker and the file toggles live in /data/params_bogpilot. Nothing here touches
CarParams, panda safety, or driving code; it only stores toggle values.

The profile only lists values that differ from the table defaults, except the
few in EXPLICIT_DEFAULT_KEYS that are spelled out on purpose. Keys that are
secret, personal, or tied to one device or car are never part of it (see
NEVER_PROFILE_KEYS); the tests enforce that.

Speed-limit offsets are kept in mph (AP1_SPEED_OFFSETS_MPH). On a metric device
(IsMetric) they are converted to km/h and rounded before writing, because the
Offset params are stored in the device's display unit.

Theme: every theme menu (Color Scheme, Distance Button, Icon Pack, Sound Pack,
Steering Wheel, Turn Signal) is set to the BogPilot theme, whose colors, icons,
sounds and wheel are copies of the stock openpilot files
(bogpilot/assets/bogpilot_theme). Colors and wheel still look exactly stock
through the stand-in in bogpilot_variables.resolve_bogpilot_theme. A separate
one-time step (marker AP1ThemeBogPilot2) also moves values that only pick the
stock look ("stock", or "none" for turn signals) to BogPilot, because those
render the same. It runs once per device even where the main profile already
ran, and never touches Distance Button, a "none" steering wheel, or a
downloaded or user-made theme.
"""

import os
from pathlib import Path

AP1_CAR_MODEL = "TESLA_AP1_MODELS"

BOGPILOT_DIR = Path(os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))
MARKER_NAME = "AP1DefaultsApplied"
# "2": the 293184ad step (marker AP1ThemeBogPilot) left Color Scheme and Steering Wheel on stock, so the
# widened step must run once more on devices that already ran that one.
THEME_MARKER_NAME = "AP1ThemeBogPilot2"
OLD_THEME_MARKER_NAMES = ("AP1ThemeBogPilot",)
BOGPILOT_THEME = "BogPilot"

# BogPilot file-backed toggles (not Params keys). Absent file = that toggle's built-in default.
FILE_TOGGLE_KEYS = ("ConfidenceBall", "ConfidenceBallSide", "DeveloperHUD", "RemoteUIStream",
                    "EnableICIntegration", "RegenComfortBrake", "SwapSpeedGraph")

# Written as a pair, and only while the tuning level was never confirmed. Without
# TuningLevelConfirmed=1 the settings panel's first-open popup would drop a new
# owner to "Minimal" (TuningLevel 0). Terms and training (HasAcceptedTerms,
# CompletedTrainingVersion) are separate keys and are never touched here.
TUNING_LEVEL_KEYS = ("TuningLevel", "TuningLevelConfirmed")

# Params the profile must never carry: secrets, personal data, per-device or
# per-car state, connectivity and data-sharing choices, units, and the model
# (a fresh device has not downloaded it). All *Stock keys are excluded too.
NEVER_PROFILE_KEYS = frozenset({
  # secrets and accounts
  "GithubSshKeys", "GithubUsername", "MapboxPublicKey", "MapboxSecretKey", "AMapKey1", "AMapKey2",
  "WeatherToken", "SecOCKey", "SecOCKeys", "KonikDongleId", "DiscordUsername", "GsmApn", "BogPilotStats",
  # personal places and recordings
  "FavoriteDestinations", "MapsSelected", "SearchInput", "RecordFront",
  # vehicle selection (the trigger itself, never written by the profile)
  "CarMake", "CarModel", "CarModelName", "ForceFingerprint",
  # per-car learned or hand-measured tuning
  "SteerRatio", "SteerDelay", "SteerFriction", "SteerKP", "SteerLatAccel", "LongitudinalActuatorDelay",
  "StartAccel", "StopAccel", "StoppingDecelRate", "VEgoStarting", "VEgoStopping", "LiveDelay",
  "CalibratedLateralAcceleration",
  # device bookkeeping
  "ThemesDownloaded", "ShownToggleDescriptions", "ExperimentalModeConfirmed", "UpdatedToggles",
  "MinimumBackupSize", "LastKnownTime",
  # connectivity, uploads, data sharing, updates
  "SshEnabled", "TetheringEnabled", "GsmRoaming", "NoUploads", "NoLogging", "DisableOnroadUploads",
  "UseKonikServer", "HigherBitrate", "DeviceManagement", "AutomaticUpdates",
  # units are the owner's locale, not an AP1 recommendation
  "IsMetric", "Fahrenheit", "UseSI",
  # driving model: a fresh device won't have the maintainer's model downloaded
  "Model",
  # BogPilot Alerts: independent Green Light / Lead Departed / Loud Blindspot / Speed Limit Changed defaults ON;
  # saved OFF must survive AP1 profile / DoToggleReset marker cycles. Never reintroduce these as profile writes.
  "GreenLightAlert", "LeadDepartingAlert", "LoudBlindspotAlert", "SpeedLimitChangedAlert",
  "CruiseEngageDisengageChimes",
})

# Keys deliberately listed even though the value equals the table default, so the
# profile states the maintainer's full choice for them.
# Theme params: all set to the BogPilot theme (equal to the table default, listed on purpose).
THEME_KEYS = ("CustomColors", "CustomDistanceIcons", "CustomIcons", "CustomSignals", "CustomSounds", "WheelIcon")

EXPLICIT_DEFAULT_KEYS = frozenset({"AccelerationProfile", "PersonalizeOpenpilot", "RandomThemes", *THEME_KEYS})

# Theme values that only select the stock look, per key, which the BogPilot theme
# reproduces exactly today. The one-time theme step moves these to BogPilot.
# Not listed on purpose: CustomDistanceIcons (BogPilot has its own distance icons,
# so stock ones would change) and WheelIcon "none" (no wheel drawn at all).
STOCK_LOOK_THEME_VALUES: dict[str, frozenset[str]] = {
  "CustomColors": frozenset({"stock"}),
  "CustomIcons": frozenset({"stock"}),
  "CustomSounds": frozenset({"stock"}),
  "CustomSignals": frozenset({"stock", "none"}),
  "WheelIcon": frozenset({"stock"}),
}

# Speed-limit controller offsets in mph, by posted-limit band (the bands are the
# settings labels for Offset1..Offset7 and speed_limit_controller.py's mph table).
AP1_SPEED_OFFSETS_MPH: dict[str, int] = {
  "Offset1": 4,                          # 0-24 mph limits: +4
  "Offset2": 5,                          # 25-34 mph: +5
  "Offset3": 5,                          # 35-44 mph: +5
  "Offset4": 5,                          # 45-54 mph: +5
  "Offset5": 7,                          # 55-64 mph: +7
  "Offset6": 8,                          # 65-74 mph: +8
  "Offset7": 10,                         # 75-99 mph: +10 (same as the table default)
}
MPH_TO_KPH = 1.609344

# Recommended Params values. Strings are stored exactly as the settings UI writes them.
AP1_PARAM_PROFILE: dict[str, str] = {
  "ShowMemoryUsage": "1",
  "ShowGPU": "1",
  "ShowCPU": "1",
  "SidebarMetrics": "1",
  "NudgelessLaneChange": "0",
  "DeveloperWidgets": "0",
  # --- Driving / longitudinal ---
  "ConditionalExperimental": "0",        # Conditional Experimental Mode off (no automatic EM switching)
  "CECurves": "1",                       # CE child: switch to EM for curves (inert while CE is off)
  "CENavigationIntersections": "1",      # CE child: EM for nav intersections (inert while CE is off)
  "CustomPersonalities": "1",            # custom follow-distance personalities on
  "RelaxedFollow": "2.000000",           # Relaxed personality follow time 2.0 s (default 1.75 s)
  # Profile enums (longitudinal_settings.cc): acceleration 0 Standard, 1 Eco, 2 Sport, 3 Sport+;
  # deceleration 0 Standard, 1 Eco, 2 Eco+.
  "AccelerationProfile": "2",            # acceleration profile Sport (same as the table default, listed on purpose)
  "DecelerationProfile": "2",            # deceleration profile Eco+ (coasts more, brakes as softly as possible; default Eco)
  "NewLongAPI": "0",                     # comma new long API off (Hyundai-only, no effect on Tesla)
  "SLCOverride": "2",                    # SLC override after driving faster: Max Set Speed
  "SLCPriority1": "Dashboard",           # SLC source 1: Dashboard (BogPilot feeds AP1 cluster limits here)
  "SLCPriority3": "Navigation",          # SLC source 3: Navigation
  "SLCLookaheadHigher": "0",             # unused: look-ahead never raises the set speed early
  "SLCLookaheadLower": "5",              # horizon for early slowdown toward a lower upcoming limit (0 = off; default 5 s)
  # Offset1..Offset7 come from AP1_SPEED_OFFSETS_MPH (unit-aware), not from this table.

  # --- Lateral ---
  "AlwaysOnLateral": "0",                # Always On Lateral off
  "NNFFLite": "1",                       # NNFF-Lite on (inert on AP1: angle steering skips it)

  # --- Visuals / screen ---
  "DeveloperUI": "1",                    # Developer UI parent on (Developer HUD, border metrics)
  "BorderMetrics": "1",                  # screen-edge status border (blind spot / torque / signal)
  "DeveloperSidebar": "0",               # 300 px developer sidebar off (keeps the full driving view)
  "LeadInfo": "0",                       # lead metrics off: the Developer HUD already shows lead data
  "FPSCounter": "0",                     # FPS counter off
  # AdjacentLeadsUI inherits the registry ON default; an owner's saved OFF is never overridden.
  "ShowStoppingPoint": "0",              # model stopping-point marker off
  "ShowStoppingPointMetrics": "0",       # stopping-point distance off
  "ShowSLCOffset": "0",                  # hide the SLC offset under the speed limit
  "OnroadDistanceButton": "1",           # driving-personality button on the driving screen
  "CameraView": "0",                     # camera view Auto (also the registered default)
  "DriverCamera": "1",                   # show driver camera in reverse
  "MapStyle": "0",                       # map style: stock openpilot
  # --- Theme: BogPilot in every theme menu (assets are copies of the stock look) ---
  "PersonalizeOpenpilot": "1",           # Custom Themes on, so the theme selections below apply (table default)
  "RandomThemes": "0",                   # no random theme per drive (table default)
  "CustomColors": BOGPILOT_THEME,        # Color Scheme (renders stock while its colors.json equals stock)
  "WheelIcon": BOGPILOT_THEME,           # Steering Wheel (renders stock while its wheel.png equals stock)
  "CustomDistanceIcons": BOGPILOT_THEME, # Distance Button
  "CustomIcons": BOGPILOT_THEME,         # Icon Pack (copies of the stock icons)
  "CustomSounds": BOGPILOT_THEME,        # Sound Pack (copies of the stock sounds)
  "CustomSignals": BOGPILOT_THEME,       # Turn Signal (BogPilot has no frames, same as "None")

  # --- Alerts / sounds ---
  # Alert volumes are NOT part of this profile (alert volumes): AP1 keeps the BogPilot defaults
  # (AlertVolumeControl 0, every volume 101) from openpilot/common/bogpilot_alert_volumes.py. The legacy
  # 367e1fe engage/disengage mute is intentionally dropped and must never be re-applied.
  # CustomAlerts master gate intentionally omitted: GreenLightAlert / LeadDepartingAlert are
  # independent, fresh-ON, and listed in NEVER_PROFILE_KEYS so saved OFF cannot be clobbered.
  # GoatScream stays omitted from runtime and menus. LoudBlindspotAlert / SpeedLimitChangedAlert are real rows
  # (fresh-ON like Green Light) and are never written by this profile either.

  # --- System ---
  "PreferredSchedule": "1",              # OSM map update schedule: Weekly (default Monthly)
  # BogPilot telemetry, stats uploads and device registration are removed from BogPilot entirely, so
  # BogPilotTelemetry is no longer part of the profile (its table default is now 0 and the toggle is hidden).
}

# Recommended /data/params_bogpilot file toggles (written only when the file is absent).
AP1_FILE_TOGGLE_PROFILE: dict[str, str] = {
  "SwapSpeedGraph": "1",
  "DeveloperHUD": "0",                   # Developer HUD on (default off)
}


def _text(value) -> str | None:
  if value is None:
    return None
  if isinstance(value, bytes):
    return value.decode("utf-8", errors="replace")
  return str(value)


def values_equal(a, b) -> bool:
  """Stored-value equality: exact text, or the same number ("5" == "5.000000")."""
  a, b = _text(a), _text(b)
  if a == b:
    return True
  if a is None or b is None:
    return False
  try:
    return abs(float(a) - float(b)) < 1e-6
  except ValueError:
    return False


def _default_table() -> dict[str, str]:
  from openpilot.common.bogpilot_params import bogpilot_defaults
  return {key: value for key, value, _level, _stock in bogpilot_defaults()}


def _persistent_fingerprint(params) -> str | None:
  try:
    raw = params.get("CarParamsPersistent")
    if not raw:
      return None
    from openpilot.cereal import car
    with car.CarParams.from_bytes(raw) as cp:
      return str(cp.carFingerprint)
  except Exception:
    return None


def _is_metric(params) -> bool:
  try:
    return _text(params.get("IsMetric")) == "1"
  except Exception:
    return False


def speed_offsets_for_units(metric: bool) -> dict[str, str]:
  """Offset1..7 as stored text: mph as-is, or converted to km/h and rounded on a metric device."""
  out = {}
  for key, mph in AP1_SPEED_OFFSETS_MPH.items():
    value = round(mph * MPH_TO_KPH) if metric else mph
    out[key] = f"{value:.6f}"
  return out


# Keys the one-time profile must never write (alert volumes: no re-mute).
_NEVER_PROFILE_VOLUME_KEYS = ("AlertVolumeControl", "EngageVolume", "DisengageVolume", "RefuseVolume", "PromptVolume",
                              "PromptDistractedVolume", "WarningSoftVolume", "WarningImmediateVolume")


def _profile_for_units(params) -> dict[str, str]:
  from openpilot.common.bogpilot_shipping_defaults import patch_ap1_param_profile
  # shipping overlay: drops TuningLevel/TuningLevelConfirmed (left unset), AOL off, metrics on
  profile = patch_ap1_param_profile(dict(AP1_PARAM_PROFILE))
  profile.update(speed_offsets_for_units(_is_metric(params)))
  for key in _NEVER_PROFILE_VOLUME_KEYS:
    profile.pop(key, None)
  return profile


def _is_converted_default(key, current, table, metric) -> bool:
  """On a metric device the settings UI converted the mph table default to km/h (truncating), e.g. 5 -> 8.

  Treat that converted value as "still default" so a metric owner who never touched an offset gets the profile.
  """
  if not metric or key not in AP1_SPEED_OFFSETS_MPH:
    return False
  try:
    default_mph = float(table[key])
    cur = float(_text(current))
  except (TypeError, ValueError, KeyError):
    return False
  return cur in (int(default_mph * MPH_TO_KPH), round(default_mph * MPH_TO_KPH))


def is_ap1(params) -> bool:
  """Model S AP1 only. Model X (TESLA_AP1_MODELX) must not receive the S profile."""
  try:
    if _text(params.get("CarModel")) == AP1_CAR_MODEL:
      return True
  except Exception:
    pass
  return _persistent_fingerprint(params) == AP1_CAR_MODEL


def marker_path(bogpilot_dir: Path | None = None) -> Path:
  return Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR) / MARKER_NAME


def theme_marker_path(bogpilot_dir: Path | None = None) -> Path:
  return Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR) / THEME_MARKER_NAME


def clear_ap1_defaults_marker(bogpilot_dir: Path | None = None) -> None:
  """Called on DoToggleReset so the next run re-applies the AP1 profile."""
  directory = Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR)
  for path in (marker_path(bogpilot_dir), theme_marker_path(bogpilot_dir), legacy_slc_marker_path(bogpilot_dir),
               legacy_tesla_long_marker_path(bogpilot_dir), legacy_tesla_ce_marker_path(bogpilot_dir),
               *(directory / n for n in OLD_THEME_MARKER_NAMES), *(directory / n for n in OLD_LEGACY_SLC_MARKER_NAMES)):
    try:
      path.unlink(missing_ok=True)
    except Exception:
      pass


def _apply_theme_once(params, directory: Path) -> list[str]:
  """Move theme values that only pick the stock look to BogPilot, once per device."""
  marker = theme_marker_path(directory)
  if marker.exists():
    return []
  written = []
  for key, stock_values in STOCK_LOOK_THEME_VALUES.items():
    current = _text(params.get(key))
    if current is not None and current.strip().lower() in stock_values:
      params.put(key, BOGPILOT_THEME)
      written.append(key)
  directory.mkdir(parents=True, exist_ok=True)
  marker.write_text("1\n")
  return written


def apply_ap1_defaults_once(params=None, bogpilot_dir: Path | None = None, default_table: dict | None = None,
                            refresh: bool = True) -> list[str]:
  """Apply the AP1 profile once. Returns the keys written ([] when it did nothing).

  Never raises: a problem here must not block boot or the toggle loop.
  """
  try:
    if params is None:
      params = StoreParams()
    elif not hasattr(params, "invalidate"):
      # a bare Params (manager boot hook): BogPilot keys an old libparams_c.so does not know yet
      # must still land in the file store instead of raising UnknownKeyName
      params = StoreParams(_shared_store(params))
    directory = Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR)
    marker = marker_path(directory)

    if not is_ap1(params) or (marker.exists() and theme_marker_path(directory).exists()):
      return []

    written = []
    if not marker.exists():
      written += _apply_profile(params, directory, default_table)
      marker.write_text("1\n")
    written += [key for key in _apply_theme_once(params, directory) if key not in written]

    if written and refresh:
      try:
        params.invalidate()
      except Exception:
        pass
    return written
  except Exception:
    return []


def _apply_profile(params, directory: Path, default_table: dict | None) -> list[str]:
  table = default_table if default_table is not None else _default_table()
  metric = _is_metric(params)
  written = []

  # Tuning level: only for an owner who never confirmed one, and only as a pair.
  tuning_unset = all(values_equal(params.get(k), table.get(k)) or params.get(k) is None for k in TUNING_LEVEL_KEYS)

  for key, value in _profile_for_units(params).items():
    if key not in table or key in NEVER_PROFILE_KEYS:
      continue
    if key in TUNING_LEVEL_KEYS and not tuning_unset:
      continue
    current = params.get(key)
    if current is None or values_equal(current, table[key]) or _is_converted_default(key, current, table, metric):
      params.put(key, value)
      written.append(key)

  directory.mkdir(parents=True, exist_ok=True)
  for key, value in AP1_FILE_TOGGLE_PROFILE.items():
    path = directory / key
    if not path.exists():
      path.write_text(value)
      written.append(key)
  return written


# Pre-AP Model S and AP1 Model X get the SLC source / look-ahead defaults, not the full AP1 S profile.
LEGACY_SLC_PLATFORMS = frozenset({"TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"})
# Marker 2: written once the full legacy SLC profile below (including the speed / Override keys) was offered.
LEGACY_SLC_MARKER_NAME = "LegacySlcDefaultsApplied2"
# Earlier builds wrote this marker after offering LEGACY_SLC_PROFILE only (sources and look-ahead). A device that has it
# but not marker 2 is offered only the keys added since, with the same still-at-default rule.
OLD_LEGACY_SLC_MARKER_NAMES = ("LegacySlcDefaultsApplied",)
LEGACY_SLC_PROFILE: dict[str, str] = {
  "SLCPriority1": "Dashboard",
  "SLCPriority2": "Map Data",
  "SLCPriority3": "Navigation",
  "SLCLookaheadLower": "5",
  "SLCLookaheadHigher": "0",
}
# Pre-AP Model S also gets the AP1 profile's speed settings, read from the AP1 profile itself (nothing copied): the
# Offset1-7 table AP1_SPEED_OFFSETS_MPH through speed_offsets_for_units() (km/h, same conversion and rounding, on a
# metric device) and AP1_PARAM_PROFILE's SLCOverride (Max Set Speed). The fallback is not written: its table default
# (Previous Limit) is already what AP1 uses. No AP1-only display key (ShowSLCOffset) is added.
LEGACY_SLC_AP1_SPEED_PLATFORMS = frozenset({"TESLA_PREAP_MODELS"})
LEGACY_SLC_AP1_SPEED_KEYS = ("SLCOverride",)
# AP1 Model X gets the AP1 Model S profile's SLC settings, and only those: the keys below as _profile_for_units()
# writes them (offsets unit-aware). No other AP1 profile key (themes, personalities, Conditional Experimental Mode,
# ...) reaches the X, and is_ap1() stays Model S only. Same one-time path and marker as the rest of this profile.
LEGACY_SLC_AP1_SLC_PLATFORMS = frozenset({"TESLA_AP1_MODELX"})
AP1_SLC_KEYS = ("SLCOverride", "SLCPriority1", "SLCPriority2", "SLCPriority3", "SLCLookaheadLower",
                "SLCLookaheadHigher", "ShowSLCOffset", *AP1_SPEED_OFFSETS_MPH)


def _legacy_slc_fingerprint(params) -> str | None:
  try:
    model = _text(params.get("CarModel"))
    if model:
      return str(model)
  except Exception:
    pass
  return _persistent_fingerprint(params)


def is_legacy_slc_platform(params) -> bool:
  """AP1 Model X or Pre-AP Model S. Never the AP1 Model S (that uses the S profile)."""
  return _legacy_slc_fingerprint(params) in LEGACY_SLC_PLATFORMS


def is_preap_slc_platform(params) -> bool:
  """Pre-AP Model S: the legacy SLC platform that also gets the AP1 speed settings."""
  return _legacy_slc_fingerprint(params) in LEGACY_SLC_AP1_SPEED_PLATFORMS and not is_ap1(params)


def is_ap1x_slc_platform(params) -> bool:
  """AP1 Model X: the legacy SLC platform that gets the AP1 Model S profile's SLC settings."""
  return _legacy_slc_fingerprint(params) in LEGACY_SLC_AP1_SLC_PLATFORMS and not is_ap1(params)


def ap1_slc_profile_for_units(params) -> dict[str, str]:
  """The AP1 Model S profile's SLC settings only (AP1_SLC_KEYS), as stored text for this device's units."""
  return {key: value for key, value in _profile_for_units(params).items() if key in AP1_SLC_KEYS}


def legacy_slc_profile_for_units(params) -> dict[str, str]:
  """The legacy SLC values this car receives as stored text ({} on AP1 Model S and on non-legacy cars)."""
  if not is_legacy_slc_platform(params) or is_ap1(params):
    return {}
  profile = dict(LEGACY_SLC_PROFILE)
  if is_preap_slc_platform(params):
    profile.update({key: AP1_PARAM_PROFILE[key] for key in LEGACY_SLC_AP1_SPEED_KEYS})
    profile.update(speed_offsets_for_units(_is_metric(params)))
  elif is_ap1x_slc_platform(params):
    profile.update(ap1_slc_profile_for_units(params))
  return profile


def legacy_slc_marker_path(bogpilot_dir: Path | None = None) -> Path:
  return Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR) / LEGACY_SLC_MARKER_NAME


def apply_legacy_slc_defaults_once(params=None, bogpilot_dir: Path | None = None,
                                   default_table: dict | None = None, refresh: bool = True) -> list[str]:
  """One-shot SLC defaults for Pre-AP and AP1 X (legacy_slc_profile_for_units). Saved values are preserved: only a
  key still at its table default (for an offset on a metric device, also the UI's km/h conversion of it) is written.

  A device from an earlier build (OLD_LEGACY_SLC_MARKER_NAMES present, marker 2 absent) already had LEGACY_SLC_PROFILE
  offered once: it is offered only the keys added since (Offset1-7, SLCOverride, and on the X ShowSLCOffset), so a
  source / look-ahead value set back to the table default after that first run is kept.

  Never raises. AP1 Model S is ignored here (apply_ap1_defaults_once owns those keys).
  """
  try:
    if params is None:
      params = StoreParams()
    elif not hasattr(params, "invalidate"):
      params = StoreParams(_shared_store(params))
    directory = Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR)
    marker = legacy_slc_marker_path(directory)
    if not is_legacy_slc_platform(params) or is_ap1(params) or marker.exists():
      return []
    table = default_table if default_table is not None else _default_table()
    metric = _is_metric(params)
    profile = legacy_slc_profile_for_units(params)
    if any((directory / name).exists() for name in OLD_LEGACY_SLC_MARKER_NAMES):
      profile = {key: value for key, value in profile.items() if key not in LEGACY_SLC_PROFILE}
    written = []
    for key, value in profile.items():
      if key not in table:
        continue
      current = params.get(key)
      if current is None or values_equal(current, table[key]) or _is_converted_default(key, current, table, metric):
        params.put(key, value)
        written.append(key)
    directory.mkdir(parents=True, exist_ok=True)
    marker.write_text("1\n")
    if written and refresh:
      try:
        params.invalidate()
      except Exception:
        pass
    return written
  except Exception:
    return []



# ---------------------------------------------------------------------------------------------------------------
# Legacy Tesla long-tune defaults (rc5): the stored 0.9.7 Gas/Brake profiles and driving personalities.
#
# Platforms: the three tesla_ap1 platforms (AP1 Model S, AP1 Model X, Pre-AP Model S). AP2 is not a platform in this
# tree (values.py), so it receives nothing. Values are exactly what the 0.9.7 device stored (initData.params of the
# logged 0.9.7 drive and the bench device, read-only) and what the 0.9.7 source (026cfb31 = 04d560f3e,
# frogpilot_acceleration.py / frogpilot_following.py, byte-identical in both) turns into limits:
#   Acceleration Sport (max 3.0/2.5/2.0/1.5/1.0/0.8/0.6 m/s^2 at 0/5/10/15/20/25/40 m/s), Deceleration Eco+ (ACCEL_MIN/4 =
#   -0.875 m/s^2), Human-Like Acceleration on, Human Following on, Custom Personalities on with Aggressive 1.25 s / Standard
#   1.45 s / Relaxed 2.0 s follow time and jerk factors Aggressive 50/50/100/50/50 and Standard, Relaxed 100 (acceleration,
#   deceleration, danger, speed, speed decrease; stored in percent).
#
# Migration rule (never overwrites a custom setting; applied once per device, marker below, DoToggleReset clears it):
#   1. only on a legacy Tesla platform (CarModel, else the persistent fingerprint); unknown platform = retry next boot
#   2. a group is skipped as a whole when its adoption file (Phase3LongAccelProfilesEnabled / Phase3PersonalitiesEnabled /
#      Phase3HumanFollowingEnabled) is set: the owner already used the new panel, their values are theirs
#   3. a key is written only if it is unset/empty, or its stored value still equals the registry default (the same
#      "still default" rule as the AP1 profile). Anything else is a user value and stays
#   4. AP1 Model S with the AP1DefaultsApplied marker: that profile already rewrote every still-default value once, so a
#      value that is back at the registry default now was chosen by the owner after it: only unset keys are written
#   5. "Reset to stock" (AP1StockReset1) suppresses it (bogpilot_startup), and LongitudinalTune=0 keeps the planner off
#   Known limit (Pre-AP / Model X): an owner who explicitly picked the registry default itself (for example Eco
#   deceleration) cannot be told apart from an untouched device and is moved to Eco+; the one-shot never repeats.
# The marker records what was written and what was kept, for audit and for a manual undo.
LEGACY_TESLA_PLATFORMS = frozenset({"TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"})
LEGACY_TESLA_LONG_MARKER_NAME = "LegacyTeslaLongDefaultsApplied1"
_ACK_PROFILES, _ACK_PERSONALITIES, _ACK_HUMAN_FOLLOWING = (
  "Phase3LongAccelProfilesEnabled", "Phase3PersonalitiesEnabled", "Phase3HumanFollowingEnabled")
LEGACY_TESLA_LONG_PROFILE: dict[str, dict[str, str]] = {
  _ACK_PROFILES: {
    "LongitudinalTune": "1",
    "AccelerationProfile": "2",      # Sport
    "DecelerationProfile": "2",      # Eco+
    "HumanAcceleration": "1",
  },
  _ACK_PERSONALITIES: {
    "CustomPersonalities": "1",
    "AggressivePersonalityProfile": "1", "StandardPersonalityProfile": "1", "RelaxedPersonalityProfile": "1",
    "AggressiveFollow": "1.25", "StandardFollow": "1.45", "RelaxedFollow": "2.0",
    "AggressiveJerkAcceleration": "50", "AggressiveJerkDeceleration": "50", "AggressiveJerkDanger": "100",
    "AggressiveJerkSpeed": "50", "AggressiveJerkSpeedDecrease": "50",
    "StandardJerkAcceleration": "100", "StandardJerkDeceleration": "100", "StandardJerkDanger": "100",
    "StandardJerkSpeed": "100", "StandardJerkSpeedDecrease": "100",
    "RelaxedJerkAcceleration": "100", "RelaxedJerkDeceleration": "100", "RelaxedJerkDanger": "100",
    "RelaxedJerkSpeed": "100", "RelaxedJerkSpeedDecrease": "100",
  },
  _ACK_HUMAN_FOLLOWING: {"HumanFollowing": "1"},
}


def legacy_tesla_long_marker_path(bogpilot_dir: Path | None = None) -> Path:
  return Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR) / LEGACY_TESLA_LONG_MARKER_NAME


def is_legacy_tesla_platform(params) -> bool:
  """AP1 Model S, AP1 Model X or Pre-AP Model S (the tesla_ap1 platforms)."""
  return _legacy_slc_fingerprint(params) in LEGACY_TESLA_PLATFORMS


def _adopted_by_owner(params, directory: Path, ack: str) -> bool:
  """True when the adoption file of a group is set (the owner used the new panel for that group)."""
  on = ("1", "true", "on")
  try:
    value = _text(params.get(ack))
    if value is not None and value.strip().lower() in on:
      return True
  except Exception:
    pass
  try:
    return (directory / ack).read_text().strip().lower() in on
  except OSError:
    return False


def _unset(value) -> bool:
  return value is None or str(_text(value)).strip() == ""


def apply_legacy_tesla_long_defaults_once(params=None, bogpilot_dir: Path | None = None, default_table: dict | None = None,
                                          refresh: bool = True) -> list[str]:
  """Apply the legacy Tesla long-tune profile once (rules above). Returns the keys written. Never raises."""
  try:
    import json
    if params is None:
      params = StoreParams()
    elif not hasattr(params, "invalidate"):
      params = StoreParams(_shared_store(params))
    directory = Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR)
    marker = legacy_tesla_long_marker_path(directory)
    if marker.exists() or not is_legacy_tesla_platform(params):
      return []
    table = default_table if default_table is not None else _default_table()
    ap1_profile_ran = is_ap1(params) and marker_path(directory).exists()
    written: list[str] = []
    audit: dict = {"written": {}, "kept": {}, "skipped_groups": []}
    for ack, profile in LEGACY_TESLA_LONG_PROFILE.items():
      if _adopted_by_owner(params, directory, ack):
        audit["skipped_groups"].append(ack)
        continue
      for key, value in profile.items():
        if key not in table or key in NEVER_PROFILE_KEYS:
          continue
        current = params.get(key)
        if _unset(current):
          still_default = True
        else:
          still_default = values_equal(current, table[key]) and not ap1_profile_ran
        if still_default and not values_equal(current, value):
          params.put(key, value)
          written.append(key)
          audit["written"][key] = [None if _unset(current) else _text(current), value]
        elif not values_equal(current, value):
          audit["kept"][key] = _text(current)
    directory.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(audit, sort_keys=True) + "\n")
    if written and refresh:
      try:
        params.invalidate()
      except Exception:
        pass
    return written
  except Exception:
    return []


# ---------------------------------------------------------------------------------------------------------------
# Conditional Experimental Mode off on every legacy Tesla (AP1 Model S, AP1 Model X, Pre-AP Model S).
#
# Conditional Experimental Mode does not work on these cars yet, so it ships off on them: as the default (one-time
# write below), after a section reset (the car-type reset tables in phase3_speed_control_settings.py) and after
# "Reset BogPilot Settings to Defaults" (phase3_system_utilities.py writes it with the shipped table, and clearing the
# marker makes the next start apply it again). AP2 is not a platform in this tree, so it receives nothing.
# The AP1 Model S profile already sets it (AP1_PARAM_PROFILE); this covers the X and Pre-AP and an S whose profile
# never ran. Migration rule, same as the long-tune defaults above: written only while the key is unset or still at its
# registry default ("1"); on an AP1 Model S whose AP1 profile already ran, only an unset key is written, because a
# value back at the default was then chosen after the profile. Never raises.
LEGACY_TESLA_CE_OFF: dict[str, str] = {"ConditionalExperimental": "0"}
LEGACY_TESLA_CE_MARKER_NAME = "LegacyTeslaCEOffApplied"


def legacy_tesla_ce_marker_path(bogpilot_dir: Path | None = None) -> Path:
  return Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR) / LEGACY_TESLA_CE_MARKER_NAME


def legacy_tesla_ce_off_values(params) -> dict[str, str]:
  """{key: stored text} every legacy Tesla resets to for Conditional Experimental Mode; {} on any other car."""
  try:
    return dict(LEGACY_TESLA_CE_OFF) if is_legacy_tesla_platform(params) else {}
  except Exception:
    return {}


def apply_legacy_tesla_ce_off_once(params=None, bogpilot_dir: Path | None = None, default_table: dict | None = None,
                                   refresh: bool = True) -> list[str]:
  """Write LEGACY_TESLA_CE_OFF once per device on a legacy Tesla (rule above). Returns the keys written."""
  try:
    if params is None:
      params = StoreParams()
    elif not hasattr(params, "invalidate"):
      params = StoreParams(_shared_store(params))
    directory = Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR)
    marker = legacy_tesla_ce_marker_path(directory)
    if marker.exists() or not is_legacy_tesla_platform(params):
      return []
    table = default_table if default_table is not None else _default_table()
    ap1_profile_ran = is_ap1(params) and marker_path(directory).exists()
    written: list[str] = []
    for key, value in LEGACY_TESLA_CE_OFF.items():
      if key not in table:
        continue
      current = params.get(key)
      still_default = _unset(current) or (values_equal(current, table[key]) and not ap1_profile_ran)
      if still_default and not values_equal(current, value):
        params.put(key, value, block=True)      # persisted before the once-only marker below
        written.append(key)
    directory.mkdir(parents=True, exist_ok=True)
    _write_marker_durable(marker, "1\n")
    if written and refresh:
      try:
        params.invalidate()
      except Exception:
        pass
    return written
  except Exception:
    return []


def _write_marker_durable(marker: Path, text: str) -> None:
  """Write a once-only marker so it survives a power cut: temp file, fsync, rename, fsync of the directory.

  The values the marker stands for are written with block=True first, so a lost marker only means the
  one-time write runs again on the next start (it rechecks the still-default rule), never a marker without its values.
  """
  tmp = marker.with_name(marker.name + ".tmp")
  with open(tmp, "w") as f:
    f.write(text)
    f.flush()
    os.fsync(f.fileno())
  os.replace(tmp, marker)
  try:
    fd = os.open(marker.parent, os.O_RDONLY)
    try:
      os.fsync(fd)
    finally:
      os.close(fd)
  except OSError:
    pass


def _shared_store(params=None):
  from openpilot.common.bogpilot_store import ParamStore, store
  return store() if params is None else ParamStore(params)


class StoreParams:
  """The get/put surface the profile code expects, backed by the shared ParamStore.

  get() returns None for an unset key (Params semantics), so "unset" still counts as default.
  CarParamsPersistent is read from real Params as bytes.
  """

  def __init__(self, store=None):
    self._store = store if store is not None else _shared_store()

  def get(self, key: str):
    if key == "CarParamsPersistent":
      try:
        return self._store._params.get(key)
      except Exception:
        return None
    return self._store._raw(key)

  def put(self, key: str, value, *, block: bool = False) -> None:
    self._store.put(key, value, block=block)

  def invalidate(self) -> None:
    self._store.invalidate()
