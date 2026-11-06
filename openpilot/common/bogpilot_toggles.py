"""BogPilot file toggles: plain files under /data/params_bogpilot/<Key>.

These predate the 0.11 params rebuild (the 0.9.7 device ran a prebuilt params library that could
not store new keys), and owners flip them over SSH (`echo 0 > /data/params_bogpilot/<Key>`), so
the 19.9 port keeps them as files with exactly the reference read rules:

  * text is trimmed; "1"/"true"/"on" = on, "0"/"false"/"off" = off
  * a missing, empty or unknown value means the toggle's default
  * writes are "1" or "0"

Defaults below match BogPilot/openpilot@367e1fe. CAR_DEPENDENT toggles are owned by car code
(Tesla AP1): their default is decided there (on for AP1-fingerprinted cars, off otherwise), and
on any other car they read as off unless the file says otherwise.
"""
import os
from pathlib import Path

BOGPILOT_DIR = Path(os.environ.get("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))

CAR_DEPENDENT = None

# key: (default, description)
# Legacy UI keys that stream 4 keeps file-backed only (never Params get/put).
FILE_ONLY_UI_KEYS = frozenset({"RedesignUI", "BSMFlameTracks", "SwapSpeedGraph", "DeveloperHUD"})

FILE_TOGGLES: dict[str, tuple[bool | None, str]] = {
  # UI (default on)
  "OffroadScreensaver": (True, "Offroad screensaver: bounce the upload readout / BogPilot logo instead of screen off"),
  "BSMFlameTracks": (True, "'Bog to the Future' flame tracks behind >88 mph blind-spot passers"),
  "ConfidenceBall": (True, "Model confidence ball on the onroad edge"),
  "RedesignUI": (True, "BogPilot onroad redesign"),
  "ShowUploadRate": (True, "Onroad upload-rate readout"),
  "RemoteUIStream": (True, "Remote UI screen stream server (only serves while a viewer is connected)"),
  # UI (default off)
  "DeveloperHUD": (False, "Developer HUD"),
  "SwapSpeedGraph": (True, "Accel graph on top, speed row below it"),
  "HideAccelGraph": (False, "Hide the accel graph; the speed row stays in the lower slot"),
  # Reserved, default OFF. Not features yet; the names are pinned so nothing ships them on.
  "OccViz": (False, "Occupancy visualisation (reserved, default OFF)"),
  "LiveYOLO": (False, "Live YOLO object overlay (reserved, default OFF)"),
  # System
  "HevcStream": (True, "hevc_streamd live route video stream (onroad only, not on PC)"),
  # Car code (Tesla AP1); default decided by the car port
  "EnableICIntegration": (CAR_DEPENDENT, "AP1 instrument-cluster substitution"),
  "RegenComfortBrake": (CAR_DEPENDENT, "AP1 regen-sized lead approaches"),
  "RegenAwareStop": (CAR_DEPENDENT, "AP1 regen-aware stopping"),
  "AP1StandstillEngage": (CAR_DEPENDENT, "AP1 standstill engage"),
}

# key: (default, allowed values) for the few text-valued files
FILE_CHOICES: dict[str, tuple[str, tuple[str, ...]]] = {
  "ConfidenceBallSide": ("left", ("left", "right")),
}

# Data files and one-shot markers kept in the same directory (not toggles)
DATA_FILES = ("LastKnownTime", "DriveHistory", "AP1DefaultsApplied")

_ON = ("1", "true", "on")
_OFF = ("0", "false", "off")


def toggle_path(key: str) -> Path:
  return BOGPILOT_DIR / key


def _read_text(key: str, limit: int = 64) -> str | None:
  try:
    with open(toggle_path(key), encoding="utf-8", errors="replace") as f:
      return f.read(limit).strip()
  except OSError:
    return None


def read_toggle(key: str, default: bool | None = None) -> bool:
  """Read a file toggle. default=None uses the registry default (car-dependent ones read off)."""
  if default is None:
    reg = FILE_TOGGLES.get(key, (False, ""))[0]
    default = bool(reg) if reg is not None else False
  text = _read_text(key)
  if text is None:
    return default
  text = text.lower()
  if text in _ON:
    return True
  if text in _OFF:
    return False
  return default


def write_toggle(key: str, on: bool) -> None:
  BOGPILOT_DIR.mkdir(parents=True, exist_ok=True)
  path = toggle_path(key)
  tmp = path.with_name(f".{key}.tmp")
  tmp.write_text("1" if on else "0")
  os.replace(tmp, path)


def read_choice(key: str) -> str:
  default, allowed = FILE_CHOICES[key]
  text = _read_text(key)
  return text if text in allowed else default


def write_choice(key: str, value: str) -> None:
  default, allowed = FILE_CHOICES[key]
  if value not in allowed:
    raise ValueError(f"{key}: {value!r} not in {allowed}")
  BOGPILOT_DIR.mkdir(parents=True, exist_ok=True)
  path = toggle_path(key)
  tmp = path.with_name(f".{key}.tmp")
  tmp.write_text(value)
  os.replace(tmp, path)
