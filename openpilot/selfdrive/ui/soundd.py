import math
import numpy as np
import time
import wave


from openpilot.cereal import log, messaging
from openpilot.common.basedir import BASEDIR
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import Ratekeeper
from openpilot.common.utils import retry
from openpilot.common.swaglog import cloudlog

from openpilot.system import micd
from openpilot.common.hardware import HARDWARE

# --- BogPilot alert volumes (stream 7) ---
# FrogPilot defaults: AlertVolumeControl off -> ambient for all alerts (engage/disengage audible).
# When a future AP1/defaults stream writes volume params, honor them; never default to mute.
try:
  from openpilot.selfdrive.ui.bogpilot.alert_volumes import (
    FROGPILOT_VOLUME_DEFAULTS,
    VOLUME_PARAM_KEYS,
    resolve_alert_gain,
  )
except Exception:  # pragma: no cover - keep stock soundd usable without the package
  FROGPILOT_VOLUME_DEFAULTS = {
    "AlertVolumeControl": "0",
    "EngageVolume": "101",
    "DisengageVolume": "101",
    "PromptVolume": "101",
    "PromptDistractedVolume": "101",
    "RefuseVolume": "101",
    "WarningSoftVolume": "101",
    "WarningImmediateVolume": "101",
  }
  VOLUME_PARAM_KEYS = tuple(k for k in FROGPILOT_VOLUME_DEFAULTS if k != "AlertVolumeControl")

  def resolve_alert_gain(*, alert_volume_control, percent, ambient, key=None):
    if not alert_volume_control:
      return ambient
    pct = int(percent)
    if key in ("PromptVolume", "PromptDistractedVolume", "WarningSoftVolume", "WarningImmediateVolume"):
      pct = max(pct, 25)
    frac = pct / 100.0
    return ambient if abs(frac - 1.01) < 1e-9 else frac

import os
from pathlib import Path

_VOLUME_ALERT_KEYS = {
  # filled after AudibleAlert is defined — see _bogpilot_bind_volume_keys()
}

def _bogpilot_params_dir() -> Path:
  return Path(os.getenv("BOGPILOT_PARAMS_DIR", "/data/params_bogpilot"))

def _bogpilot_read_param(key: str) -> str | None:
  # Prefer file store so this works before Params keys are registered (stream 6).
  try:
    return (_bogpilot_params_dir() / key).read_text(encoding="utf-8").strip()
  except OSError:
    pass
  try:
    from openpilot.common.params import Params  # C3X
    v = Params().get(key)
    if v is None:
      return None
    return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v)
  except Exception:
    pass
  try:
    from common.params import Params  # C3 flat
    v = Params().get(key)
    if v is None:
      return None
    return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v)
  except Exception:
    return None

def _bogpilot_bool(text: str | None, default: bool) -> bool:
  if text is None:
    return default
  t = text.strip().lower()
  if t in ("1", "true", "on"):
    return True
  if t in ("0", "false", "off"):
    return False
  return default

def _bogpilot_int(text: str | None, default: int) -> int:
  if text is None:
    return default
  try:
    return int(float(text))
  except (ValueError, TypeError, OverflowError):
    return default

SAMPLE_RATE = 48000
SAMPLE_BUFFER = 4096 # (approx 100ms)
MAX_VOLUME = 1.0
MIN_VOLUME = 0.1
ALERT_RAMP_TIME = 4 # seconds to ramp critical alerts to max volume
ALERT_MAX_TIME = 8 # seconds before critical alerts switch to the max sound
SELFDRIVE_STATE_TIMEOUT = 5 # 5 seconds
FILTER_DT = 1. / (micd.SAMPLE_RATE / micd.FFT_SAMPLES)

AMBIENT_DB = 22 # DB where MIN_VOLUME is applied
DB_SCALE = 30 # AMBIENT_DB + DB_SCALE is where MAX_VOLUME is applied

VOLUME_BASE = 20
if HARDWARE.get_device_type() == "tizi":
  AMBIENT_DB = 30
  VOLUME_BASE = 10

AudibleAlert = log.SelfdriveState.AudibleAlert
CRITICAL_MAX = -1 # internal sound key, not an AudibleAlert


def _bogpilot_bind_volume_keys():
  global _VOLUME_ALERT_KEYS
  _VOLUME_ALERT_KEYS = {
    AudibleAlert.engage: "EngageVolume",
    AudibleAlert.disengage: "DisengageVolume",
    AudibleAlert.refuse: "RefuseVolume",
    AudibleAlert.prompt: "PromptVolume",
    AudibleAlert.promptRepeat: "PromptVolume",
    AudibleAlert.promptDistracted: "PromptDistractedVolume",
    AudibleAlert.warningSoft: "WarningSoftVolume",
    AudibleAlert.warningImmediate: "WarningImmediateVolume",
  }

_bogpilot_bind_volume_keys()



sound_list: dict[int, tuple[str, int | None, float]] = {
  # AudibleAlert, file name, play count (none for infinite)
  AudibleAlert.engage: ("engage.wav", 1, MAX_VOLUME),
  AudibleAlert.disengage: ("disengage.wav", 1, MAX_VOLUME),
  AudibleAlert.refuse: ("refuse.wav", 1, MAX_VOLUME),

  AudibleAlert.prompt: ("warning.wav", 1, MAX_VOLUME),
  AudibleAlert.promptRepeat: ("warning.wav", None, MAX_VOLUME),
  AudibleAlert.promptDistracted: ("dm_warning.wav", None, MAX_VOLUME),

  AudibleAlert.preAlert: ("pre_alert.wav", 1, MAX_VOLUME),

  AudibleAlert.warningSoft: ("critical.wav", None, MAX_VOLUME),
  AudibleAlert.warningImmediate: ("dm_critical.wav", None, MAX_VOLUME),
  CRITICAL_MAX: ("dm_critical_max.wav", None, MAX_VOLUME),
}

def check_selfdrive_timeout_alert(sm):
  ss_missing = time.monotonic() - sm.recv_time['selfdriveState']

  if ss_missing > SELFDRIVE_STATE_TIMEOUT:
    if sm['selfdriveState'].enabled and (ss_missing - SELFDRIVE_STATE_TIMEOUT) < 10:
      return True

  return False


class Soundd:
  def __init__(self):
    self.load_sounds()

    self.current_alert = AudibleAlert.none
    self.current_sound = AudibleAlert.none
    self.current_volume = MIN_VOLUME
    self.current_sound_frame = 0

    self.ramp_start_volume = MIN_VOLUME
    self.ramp_start_time = 0.

    self.selfdrive_timeout_alert = False
    self.pending_stop = False

    self.spl_filter_weighted = FirstOrderFilter(0, 2.5, FILTER_DT, initialized=False)
    self._bp_ambient_volume = MIN_VOLUME
    self._bp_next_reload = 0.0
    self._bp_reload_volumes()

  def _bp_reload_volumes(self):
    """Live consumer: re-read file-first store; clamp percents to 0..101.
    Safety-alert floor (>=25 for Prompt, PromptDistracted, WarningSoft, WarningImmediate) remains in alert_volumes.volume_fraction / resolve_alert_gain.
    Stock warningSoft/warningImmediate ramp to MAX_VOLUME is unchanged.
    """
    self._bp_alert_volume_control = _bogpilot_bool(
      _bogpilot_read_param("AlertVolumeControl"),
      _bogpilot_bool(FROGPILOT_VOLUME_DEFAULTS.get("AlertVolumeControl"), False),
    )
    self._bp_volume_percents = {
      key: max(0, min(101, _bogpilot_int(_bogpilot_read_param(key), int(float(FROGPILOT_VOLUME_DEFAULTS.get(key, "101"))))))
      for key in VOLUME_PARAM_KEYS
    }

  def load_sounds(self):
    self.loaded_sounds: dict[int, np.ndarray] = {}

    # Load all sounds
    for sound in sound_list:
      filename, play_count, volume = sound_list[sound]

      with wave.open(BASEDIR + "/openpilot/selfdrive/assets/sounds/" + filename, 'r') as wavefile:
        assert wavefile.getnchannels() == 1
        assert wavefile.getsampwidth() == 2
        assert wavefile.getframerate() == SAMPLE_RATE

        length = wavefile.getnframes()
        self.loaded_sounds[sound] = np.frombuffer(wavefile.readframes(length), dtype=np.int16).astype(np.float32) / (2**16/2)

  def get_sound_data(self, frames): # get "frames" worth of data from the current alert sound, looping when required

    ret = np.zeros(frames, dtype=np.float32)

    if self.current_alert != AudibleAlert.none:
      num_loops = sound_list[self.current_alert][1]
      sound_data = self.loaded_sounds[self.current_sound]
      written_frames = 0

      current_sound_frame = self.current_sound_frame % len(sound_data)
      loops = self.current_sound_frame // len(sound_data)

      while written_frames < frames and (num_loops is None or loops < num_loops):
        available_frames = sound_data.shape[0] - current_sound_frame
        frames_to_write = min(available_frames, frames - written_frames)
        ret[written_frames:written_frames+frames_to_write] = sound_data[current_sound_frame:current_sound_frame+frames_to_write]
        written_frames += frames_to_write
        self.current_sound_frame += frames_to_write
        current_sound_frame = self.current_sound_frame % len(sound_data)
        loops = self.current_sound_frame // len(sound_data)
        if self.pending_stop and current_sound_frame == 0:
          self.current_alert = AudibleAlert.none
          self.pending_stop = False
          break

    return ret * self.current_volume

  def callback(self, data_out: np.ndarray, frames: int, time, status) -> None:
    if status:
      cloudlog.warning(f"soundd stream over/underflow: {status}")
    data_out[:frames, 0] = self.get_sound_data(frames)

  def update_alert(self, new_alert):
    current_alert_played_once = self.current_alert == AudibleAlert.none or self.current_sound_frame >= len(self.loaded_sounds[self.current_sound])
    # let looping sounds finish the current loop instead of cutting off mid tone
    if new_alert == AudibleAlert.none and self.current_alert != AudibleAlert.none and sound_list[self.current_alert][1] is None:
      if current_alert_played_once:
        self.pending_stop = True
      else:
        self.current_alert = AudibleAlert.none
        self.current_sound_frame = 0
      return
    self.pending_stop = False
    if self.current_alert != new_alert and (new_alert != AudibleAlert.none or current_alert_played_once):
      if new_alert in (AudibleAlert.warningSoft, AudibleAlert.warningImmediate):
        self.ramp_start_volume = self.current_volume
        self.ramp_start_time = time.monotonic()
      self.current_alert = new_alert
      self.current_sound = new_alert
      self.current_sound_frame = 0

  def get_audible_alert(self, sm):
    if sm.updated['selfdriveState']:
      new_alert = sm['selfdriveState'].alertSound.raw
      self.update_alert(new_alert)
    elif check_selfdrive_timeout_alert(sm):
      self.update_alert(AudibleAlert.warningImmediate)
      self.selfdrive_timeout_alert = True
    elif self.selfdrive_timeout_alert:
      self.update_alert(AudibleAlert.none)
      self.selfdrive_timeout_alert = False

  def calculate_volume(self, weighted_db):
    volume = ((weighted_db - AMBIENT_DB) / DB_SCALE) * (MAX_VOLUME - MIN_VOLUME) + MIN_VOLUME
    return math.pow(VOLUME_BASE, (np.clip(volume, MIN_VOLUME, MAX_VOLUME) - 1))

  @retry(attempts=10, delay=3)
  def get_stream(self, sd):
    # reload sounddevice to reinitialize portaudio
    sd._terminate()
    sd._initialize()
    return sd.OutputStream(channels=1, samplerate=SAMPLE_RATE, callback=self.callback, blocksize=SAMPLE_BUFFER)

  def soundd_thread(self):
    # sounddevice must be imported after forking processes
    import sounddevice as sd
    micd.patch_sounddevice(sd)

    sm = messaging.SubMaster(['selfdriveState', 'soundPressure'])

    with self.get_stream(sd) as stream:
      rk = Ratekeeper(20)

      cloudlog.info(f"soundd stream started: {stream.samplerate=} {stream.channels=} {stream.dtype=} {stream.device=}, {stream.blocksize=}")
      while True:
        sm.update(0)

        # BogPilot: idle ~1 s reload of Alert Volume Controller (skip while an alert plays)
        if self.current_alert == AudibleAlert.none and time.monotonic() >= self._bp_next_reload:
          self._bp_reload_volumes()
          self._bp_next_reload = time.monotonic() + 1.0

        # freeze ambient estimate during alerts to avoid mic feedback increasing volume
        if sm.updated['soundPressure']:
          self.spl_filter_weighted.update(sm["soundPressure"].soundPressureWeightedDb)
          if self.current_alert == AudibleAlert.none:
            self._bp_ambient_volume = self.calculate_volume(float(self.spl_filter_weighted.x))
            self.current_volume = self._bp_ambient_volume

        self.get_audible_alert(sm)

        # BogPilot: per-alert volumes (FrogPilot defaults — engage/disengage audible)
        if self.current_alert != AudibleAlert.none:
          key = _VOLUME_ALERT_KEYS.get(self.current_alert)
          if key is None:
            self.current_volume = self._bp_ambient_volume
          else:
            self.current_volume = resolve_alert_gain(
              alert_volume_control=self._bp_alert_volume_control,
              percent=self._bp_volume_percents.get(key, 101),
              ambient=self._bp_ambient_volume,
              key=key,
            )

        if self.current_alert in (AudibleAlert.warningSoft, AudibleAlert.warningImmediate):
          elapsed = time.monotonic() - self.ramp_start_time
          ramp_vol = float(np.interp(elapsed, [0, ALERT_RAMP_TIME], [self.ramp_start_volume, MAX_VOLUME]))
          self.current_volume = max(self.current_volume, ramp_vol)
          if elapsed >= ALERT_MAX_TIME and self.current_sound != CRITICAL_MAX:
            self.current_sound = CRITICAL_MAX
            self.current_sound_frame = 0

        rk.keep_time()

        assert stream.active


def main():
  s = Soundd()
  s.soundd_thread()


if __name__ == "__main__":
  main()
