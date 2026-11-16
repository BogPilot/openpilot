"""BogPilot Pre-AP param keys (file-backed under /data/params_bogpilot).

July prebuilt params_pyx.so cannot store new Params keys (UnknownKeyName at
boot if added to bogpilot_default_params). Same pattern as EnableICIntegration.

Credit: NotAutopilot nap_params / nap_conf (names without NAP prefix).
User-facing product name: BogPilot.
"""
from __future__ import annotations

from pathlib import Path

PARAMS_DIR = Path("/data/params_bogpilot")

# Registration SoT — key names used by UI, car code, and tests.
class PreApParamKeys:
  PEDAL_CALIB_DONE = "PedalCalibDone"
  PEDAL_CALIB_MIN = "PedalCalibMin"
  PEDAL_CALIB_MAX = "PedalCalibMax"
  PEDAL_CALIB_FACTOR = "PedalCalibFactor"
  PEDAL_CALIB_ZERO = "PedalCalibZero"
  PEDAL_CAN_BUS = "PedalCanBus"
  PEDAL_CALIB_ARMED = "PedalCalibArmed"  # runtime: UI arms, car completes
  PEDAL_CALIB_MESSAGE = "PedalCalibMessage"  # runtime UI status / fail reason
  PEDAL_DETECTED = "PedalDetected"      # runtime mirror for UI status line
  PEDAL_CALIB_STAGE = "PedalCalibStage"  # runtime: "", coast, coast_ok, saved, failed (the car publishes, the UI reads)
  PEDAL_SEEN_TS = "PedalSeenTs"          # runtime: wall-clock heartbeat while the pedal is heard (UI status goes stale without it)
  PEDAL_SEEN_MONO = "PedalSeenMono"      # runtime: the same heartbeat on time.monotonic() (survives a wall-clock jump)
  # Pre-AP NAP-style double-pull under Always On Lateral. Default ON.
  # File-backed: July params_pyx.so cannot store new Params keys.
  DOUBLE_PULL = "TeslaPreApDoublePull"
  # Driver Override Sensitivity, 1 to 5 (default 2, override.SENSITIVITY_DEFAULT). File-backed and read by the car code once per drive
  # (override.py); it is not a compiled Params key. A missing or bad value is 2.
  OVERRIDE_SENSITIVITY = "OverrideSensitivity"
  # Runtime: pandad records the panda firmware version it found (and "Not found" with no panda) so the Vehicle screen can show it.
  PANDA_FIRMWARE = "PandaFirmwareVersion"
  # Bosch radar retrofit (NotAutopilot NAPRadarEnabled / NAPRadarBehindNosecone, common/params_keys.h:147-148@e99f4dc75).
  # Default OFF, Pre-AP only, read once when the car starts (CarParams + safety flags). Nosecone is a sub-option of Enabled.
  RADAR_ENABLED = "TeslaRadarEnabled"
  RADAR_BEHIND_NOSECONE = "TeslaRadarBehindNosecone"
  # Aftermarket iBooster swap (Tinkla TinklaHasIBooster, selfdrive/car/tesla/carstate.py:115@501c7de). Default OFF, Pre-AP
  # only, read once when the car starts. Display only: the onroad brake bar follows 0x554 BrakePedalPosition instead of
  # the binary brake press. NotAutopilot's NAPiBoosterEnabled (nap_params.py:31@e99f4dc75) is defined there but unused.
  HAS_IBOOSTER = "TeslaHasIBooster"


# Safe defaults (match NotAutopilot DEFAULT_CONFIG).
DEFAULTS = {
  PreApParamKeys.PEDAL_CALIB_DONE: False,
  PreApParamKeys.PEDAL_CALIB_MIN: -3.0,
  PreApParamKeys.PEDAL_CALIB_MAX: 99.6,
  PreApParamKeys.PEDAL_CALIB_FACTOR: 1.0,
  PreApParamKeys.PEDAL_CALIB_ZERO: 0.0,
  PreApParamKeys.PEDAL_CAN_BUS: 2,
  PreApParamKeys.PEDAL_CALIB_ARMED: False,
  PreApParamKeys.PEDAL_CALIB_MESSAGE: "",
  PreApParamKeys.PEDAL_DETECTED: False,
  PreApParamKeys.PEDAL_CALIB_STAGE: "",
  PreApParamKeys.PEDAL_SEEN_TS: 0.0,
  PreApParamKeys.PEDAL_SEEN_MONO: 0.0,
  PreApParamKeys.DOUBLE_PULL: True,
  PreApParamKeys.PANDA_FIRMWARE: "",
  PreApParamKeys.OVERRIDE_SENSITIVITY: 2,
  PreApParamKeys.RADAR_ENABLED: False,
  PreApParamKeys.RADAR_BEHIND_NOSECONE: False,
  PreApParamKeys.HAS_IBOOSTER: False,
}

# Overridable in tests.
_params_dir = PARAMS_DIR


def _path(key: str) -> Path:
  return _params_dir / key


def _read_text(key: str) -> str:
  try:
    p = _path(key)
    if p.is_file():
      return p.read_text(encoding="utf-8", errors="replace").strip()
  except OSError:
    pass
  return ""


def _write_text(key: str, text: str) -> None:
  _params_dir.mkdir(parents=True, exist_ok=True)
  _path(key).write_text(text, encoding="utf-8")


def get_bool(key: str, default: bool | None = None) -> bool:
  if default is None:
    default = bool(DEFAULTS.get(key, False))
  text = _read_text(key)
  if text == "":
    return default
  if text in ("1", "true", "on"):
    return True
  if text in ("0", "false", "off"):
    return False
  return default


def set_bool(key: str, value: bool) -> None:
  # Avoid rewriting identical values every controlsd frame (PedalDetected mirror).
  want = "1" if value else "0"
  if _read_text(key) == want:
    return
  try:
    _write_text(key, want)
  except OSError:
    # Fresh device / read-only /data must not kill controlsd.
    pass


def get_float(key: str, default: float | None = None) -> float:
  if default is None:
    default = float(DEFAULTS.get(key, 0.0))
  text = _read_text(key)
  if text == "":
    return default
  try:
    return float(text)
  except ValueError:
    return default


def set_float(key: str, value: float) -> None:
  _write_text(key, repr(float(value)))


def get_int(key: str, default: int | None = None) -> int:
  if default is None:
    default = int(DEFAULTS.get(key, 0))
  text = _read_text(key)
  if text == "":
    return default
  try:
    return int(float(text))
  except ValueError:
    return default


def set_int(key: str, value: int) -> None:
  _write_text(key, str(int(value)))


def get_str(key: str, default: str | None = None) -> str:
  if default is None:
    default = str(DEFAULTS.get(key, ""))
  text = _read_text(key)
  return default if text == "" else text


def set_str(key: str, value: str) -> None:
  # Do not log value — may hold a donor VIN.
  try:
    _write_text(key, str(value))
  except OSError:
    pass


_aol_provider = None


def register_aol_provider(provider) -> None:
  """The ONE interface the Always On Lateral lane has to satisfy for Pre-AP double pull.

  `provider` is a zero-argument callable returning True only while the AOL lane's complete fail-closed policy passes for THIS car
  (Pre-AP fingerprint admitted, safety mode, consent, firmware attestation, ... whatever that lane decides). card.py registers
  `selfdrive.car.ap1_runtime.preap_aol_available(CP)` if, and only if, that function exists; it does not exist in this build, so
  nothing is registered. None un-registers. Pre-AP code never reads the AlwaysOnLateral param itself and never enables AOL.
  """
  global _aol_provider
  _aol_provider = provider


def aol_available() -> bool:
  """True only while a registered provider says AOL may run for this car. No provider, a provider that raises, or a non-True answer = False.

  False (this build) = double pull is inert: the saved TeslaPreApDoublePull value is kept untouched but not applied, the menu row is hidden,
  and one pull engages steering and pedal longitudinal together (single pull).
  """
  provider = _aol_provider
  if provider is None:
    return False
  try:
    return provider() is True
  except Exception:
    return False


def double_pull_enabled() -> bool:
  """The pull mode actually applied: the saved choice AND AOL available. False = single pull."""
  return bool(aol_available() and get_bool(PreApParamKeys.DOUBLE_PULL))
