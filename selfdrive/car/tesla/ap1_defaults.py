"""One-time BogPilot toggle profile for the Tesla AP1 Model S.

AP1 is never auto-fingerprinted: owners pick "Tesla AP1 Model S" under
Vehicle Settings, which stores CarModel=TESLA_AP1_MODELS. The first time
BogPilot sees that (at boot, or offroad when settings close), it applies the
maintainer's recommended toggles below, once:

  - a Params key is written only if its current value still equals the
    frogpilot_default_params table default, so anything the owner already
    changed stays put
  - a /data/params_bogpilot file toggle is written only if the file is absent
  - then /data/params_bogpilot/AP1DefaultsApplied is written so it never runs
    again. "Reset toggles to default" (DoToggleReset) deletes that marker, so
    a reset re-applies the AP1 profile. "Reset to stock" leaves it alone.

No new Params keys (the prebuilt params_pyx.so raises on unknown keys): the
marker and the file toggles live in /data/params_bogpilot. Nothing here touches
CarParams, panda safety, or driving code; it only stores toggle values.

The profile only lists values that differ from the table defaults. Keys that
are secret, personal, or tied to one device or car are never part of it (see
NEVER_PROFILE_KEYS); the tests enforce that.
"""

from pathlib import Path

AP1_CAR_MODEL = "TESLA_AP1_MODELS"

BOGPILOT_DIR = Path("/data/params_bogpilot")
MARKER_NAME = "AP1DefaultsApplied"

# BogPilot file-backed toggles (not Params keys). Absent file = that toggle's built-in default.
FILE_TOGGLE_KEYS = ("ConfidenceBall", "ConfidenceBallSide", "DeveloperHUD", "RemoteUIStream",
                    "EnableICIntegration", "RegenComfortBrake")

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
  "WeatherToken", "SecOCKey", "SecOCKeys", "KonikDongleId", "DiscordUsername", "GsmApn", "FrogPilotStats",
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
  "UseKonikServer", "HigherBitrate", "DeviceManagement", "AutomaticUpdates", "FrogPilotTelemetry",
  # units are the owner's locale, not an AP1 recommendation
  "IsMetric", "Fahrenheit", "UseSI",
  # driving model: a fresh device won't have the maintainer's model downloaded
  "Model",
})

# Recommended Params values. Strings are stored exactly as the settings UI writes them.
AP1_PARAM_PROFILE: dict[str, str] = {
  # --- Driving / longitudinal ---
  "ConditionalExperimental": "0",        # Conditional Experimental Mode off (no automatic EM switching)
  "CECurves": "1",                       # CE child: switch to EM for curves (inert while CE is off)
  "CENavigationIntersections": "1",      # CE child: EM for nav intersections (inert while CE is off)
  "CustomPersonalities": "1",            # custom follow-distance personalities on
  "RelaxedFollow": "2.000000",           # Relaxed personality follow time 2.0 s (default 1.75 s)
  "DecelerationProfile": "2",            # deceleration profile Sport (firmer braking; default Eco)
  "NewLongAPI": "0",                     # comma new long API off (Hyundai-only, no effect on Tesla)
  "SLCOverride": "2",                    # SLC override after driving faster: Max Set Speed
  "SLCPriority1": "Dashboard",           # SLC source 1: Dashboard (BogPilot feeds AP1 cluster limits here)
  "SLCPriority3": "Navigation",          # SLC source 3: Navigation
  "SLCLookaheadHigher": "1.000000",      # look 1 s ahead for a higher upcoming limit
  "SLCLookaheadLower": "1.000000",       # look 1 s ahead for a lower upcoming limit
  "Offset2": "6.000000",                 # SLC offset 25-34 mph: +6 (device units)
  "Offset3": "6.000000",                 # SLC offset 35-54 mph: +6 (device units)
  "Offset4": "6.000000",                 # SLC offset 55-99 mph: +6 (device units)

  # --- Lateral ---
  "AlwaysOnLateral": "0",                # Always On Lateral off
  "NNFFLite": "1",                       # NNFF-Lite on (inert on AP1: angle steering skips it)

  # --- Visuals / screen ---
  "DeveloperUI": "1",                    # Developer UI parent on (Developer HUD, border metrics)
  "BorderMetrics": "1",                  # screen-edge status border (blind spot / torque / signal)
  "DeveloperSidebar": "0",               # 300 px developer sidebar off (keeps the full driving view)
  "LeadInfo": "0",                       # lead metrics off: the Developer HUD already shows lead data
  "FPSCounter": "0",                     # FPS counter off
  "AdjacentLeadsUI": "0",                # adjacent radar leads off
  "ShowStoppingPoint": "0",              # model stopping-point marker off
  "ShowStoppingPointMetrics": "0",       # stopping-point distance off
  "ShowSLCOffset": "0",                  # hide the SLC offset under the speed limit
  "OnroadDistanceButton": "1",           # driving-personality button on the driving screen
  "CameraView": "0",                     # camera view Auto (default Wide)
  "DriverCamera": "1",                   # show driver camera in reverse
  "MapStyle": "0",                       # map style: stock openpilot
  "CustomColors": "stock",               # theme colors: stock (default BogPilot)
  "CustomIcons": "stock",                # theme icons: stock (default BogPilot)
  "CustomSignals": "none",               # turn-signal animation: none (default BogPilot)
  "CustomSounds": "stock",               # theme sounds: stock (default BogPilot)
  "WheelIcon": "stock",                  # steering wheel icon: stock (default BogPilot)

  # --- Alerts / sounds ---
  "AlertVolumeControl": "1",             # per-alert volume control on
  "EngageVolume": "0.000000",            # engage chime muted (default 101 = auto)
  "DisengageVolume": "0.000000",         # disengage chime muted (default 101 = auto); warnings unaffected
  "CustomAlerts": "1",                   # FrogPilot custom alerts on
  "GreenLightAlert": "1",                # green light alert
  "LeadDepartingAlert": "1",             # lead departing alert

  # --- System ---
  "PreferredSchedule": "1",              # OSM map update schedule: Weekly (default Monthly)
  "TuningLevel": "3",                    # Developer tuning level (needed for the level-3 toggles above)
  "TuningLevelConfirmed": "1",           # mark the level chosen so the first-open popup keeps Developer
}

# Recommended /data/params_bogpilot file toggles (written only when the file is absent).
AP1_FILE_TOGGLE_PROFILE: dict[str, str] = {
  "DeveloperHUD": "1",                   # Developer HUD on (default off)
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
  # Lazy import: frogpilot_variables pulls in the car interfaces.
  from openpilot.frogpilot.common.frogpilot_variables import frogpilot_default_params
  return {key: _text(value) for key, value, _, _ in frogpilot_default_params}


def _persistent_fingerprint(params) -> str | None:
  try:
    raw = params.get("CarParamsPersistent")
    if not raw:
      return None
    from cereal import car
    with car.CarParams.from_bytes(raw) as cp:
      return str(cp.carFingerprint)
  except Exception:
    return None


def is_ap1(params) -> bool:
  try:
    if _text(params.get("CarModel")) == AP1_CAR_MODEL:
      return True
  except Exception:
    pass
  return _persistent_fingerprint(params) == AP1_CAR_MODEL


def marker_path(bogpilot_dir: Path | None = None) -> Path:
  return Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR) / MARKER_NAME


def clear_ap1_defaults_marker(bogpilot_dir: Path | None = None) -> None:
  """Called on DoToggleReset so the next run re-applies the AP1 profile."""
  try:
    marker_path(bogpilot_dir).unlink(missing_ok=True)
  except Exception:
    pass


def apply_ap1_defaults_once(params=None, bogpilot_dir: Path | None = None, default_table: dict | None = None,
                            refresh: bool = True) -> list[str]:
  """Apply the AP1 profile once. Returns the keys written ([] when it did nothing).

  Never raises: a problem here must not block boot or the toggle loop.
  """
  try:
    if params is None:
      from openpilot.common.params import Params
      params = Params()
    directory = Path(bogpilot_dir if bogpilot_dir is not None else BOGPILOT_DIR)
    marker = marker_path(directory)

    if marker.exists() or not is_ap1(params):
      return []

    table = default_table if default_table is not None else _default_table()
    written = []

    # Tuning level: only for an owner who never confirmed one, and only as a pair.
    tuning_unset = all(values_equal(params.get(k), table.get(k)) or params.get(k) is None for k in TUNING_LEVEL_KEYS)

    for key, value in AP1_PARAM_PROFILE.items():
      if key not in table or key in NEVER_PROFILE_KEYS:
        continue
      if key in TUNING_LEVEL_KEYS and not tuning_unset:
        continue
      current = params.get(key)
      if current is None or values_equal(current, table[key]):
        params.put(key, value)
        written.append(key)

    directory.mkdir(parents=True, exist_ok=True)
    for key, value in AP1_FILE_TOGGLE_PROFILE.items():
      path = directory / key
      if not path.exists():
        path.write_text(value)
        written.append(key)

    marker.write_text("1\n")

    if refresh:
      try:
        from openpilot.frogpilot.common.frogpilot_variables import update_frogpilot_toggles
        update_frogpilot_toggles()
      except Exception:
        pass
    return written
  except Exception:
    return []
