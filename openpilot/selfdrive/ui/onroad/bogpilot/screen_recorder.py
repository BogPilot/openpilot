"""BogPilot screen recorder: Python/raylib port of daily bogpilot/ui/screenrecorder (bogpilot-tesla 04d560f3e).

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

CPU placement (next build): the UI process runs SCHED_FIFO 53 on core 5 (selfdrive/ui/ui.py), and threads and child
processes inherit both. Before this change the capture thread and the ffmpeg/libx264 encoder therefore ran as realtime
FIFO 53 on the UI core: a busy encoder starved the UI (same priority, FIFO never time-slices) and every slow UI frame was
repeated up to 5 times, so the encoder got even busier. Now:
- the capture thread leaves FIFO (SCHED_OTHER, nice 0, so it never holds the GIL against the UI while starved) and moves
  to the little cores RECORDER_CORES (0-2); ffmpeg is spawned from it, so it never starts as realtime or on a driving core;
- ffmpeg, every thread of it, is then SCHED_BATCH nice 19 on RECORDER_CORES with best-effort IO level 7 (not SCHED_IDLE /
  the idle IO class: a starved writer can hold an ext4 journal handle that loggerd waits on), re-applied after the first
  frame and every DISK_CHECK_S for threads ffmpeg creates late;
- RECORDER_CORES never include core 3 (pandad FIFO 54, encoderd FIFO 52, the panda SPI kthread), 4 (card, controlsd,
  selfdrived FIFO 53), 5 (UI), 6 (camerad, isolated) or 7 (modeld, plannerd, radard, dmonitoringmodeld, isolated);
- frames are encoded at half size (SCALE_DIV, 1080x540 from the 2160x1080 C3X screen) at a quarter of the bitrate, with
  libx264 limited to ENCODER_THREADS threads, and slow frames are not repeated while the encoder has a backlog, and the
  screen is not read back while the queue is full (the frame would be dropped anyway).

Resource use (next build): the UI thread no longer copies the 9.3 MB readback into Python bytes; the readback is handed to
the capture thread, which keeps every other pixel of every other row as rgb24 in one reused buffer (1.7 MB) and frees the
readback. The pipe carries 1.7 MB per frame instead of 9.3 MB and ffmpeg has no scaler to run.
"""
from __future__ import annotations

import atexit
from collections import deque
import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
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

# --- CPU / IO placement ---------------------------------------------------------------------------------------------
RECORDER_CORES = (0, 1, 2)                     # little cores; loggerd / locationd family share them, all non-control
DRIVING_CORES = frozenset({3, 4, 5, 6, 7})     # 3 pandad+encoderd+spi, 4 card/controlsd/selfdrived, 5 UI, 6 camerad, 7 modeld/planner
ENCODER_NICE = 19
WORKER_NICE = 0
ENCODER_THREADS = 3
ENCODER_CRF = 23           # libx264's own default quality; BITRATE / SCALE_DIV**2 stays the cap
SCALE_DIV = 2
SCHED_OTHER = getattr(os, "SCHED_OTHER", 0)
SCHED_BATCH = getattr(os, "SCHED_BATCH", 3)
IOPRIO_CLASS_BE = 2
IO_LEVEL_LOWEST = 7
_IOPRIO_WHO_PROCESS = 1
_SYS_IOPRIO_SET = {"aarch64": 30, "arm64": 30, "x86_64": 251}


def ioprio_value(cls: int, level: int) -> int:
  return (cls << 13) | level


def set_ioprio(tid: int, cls: int = IOPRIO_CLASS_BE, level: int = IO_LEVEL_LOWEST) -> bool:
  import platform
  nr = _SYS_IOPRIO_SET.get(platform.machine())
  if nr is None or not sys.platform.startswith("linux"):
    return False
  try:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    return libc.syscall(nr, _IOPRIO_WHO_PROCESS, int(tid), ioprio_value(cls, level)) == 0
  except Exception:
    return False


def process_threads(pid: int) -> list[int]:
  try:
    return sorted(int(t) for t in os.listdir(f"/proc/{int(pid)}/task"))
  except (OSError, ValueError):
    return [int(pid)]


def check_cores(cores) -> tuple[int, ...]:
  c = tuple(sorted(set(int(x) for x in cores)))
  if not c:
    raise ValueError("recorder core set is empty")
  bad = set(c) & DRIVING_CORES
  if bad:
    raise ValueError(f"recorder cores {sorted(bad)} overlap the driving cores")
  return c


class Placement:
  """Moves the capture thread and the encoder off the realtime class and off the driving cores. Every call is best
  effort (fails quietly, returns what took effect): recording must never fail because a priority call did. The OS calls
  are injectable for tests; `enabled` defaults to on only on the device (AGNOS)."""

  def __init__(self, cores=RECORDER_CORES, encoder_nice: int = ENCODER_NICE, enabled: bool | None = None,
               setaffinity=None, setscheduler=None, setpriority=None, setioprio=None, threads_fn=process_threads,
               gettid=None):
    self.cores = check_cores(cores)
    self.encoder_nice = encoder_nice
    self.enabled = os.path.isfile("/AGNOS") if enabled is None else enabled
    self.setaffinity = setaffinity or getattr(os, "sched_setaffinity", None)
    self.setscheduler = setscheduler or getattr(os, "sched_setscheduler", None)
    self.setpriority = setpriority or (lambda tid, n: os.setpriority(os.PRIO_PROCESS, tid, n))
    self.setioprio = setioprio or set_ioprio
    self.threads_fn = threads_fn
    self.gettid = gettid or threading.get_native_id
    self.applied: dict[int, tuple] = {}

  @staticmethod
  def _try(fn, *a) -> bool:
    if fn is None:
      return False
    try:
      fn(*a)
      return True
    except (OSError, ValueError, TypeError, AttributeError):
      return False

  def _param(self):
    sp = getattr(os, "sched_param", None)
    return sp(0) if sp is not None else 0

  def worker_thread(self) -> dict:
    """Call on the capture thread itself, before it spawns ffmpeg (ffmpeg inherits all of this)."""
    if not self.enabled:
      return {}
    tid = self.gettid()
    r = {"sched": self._try(self.setscheduler, tid, SCHED_OTHER, self._param()),
         "nice": self._try(self.setpriority, tid, WORKER_NICE),
         "affinity": self._try(self.setaffinity, tid, set(self.cores)),
         "io": bool(self.setioprio(tid, IOPRIO_CLASS_BE, IO_LEVEL_LOWEST))}
    return r

  def encoder(self, pid: int) -> int:
    """SCHED_BATCH, nice ENCODER_NICE, RECORDER_CORES, IO best-effort 7 on every thread of `pid`. Threads already
    handled are skipped, so it is cheap to call again. Returns how many threads are placed in total."""
    if not self.enabled or not pid:
      return 0
    for tid in self.threads_fn(pid):
      if tid in self.applied:
        continue
      res = (self._try(self.setscheduler, tid, SCHED_BATCH, self._param()),
             self._try(self.setpriority, tid, self.encoder_nice),
             self._try(self.setaffinity, tid, set(self.cores)),
             bool(self.setioprio(tid, IOPRIO_CLASS_BE, IO_LEVEL_LOWEST)))
      if res[0] or res[1] or res[2]:
        self.applied[tid] = res
    return len(self.applied)

  def reset(self) -> None:
    self.applied = {}


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
               codec: str = "libx264", scale_div: int = 1, threads: int = ENCODER_THREADS):
    self.path, self.width, self.height, self.fps, self.bitrate = path, width, height, fps, bitrate
    self.ffmpeg, self.codec, self.scale_div, self.threads = ffmpeg, codec, max(1, int(scale_div)), threads
    # Half size (scale_div > 1): the frame is shrunk here into one reused rgb24 buffer, every scale_div-th pixel of every
    # scale_div-th row, both sides even for yuv420p, so the pipe and ffmpeg see a quarter of the pixels without alpha
    # (1080x540x3 = 1.7 MB per frame instead of 2160x1080x4 = 9.3 MB) and ffmpeg has no scaler to run.
    sd = self.scale_div
    self.in_width, self.in_height = ((width // sd) // 2 * 2, (height // sd) // 2 * 2) if sd > 1 else (width, height)
    self._buf = None
    self._shrunk_from = None   # the frame _buf holds (a repeated frame is not shrunk again)
    self.proc: subprocess.Popen | None = None
    self.lock_path = path + ".lock"
    self.error: str | None = None
    self.frames = 0

  def args(self) -> list[str]:
    pix = "rgb24" if self.scale_div > 1 else "rgba"
    a = [self.ffmpeg, "-v", "error", "-nostats", "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{self.in_width}x{self.in_height}",
         "-r", str(self.fps), "-i", "pipe:0", "-filter_threads", "1", "-vf", self.video_filter(), "-c:v", self.codec]
    if self.codec == "libx264":
      a += ["-preset", "ultrafast", "-tune", "zerolatency", "-threads", str(self.threads)]
    # libx264: constant quality (CRF) capped at the old constant bitrate, so a frame never gets fewer bits than before
    # it needs, and easy frames (a still screen, the HUD) stop padding the file up to the cap
    rate = ["-crf", str(ENCODER_CRF)] if self.codec == "libx264" else ["-b:v", str(self.bitrate)]
    a += rate + ["-maxrate", str(self.bitrate), "-bufsize", str(self.bitrate), "-g", str(self.fps * 2),
          "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-flush_packets", "1", "-f", "mp4", "-y", self.path]
    return a

  def video_filter(self) -> str:
    return "format=yuv420p"   # half size is done before the pipe (shrink), not by an ffmpeg scaler

  def shrink(self, data):
    """The bytes to pipe for one full-size RGBA frame: itself at full size, else the reused half-size rgb24 buffer."""
    sd = self.scale_div
    if sd <= 1:
      return data
    if self._buf is not None and data is self._shrunk_from:
      return memoryview(self._buf).cast("B")
    import numpy as np
    src = np.frombuffer(data, dtype=np.uint8)
    if src.size != self.width * self.height * 4:
      raise ValueError(f"frame is {src.size} bytes, expected {self.width}x{self.height} RGBA")
    if self._buf is None:
      self._buf = np.empty((self.in_height, self.in_width, 3), dtype=np.uint8)
    self._shrunk_from = data
    np.copyto(self._buf, src.reshape(self.height, self.width, 4)[:self.in_height * sd:sd, :self.in_width * sd:sd, :3])
    return memoryview(self._buf).cast("B")

  @property
  def pid(self) -> int | None:
    return self.proc.pid if self.proc is not None else None

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
      self.proc.stdin.write(self.shrink(data))
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


def _release(item) -> None:
  rel = item[4] if len(item) > 4 else None
  if rel is not None:
    try:
      rel()
    except Exception as e:   # never stops a recording
      log_error(f"screenrecorder: frame release failed: {e}")


class RecorderEngine:
  """Thread-safe engine: submit_frame() from the render thread, encoding on a worker thread."""

  def __init__(self, directory: str = RECORDINGS_DIR, fps: int = CAPTURE_HZ, bitrate: int = BITRATE,
               max_segment_s: float = MAX_SEGMENT_S, min_free: int = MIN_FREE_BYTES, encoder_factory=None,
               clock=time.monotonic, wallclock=datetime.datetime.now, free_fn=free_bytes, placement: Placement | None = None,
               scale_div: int = SCALE_DIV):
    self.directory, self.fps, self.bitrate = directory, fps, bitrate
    self.max_segment_s, self.min_free = max_segment_s, min_free
    enc_bitrate = max(1, bitrate // (max(1, scale_div) ** 2))
    self.encoder_factory = encoder_factory or (lambda path, w, h: FfmpegEncoder(path, w, h, fps, enc_bitrate,
                                                                                scale_div=scale_div))
    self.placement = placement if placement is not None else Placement()
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
    self._atexit_registered = False

  @property
  def recording(self) -> bool:
    """Recording REQUESTED (armed or running). Use `active` / `status` for what the indicator shows."""
    return self._recording

  @property
  def active(self) -> bool:
    """Truth for the indicator: requested, an encoder is open and alive, and it has accepted at least one frame."""
    enc = self.encoder
    if not self._recording or enc is None:
      return False
    alive = getattr(enc, "alive", None)
    return bool((alive() if callable(alive) else True) and getattr(enc, "frames", 0) > 0 and not getattr(enc, "error", None))

  @property
  def status(self) -> str:
    """"recording" (active), "starting" (armed, no frame encoded yet), "error" (stopped by a failure; last_error set,
    cleared by the next start) or "idle"."""
    if self.active:
      return "recording"
    if self._recording:
      return "starting"
    return "error" if self.last_error else "idle"

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
    self._place_encoder()
    return True

  def _place_encoder(self) -> None:
    enc = self.encoder
    pid = getattr(enc, "pid", None) if enc is not None else None
    if pid:
      try:
        self.placement.encoder(pid)
      except Exception as e:   # best effort, never stops a recording
        log_error(f"screenrecorder: encoder placement failed: {e}")

  def _close_segment(self):
    enc, self.encoder = self.encoder, None
    self.placement.reset()
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
    if not self._atexit_registered:
      # normal interpreter shutdown (UI exit) finalizes the open segment, bounded by CLOSE_TIMEOUT_S
      atexit.register(self.stop)
      self._atexit_registered = True
    with self._lock:
      stale = list(self._queue)
      self._queue.clear()
      self._recording = True
      self.size = None
      self._t0, self._submitted = self.clock(), 0
      self._last_disk_check = self.clock()
    for item in stale:
      _release(item)
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

  def backlogged(self) -> bool:
    """The queue is full: a new frame would only push out the oldest one, so the UI can skip the readback."""
    with self._lock:
      return len(self._queue) >= MAX_QUEUE

  def submit_frame(self, data, width: int, height: int, repeat: int = 1, release=None) -> None:
    """Queue one RGBA frame. `data` is any buffer; with `release`, it is borrowed (the UI's screen readback, not
    copied) and release() is called exactly once when the worker is done with it or it is dropped."""
    dropped = None
    with self._cv:
      if not self._recording or repeat <= 0:
        dropped = (None, 0, 0, 0, release)
      else:
        if len(self._queue) == self._queue.maxlen:
          self.dropped += 1
          dropped = self._queue.popleft()
        self._queue.append((data, width, height, repeat, release))
        self._submitted += repeat
        self._cv.notify()
    if dropped is not None:
      _release(dropped)

  def _fail(self, msg: str):
    self.last_error = msg
    log_error("screenrecorder: " + msg)
    with self._lock:
      self._recording = False

  def _loop(self):
    try:
      self.placement.worker_thread()
    except Exception as e:   # best effort
      log_error(f"screenrecorder: capture thread placement failed: {e}")
    try:
      while True:
        with self._cv:
          while self._recording and not self._queue:
            self._cv.wait(0.1)
            enc = self.encoder
            if self._recording and not self._queue and enc is not None and callable(getattr(enc, "alive", None)) and not enc.alive():
              break   # encoder died while idle: handled below
          enc = self.encoder
          if self._recording and not self._queue and enc is not None and callable(getattr(enc, "alive", None)) and not enc.alive():
            self._recording = False
            dead = True
          else:
            dead = False
        if dead:
          self.last_error = getattr(enc, "error", None) or "encoder process exited"
          log_error("screenrecorder: " + self.last_error)
          break
        with self._cv:
          if not self._recording and not self._queue:
            break
          item = self._queue.popleft() if self._queue else None
          stopping = not self._recording
          backlog = len(self._queue)
        if item is None:
          if stopping:
            break
          continue
        data, w, h, repeat, _rel = item
        try:
          if backlog:
            repeat = 1   # encoder is behind: do not multiply its work by repeating frames
          if len(data) != w * h * 4:
            continue
          now = self.clock()
          if self.encoder is not None and (now - self.segment_start >= self.max_segment_s or self.size != (w, h)):
            self._close_segment()
          if now - self._last_disk_check >= DISK_CHECK_S:
            self._last_disk_check = now
            self._place_encoder()   # threads ffmpeg created after the first placement
            if not self._space_ok():
              self._fail(str(self.last_error))
              break
          if self.encoder is None and not self._open_segment(w, h):
            self._fail(str(self.last_error))
            break
          first = getattr(self.encoder, "frames", 1) == 0
          for _ in range(repeat):
            if not self.encoder.write(data):
              self._fail(self.encoder.error or "encoder write failed")
              break
          if first and self.encoder is not None:
            self._place_encoder()   # libx264 creates its threads once the first frame arrives
          if not self._recording and not stopping:
            break
        finally:
          _release(item)
    finally:
      with self._lock:
        left = list(self._queue)
        self._queue.clear()
        self._recording = False
      for it in left:
        _release(it)
      self._close_segment()


class ScreenRecorder:
  """UI glue: the capture hook (render thread) and the toggle. One per process."""

  def __init__(self, engine: RecorderEngine | None = None):
    self.engine = engine or RecorderEngine()
    self._frame = 0
    self.started_at = 0.0

  @property
  def recording(self) -> bool:
    """Indicator truth (engine.active): False while only armed, and False once the encoder is dead."""
    return self.engine.active

  @property
  def status(self) -> str:
    return self.engine.status

  @property
  def last_error(self) -> str | None:
    return self.engine.last_error

  def toggle(self) -> bool:
    """Start when idle/error, stop when armed or running. Returns whether recording is requested afterwards."""
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
    if n <= 0 or self.engine.backlogged():
      return
    import pyray as rl
    img = rl.load_image_from_screen()
    try:
      w, h = img.width, img.height
      data = rl.ffi.buffer(img.data, w * h * 4)
    except Exception:
      rl.unload_image(img)
      raise
    # no copy here on the UI thread: the worker shrinks straight from the readback and frees it (UnloadImage is a free())
    self.engine.submit_frame(data, w, h, n, release=lambda: rl.unload_image(img))


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
