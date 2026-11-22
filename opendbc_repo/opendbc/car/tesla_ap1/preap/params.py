"""BogPilot Pre-AP param keys (file-backed under /data/params_bogpilot).

July prebuilt params_pyx.so cannot store new Params keys (UnknownKeyName at
boot if added to bogpilot_default_params). Same pattern as EnableICIntegration.

Credit: NotAutopilot nap_params / nap_conf (names without NAP prefix).
User-facing product name: BogPilot.
"""
from __future__ import annotations

import os
import tempfile
import threading
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
  # Donor VIN for a salvage Bosch radar (17 letters / digits; empty = this car). Set by the Read Radar VIN button or by hand.
  # Read once when the car starts, sent to the panda on 0x560 only (preap/radar_donor.py). A /data/params_bogpilot file, not an
  # openpilot Params key, so it is never in initData / rlog params; kept out of log text, crash reports, settings backups and the
  # settings dump. Raw CAN in drive logs does carry it (the host 0x560 frames in sendcan and their rejected echo in can).
  # NAP NAPRadarDonorVin (nap_params.py:31 @ openpilot naponsp-alpha-prebuilt 7eb09d2a7); NAP's automatic F190 read is not ported.
  RADAR_DONOR_VIN = "TeslaRadarDonorVin"
  # Donor radar car type sent to the panda in 0x560 record 0 (the 0x2A9 position field): 0 pre-facelift Model S (default),
  # 1 facelift Model S, 2 Model X. NAP NAPRadarPosition (nap_conf.py:41,256-261; sunnypilot nap.py:287-288 @ 7eb09d2a7).
  # Separate from Radar Behind Nosecone. Read once when the car starts; a missing or bad value is 0.
  RADAR_DONOR_TYPE = "TeslaRadarDonorType"
  # Donor radar EPAS (steering rack) type sent to the panda in 0x560 record 0 (the 0x2A9 EPAS field): 0 Bosch L538 (default),
  # 1 Bosch L405, 2 Mando FGR64, 3 Mando VGR66, 4 Mando VGR66 Gen3. NAP nap-dev NAPRadarEpasType (nap_conf.py radar_epas_type,
  # clamp 0..4; ui layouts/settings/nap.py "Donor EPAS Type"; wiki hardware/bosch-radar). Read once when the car starts; a missing
  # or bad value is 0, which sends the same 0x2A9 bytes as before this setting existed.
  RADAR_EPAS_TYPE = "TeslaRadarEpasType"
  # Read Radar VIN button (preap/radar_vin_read.py): request flag set by the UI, cleared by the reader; status words only
  # (never the VIN). Neither is backed up.
  RADAR_READ_VIN = "TeslaRadarReadVin"
  RADAR_VIN_READ_STATUS = "TeslaRadarVinReadStatus"
  # Ignore radar HWFail (NotAutopilot NAPRadarIgnoreHwFail, opendbc/car/tesla/preap/nap_params.py:32,67 @ opendbc 508d26fcb, added in
  # a4c8a40f). Default OFF: RADC_HWFail is a radarFault (no entry / soft disable). ON: HWFail is advisory only, as NAP
  # radar_interface.py:211: no radarFault, the radar-valid gate still sees it (points kept out, the one warning). Read every radar
  # cycle, as NAP (through card's params snapshot, so no file IO in the step). Vehicle Settings toggle on a detected
  # Pre-AP Model S while Bosch Radar is on; the same file can still be set over ssh.
  RADAR_IGNORE_HW_FAIL = "TeslaRadarIgnoreHwFail"
  # Aftermarket iBooster swap (Tinkla TinklaHasIBooster, selfdrive/car/tesla/carstate.py:115@501c7de). Default OFF, Pre-AP
  # only, read once when the car starts. Display only: the onroad brake bar follows 0x554 BrakePedalPosition instead of
  # the binary brake press. NotAutopilot's NAPiBoosterEnabled (nap_params.py:31@e99f4dc75) is defined there but unused.
  HAS_IBOOSTER = "TeslaHasIBooster"
  # Radar mounting corrections, Pre-AP Bosch radar only (Tinkla TinklaUseTeslaRadarUpsideDown / TinklaRadarOffset, selfdrive/car/tesla/
  # radar_interface.py:67-69,145-151 @501c7de, MIT). Flip Radar: radar mounted upside down, so each track's lateral position (yRel) is
  # negated (Tinkla also negates yvRel; this schema has no live yvRel). Radar Offset: meters added to each track's lateral position, positive left, -1.0..1.0. Both default OFF / 0.0 (no
  # change), host side only (radar_interface.py), read once when the car starts. No panda change.
  RADAR_FLIP = "TeslaRadarUpsideDown"
  RADAR_OFFSET = "TeslaRadarOffset"
  # Pre AP Auto Speed. Default OFF: NAP-style engage, the set speed is captured from the current speed (NAP preap/engagement.py
  # @ e99f4dc75) and the Speed Limit Controller never moves it; the posted limit is still shown. ON: the BogPilot SLC set-speed
  # logic, as on AP1 (Set Speed Limit engage at limit + offset, SLC raises and lowers the set). Pre-AP pedal longitudinal only.
  # Read once when the car starts (card and plannerd). File-backed like the keys above: no libparams key, so a missing file is
  # the default and a saved choice is never overwritten.
  AUTO_SPEED = "TeslaPreApAutoSpeed"
  # Pre-AP From-Stop Speed. Default OFF: NAP standstill engage. A speed-control engage at a standstill restores the last set of
  # this drive, else captures the current speed (0) as NAP does (NAP preap/engagement.py:142,243-246 @ e99f4dc75); either way
  # the car is held at 0 until the accelerator. ON: a standstill engage (pull or tip) sets the driver's from-stop speed (the AP1
  # Standstill Tap Speed, AP1TapFromZeroMs) instead. Applies with Pre AP Auto Speed OFF only (Auto Speed ON always uses the
  # from-stop speed from a stop). Pedal longitudinal only. Read once when the car starts (card). File-backed like the keys above.
  FROM_STOP_SPEED = "TeslaPreApFromStopSpeed"
  # AP1 follow-distance stalk retrofit detected on this car (preap/stalk_retrofit.py). Hidden: no menu row, not a toggle, not in the
  # settings backup or any defaults list. Default 0. The car writes 1 once, when the detector first latches (through the StepCache
  # thread, never file IO in the 100 Hz step); at startup a 1 skips detection and the dial is read from the first frame. Cleared
  # by Reset Hardware Settings (preap/hw_tools.py). File-backed like every key above: it is NOT in libparams_c.so, so the
  # libparams table needs no rebuild (adding it there would, and the July prebuilt would refuse the unknown key at boot).
  STALK_RETROFIT_DETECTED = "PreAPStalkRetrofitDetected"


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
  PreApParamKeys.RADAR_DONOR_VIN: "",
  PreApParamKeys.RADAR_DONOR_TYPE: 0,
  PreApParamKeys.RADAR_EPAS_TYPE: 0,
  PreApParamKeys.RADAR_READ_VIN: False,
  PreApParamKeys.RADAR_VIN_READ_STATUS: "",
  PreApParamKeys.RADAR_IGNORE_HW_FAIL: False,
  PreApParamKeys.HAS_IBOOSTER: False,
  PreApParamKeys.RADAR_FLIP: False,
  PreApParamKeys.RADAR_OFFSET: 0.0,
  PreApParamKeys.AUTO_SPEED: False,
  PreApParamKeys.FROM_STOP_SPEED: False,
  PreApParamKeys.STALK_RETROFIT_DETECTED: False,
}

# Overridable in tests.
_params_dir = PARAMS_DIR


def _path(key: str) -> Path:
  return _params_dir / key


class StepCache:
  """card's 100 Hz step never touches /data while this is on (card.py starts it for Pre-AP).

  Reads come from an in-memory snapshot that a background thread refreshes every REFRESH_S; writes update the snapshot at
  once (the next read in the step sees them) and the thread writes them out, latest value wins, errors counted, never
  raised into the step. A key outside the snapshot is read directly once and then kept (counted in `misses`). Values are
  never logged (one may be a donor VIN).
  """
  REFRESH_S = 0.1

  def __init__(self, keys):
    self._lock = threading.Lock()
    self._vals = {k: _read_text_file(k) for k in keys}     # card init, before the loop
    self._pending: dict[str, str] = {}
    self.misses = 0
    self.write_errors = 0
    self.thread: threading.Thread | None = None
    self._stop = threading.Event()

  def read(self, key: str) -> str:
    with self._lock:
      if key in self._vals:
        return self._vals[key]
      self.misses += 1
    text = _read_text_file(key)
    with self._lock:
      self._vals.setdefault(key, text)
    return text

  def write(self, key: str, text: str) -> None:
    with self._lock:
      self._vals[key] = text
      self._pending[key] = text

  def refresh_once(self) -> None:
    with self._lock:
      pending, self._pending = self._pending, {}
      keys = list(self._vals)
    for k, text in pending.items():
      try:
        _write_text_file(k, text)
      except OSError:
        self.write_errors += 1
    fresh = {k: _read_text_file(k) for k in keys}
    with self._lock:
      for k, text in fresh.items():
        if k not in self._pending:                  # a newer write from the step wins over the file
          self._vals[k] = text

  def _loop(self) -> None:
    while not self._stop.is_set():
      self.refresh_once()
      self._stop.wait(self.REFRESH_S)
    self.refresh_once()                             # flush the last writes

  def start(self) -> "StepCache":
    self.thread = threading.Thread(target=self._loop, name="preap_params", daemon=True)
    self.thread.start()
    return self

  def stop(self) -> None:
    self._stop.set()
    if self.thread is not None:
      self.thread.join(timeout=2.0)


_step_cache: StepCache | None = None


def start_step_cache() -> StepCache:
  """Card: from now on this process reads and writes these params through the snapshot (see StepCache)."""
  global _step_cache
  if _step_cache is None:
    keys = [v for k, v in vars(PreApParamKeys).items() if not k.startswith("_") and isinstance(v, str)]
    _step_cache = StepCache(keys).start()
  return _step_cache


def stop_step_cache() -> None:
  global _step_cache
  if _step_cache is not None:
    _step_cache.stop()
    _step_cache = None


def _read_text(key: str) -> str:
  c = _step_cache
  if c is not None and threading.current_thread() is not c.thread:
    return c.read(key)
  return _read_text_file(key)


def _write_text(key: str, text: str) -> None:
  c = _step_cache
  if c is not None and threading.current_thread() is not c.thread:
    c.write(key, text)
    return
  _write_text_file(key, text)


def _read_text_file(key: str) -> str:
  try:
    p = _path(key)
    if p.is_file():
      return p.read_text(encoding="utf-8", errors="replace").strip()
  except OSError:
    pass
  return ""


def _write_text_file(key: str, text: str) -> None:
  """Atomic replace in the same directory so a concurrent reader never sees a truncated file.

  07e8bd68f's StepCache writes these files from a background thread while readers (the next
  refresh, the UI, tests) may open the same path. Path.write_text truncates first, so a
  reader can see empty text and fall back to the default. Write a tmp next to the destination,
  flush+fsync, then os.replace. The tmp is removed only if that fails.

  tempfile.mkstemp creates the tmp as 0o600. os.replace keeps that mode, which would change
  an existing 0o644 file (Path.write_text left the mode alone) and would create new files
  as 0o600 instead of 0o644 (Path.write_text with umask 0o022). Set the tmp to the existing
  file's mode, or 0o644 if the file is new, before replacing.
  """
  _params_dir.mkdir(parents=True, exist_ok=True)
  dest = _path(key)
  mode = dest.stat().st_mode & 0o777 if dest.is_file() else 0o644
  fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=str(dest.parent))
  try:
    os.fchmod(fd, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
      fd = -1
      f.write(text)
      f.flush()
      os.fsync(f.fileno())
    os.replace(tmp_name, dest)
    tmp_name = ""
    try:
      dirfd = os.open(str(dest.parent), os.O_RDONLY)
      try:
        os.fsync(dirfd)
      finally:
        os.close(dirfd)
    except OSError:
      pass
  except Exception:
    if fd >= 0:
      try:
        os.close(fd)
      except OSError:
        pass
    if tmp_name:
      try:
        os.unlink(tmp_name)
      except OSError:
        pass
    raise


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


RADAR_OFFSET_LIMIT_M = 1.0


def radar_offset_m() -> float:
  """TeslaRadarOffset in meters, clamped to -1.0..1.0. Missing, empty, bad, nan or inf is 0.0 (no offset)."""
  value = get_float(PreApParamKeys.RADAR_OFFSET)
  if value != value or value in (float("inf"), float("-inf")):
    return 0.0
  return max(-RADAR_OFFSET_LIMIT_M, min(RADAR_OFFSET_LIMIT_M, value))


RADAR_DONOR_TYPES = (0, 1, 2)   # pre-facelift Model S, facelift Model S, Model X


def radar_donor_type() -> int:
  """TeslaRadarDonorType as 0, 1 or 2; anything else (missing, bad, out of range) is 0, the NAP default. Exact text only, so a
  bad file ("inf", "1.5") can never raise or round into a valid type."""
  text = _read_text(PreApParamKeys.RADAR_DONOR_TYPE)
  return int(text) if text in ("0", "1", "2") else 0


RADAR_EPAS_TYPE_MAX = 4   # Bosch L538, Bosch L405, Mando FGR64, Mando VGR66, Mando VGR66 Gen3


def clamp_radar_epas_type(value) -> int:
  """0..RADAR_EPAS_TYPE_MAX for an int (bool and anything else that is not an int is 0)."""
  if type(value) is not int:
    return 0
  return max(0, min(RADAR_EPAS_TYPE_MAX, value))


def radar_epas_type() -> int:
  """TeslaRadarEpasType clamped to 0..4, as NAP's radar_epas_type max(0, min(4, ...)). Whole-number text only: missing, empty,
  "1.5", "inf", "nan" or other text is 0, so a bad file can never raise or round into a type."""
  text = _read_text(PreApParamKeys.RADAR_EPAS_TYPE)   # surrounding whitespace is already stripped
  digits = text[1:] if text.startswith("-") else text
  return clamp_radar_epas_type(int(text)) if digits.isascii() and digits.isdigit() else 0


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


def preap_auto_speed() -> bool:
  """Pre AP Auto Speed (default OFF). Any read problem reads as OFF (NAP-style engage at the current speed)."""
  try:
    return bool(get_bool(PreApParamKeys.AUTO_SPEED))
  except Exception:
    return False


def preap_from_stop_speed() -> bool:
  """Pre-AP From-Stop Speed (default OFF = NAP standstill engage). Any read problem reads as OFF."""
  try:
    return bool(get_bool(PreApParamKeys.FROM_STOP_SPEED))
  except Exception:
    return False


def double_pull_enabled() -> bool:
  """The pull mode actually applied: the saved choice AND AOL available. False = single pull."""
  return bool(aol_available() and get_bool(PreApParamKeys.DOUBLE_PULL))
