"""Screen recorder CPU / IO placement (headless; no window, no screen capture, no device).

The recorder's capture thread and its ffmpeg encoder must never run realtime or on a core used by the driving
processes. Pure tests use fake OS calls; the Linux-only tests apply the real calls to a throwaway child process
(`sleep`) or to a real ffmpeg encode of synthetic frames in a temporary directory."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load

SR = load("screen_recorder")
OP = Path(__file__).resolve().parents[5]
LINUX = sys.platform.startswith("linux")
FFMPEG = shutil.which("ffmpeg")


def source_cores(rel: str) -> set[int]:
  """Cores a driving process pins itself to, read from its source (config_realtime_process / set_core_affinity)."""
  src = (OP / rel).read_text()
  cores = set()
  for m in re.finditer(r"(?:config_realtime_process|set_core_affinity)\(\s*(\[[^\]]*\]|\{[^}]*\}|\d+)", src):
    cores |= {int(x) for x in re.findall(r"\d+", m.group(1))}
  return cores


DRIVING_SOURCES = {
  "card": "selfdrive/car/card.py",
  "controlsd": "selfdrive/controls/controlsd.py",
  "selfdrived": "selfdrive/selfdrived/selfdrived.py",
  "plannerd": "selfdrive/controls/plannerd.py",
  "radard": "selfdrive/controls/radard.py",
  "modeld": "selfdrive/modeld/modeld.py",
  "dmonitoringmodeld": "selfdrive/modeld/dmonitoringmodeld.py",
  "pandad": "selfdrive/pandad/main.cc",
  "encoderd": "system/loggerd/encoderd.cc",
  "camerad": "system/camerad/main.cc",
}


class TestCoreMap(unittest.TestCase):
  def test_recorder_cores_never_overlap_driving_processes(self):
    for name, rel in DRIVING_SOURCES.items():
      cores = source_cores(rel)
      self.assertTrue(cores, f"{name}: no core pin found in {rel}")
      self.assertFalse(cores & set(SR.RECORDER_CORES), f"{name} runs on {sorted(cores)}")
      self.assertTrue(cores <= SR.DRIVING_CORES, f"{name} on {sorted(cores)} missing from DRIVING_CORES")

  def test_ui_core_is_a_driving_core(self):
    src = (OP / "selfdrive/ui/ui.py").read_text()
    m = re.search(r"cores = \{(\d+), \}", src)
    self.assertIsNotNone(m)
    self.assertIn(int(m.group(1)), SR.DRIVING_CORES)
    self.assertFalse({int(m.group(1))} & set(SR.RECORDER_CORES))

  def test_check_cores(self):
    self.assertEqual(SR.check_cores([2, 0, 1, 1]), (0, 1, 2))
    for bad in ([], [3], [0, 4], [5], [6], [7]):
      with self.assertRaises(ValueError):
        SR.check_cores(bad)
    with self.assertRaises(ValueError):
      SR.Placement(cores=(0, 4), enabled=True)


class FakeOS:
  def __init__(self, fail=()):
    self.calls, self.fail = [], set(fail)

  def _rec(self, kind, *a):
    if kind in self.fail:
      raise OSError(1, "not permitted")
    self.calls.append((kind,) + a)

  def placement(self, threads=(100,), **kw):
    self.threads = list(threads)
    return SR.Placement(enabled=True, setaffinity=lambda t, c: self._rec("aff", t, frozenset(c)),
                        setscheduler=lambda t, pol, p: self._rec("sched", t, pol),
                        setpriority=lambda t, n: self._rec("nice", t, n),
                        setioprio=lambda t, c, l: self._rec("io", t, c, l) or True,
                        threads_fn=lambda pid: list(self.threads), gettid=lambda: 42, **kw)

  def of(self, tid):
    return {c[0]: c[2:] for c in self.calls if c[1] == tid}


class TestPlacement(unittest.TestCase):
  def test_worker_thread_leaves_realtime_and_moves_to_little_cores(self):
    f = FakeOS()
    r = f.placement().worker_thread()
    self.assertTrue(all(r.values()), r)
    got = f.of(42)
    self.assertEqual(got["sched"], (SR.SCHED_OTHER,))
    self.assertEqual(got["nice"], (SR.WORKER_NICE,))
    self.assertEqual(got["aff"], (frozenset(SR.RECORDER_CORES),))
    self.assertEqual(got["io"], (SR.IOPRIO_CLASS_BE, SR.IO_LEVEL_LOWEST))
    self.assertEqual(SR.WORKER_NICE, 0)   # not lowered: it takes the GIL, a starved holder would stall the UI

  def test_encoder_every_thread_batch_nice19_little_cores(self):
    f = FakeOS()
    p = f.placement(threads=(200, 201, 202))
    self.assertEqual(p.encoder(200), 3)
    for tid in (200, 201, 202):
      got = f.of(tid)
      self.assertEqual(got["sched"], (SR.SCHED_BATCH,))
      self.assertEqual(got["nice"], (19,))
      self.assertEqual(got["aff"], (frozenset({0, 1, 2}),))
      self.assertEqual(got["io"], (2, 7))
    n = len(f.calls)
    self.assertEqual(p.encoder(200), 3)          # already placed: no new calls
    self.assertEqual(len(f.calls), n)
    f.threads.append(203)                        # a thread libx264 created later
    self.assertEqual(p.encoder(200), 4)
    self.assertEqual(f.of(203)["sched"], (SR.SCHED_BATCH,))
    p.reset()
    self.assertEqual(p.applied, {})

  def test_never_realtime_never_idle(self):
    self.assertNotIn(SR.SCHED_BATCH, (getattr(os, "SCHED_FIFO", 1), getattr(os, "SCHED_RR", 2), getattr(os, "SCHED_IDLE", 5)))
    self.assertEqual(SR.SCHED_BATCH, 3)
    self.assertEqual(SR.SCHED_OTHER, 0)

  def test_disabled_off_device_does_nothing(self):
    f = FakeOS()
    p = f.placement()
    p.enabled = False
    self.assertEqual(p.worker_thread(), {})
    self.assertEqual(p.encoder(200), 0)
    self.assertEqual(f.calls, [])

  def test_failures_are_quiet(self):
    f = FakeOS(fail={"sched", "aff"})
    p = f.placement(threads=(300,))
    r = p.worker_thread()
    self.assertFalse(r["sched"])
    self.assertTrue(r["nice"])
    self.assertEqual(p.encoder(300), 1)          # nice still took effect
    f2 = FakeOS(fail={"sched", "aff", "nice"})
    self.assertEqual(f2.placement(threads=(301,)).encoder(301), 0)


class TestEncoderArgs(unittest.TestCase):
  def test_half_size_threads_and_bitrate(self):
    e = SR.RecorderEngine(tempfile.mkdtemp(prefix="bp_srp_"), free_fn=lambda p: 10 << 30,
                          placement=SR.Placement(enabled=False))
    enc = e.encoder_factory("/tmp/x.mp4", 2160, 1080)
    a = enc.args()
    vf = a[a.index("-vf") + 1]
    self.assertEqual(vf, "format=yuv420p")                  # half size is done before the pipe, no ffmpeg scaler
    self.assertEqual(a[a.index("-s") + 1], "1080x540")
    self.assertEqual(a[a.index("-pix_fmt") + 1], "rgb24")
    self.assertEqual(a[a.index("-threads") + 1], str(SR.ENCODER_THREADS))
    self.assertEqual(a[a.index("-filter_threads") + 1], "1")
    self.assertEqual(enc.bitrate, SR.BITRATE // 4)
    self.assertLessEqual(SR.ENCODER_THREADS, len(SR.RECORDER_CORES))

  def test_full_size_option(self):
    enc = SR.FfmpegEncoder("/tmp/x.mp4", 64, 32, 10, 1_000_000, scale_div=1)
    a = enc.args()
    self.assertEqual(a[a.index("-vf") + 1], "format=yuv420p")


class PidEncoder:
  """Fake encoder with a pid, an optional gate that blocks the first write, and a write counter."""
  def __init__(self, path, gate=None):
    self.path, self.lock_path, self.frames, self.error, self.pid, self.gate = path, path + ".lock", 0, None, 4242, gate
    self.writes_by_frame = []

  def alive(self):
    return True

  def open(self):
    return True

  def write(self, data):
    if self.gate is not None:
      self.gate.wait(5)
    self.frames += 1
    self.writes_by_frame.append(data[:1])
    return True

  def close(self):
    return self.frames > 0


class RecPlacement:
  def __init__(self):
    self.worker_threads, self.encoder_calls, self.resets = [], [], 0

  def worker_thread(self):
    self.worker_threads.append(threading.current_thread().name)
    return {}

  def encoder(self, pid):
    self.encoder_calls.append(pid)
    return 1

  def reset(self):
    self.resets += 1


def wait_until(cond, timeout=5.0):
  t = time.monotonic() + timeout
  while time.monotonic() < t:
    if cond():
      return True
    time.sleep(0.01)
  return cond()


class TestEngineUsesPlacement(unittest.TestCase):
  def setUp(self):
    self.dir = tempfile.mkdtemp(prefix="bp_srp_")

  def tearDown(self):
    shutil.rmtree(self.dir, ignore_errors=True)

  def test_capture_thread_placed_before_spawn_and_encoder_after_open_and_first_frame(self):
    rp, encs = RecPlacement(), []
    e = SR.RecorderEngine(self.dir, free_fn=lambda p: 10 << 30, placement=rp,
                          encoder_factory=lambda p, w, h: encs.append(PidEncoder(p)) or encs[-1])
    e.start()
    e.submit_frame(bytes(16), 2, 2)
    self.assertTrue(wait_until(lambda: encs and encs[0].frames >= 1))
    e.stop()
    self.assertEqual(rp.worker_threads, ["sr-capture"])   # on the capture thread itself, which spawns ffmpeg
    self.assertGreaterEqual(rp.encoder_calls.count(4242), 2)   # after open and after the first frame
    self.assertGreaterEqual(rp.resets, 1)

  def test_no_repeats_while_backlogged(self):
    gate, encs = threading.Event(), []
    e = SR.RecorderEngine(self.dir, free_fn=lambda p: 10 << 30, placement=RecPlacement(),
                          encoder_factory=lambda p, w, h: encs.append(PidEncoder(p, gate)) or encs[-1])
    e.start()
    e.submit_frame(b"A" * 16, 2, 2, 1)
    self.assertTrue(wait_until(lambda: bool(encs)))
    time.sleep(0.1)                                    # worker is blocked inside the first write
    for c in b"BCD":
      e.submit_frame(bytes([c]) * 16, 2, 2, 3)         # slow frames, each owed 3 copies
    self.assertFalse(e.backlogged())                   # 3 queued of 4
    e.submit_frame(b"E" * 16, 2, 2, 3)
    self.assertTrue(e.backlogged())
    gate.set()
    self.assertTrue(wait_until(lambda: not e._queue and encs[0].frames >= 5))
    e.stop()
    w = [x for x in encs[0].writes_by_frame]
    self.assertEqual(w.count(b"B"), 1)                 # backlog behind it: not repeated
    self.assertEqual(w.count(b"C"), 1)
    self.assertEqual(w.count(b"E"), 3)                 # last one, no backlog: real-time repeats kept

  def test_capture_hook_skips_readback_when_backlogged(self):
    class Eng:
      recording = True
      def frames_due(self):
        return 2
      def backlogged(self):
        return True
      def submit_frame(self, *a):
        raise AssertionError("must not read back or submit")
    r = SR.ScreenRecorder(Eng())
    r.capture_hook()                                   # returns before importing pyray / reading the screen


@unittest.skipUnless(LINUX and set(SR.RECORDER_CORES) <= os.sched_getaffinity(0) if LINUX else False,
                     "needs Linux with cores 0-2")
class TestRealLinuxCalls(unittest.TestCase):
  def test_real_calls_on_child_process(self):
    child = subprocess.Popen(["sleep", "30"])
    try:
      p = SR.Placement(enabled=True)
      self.assertEqual(p.encoder(child.pid), 1)
      self.assertEqual(os.sched_getscheduler(child.pid), os.SCHED_BATCH)
      self.assertEqual(os.getpriority(os.PRIO_PROCESS, child.pid), 19)
      self.assertEqual(os.sched_getaffinity(child.pid), set(SR.RECORDER_CORES))
    finally:
      child.kill()
      child.wait()

  def test_real_worker_thread_and_inheritance(self):
    out = {}
    def body():
      SR.Placement(enabled=True).worker_thread()
      out["aff"] = os.sched_getaffinity(0)
      out["sched"] = os.sched_getscheduler(0)
      c = subprocess.Popen(["sleep", "30"])              # what ffmpeg inherits before its own placement
      out["child_aff"], out["child_sched"] = os.sched_getaffinity(c.pid), os.sched_getscheduler(c.pid)
      c.kill()
      c.wait()
    before = os.sched_getaffinity(0)
    t = threading.Thread(target=body)
    t.start()
    t.join(10)
    self.assertEqual(out["aff"], set(SR.RECORDER_CORES))
    self.assertEqual(out["sched"], os.SCHED_OTHER)
    self.assertEqual(out["child_aff"], set(SR.RECORDER_CORES))
    self.assertEqual(out["child_sched"], os.SCHED_OTHER)
    self.assertEqual(os.sched_getaffinity(0), before)   # per thread: the calling (UI) thread is untouched

  @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
  def test_real_ffmpeg_threads_all_placed(self):
    d = tempfile.mkdtemp(prefix="bp_srp_")
    try:
      e = SR.RecorderEngine(d, free_fn=lambda p: 10 << 30, placement=SR.Placement(enabled=True))
      self.assertTrue(e.start())
      w, h = 640, 320
      for _ in range(15):
        e.submit_frame(bytes((10, 200, 30, 255)) * (w * h), w, h)
        time.sleep(0.05)
      self.assertTrue(wait_until(lambda: e.encoder is not None and getattr(e.encoder, "frames", 0) > 3))
      pid = e.encoder.pid
      e._place_encoder()
      tids = SR.process_threads(pid)
      self.assertGreater(len(tids), 1)
      for tid in tids:
        self.assertEqual(os.sched_getscheduler(tid), os.SCHED_BATCH, tid)
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, tid), 19, tid)
        self.assertEqual(os.sched_getaffinity(tid), set(SR.RECORDER_CORES), tid)
      e.stop()
      self.assertIsNone(e.last_error)
      self.assertEqual(len(e.saved), 1)
      out = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", e.saved[0]], capture_output=True, text=True)
      if out.returncode == 0:
        self.assertEqual(out.stdout.strip(), f"{w // 2},{h // 2}")
    finally:
      shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
  unittest.main()
