"""Explicit stock-toggle reset with C3X shipping policy overlays.

No boot migrations, Params construction, backup implementation or import-time IO.
Call before normal default initialization, serialized by the startup owner. A failed
write retains the request and attempts rollback; a durable pre-reset backup is
mandatory even when rollback succeeds. Caller must not restore stale cache values
or reapply AP1 profile defaults after a successful stock reset.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_shipping_defaults import PARAM_OVERRIDES
from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS, FILE_TOGGLES

REQUEST_KEY = "DoToggleResetStock"
# Reviewed settings ownership snapshot: additions to the registry are NOT reset
# automatically. Auth, identity, learned calibration and runtime data excluded.
RESET_KEYS = frozenset("""
AccelerationPath
AccelerationProfile
AdjacentLeadsUI
AdjacentPath
AdjacentPathMetrics
AdvancedCustomUI
AdvancedLateralTune
AdvancedLongitudinalTune
AggressiveFollow
AggressiveJerkAcceleration
AggressiveJerkDanger
AggressiveJerkDeceleration
AggressiveJerkSpeed
AggressiveJerkSpeedDecrease
AggressivePersonalityProfile
AlertVolumeControl
AlwaysOnLateral
AlwaysOnLateralLKAS
AlwaysOnLateralMain
AutomaticallyDownloadModels
AutomaticUpdates
BigMap
BlindSpotMetrics
BlindSpotPath
BorderMetrics
CameraView
CECurves
CECurvesLead
CELead
CEModelStopTime
CENavigation
CENavigationIntersections
CENavigationLead
CENavigationTurns
CESignalLaneDetection
CESignalSpeed
CESlowerLead
CESpeed
CESpeedLead
CEStopLights
CEStoppedLead
Compass
ConditionalExperimental
CurveSpeedController
CustomAlerts
CustomColors
CustomCruise
CustomCruiseLong
CustomDistanceIcons
CustomIcons
CustomPersonalities
CustomSignals
CustomSounds
CustomUI
DecelerationProfile
DeveloperMetrics
DeveloperSidebar
DeveloperSidebarMetric1
DeveloperSidebarMetric2
DeveloperSidebarMetric3
DeveloperSidebarMetric4
DeveloperSidebarMetric5
DeveloperSidebarMetric6
DeveloperSidebarMetric7
DeveloperUI
DeveloperWidgets
DeviceManagement
DeviceShutdown
DisableOnroadUploads
DisableOpenpilotLongitudinal
DisengageVolume
DistanceButtonControl
DriverCamera
DynamicPathWidth
DynamicPedalsOnUI
EngageVolume
ExperimentalGMTune
Fahrenheit
ForceAutoTune
ForceAutoTuneOff
ForceMPHDashboard
ForceStops
ForceTorqueController
FPSCounter
FrogPilotTelemetry
FrogsGoMoosTweak
FullMap
GasRegenCmd
GoatScream
GreenLightAlert
HideAlerts
HideLeadMarker
HideMap
HideMapIcon
HideMaxSpeed
HideSpeed
HideSpeedLimit
HigherBitrate
HolidayThemes
HondaAltTune
HondaLowSpeedPedal
HondaMaxBrake
HumanAcceleration
HumanFollowing
HumanLaneChanges
IncreasedStoppedDistance
IncreasedStoppedDistanceLowVisibility
IncreasedStoppedDistanceRain
IncreasedStoppedDistanceRainStorm
IncreasedStoppedDistanceSnow
IncreaseFollowingLowVisibility
IncreaseFollowingRain
IncreaseFollowingRainStorm
IncreaseFollowingSnow
IncreaseThermalLimits
LaneChanges
LaneChangeTime
LaneDetectionWidth
LaneLinesWidth
LateralTune
LeadDepartingAlert
LeadDetectionThreshold
LeadInfo
LKASButtonControl
LockDoors
LockDoorsTimer
LongDistanceButtonControl
LongitudinalTune
LongPitch
LoudBlindspotAlert
LowVoltageShutdown
MapAcceleration
MapDeceleration
MapGears
MapStyle
MaxDesiredAcceleration
MinimumLaneChangeSpeed
Model
ModelRandomizer
ModelUI
NavigationUI
NavSettingLeftSide
NavSettingTime24h
NewLongAPI
NNFF
NNFFLite
NoLogging
NoUploads
NudgelessLaneChange
NumericalTemp
Offset1
Offset2
Offset3
Offset4
Offset5
Offset6
Offset7
OneLaneChange
OnroadDistanceButton
PathEdgeWidth
PathWidth
PauseAOLOnBrake
PauseLateralOnSignal
PauseLateralSpeed
PedalsOnUI
PersonalizeOpenpilot
PromptDistractedVolume
PromptVolume
QOLLateral
QOLLongitudinal
QOLVisuals
RadarTracksUI
RainbowPath
RandomEvents
RandomThemes
ReduceAccelerationLowVisibility
ReduceAccelerationRain
ReduceAccelerationRainStorm
ReduceAccelerationSnow
ReduceLateralAccelerationLowVisibility
ReduceLateralAccelerationRain
ReduceLateralAccelerationRainStorm
ReduceLateralAccelerationSnow
RefuseVolume
RelaxedFollow
RelaxedJerkAcceleration
RelaxedJerkDanger
RelaxedJerkDeceleration
RelaxedJerkSpeed
RelaxedJerkSpeedDecrease
RelaxedPersonalityProfile
ReverseCruise
RoadEdgesWidth
RoadNameUI
RotatingWheel
ScreenBrightness
ScreenBrightnessOnroad
ScreenManagement
ScreenRecorder
ScreenTimeout
ScreenTimeoutOnroad
SetSpeedLimit
SetSpeedOffset
ShowCEMStatus
ShowCPU
ShowCSCStatus
ShowGPU
ShowIP
ShowMemoryUsage
ShowSLCOffset
ShowSpeedLimits
ShowSteering
ShowStoppingPoint
ShowStoppingPointMetrics
ShowStorageLeft
ShowStorageUsed
Sidebar
SidebarMetrics
SignalMetrics
SLCConfirmation
SLCConfirmationHigher
SLCConfirmationLower
SLCFallback
SLCLookaheadHigher
SLCLookaheadLower
SLCMapboxFiller
SLCOverride
SLCPriority1
SLCPriority2
SLCPriority3
SNGHack
SpeedLimitChangedAlert
SpeedLimitController
SpeedLimitFiller
SpeedLimitSources
StandardFollow
StandardJerkAcceleration
StandardJerkDanger
StandardJerkDeceleration
StandardJerkSpeed
StandardJerkSpeedDecrease
StandardPersonalityProfile
StandbyMode
StaticPedalsOnUI
StoppedTimer
SubaruSNG
TacoTune
TacoTuneHacks
TetheringEnabled
ToyotaDoors
ToyotaDSUBypass
TuningLevel
TuningLevelConfirmed
TurnDesires
UnlimitedLength
UnlockDoors
UseKonikServer
UseSI
UseVienna
VeryLongDistanceButtonControl
VoltSNG
WarningImmediateVolume
WarningSoftVolume
WeatherPresets
WheelIcon
WheelSpeed
""".split())
FILE_RESET_KEYS = FILE_ONLY_UI_KEYS | {"OffroadScreensaver", "ConfidenceBall"}
# t994 gasAccelStop adoption markers (file-only): a reset must return the consumers to the stock-equivalent un-adopted state,
# otherwise rewritten registry defaults (Sport accel, Human ON, ...) would go live on a "reset" device.
ADOPTION_MARKERS = tuple("Phase3LongAccelProfilesEnabled Phase3AdvancedLongEnabled Phase3CEMEnabled Phase3StoppedDistanceEnabled Phase3ForceStopsEnabled Phase3ManualWeatherEnabled Phase3SpeedLimitEnabled Phase3PersonalitiesEnabled Phase3HumanFollowingEnabled Phase3LeadDetectionEnabled Phase3LaneChangeEnabled Phase3HumanLaneChangesEnabled Phase3TurnDesiresEnabled Phase3StopAccelEnabled Phase3StoppingRateEnabled".split())
UNSET_KEYS = frozenset({"TuningLevel", "TuningLevelConfirmed"})  # literal on purpose: rc_settings_gate audits it statically
# t999 BogPilot Driving Model selection (+ its runtime fallback state, file store): a reset returns to Default (stock).
DRIVING_MODEL_KEYS = ("BogPilotDrivingModel", "BogPilotDrivingModelState")
UNSET_ALL = UNSET_KEYS | frozenset(ADOPTION_MARKERS) | frozenset(DRIVING_MODEL_KEYS)


@dataclass(frozen=True)
class ResetResult:
  status: str  # not_requested | completed | failed
  error: str = ""  # stage only; never contains private parameter values


def reset_defaults() -> dict[str, str | None]:
  """Stock column, approved shipping overlays, then explicit unset policy."""
  values = {k: BOGPILOT_PARAMS[k][4] for k in sorted(RESET_KEYS)}
  for k, (value, _level) in PARAM_OVERRIDES.items():
    if k in values:
      values[k] = value
  values.update({k: "1" if FILE_TOGGLES[k][0] else "0" for k in sorted(FILE_RESET_KEYS)})
  values["OffroadScreensaver"] = "0"
  values["AlertVolumeControl"] = "0"
  for k in values:
    if k.endswith("Volume"):
      values[k] = "101"
  values.update(dict.fromkeys(UNSET_ALL))
  return values


# t994: fresh-install Device Controls = STOCK power behaviour. The compiled libparams defaults (9 -> 6 h, onroad 30 s)
# cannot change without a native rebuild, so startup moves them once (bogpilot_startup) and resets use this overlay.
DEVICE_STOCK_FRESH = {"DeviceShutdown": "33", "ScreenTimeoutOnroad": "10"}


def shipping_defaults() -> dict[str, str | None]:
  """BogPilot SHIPPING defaults for the Utilities "Reset BogPilot Settings to Defaults" row.

  reset_defaults() above is the *stock openpilot* policy (BOGPILOT_PARAMS stock column), which turns the
  shipped-ON features (Green Light, Lead Departed, Adjacent Lead Speed Boxes ...) OFF. Shipping defaults
  come from the registry default column + the locked shipping overlays, so a reset restores exactly what a
  fresh install gets. Same key scope/exclusions as reset_defaults (identity/auth/calibration never touched).
  """
  values: dict[str, str | None] = {}
  for k in sorted(RESET_KEYS):
    default = BOGPILOT_PARAMS[k][2]
    if default is None:
      continue  # no shipped default: leave the saved value alone
    values[k] = default if default != "" else None
  for k, (value, _level) in PARAM_OVERRIDES.items():
    if k in values:
      values[k] = value
  values.update({k: v for k, v in DEVICE_STOCK_FRESH.items() if k in values})
  values.update({k: "1" if FILE_TOGGLES[k][0] else "0" for k in sorted(FILE_RESET_KEYS)})
  values["OffroadScreensaver"] = "0"
  values["AlertVolumeControl"] = "0"
  for k in values:
    if k.endswith("Volume"):
      values[k] = "101"
  values.update(dict.fromkeys(UNSET_ALL))
  return values


def _atomic_file(path: Path, content: bytes | None) -> None:
  if content is None:
    path.unlink(missing_ok=True)
    return
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
  try:
    with os.fdopen(fd, "wb") as f:
      f.write(content)
      f.flush()
      os.fsync(f.fileno())
    os.replace(name, path)
  finally:
    Path(name).unlink(missing_ok=True)


def reset_requested(params, file_root: Path | str, *, backup: Callable[[], object] | None = None) -> ResetResult:
  """w10 supplies w5 backup closure; only a truthy durable receipt permits IO.

  Only the active store is mutated; stale typed-key fallback files are outside
  the durable backup scope and are preserved.

  Params is typed 0.11.2 Params (all_keys/get/get_bool/cpp2python/put/remove).
  Missing compiled keys fall back to files. File-only keys NEVER touch Params.
  No request => no directory creation, backup, defaults, or mutation.
  """
  stage = "request"
  try:
    known = {k.decode() if isinstance(k, bytes) else k for k in params.all_keys()}
    if REQUEST_KEY not in known or not params.get_bool(REQUEST_KEY):
      return ResetResult("not_requested")
    if backup is None:
      return ResetResult("failed", "backup unavailable")
    stage = "backup"
    if not backup():
      return ResetResult("failed", "backup failed")
    stage = "snapshot"
    directory = Path(file_root)
    values = reset_defaults()
    typed = (set(values) & known) - FILE_ONLY_UI_KEYS
    original_params = {k: params.get(k) for k in typed}
    original_files = {}
    for k in values.keys() - typed:
      path = directory / k
      if path.is_symlink():
        raise ValueError("symlink target refused")
      original_files[k] = path.read_bytes() if path.exists() else None
  except Exception:
    return ResetResult("failed", stage + " failed")

  try:
    stage = "apply"
    for k, text in values.items():
      if k in typed:
        # Empty stock values are unset; do not send strings to typed BOOL/INT.
        value = None if text in (None, "") else params.cpp2python(k, text.encode())
        if value is None:
          params.remove(k)
        else:
          params.put(k, value, block=True)
      else:
        _atomic_file(directory / k, None if text is None else text.encode())
    stage = "clear request"
    params.remove(REQUEST_KEY)  # last operation; never clear on partial failure
    return ResetResult("completed")
  except Exception:
    rollback_failed = False
    for k, value in original_params.items():
      try:
        if value is None:
          params.remove(k)
        else:
          params.put(k, value, block=True)
      except Exception:
        rollback_failed = True
    for k, content in original_files.items():
      try:
        _atomic_file(directory / k, content)
      except Exception:
        rollback_failed = True
    return ResetResult("failed", stage + " failed" + ("; rollback incomplete; restore backup" if rollback_failed else "; rolled back"))
