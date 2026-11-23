"""Auto Height: AP1 Model S / Model X with air suspension (was Lower on Park).

One feature with two heights: when the car shifts into Park, ask the air suspension once for the Park height (default Low);
when it shifts from Park into Drive, ask once for the Drive height (default Medium). Either height can be None, which skips
that shift; with both None nothing is ever sent. The car's own location-based raise is
left on. Nothing here touches steering, speed or braking.

The touchscreen sends the height request 0x308 on the chassis bus (bus 0) at 10 Hz: byte 0 is 0x40 when idle and
0x40 + level while a height is being asked for (1 Low, 2 Medium, 3 High, 4 Very High; a tap sends it for about 2 s).
Bytes 1-7 are car and session specific, so a request is always built from the newest received 0x308 with only byte 0
replaced. A 2 s burst at 50 Hz with level 1 lowered a parked car from Medium to Low while the screen kept sending its idle
frame. The air suspension flag is GTW_airSuspensionInstalled in GTW_carConfig (0x398).

Each shift into Park, and each shift from Park into Drive, sends at most one burst, only at standstill and never while
openpilot is engaged (Drive also needs the accelerator released). The burst stops at once if the car leaves that gear (or the
gear is unknown), moves, engages, the screen's own 0x308 goes stale, or the driver taps a height on the screen (a received
0x308 whose byte 0 is not idle). The panda checks the same frame (opendbc/safety/modes/tesla_ap1.h): bytes 1-7 equal to the
newest received 0x308, rate capped, never while controls are allowed, only in Park with FLAG_TESLA_AP1_RIDE_HEIGHT and only in
Drive at standstill with FLAG_TESLA_AP1_RIDE_HEIGHT_DRIVE, and only the levels PANDA_PARK_LEVELS / the Drive rule allow.

Settings are file-backed under /data/params_bogpilot (the prebuilt params table has no keys for them):
  AutoHeight           1 = on. Missing = the saved LowerOnPark value (migration), else off.
  AutoHeightPark       none | low | medium | high | very_high. Missing = the saved LowerOnParkHeight value (migration), else low.
  AutoHeightDrive      none | low | medium | high | very_high. Missing = none after moving over from Lower on Park (a
                       LowerOnPark or LowerOnParkHeight file exists), so that behavior is unchanged; else medium.
  AirSuspensionDetected  written by car state from 0x398; the Vehicle Controls rows are shown only when it is 1.
The old LowerOnPark / LowerOnParkHeight files are only read, never changed or deleted, so a saved choice carries over as is.
"""
from __future__ import annotations

from pathlib import Path

RIDE_HEIGHT_ADDR = 0x308
RIDE_HEIGHT_BUS = 0            # chassis bus
CAR_CONFIG_ADDR = 0x398
IDLE_BYTE0 = 0x40
LEVEL_LOW = 1
LEVEL_MEDIUM = 2
LEVEL_HIGH = 3
LEVEL_VERY_HIGH = 4
LEVELS = (LEVEL_LOW, LEVEL_MEDIUM, LEVEL_HIGH, LEVEL_VERY_HIGH)
HEIGHTS = ("low", "medium", "high", "very_high")
LEVEL_BY_HEIGHT = {"low": LEVEL_LOW, "medium": LEVEL_MEDIUM, "high": LEVEL_HIGH, "very_high": LEVEL_VERY_HIGH}
NONE = "none"                  # skip this shift: no burst
CHOICES = HEIGHTS + (NONE,)    # the order the height buttons cycle through
HEIGHT_LABELS = {"low": "Low", "medium": "Medium", "high": "High", "very_high": "Very High", NONE: "None"}
HEIGHT_DEFAULT = "low"         # Park
DRIVE_HEIGHT_DEFAULT = "medium"

DT_CTRL_HZ = 100
BURST_HZ = 50
BURST_S = 2.0
BURST_PERIOD_FRAMES = DT_CTRL_HZ // BURST_HZ        # card runs at 100 Hz: one frame every 2 ticks
BURST_FRAMES = int(BURST_S * BURST_HZ)              # 100 frames
SOURCE_MAX_AGE_S = 0.5                               # the screen sends 0x308 at 10 Hz
STANDSTILL_MS = 0.1

# Panda safety bits (SAFETY_TESLA param), both set at car start only while Auto Height is on: 1024 lets the panda pass the
# request in Park, 2048 in Drive at standstill.
FLAG_TESLA_AP1_RIDE_HEIGHT = 1024
FLAG_TESLA_AP1_RIDE_HEIGHT_DRIVE = 2048

# Capability gates: what this tree's panda (opendbc/safety/modes/tesla_ap1.h) allows: levels 1-4 in Park (flag 1024) and in
# Drive at standstill (flag 2048). With the older Lower on Park panda rule these were (1, 2) and False.
PANDA_TX_SUPPORTED = True
PANDA_PARK_LEVELS = LEVELS
PANDA_DRIVE_TX_SUPPORTED = True

PARAMS_DIR = Path("/data/params_bogpilot")
ENABLE_KEY = "AutoHeight"
HEIGHT_KEY = "AutoHeightPark"
DRIVE_HEIGHT_KEY = "AutoHeightDrive"
LEGACY_ENABLE_KEY = "LowerOnPark"
LEGACY_HEIGHT_KEY = "LowerOnParkHeight"
DETECTED_KEY = "AirSuspensionDetected"
# Tests may override these module attributes.
_enable_path = PARAMS_DIR / ENABLE_KEY
_height_path = PARAMS_DIR / HEIGHT_KEY
_drive_height_path = PARAMS_DIR / DRIVE_HEIGHT_KEY
_detected_path = PARAMS_DIR / DETECTED_KEY

_ON = ("1", "true", "on", "yes")


def _text(v) -> str:
  if v is None:
    return ""
  if isinstance(v, (bytes, bytearray)):
    v = v.decode(errors="replace")
  return str(v).strip().lower()


def _read(path: Path) -> str:
  try:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
  except OSError:
    return ""


def _write(path: Path, text: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_name(path.name + ".tmp")
  tmp.write_text(text, encoding="utf-8")
  tmp.replace(path)


def _legacy(path: Path, legacy_key: str) -> Path:
  return path.with_name(legacy_key)


def _read_migrated(path: Path, legacy_key: str) -> str:
  """The new key's file when it exists, else the old Lower on Park file next to it (read only), else empty."""
  return _read(path) if path.is_file() else _read(_legacy(path, legacy_key))


def _height_text(stored) -> str:
  return _text(stored).replace(" ", "_")


def enabled(stored: str | bytes | None = None, path: Path | None = None) -> bool:
  """Auto Height on/off. Missing (and no saved LowerOnPark), empty or anything but 1/true/on/yes = off."""
  if stored is None:
    stored = _read_migrated(path if path is not None else _enable_path, LEGACY_ENABLE_KEY)
  return _text(stored) in _ON


def set_enabled(state: bool, path: Path | None = None) -> None:
  _write(path if path is not None else _enable_path, "1" if state else "0")


def _choice(stored, default: str) -> str:
  text = _height_text(stored)
  return text if text in CHOICES else default


def height(stored: str | bytes | None = None, path: Path | None = None) -> str:
  """Park height: none, low, medium, high or very_high. Missing (and no saved LowerOnParkHeight) or unknown = low."""
  if stored is None:
    stored = _read_migrated(path if path is not None else _height_path, LEGACY_HEIGHT_KEY)
  return _choice(stored, HEIGHT_DEFAULT)


def set_height(value: str, path: Path | None = None) -> None:
  value = _height_text(value)
  if value not in CHOICES:
    raise ValueError(value)
  _write(path if path is not None else _height_path, value)


def level_for(value: str | bytes | None = None, path: Path | None = None) -> int | None:
  """The 0x308 level for the Park height (None reads the file): 1 Low, 2 Medium, 3 High, 4 Very High; None for None."""
  return LEVEL_BY_HEIGHT.get(height(value, path))


def _moved_from_lower_on_park(path: Path) -> bool:
  return path.with_name(LEGACY_ENABLE_KEY).is_file() or path.with_name(LEGACY_HEIGHT_KEY).is_file()


def drive_height(stored: str | bytes | None = None, path: Path | None = None) -> str:
  """Drive height: none, low, medium, high or very_high. Missing = none for a setup moved over from Lower on Park (its old
  files sit next to this one), else medium. Unknown = medium."""
  if stored is None:
    path = path if path is not None else _drive_height_path
    if not path.is_file():
      return NONE if _moved_from_lower_on_park(path) else DRIVE_HEIGHT_DEFAULT
    stored = _read(path)
  return _choice(stored, DRIVE_HEIGHT_DEFAULT)


def set_drive_height(value: str, path: Path | None = None) -> None:
  value = _height_text(value)
  if value not in CHOICES:
    raise ValueError(value)
  _write(path if path is not None else _drive_height_path, value)


def drive_level_for(value: str | bytes | None = None, path: Path | None = None) -> int | None:
  """The 0x308 level for the Drive height (None reads the file); None for None."""
  return LEVEL_BY_HEIGHT.get(drive_height(value, path))


def park_choices() -> tuple[str, ...]:
  """Park choices this tree's panda allows (the picker offers only these), None included."""
  return tuple(h for h in HEIGHTS if LEVEL_BY_HEIGHT[h] in PANDA_PARK_LEVELS) + (NONE,)


def drive_choices() -> tuple[str, ...]:
  return CHOICES if PANDA_DRIVE_TX_SUPPORTED else ()


def park_burst_wanted(path: Path | None = None, enable_path: Path | None = None) -> bool:
  """Auto Height on and a Park height other than None: the car start sets the panda Park bit only then."""
  return enabled(path=enable_path) and level_for(path=path) is not None


def drive_burst_wanted(path: Path | None = None, enable_path: Path | None = None) -> bool:
  """Auto Height on and a Drive height other than None (the Drive bit also needs the panda Drive rule)."""
  return enabled(path=enable_path) and drive_level_for(path=path) is not None


def air_suspension_detected(stored: str | bytes | None = None, path: Path | None = None) -> bool:
  if stored is None:
    stored = _read(path if path is not None else _detected_path)
  return _text(stored) == "1"


def read_air_suspension_detected(path: Path | None = None) -> bool | None:
  """Tri-state for read-only displays: True (1), False (0), None when the car has not reported 0x398 yet (file missing or
  unreadable) or the file holds anything else."""
  text = _text(_read(path if path is not None else _detected_path))
  return True if text == "1" else False if text == "0" else None


def write_air_suspension_detected(state: bool, path: Path | None = None) -> bool:
  """Write the detection file only when it changes. Returns True when written."""
  target = path if path is not None else _detected_path
  want = "1" if state else "0"
  if _text(_read(target)) == want:
    return False
  try:
    _write(target, want)
  except OSError:
    return False
  return True


def air_suspension_from_car_config(value) -> bool | None:
  """GTW_airSuspensionInstalled: 0 = coil springs, anything else = air suspension. None when unknown."""
  try:
    return int(value) != 0
  except (TypeError, ValueError):
    return None


def tx_supported(safety_param: int | None = None) -> bool:
  """Park: True only when this build's panda allows 0x308 and (when given) the drive's safety param carries the Park bit."""
  if not PANDA_TX_SUPPORTED:
    return False
  return safety_param is None or bool(int(safety_param) & FLAG_TESLA_AP1_RIDE_HEIGHT)


def drive_tx_supported(safety_param: int | None = None) -> bool:
  """Drive: True only when this build's panda has the Drive rule and (when given) the safety param carries the Drive bit."""
  if not PANDA_DRIVE_TX_SUPPORTED:
    return False
  return safety_param is None or bool(int(safety_param) & FLAG_TESLA_AP1_RIDE_HEIGHT_DRIVE)


def frame_with_level(source: bytes, level: int) -> bytes:
  """The newest received 0x308 with byte 0 = 0x40 + level (1-4)."""
  if level not in LEVELS:
    raise ValueError(level)
  if len(source) != 8:
    raise ValueError(len(source))
  return bytes([IDLE_BYTE0 + level]) + bytes(source[1:])


class LowerOnPark:
  """Auto Height, Park part (the class keeps its Lower on Park name). One burst per Park entry. update() runs every card step
  (100 Hz) and returns the 0x308 payload to send, or None."""
  IDLE, BURST, DONE = "idle", "burst", "done"

  def __init__(self):
    self.prev_park: bool | None = None   # None until the gear is first known: starting up in Park is not a Park entry
    self.state = self.IDLE
    self.level = LEVEL_LOW
    self.sent = 0
    self.ticks = 0
    self.last_result = ""                # why the last Park entry did or did not send (tests / debugging)

  def _abort(self, why: str) -> None:
    self.state = self.DONE
    self.last_result = why

  def update(self, *, in_park: bool, gear_known: bool, can_tx: bool, controls_active: bool, v_ego: float,
             source: bytes | None, source_age_s: float, new_sources=(), prefs=None) -> bytes | None:
    """prefs: callable returning (enabled, level or None for None); read only at a Park entry (file reads stay off the 100 Hz path)."""
    tapped = any(len(f) >= 1 and f[0] != IDLE_BYTE0 for f in new_sources)
    fresh = source is not None and len(source) == 8 and source_age_s <= SOURCE_MAX_AGE_S
    moving = abs(float(v_ego)) >= STANDSTILL_MS

    entry = False
    if gear_known:
      entry = in_park and self.prev_park is False
      if not in_park:
        self.state = self.IDLE if self.state != self.BURST else self.state
      self.prev_park = in_park

    if self.state == self.BURST:
      if not gear_known or not in_park:
        self._abort("left Park")
      elif tapped:
        self._abort("driver tapped a height")
      elif controls_active:
        self._abort("engaged")
      elif moving:
        self._abort("moving")
      elif not fresh:
        self._abort("0x308 stale")
      elif not can_tx:
        self._abort("no panda permission")
      if self.state != self.BURST:
        if gear_known and not in_park:
          self.state = self.IDLE      # left Park: the next Park entry may send again
        return None
      self.ticks += 1
      if self.ticks % BURST_PERIOD_FRAMES != 0:
        return None
      return self._send(source)

    if not entry:
      return None
    # Park entry: decide once.
    self.state = self.DONE
    if not can_tx:
      self.last_result = "no panda permission"
      return None
    on, level = prefs() if prefs is not None else (False, LEVEL_LOW)
    if not on:
      self.last_result = "off"
      return None
    if level is None:
      self.last_result = "none"            # Park height None: skip this shift
      return None
    if level not in PANDA_PARK_LEVELS:
      self.last_result = "bad level"
      return None
    if controls_active or moving:
      self.last_result = "engaged or moving"
      return None
    if not fresh or source[0] != IDLE_BYTE0 or tapped:
      self.last_result = "screen busy or 0x308 missing"
      return None
    self.state = self.BURST
    self.level = level
    self.sent = 0
    self.ticks = 0
    self.last_result = "sending"
    return self._send(source)

  def _send(self, source: bytes) -> bytes:
    self.sent += 1
    if self.sent >= BURST_FRAMES:
      self.state = self.DONE
      self.last_result = "sent"
    return frame_with_level(source, self.level)


class HeightOnDrive:
  """Auto Height, Drive part: one burst per shift from Park into Drive, at standstill. update() runs every card step (100 Hz) and
  returns the 0x308 payload to send, or None.

  Armed while the car stands in Park; Neutral on the way keeps it armed while stopped. Reverse, moving, or starting up already
  in Drive never arm it, so only a shift from Park counts. An unknown gear changes nothing until the gear is known again.
  """
  IDLE, BURST, DONE = "idle", "burst", "done"
  GEARS = ("park", "drive", "neutral", "reverse", "unknown")

  def __init__(self):
    self.armed = False
    self.state = self.IDLE
    self.level = LEVEL_LOW
    self.sent = 0
    self.ticks = 0
    self.last_result = ""                # why the last shift into Drive did or did not send (tests / debugging)

  def _abort(self, why: str) -> None:
    self.state = self.DONE
    self.last_result = why

  def update(self, *, gear: str, can_tx: bool, controls_active: bool, v_ego: float, gas_pressed: bool,
             source: bytes | None, source_age_s: float, new_sources=(), prefs=None) -> bytes | None:
    """gear: park / drive / neutral / reverse / unknown. prefs: callable returning (Auto Height on, Drive level 1-4 or None); read
    only at a shift into Drive (file reads stay off the 100 Hz path)."""
    tapped = any(len(f) >= 1 and f[0] != IDLE_BYTE0 for f in new_sources)
    fresh = source is not None and len(source) == 8 and source_age_s <= SOURCE_MAX_AGE_S
    moving = abs(float(v_ego)) >= STANDSTILL_MS
    in_drive = gear == "drive"

    entry = False
    if gear == "park":
      self.armed = True
    elif gear == "drive":
      entry = self.armed
      self.armed = False
    elif gear == "reverse":
      self.armed = False
    if moving:
      self.armed = False

    if self.state == self.BURST:
      if not in_drive:
        self._abort("left Drive")
      elif tapped:
        self._abort("driver tapped a height")
      elif controls_active:
        self._abort("engaged")
      elif moving:
        self._abort("moving")
      elif gas_pressed:
        self._abort("gas pressed")
      elif not fresh:
        self._abort("0x308 stale")
      elif not can_tx:
        self._abort("no panda permission")
      if self.state != self.BURST:
        return None
      self.ticks += 1
      if self.ticks % BURST_PERIOD_FRAMES != 0:
        return None
      return self._send(source)

    if not entry:
      return None
    # Shift from Park into Drive: decide once.
    self.state = self.DONE
    if not can_tx:
      self.last_result = "no panda permission"
      return None
    on, level = prefs() if prefs is not None else (False, LEVEL_MEDIUM)
    if not on:
      self.last_result = "off"
      return None
    if level is None:
      self.last_result = "none"            # Drive height None: skip this shift
      return None
    if level not in LEVELS:
      self.last_result = "bad level"
      return None
    if controls_active or moving or gas_pressed:
      self.last_result = "engaged, moving or gas pressed"
      return None
    if not fresh or source[0] != IDLE_BYTE0 or tapped:
      self.last_result = "screen busy or 0x308 missing"
      return None
    self.state = self.BURST
    self.level = level
    self.sent = 0
    self.ticks = 0
    self.last_result = "sending"
    return self._send(source)

  def _send(self, source: bytes) -> bytes:
    self.sent += 1
    if self.sent >= BURST_FRAMES:
      self.state = self.DONE
      self.last_result = "sent"
    return frame_with_level(source, self.level)
