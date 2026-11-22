"""Lower on Park: AP1 Model S / Model X with air suspension.

When the car shifts into Park, ask the air suspension for Low (or Medium) once, so the car's own location-based raise
still works at a saved driveway or garage. Nothing here touches steering, speed or braking.

The touchscreen sends the height request 0x308 on the chassis bus (bus 0) at 10 Hz: byte 0 is 0x40 when idle and
0x40 + level while a height is being asked for (1 Low, 2 Medium, 3 High, 4 Very High; a tap sends it for about 2 s).
Bytes 1-7 are car and session specific, so a request is always built from the newest received 0x308 with only byte 0
replaced. A 2 s burst at 50 Hz with level 1 lowered a parked car from Medium to Low while the screen kept sending its idle
frame. The air suspension flag is GTW_airSuspensionInstalled in GTW_carConfig (0x398).

Each Park entry sends at most one burst. The burst stops at once if the car leaves Park (or the gear is unknown), the car
moves, openpilot engages, the screen's own 0x308 goes stale, or the driver taps a height on the screen (a received 0x308
whose byte 0 is not idle). The panda allows this frame only in Park, only Low or Medium, only with bytes 1-7 equal to the
newest received 0x308, rate capped and never while controls are allowed (opendbc/safety/modes/tesla_ap1.h).

Settings are file-backed under /data/params_bogpilot (the prebuilt params table has no keys for them):
  LowerOnPark          1 = on. Missing = off.
  LowerOnParkHeight    low | medium. Missing = low.
  AirSuspensionDetected  written by car state from 0x398; the Vehicle Controls row is shown only when it is 1.
"""
from __future__ import annotations

from pathlib import Path

RIDE_HEIGHT_ADDR = 0x308
RIDE_HEIGHT_BUS = 0            # chassis bus
CAR_CONFIG_ADDR = 0x398
IDLE_BYTE0 = 0x40
LEVEL_LOW = 1
LEVEL_MEDIUM = 2
HEIGHTS = ("low", "medium")
HEIGHT_DEFAULT = "low"
LEVEL_BY_HEIGHT = {"low": LEVEL_LOW, "medium": LEVEL_MEDIUM}
HEIGHT_LABELS = {"low": "Low", "medium": "Medium"}

DT_CTRL_HZ = 100
BURST_HZ = 50
BURST_S = 2.0
BURST_PERIOD_FRAMES = DT_CTRL_HZ // BURST_HZ        # card runs at 100 Hz: one frame every 2 ticks
BURST_FRAMES = int(BURST_S * BURST_HZ)              # 100 frames
SOURCE_MAX_AGE_S = 0.5                               # the screen sends 0x308 at 10 Hz
STANDSTILL_MS = 0.1

# Panda safety bit (SAFETY_TESLA param) that allows the 0x308 TX. Set at car start only while Lower on Park is on.
FLAG_TESLA_AP1_RIDE_HEIGHT = 1024

# Capability gate: this tree's panda allows 0x308 under the rule in opendbc/safety/modes/tesla_ap1.h (with the drive's
# FLAG_TESLA_AP1_RIDE_HEIGHT). False would hide the Vehicle Controls rows and never send.
PANDA_TX_SUPPORTED = True

PARAMS_DIR = Path("/data/params_bogpilot")
ENABLE_KEY = "LowerOnPark"
HEIGHT_KEY = "LowerOnParkHeight"
DETECTED_KEY = "AirSuspensionDetected"
# Tests may override these module attributes.
_enable_path = PARAMS_DIR / ENABLE_KEY
_height_path = PARAMS_DIR / HEIGHT_KEY
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


def enabled(stored: str | bytes | None = None, path: Path | None = None) -> bool:
  """Lower on Park on/off. Missing, empty or anything but 1/true/on/yes = off."""
  if stored is None:
    stored = _read(path if path is not None else _enable_path)
  return _text(stored) in _ON


def set_enabled(state: bool, path: Path | None = None) -> None:
  _write(path if path is not None else _enable_path, "1" if state else "0")


def height(stored: str | bytes | None = None, path: Path | None = None) -> str:
  """low or medium. Missing or unknown = low."""
  if stored is None:
    stored = _read(path if path is not None else _height_path)
  text = _text(stored)
  return text if text in HEIGHTS else HEIGHT_DEFAULT


def set_height(value: str, path: Path | None = None) -> None:
  value = _text(value)
  if value not in HEIGHTS:
    raise ValueError(value)
  _write(path if path is not None else _height_path, value)


def level_for(value: str | bytes | None = None, path: Path | None = None) -> int:
  """The 0x308 level for a stored height (None reads the file): 1 Low, 2 Medium."""
  return LEVEL_BY_HEIGHT[height(value, path)]


def air_suspension_detected(stored: str | bytes | None = None, path: Path | None = None) -> bool:
  if stored is None:
    stored = _read(path if path is not None else _detected_path)
  return _text(stored) == "1"


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
  """True only when this build's panda allows 0x308 and (when given) the drive's safety param carries the bit."""
  if not PANDA_TX_SUPPORTED:
    return False
  return safety_param is None or bool(int(safety_param) & FLAG_TESLA_AP1_RIDE_HEIGHT)


def frame_with_level(source: bytes, level: int) -> bytes:
  """The newest received 0x308 with byte 0 = 0x40 + level. Only Low and Medium."""
  if level not in (LEVEL_LOW, LEVEL_MEDIUM):
    raise ValueError(level)
  if len(source) != 8:
    raise ValueError(len(source))
  return bytes([IDLE_BYTE0 + level]) + bytes(source[1:])


class LowerOnPark:
  """One burst per Park entry. update() runs every card step (100 Hz) and returns the 0x308 payload to send, or None."""
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
    """prefs: callable returning (enabled, level); read only at a Park entry (file reads stay off the 100 Hz path)."""
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
    if level not in (LEVEL_LOW, LEVEL_MEDIUM):
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
