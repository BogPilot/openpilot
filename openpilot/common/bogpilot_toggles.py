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
# Legacy UI keys that the onroad UI keeps file-backed only (never Params get/put).
FILE_ONLY_UI_KEYS = frozenset({"RedesignUI", "BSMFlameTracks", "SwapSpeedGraph", "HideAccelGraph", "DeveloperHUD", "ShowAccelGraph", "LowerSpeedLimitsBox"})

FILE_TOGGLES: dict[str, tuple[bool | None, str]] = {
  # UI (default on)
  # Reserved, default OFF (default OFF: the normal screen-sleep timer wins). bogpilot-tesla-c3x ships no
  # screensaver and no settings row; nothing reads this key.
  "OffroadScreensaver": (False, "Reserved offroad screensaver setting (default OFF, no C3X implementation)"),
  "BSMFlameTracks": (True, "'Bog to the Future' flame tracks behind >88 mph blind-spot passers"),
  "ConfidenceBall": (True, "Model confidence ball on the onroad edge"),
  "RedesignUI": (True, "BogPilot onroad redesign"),
  # Telemetry-removal orphans: no uploader/athena/webrtc/hevc_streamd
  # processes remain on feae. Defaults OFF; do NOT register menus. Preserve any existing
  # owner file values if present; only the missing-file default changes.
  "ShowUploadRate": (False, "REMOVED/unsupported: onroad upload-rate readout (no uploader)"),
  "RemoteUIStream": (False, "REMOVED/unsupported: remote UI stream server (no webrtc/stream)"),
  # UI (default off)
  "DeveloperHUD": (False, "Developer HUD"),
  "SwapSpeedGraph": (True, "Legacy file key; layout is now LowerSpeedLimitsBox + ShowAccelGraph"),
  "HideAccelGraph": (False, "Legacy file key; replaced by ShowAccelGraph (default off)"),
  "ShowAccelGraph": (False, "Show the acceleration graph on the driving screen (can slow UI draw time)"),
  "LowerSpeedLimitsBox": (False, "Lower the top-left speed limits box if a rear-view mirror covers the top"),
  # Reserved, default OFF. Not features yet; the names are pinned so nothing ships them on.
  "OccViz": (False, "Occupancy visualisation (reserved, default OFF)"),
  "LiveYOLO": (False, "Live YOLO object overlay (reserved, default OFF)"),
  # System — HevcStream orphan (no hevc_streamd process packaged)
  "HevcStream": (False, "REMOVED/unsupported: hevc_streamd live route video stream"),
  # Car code (Tesla AP1); default decided by the car port
  "EnableICIntegration": (CAR_DEPENDENT, "AP1 instrument-cluster substitution"),
  "RegenComfortBrake": (CAR_DEPENDENT, "AP1 regen-sized lead approaches"),
  "RegenAwareStop": (CAR_DEPENDENT, "AP1 regen-aware stopping"),
  "AP1StandstillEngage": (CAR_DEPENDENT, "AP1 standstill engage"),
}

# key: (default, allowed values) for the few text-valued files
FILE_CHOICES: dict[str, tuple[str, tuple[str, ...]]] = {
  "ConfidenceBallSide": ("left", ("left", "right")),
  # Onroad sidebar middle box: the vehicle status (default, as before) or CPU usage. Saved by tapping the box.
  "SidebarVehicleSlot": ("vehicle", ("vehicle", "cpu")),
}

# Data files and one-shot markers kept in the same directory (not toggles)
DATA_FILES = ("LastKnownTime", "DriveHistory", "AP1DefaultsApplied", "ScreensaverDefaultOff1")

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


SCREENSAVER_MIGRATION_MARKER = "ScreensaverDefaultOff1"


def migrate_screensaver_default_off(directory: Path | None = None) -> bool:
  """One-shot: turn an inherited OffroadScreensaver=ON file off, so the normal screen-sleep timer applies.

  Runs once per device (marker file). It never touches the stock screen timeout, and a later deliberate
  opt-in (writing "1" after the marker exists) is left alone. Returns True if the file was switched off.
  """
  directory = Path(directory) if directory is not None else BOGPILOT_DIR
  marker = directory / SCREENSAVER_MIGRATION_MARKER
  if marker.exists():
    return False
  changed = False
  try:
    path = directory / "OffroadScreensaver"
    try:
      text = path.read_text(encoding="utf-8", errors="replace")[:64].strip().lower()
    except OSError:
      text = None
    directory.mkdir(parents=True, exist_ok=True)
    if text in _ON:
      tmp = path.with_name(".OffroadScreensaver.tmp")
      tmp.write_text("0")
      os.replace(tmp, path)
      changed = True
    marker.write_text("1\n")
  except OSError:
    pass  # a migration must never block startup
  return changed


ACCEL_GRAPH_MIGRATION_MARKER = "AccelGraphDefaultOff1"


def _file_truth(directory: Path, key: str) -> bool | None:
  """ON/OFF from an existing file, or None when the file is missing or unreadable."""
  try:
    text = (directory / key).read_text(encoding="utf-8", errors="replace")[:64].strip().lower()
  except OSError:
    return None
  if text in _ON:
    return True
  if text in _OFF:
    return False
  return None


def migrate_ui_layout_defaults(directory: Path | None = None) -> bool:
  """One-shot: adopt the new onroad layout defaults without overwriting a real user choice.

  Rule (flag for review): a missing file or a file whose value equals the old shipping default is treated
  as "never customized" and takes the new default. A value that differs from the old default is left alone,
  and any already-written new-key file is never overwritten.

  Old defaults were HideAccelGraph=OFF (graph shown) and the speed row in the lower slot (because
  SwapSpeedGraph shipped ON). New defaults are ShowAccelGraph=OFF and LowerSpeedLimitsBox=OFF (speed row
  at the top). The one custom combo we preserve is HideAccelGraph=ON: that user already hid the graph and
  the old hide path forced the speed row into the lower slot, so we write LowerSpeedLimitsBox=ON.

  Fresh installs write nothing (the new defaults apply to missing files). Returns True if a file was written.
  """
  directory = Path(directory) if directory is not None else BOGPILOT_DIR
  marker = directory / ACCEL_GRAPH_MIGRATION_MARKER
  if marker.exists():
    return False
  changed = False
  try:
    directory.mkdir(parents=True, exist_ok=True)
    hide = _file_truth(directory, "HideAccelGraph")
    show_exists = (directory / "ShowAccelGraph").exists()
    lower_exists = (directory / "LowerSpeedLimitsBox").exists()
    # Only the custom hide-graph value (old default was off) is preserved, including its lower capsule.
    if hide is True:
      if not show_exists:
        tmp = directory / ".ShowAccelGraph.tmp"
        tmp.write_text("0")
        os.replace(tmp, directory / "ShowAccelGraph")
        changed = True
      if not lower_exists:
        tmp = directory / ".LowerSpeedLimitsBox.tmp"
        tmp.write_text("1")
        os.replace(tmp, directory / "LowerSpeedLimitsBox")
        changed = True
    marker.write_text("1\n")
  except OSError:
    pass  # a migration must never block startup
  return changed
