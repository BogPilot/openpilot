"""Byte-exact, scoped BogPilot settings snapshots. Never restores or changes live settings.

Daily caches settings at boot and periodically archives them. This port deliberately
separates durable archival from boot/default/reset policy. /cache can be evicted;
this is not an off-device recovery system. No automatic archive restoration.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS

DEFAULT_BACKUP_ROOT = Path("/cache/bogpilot/settings-backups")
# Audited frozen scope: future registry additions do not silently enter backups.
SETTING_KEYS = frozenset("""
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
ClusterOffset
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
LongitudinalActuatorDelay
LongitudinalActuatorDelayStock
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
SLCPriority
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
StartAccel
StartAccelStock
StaticPedalsOnUI
SteerDelay
SteerDelayStock
SteerFriction
SteerFrictionStock
SteerKP
SteerKPStock
SteerLatAccel
SteerLatAccelStock
SteerRatio
SteerRatioStock
StopAccel
StopAccelStock
StoppedTimer
StoppingDecelRate
StoppingDecelRateStock
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
VEgoStarting
VEgoStartingStock
VEgoStopping
VEgoStoppingStock
VeryLongDistanceButtonControl
VoltSNG
WarningImmediateVolume
WarningSoftVolume
WeatherPresets
WheelControls
WheelIcon
WheelSpeed
""".split())
FILE_KEYS = frozenset("""BSMFlameTracks ConfidenceBall RedesignUI RemoteUIStream DeveloperHUD SwapSpeedGraph HideAccelGraph OccViz LiveYOLO HevcStream EnableICIntegration RegenComfortBrake RegenAwareStop AP1StandstillEngage ConfidenceBallSide OffroadScreensaver Phase3LongAccelProfilesEnabled Phase3AdvancedLongEnabled Phase3CEMEnabled Phase3StoppedDistanceEnabled Phase3ForceStopsEnabled Phase3ManualWeatherEnabled Phase3SpeedLimitEnabled Phase3PersonalitiesEnabled Phase3HumanFollowingEnabled Phase3LeadDetectionEnabled Phase3LaneChangeEnabled Phase3HumanLaneChangesEnabled Phase3TurnDesiresEnabled Phase3StopAccelEnabled Phase3StoppingRateEnabled""".split())
MAX_VALUE_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class BackupResult:
  success: bool
  path: Path | None = None
  error: str | None = None

  def __bool__(self):
    return self.success


def _digest(entries):
  return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read_value(path):
  # Params' parent d symlink is normal; individual setting symlinks are not.
  if path.is_symlink():
    raise ValueError("setting symlink refused")
  try:
    with path.open("rb") as f:
      value = f.read(MAX_VALUE_BYTES + 1)
  except FileNotFoundError:
    return None
  if len(value) > MAX_VALUE_BYTES:
    raise ValueError("setting exceeds backup size limit")
  return value


def _atomic_write(path, data):
  fd, name = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
  try:
    with os.fdopen(fd, "wb") as f:
      f.write(data)
      f.flush()
      os.fsync(f.fileno())
    os.replace(name, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
      os.fsync(directory)
    finally:
      os.close(directory)
  finally:
    try:
      os.unlink(name)
    except FileNotFoundError:
      pass


def read_snapshot(path):
  """Validate a v1 snapshot; return its document. Never applies settings.

  Corruption, unknown versions/keys, invalid base64 and scope expansion fail closed.
  """
  with Path(path).open("rb") as f:
    raw = f.read(MAX_SNAPSHOT_BYTES + 1)
  if len(raw) > MAX_SNAPSHOT_BYTES:
    raise ValueError("snapshot exceeds size limit")
  doc = json.loads(raw)
  if doc.get("version") != 1 or not isinstance(doc.get("entries"), dict):
    raise ValueError("unsupported snapshot")
  for key, entry in doc["entries"].items():
    if key not in SETTING_KEYS | FILE_KEYS or set(entry) != {"store", "value"}:
      raise ValueError("unknown setting or entry")
    if entry["store"] not in ("params", "file") or (key in FILE_ONLY_UI_KEYS and entry["store"] != "file"):
      raise ValueError("invalid store")
    if len(base64.b64decode(entry["value"], validate=True)) > MAX_VALUE_BYTES:
      raise ValueError("setting exceeds size limit")
  if doc.get("digest") != _digest(doc["entries"]):
    raise ValueError("snapshot digest mismatch")
  return doc


def backup_settings(params, *, file_root, backup_root=DEFAULT_BACKUP_ROOT, reason="startup"):
  """Return truthy only after a complete durable snapshot and latest.json commit.

  Caller supplies file_root explicitly. Reads existing bytes, never registry defaults.
  No fallback writes to /data; failures are nonfatal receipts without secret values.
  Before-reset callers MUST require bool(result) before changing any settings.
  Settings writers should be quiescent (startup before processes/defaults/reset).
  """
  # reason is caller context only; intentionally not persisted (no timestamps/PII).
  del reason
  try:
    entries = {}
    known = {k.decode() if isinstance(k, bytes) else k for k in params.all_keys()}
    for key in sorted(SETTING_KEYS | FILE_KEYS):
      row = BOGPILOT_PARAMS.get(key)
      if key in SETTING_KEYS and (row is None or row[0] != "PERSISTENT"):
        continue
      native = key in known and key not in FILE_ONLY_UI_KEYS
      if native:
        params.check_key(key)
        path = Path(params.get_param_path(key))
      else:
        path = Path(file_root) / key
      value = _read_value(path)
      if value is not None:
        entries[key] = {"store": "params" if native else "file", "value": base64.b64encode(value).decode("ascii")}
    digest = _digest(entries)
    doc = {"version": 1, "digest": digest, "entries": entries}
    data = json.dumps(doc, sort_keys=True).encode()
    if len(data) > MAX_SNAPSHOT_BYTES:
      raise ValueError("snapshot exceeds size limit")
    root = Path(backup_root)
    if root.is_symlink():
      raise ValueError("backup directory symlink refused")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    # Serialize only publishers, never block startup on a competing backup.
    fd = os.open(root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as lock:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
      snapshot = root / (digest + ".json")
      if snapshot.exists():
        if read_snapshot(snapshot) != doc:
          raise ValueError("existing snapshot invalid")
      else:
        _atomic_write(snapshot, data)
      _atomic_write(root / "latest.json", data)
    return BackupResult(True, snapshot)
  except Exception as exc:
    # Never include exception text: native errors may contain private param values.
    return BackupResult(False, error=type(exc).__name__)
