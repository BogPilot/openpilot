"""Screen recorder resource use (headless; no window, no screen capture, no device).

The UI thread hands its screen readback to the capture thread without copying it; the capture thread shrinks it into one
reused half-size rgb24 buffer and frees the readback exactly once, whether the frame was encoded, dropped or never queued."""
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest

import numpy as np

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load

SR = load("screen_recorder")
FFMPEG = shutil.which("ffmpeg")


def rgba(w, h):
  """Every pixel unique: R = x, G = y, B = x ^ y, A = 255."""
  y, x = np.mgrid[0:h, 0:w]
  return np.stack([x & 255, y & 255, (x ^ y) & 255, np.full_like(x, 255)], axis=-1).astype(np.uint8)


class Rel:
  def __init__(self):
    self.n = 0
    self.lock = threading.Lock()

  def __call__(self):
    with self.lock:
      self.n += 1


def wait_until(cond, timeout=5.0):
  t = time.monotonic() + timeout
  while time.monotonic() < t:
    if cond():
      return True
    time.sleep(0.01)
  return cond()


class TestShrink(unittest.TestCase):
  def test_every_other_pixel_rgb24_even_sides(self):
    for w, h in ((2160, 1080), (64, 32), (14, 10), (15, 11)):
      enc = SR.FfmpegEncoder("/tmp/x.mp4", w, h, 10, 1_000_000, scale_div=2)
      self.assertEqual((enc.in_width % 2, enc.in_height % 2), (0, 0))
      self.assertEqual((enc.in_width, enc.in_height), ((w // 2) // 2 * 2, (h // 2) // 2 * 2))
      img = rgba(w, h)
      out = np.frombuffer(bytes(enc.shrink(memoryview(img).cast("B"))), np.uint8).reshape(enc.in_height, enc.in_width, 3)
      self.assertTrue(np.array_equal(out, img[:enc.in_height * 2:2, :enc.in_width * 2:2, :3]))

  def test_buffer_reused_and_repeat_not_shrunk_again(self):
    enc = SR.FfmpegEncoder("/tmp/x.mp4", 64, 32, 10, 1_000_000, scale_div=2)
    a, b = rgba(64, 32).tobytes(), bytes(64 * 32 * 4)
    ma = enc.shrink(a)
    buf = enc._buf
    self.assertIs(enc.shrink(a).obj, buf)
    mb = enc.shrink(b)
    self.assertIs(enc._buf, buf)                 # one buffer for the whole segment
    self.assertEqual(bytes(mb), bytes(len(mb)))
    self.assertEqual(len(ma), 32 * 16 * 3)

  def test_wrong_size_rejected(self):
    enc = SR.FfmpegEncoder("/tmp/x.mp4", 64, 32, 10, 1_000_000, scale_div=2)
    with self.assertRaises(ValueError):
      enc.shrink(bytes(10))

  def test_full_size_passes_the_frame_through(self):
    enc = SR.FfmpegEncoder("/tmp/x.mp4", 64, 32, 10, 1_000_000, scale_div=1)
    d = bytes(64 * 32 * 4)
    self.assertIs(enc.shrink(d), d)
    a = enc.args()
    self.assertEqual((a[a.index("-pix_fmt") + 1], a[a.index("-s") + 1]), ("rgba", "64x32"))


class TestRate(unittest.TestCase):
  def test_libx264_constant_quality_under_the_old_cap(self):
    e = SR.RecorderEngine(tempfile.mkdtemp(prefix="bp_srperf_"), free_fn=lambda p: 10 << 30, placement=SR.Placement(enabled=False))
    a = e.encoder_factory("/tmp/x.mp4", 2160, 1080).args()
    self.assertEqual(a[a.index("-crf") + 1], str(SR.ENCODER_CRF))
    self.assertNotIn("-b:v", a)
    cap = str(SR.BITRATE // SR.SCALE_DIV ** 2)
    self.assertEqual((a[a.index("-maxrate") + 1], a[a.index("-bufsize") + 1]), (cap, cap))

  def test_other_codec_keeps_a_bitrate(self):
    a = SR.FfmpegEncoder("/tmp/x.mp4", 64, 32, 10, 1_000_000, codec="h264_v4l2m2m").args()
    self.assertEqual(a[a.index("-b:v") + 1], "1000000")
    self.assertNotIn("-crf", a)


class FakeEnc:
  def __init__(self, path, gate=None):
    self.path, self.lock_path, self.frames, self.error, self.pid, self.gate = path, path + ".lock", 0, None, None, gate

  def alive(self):
    return True

  def open(self):
    return True

  def write(self, data):
    if self.gate is not None:
      self.gate.wait(5)
    self.frames += 1
    return True

  def close(self):
    return self.frames > 0


class TestRelease(unittest.TestCase):
  def setUp(self):
    self.dir = tempfile.mkdtemp(prefix="bp_srperf_")

  def tearDown(self):
    shutil.rmtree(self.dir, ignore_errors=True)

  def engine(self, gate=None):
    encs = []
    e = SR.RecorderEngine(self.dir, free_fn=lambda p: 10 << 30, placement=SR.Placement(enabled=False),
                          encoder_factory=lambda p, w, h: encs.append(FakeEnc(p, gate)) or encs[-1])
    return e, encs

  def test_encoded_frames_released_once(self):
    e, encs = self.engine()
    e.start()
    rels = [Rel() for _ in range(5)]
    for r in rels:
      e.submit_frame(bytes(16), 2, 2, 2, release=r)
      time.sleep(0.02)
    self.assertTrue(wait_until(lambda: sum(r.n for r in rels) == 5))
    e.stop()
    self.assertEqual([r.n for r in rels], [1] * 5)

  def test_not_recording_released_at_once(self):
    e, _ = self.engine()
    r = Rel()
    e.submit_frame(bytes(16), 2, 2, 1, release=r)
    self.assertEqual(r.n, 1)
    e.start()
    r2 = Rel()
    e.submit_frame(bytes(16), 2, 2, 0, release=r2)   # nothing owed
    self.assertEqual(r2.n, 1)
    e.stop()

  def test_dropped_and_stopped_frames_released_once(self):
    gate = threading.Event()
    e, encs = self.engine(gate)
    e.start()
    rels = [Rel() for _ in range(SR.MAX_QUEUE + 4)]
    e.submit_frame(bytes(16), 2, 2, 1, release=rels[0])
    self.assertTrue(wait_until(lambda: bool(encs)))
    time.sleep(0.1)                                     # worker blocked in the first write
    for r in rels[1:]:
      e.submit_frame(bytes(16), 2, 2, 1, release=r)
    self.assertEqual(e.dropped, 3)
    self.assertEqual([r.n for r in rels[1:4]], [1, 1, 1])   # oldest pushed out, freed at once
    gate.set()
    e.stop()
    self.assertEqual([r.n for r in rels], [1] * len(rels))

  def test_bad_size_frame_released(self):
    e, _ = self.engine()
    e.start()
    r = Rel()
    e.submit_frame(bytes(7), 2, 2, 1, release=r)
    self.assertTrue(wait_until(lambda: r.n == 1))
    e.stop()

  def test_release_error_does_not_stop_recording(self):
    e, encs = self.engine()
    e.start()
    def boom():
      raise RuntimeError("x")
    e.submit_frame(bytes(16), 2, 2, 1, release=boom)
    e.submit_frame(bytes(16), 2, 2, 1)
    self.assertTrue(wait_until(lambda: bool(encs) and encs[0].frames >= 2))
    self.assertTrue(e.recording)
    e.stop()


class TestCaptureHookNoCopy(unittest.TestCase):
  def test_readback_handed_over_and_unloaded_by_the_worker(self):
    unloaded, sub = [], []
    img = types.SimpleNamespace(width=4, height=2, data=object())
    buf = memoryview(bytes(4 * 2 * 4))
    fake = types.SimpleNamespace(load_image_from_screen=lambda: img, unload_image=lambda i: unloaded.append(i),
                                 ffi=types.SimpleNamespace(buffer=lambda p, n: buf))

    class Eng:
      recording = True
      def frames_due(self):
        return 1
      def backlogged(self):
        return False
      def submit_frame(self, data, w, h, n, release=None):
        sub.append((data, w, h, n, release))
    old = sys.modules.get("pyray")
    sys.modules["pyray"] = fake
    try:
      SR.ScreenRecorder(Eng()).capture_hook()
    finally:
      if old is None:
        sys.modules.pop("pyray", None)
      else:
        sys.modules["pyray"] = old
    self.assertEqual(len(sub), 1)
    data, w, h, n, release = sub[0]
    self.assertIs(data, buf)                             # the readback itself, not a bytes copy
    self.assertEqual((w, h, n), (4, 2, 1))
    self.assertEqual(unloaded, [])                       # still owned by the worker
    release()
    self.assertEqual(unloaded, [img])


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class TestRealEncode(unittest.TestCase):
  def test_half_size_real_h264_colours(self):
    d = tempfile.mkdtemp(prefix="bp_srperf_")
    try:
      w, h = 320, 160
      enc = SR.FfmpegEncoder(os.path.join(d, "a.mp4"), w, h, 10, 1_000_000, ffmpeg=FFMPEG, scale_div=2)
      self.assertTrue(enc.open())
      img = np.zeros((h, w, 4), np.uint8)
      img[: h // 2] = (255, 0, 0, 255)
      img[h // 2:] = (0, 0, 255, 255)
      for _ in range(12):
        self.assertTrue(enc.write(memoryview(img).cast("B")))
      self.assertTrue(enc.close())
      import subprocess
      raw = subprocess.run([FFMPEG, "-v", "error", "-i", enc.path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, check=True).stdout
      ow = w // 2
      self.assertEqual(len(raw), ow * (h // 2) * 3)
      px = lambda x, y: raw[(y * ow + x) * 3:(y * ow + x) * 3 + 3]  # noqa: E731
      self.assertGreater(px(80, 10)[0], 200)
      self.assertGreater(px(80, 70)[2], 200)
    finally:
      shutil.rmtree(d, ignore_errors=True)
