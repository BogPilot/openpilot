"""BogPilot screen recorder (t913u): Python/raylib port of daily frogpilot/ui/screenrecorder (bogpilot-tesla 04d560f3e).

Daily semantics kept: recordings in /data/media/screen_recordings, "<Month>_<dd>_<yyyy>-<hh>-<mm>-<ss><AM|PM>.mp4",
5-minute segments, refuse to start (or rotate) with < 1 GiB free, a "<file>.lock" beside the file while it is being
written, ~10 Mbit/s H.264 at 2160x1080, capture every other 20 Hz UI frame (10 Hz), bounded queue of 4 frames that
drops the oldest, stop on any onroad/offroad transition, the record button toggles.
C3X differences (documented): frames are read back from the finished UI framebuffer just before end_drawing (so alerts,
drawn last, are included) instead of QWidget::grab; encoding is an ffmpeg subprocess (the AGNOS 19.9 image ships
ffmpeg with libx264 and h264_v4l2m2m) instead of the daily direct V4L2 encoder; daily's blended mid-frames are replaced
by repeating the last frame so the file plays in real time when the UI renders slower; output is fragmented MP4 so a
crash or power loss leaves a playable file; free space is also re-checked every 5 s while recording.
Only what the UI itself draws is captured, and only after the user presses the button.
"""
from __future__ import annotations

from collections import deque
import datetime
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

RECORDINGS_DIR = "/data/media/screen_recordings"
MAX_SEGMENT_S = 5 * 60
MIN_FREE_BYTES = 1 << 30
CAPTURE_HZ = 10
BITRATE = 10 * 1024 * 1024
MAX_QUEUE = 4
MAX_REPEAT = 5             # at most 0.5 s of repeated frames for one slow UI frame
DISK_CHECK_S = 5.0
CLOSE_TIMEOUT_S = 30.0


def log_error(msg: str) -> None:
  try:
    from openpilot.common.swaglog import cloudlog
    cloudlog.error(msg)
  except Exception:
    pass


def segment_name(now: datetime.datetime) -> str:
  # Qt "MMMM_dd_yyyy-hh-mm-ssAP": 12-hour clock with AM/PM
  return now.strftime("%B_%d_%Y-%I-%M-%S%p") + ".mp4"


def free_bytes(path: str) -> int:
  return shutil.disk_usage(path).free


class FfmpegEncoder:
  """rawvideo RGBA on stdin -> H.264 fragmented MP4. `ffmpeg`/`codec` are injectable for tests."""

  def __init__(self, path: str, width: int, height: int, fps: int, bitrate: int, ffmpeg: str = "ffmpeg",
               codec: str = "libx264"):
    self.path, self.width, self.height, self.fps, self.bitrate = path, width, height, fps, bitrate
    self.ffmpeg, self.codec = ffmpeg, codec
    self.proc: subprocess.Popen | None = None
    self.lock_path = path + ".lock"
    self.error: str | None = None
    self.frames = 0

  def args(self) -> list[str]:
    a = [self.ffmpeg, "-v", "error", "-nostats", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{self.width}x{self.height}",
         "-r", str(self.fps), "-i", "pipe:0", "-vf", "format=yuv420p", "-c:v", self.codec]
    if self.codec == "libx264":
      a += ["-preset", "ultrafast", "-tune", "zerolatency"]
    a += ["-b:v", str(self.bitrate), "-maxrate", str(self.bitrate), "-bufsize", str(self.bitrate), "-g", str(self.fps * 2),
          "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-flush_packets", "1", "-f", "mp4", "-y", self.path]
    return a

  def open(self) -> bool:
    try:
      with open(self.lock_path, "w") as f:
        f.write(str(os.getpid()))
      self.proc = subprocess.Popen(self.args(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
      return True
    except OSError as e:
      self.error = f"encoder start failed: {e}"
      self._discard()
      return False

  def write(self, data: bytes) -> bool:
    if self.proc is None or self.proc.stdin is None:
      return False
    try:
      self.proc.stdin.write(data)
      self.frames += 1
      return True
    except (BrokenPipeError, OSError, ValueError) as e:
      self.error = f"encoder write failed: {e}"
      return False

  def alive(self) -> bool:
    return self.proc is not None and self.proc.poll() is None

  def close(self) -> bool:
    """Finalize. True when a non-empty playable file was saved; otherwise the partial file is removed."""
    ok = False
    if self.proc is not None:
      try:
        if self.proc.stdin is not None:
          self.proc.stdin.close()
      except (BrokenPipeError, OSError, ValueError):
        pass
      try:
        rc = self.proc.wait(timeout=CLOSE_TIMEOUT_S)
      except subprocess.TimeoutExpired:
        self.proc.kill()
        rc = self.proc.wait()
      err = b""
      try:
        err = self.proc.stderr.read() if self.proc.stderr is not None else b""
      except (OSError, ValueError):
        pass
      ok = rc == 0 and self.frames > 0 and os.path.exists(self.path) and os.path.getsize(self.path) > 0
      if rc != 0 and self.error is None:
        self.error = f"encoder exited {rc}: {err.decode(errors='replace')[-300:]}"
      self.proc = None
    if not ok:
      self._discard()
    else:
      self._unlock()
    return ok

  def _unlock(self):
    try:
      os.remove(self.lock_path)
    except FileNotFoundError:
      pass

  def _discard(self):
    for p in (self.path, self.lock_path):
      try:
        os.remove(p)
      except FileNotFoundError:
        pass
      except OSError as e:
        log_error(f"screenrecorder: cleanup failed for {p}: {e}")


def _pid_alive(pid: int) -> bool:
  try:
    os.kill(pid, 0)
    return True
  except ProcessLookupError:
    return False
  except PermissionError:
    return True


def cleanup_stale(directory: str) -> list[str]:
  """Locks left by a crashed recorder: drop the lock; keep the (fragmented, playable) file unless it is empty."""
  removed = []
  d = Path(directory)
  if not d.is_dir():
    return removed
  for lock in d.glob("*.mp4.lock"):
    try:
      pid = int(lock.read_text().strip() or "0")
    except (OSError, ValueError):
      pid = 0
    if pid > 0 and pid != os.getpid() and _pid_alive(pid):
      continue
    if pid == os.getpid():
      continue
    video = Path(str(lock)[:-len(".lock")])
    try:
      if video.exists() and video.stat().st_size == 0:
        video.unlink()
        removed.append(str(video))
      lock.unlink()
      removed.append(str(lock))
    except OSError as e:
      log_error(f"screenrecorder: stale cleanup failed for {lock}: {e}")
  return removed


class RecorderEngine:
  """Thread-safe engine: submit_frame() from the render thread, encoding on a worker thread."""

  def __init__(self, directory: str = RECORDINGS_DIR, fps: int = CAPTURE_HZ, bitrate: int = BITRATE,
               max_segment_s: float = MAX_SEGMENT_S, min_free: int = MIN_FREE_BYTES, encoder_factory=None,
               clock=time.monotonic, wallclock=datetime.datetime.now, free_fn=free_bytes):
    self.directory, self.fps, self.bitrate = directory, fps, bitrate
    self.max_segment_s, self.min_free = max_segment_s, min_free
    self.encoder_factory = encoder_factory or (lambda path, w, h: FfmpegEncoder(path, w, h, fps, bitrate))
    self.clock, self.wallclock, self.free_fn = clock, wallclock, free_fn
    self._lock = threading.Lock()
    self._cv = threading.Condition(self._lock)
    self._queue: deque = deque(maxlen=MAX_QUEUE)
    self._worker: threading.Thread | None = None
    self._recording = False
    self.encoder = None
    self.size: tuple[int, int] | None = None
    self.segment_start = 0.0
    self._last_disk_check = 0.0
    self.saved: list[str] = []
    self.last_error: str | None = None
    self.dropped = 0
    self._t0 = 0.0
    self._submitted = 0

  @property
  def recording(self) -> bool:
    return self._recording

  def _space_ok(self) -> bool:
    try:
      free = self.free_fn(self.directory)
    except OSError as e:
      self.last_error = f"free-space check failed: {e}"
      return False
    if free < self.min_free:
      self.last_error = f"not enough free space to record ({free >> 20} MB free)"
      return False
    return True

  def _open_segment(self, w: int, h: int) -> bool:
    if not self._space_ok():
      log_error("screenrecorder: " + str(self.last_error))
      return False
    path = os.path.join(self.directory, segment_name(self.wallclock()))
    n = 1
    while os.path.exists(path):   # two segments within one second
      path = os.path.join(self.directory, segment_name(self.wallclock())[:-4] + f"_{n}.mp4")
      n += 1
    enc = self.encoder_factory(path, w, h)
    if not enc.open():
      self.last_error = enc.error or "encoder open failed"
      log_error("screenrecorder: " + self.last_error)
      return False
    self.encoder, self.size, self.segment_start = enc, (w, h), self.clock()
    return True

  def _close_segment(self):
    enc, self.encoder = self.encoder, None
    if enc is not None:
      if enc.close():
        self.saved.append(enc.path)
      elif enc.error:
        self.last_error = enc.error

  def start(self) -> bool:
    with self._lock:
      if self._recording:
        return True
    try:
      os.makedirs(self.directory, exist_ok=True)
    except OSError as e:
      self.last_error = f"cannot create {self.directory}: {e}"
      return False
    cleanup_stale(self.directory)
    if not self._space_ok():
      log_error("screenrecorder: " + str(self.last_error))
      return False
    self.last_error = None
    with self._lock:
      self._queue.clear()
      self._recording = True
      self.size = None
      self._t0, self._submitted = self.clock(), 0
      self._last_disk_check = self.clock()
    self._worker = threading.Thread(target=self._loop, name="sr-capture", daemon=True)
    self._worker.start()
    return True

  def stop(self) -> None:
    with self._cv:
      self._recording = False
      self._cv.notify_all()
    if self._worker is not None and self._worker is not threading.current_thread():
      self._worker.join(timeout=CLOSE_TIMEOUT_S + 5)
    self._worker = None

  def frames_due(self) -> int:
    """How many copies of the next captured frame keep the file in real time (0 = not yet time for a frame)."""
    if not self._recording:
      return 0
    due = int((self.clock() - self._t0) * self.fps) + 1 - self._submitted
    return max(0, min(due, MAX_REPEAT))

  def submit_frame(self, data: bytes, width: int, height: int, repeat: int = 1) -> None:
    with self._cv:
      if not self._recording or repeat <= 0:
        return
      if len(self._queue) == self._queue.maxlen:
        self.dropped += 1
      self._queue.append((data, width, height, repeat))
      self._submitted += repeat
      self._cv.notify()

  def _fail(self, msg: str):
    self.last_error = msg
    log_error("screenrecorder: " + msg)
    with self._lock:
      self._recording = False

  def _loop(self):
    try:
      while True:
        with self._cv:
          while self._recording and not self._queue:
            self._cv.wait(0.1)
          if not self._recording and not self._queue:
            break
          item = self._queue.popleft() if self._queue else None
          stopping = not self._recording
        if item is None:
          if stopping:
            break
          continue
        data, w, h, repeat = item
        if len(data) != w * h * 4:
          continue
        now = self.clock()
        if self.encoder is not None and (now - self.segment_start >= self.max_segment_s or self.size != (w, h)):
          self._close_segment()
        if now - self._last_disk_check >= DISK_CHECK_S:
          self._last_disk_check = now
          if not self._space_ok():
            self._fail(str(self.last_error))
            break
        if self.encoder is None and not self._open_segment(w, h):
          self._fail(str(self.last_error))
          break
        for _ in range(repeat):
          if not self.encoder.write(data):
            self._fail(self.encoder.error or "encoder write failed")
            break
        if not self._recording and not stopping:
          break
    finally:
      with self._lock:
        self._queue.clear()
        self._recording = False
      self._close_segment()


class ScreenRecorder:
  """UI glue: the capture hook (render thread) and the toggle. One per process."""

  def __init__(self, engine: RecorderEngine | None = None):
    self.engine = engine or RecorderEngine()
    self._frame = 0
    self.started_at = 0.0

  @property
  def recording(self) -> bool:
    return self.engine.recording

  def toggle(self) -> bool:
    if self.engine.recording:
      self.engine.stop()
      return False
    ok = self.engine.start()
    if ok:
      self.started_at = time.monotonic()
    return ok

  def stop(self) -> None:
    if self.engine.recording:
      self.engine.stop()

  def capture_hook(self) -> None:
    """Call just before rl.end_drawing(): reads back the finished frame when one is due."""
    if not self.engine.recording:
      return
    n = self.engine.frames_due()
    if n <= 0:
      return
    import pyray as rl
    img = rl.load_image_from_screen()
    try:
      w, h = img.width, img.height
      data = bytes(rl.ffi.buffer(img.data, w * h * 4))
    finally:
      rl.unload_image(img)
    self.engine.submit_frame(data, w, h, n)


_recorder: ScreenRecorder | None = None


def recorder() -> ScreenRecorder:
  """Process singleton, registered once as a gui_app frame hook and stopped on every onroad/offroad transition."""
  global _recorder
  if _recorder is None:
    _recorder = ScreenRecorder()
    try:
      from openpilot.system.ui.lib.application import gui_app
      from openpilot.selfdrive.ui.ui_state import ui_state
      gui_app.add_frame_hook(_recorder.capture_hook)
      ui_state.add_offroad_transition_callback(_recorder.stop)
    except Exception:
      log_error("screenrecorder: hook registration failed")
  return _recorder
