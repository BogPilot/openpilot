"""FPS counter: tracker, text, gate and hook (headless, no window)."""
import importlib.util
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load

FPS = load("fps_counter")
OVG = load("overlay_gate")
ROOT = Path(__file__).resolve().parents[1]


def run(tracker, seconds, hz, start=100.0):
  t = start
  for _ in range(int(seconds * hz) + 1):
    tracker.frame(t)
    t += 1.0 / hz
  return t


class TestTracker(unittest.TestCase):
  def test_no_number_before_a_full_second(self):
    t = FPS.FpsTracker()
    run(t, 0.5, 20)
    self.assertEqual(t.text(), "FPS: -")

  def test_steady_rate(self):
    t = FPS.FpsTracker()
    run(t, 5, 20)
    self.assertEqual(t.text(), "FPS: 20 | Min: 20 | Max: 20 | Avg: 20")

  def test_min_and_max_follow_the_rate(self):
    t = FPS.FpsTracker()
    end = run(t, 3, 20)
    run(t, 3, 10, start=end)
    self.assertEqual(round(t.max_fps), 20)
    self.assertLessEqual(t.min_fps, 11)
    self.assertLessEqual(round(t.fps), 11)
    self.assertTrue(10 < t.avg_fps < 20)

  def test_average_covers_the_last_minute_only(self):
    t = FPS.FpsTracker()
    end = run(t, 5, 5)           # 5 fps for a while
    end = run(t, 70, 20, start=end)
    self.assertEqual(round(t.avg_fps), 20)   # the slow start fell out of the 60 s window
    self.assertEqual(round(t.min_fps), 5)    # min is for the whole drive

  def test_reset_starts_a_new_drive(self):
    t = FPS.FpsTracker()
    run(t, 3, 20)
    t.reset()
    self.assertEqual(t.text(), "FPS: -")

  def test_clock_going_backwards_starts_over(self):
    t = FPS.FpsTracker()
    run(t, 3, 20, start=500.0)
    t.frame(10.0)
    self.assertEqual(t.text(), "FPS: -")

  def test_history_stays_bounded(self):
    t = FPS.FpsTracker()
    run(t, 130, 20)
    self.assertLess(len(t._history), 20 * 62)
    self.assertLess(len(t._frames), 25)


class FakeStore:
  def __init__(self, raw=None, level_ok=True, default=True, fail=False):
    self._raw, self.level_ok, self.default, self.fail, self.reads = raw, level_ok, default, fail, 0

  def honoured(self, key):
    self.reads += 1
    if self.fail:
      raise OSError("store down")
    return self.level_ok

  def raw(self, key):
    return self._raw

  def get_bool(self, key):
    return self.default if self._raw is None else self._raw == "1"


class TestGate(unittest.TestCase):
  def test_stored_only_unset_is_off_even_when_the_registry_default_is_on(self):
    self.assertFalse(OVG.OverlayGate("FPSCounter", stored_only=True, store=FakeStore(raw=None, default=True)).get())

  def test_stored_on_and_off(self):
    self.assertTrue(OVG.OverlayGate("FPSCounter", stored_only=True, store=FakeStore(raw="1")).get())
    self.assertFalse(OVG.OverlayGate("FPSCounter", stored_only=True, store=FakeStore(raw="0")).get())

  def test_tuning_level_below_the_row_is_off(self):
    self.assertFalse(OVG.OverlayGate("FPSCounter", stored_only=True, store=FakeStore(raw="1", level_ok=False)).get())

  def test_plain_gate_uses_the_stored_or_default_value(self):
    self.assertFalse(OVG.OverlayGate("ShowIP", store=FakeStore(raw=None, default=False)).get())
    self.assertTrue(OVG.OverlayGate("ShowIP", store=FakeStore(raw="1")).get())

  def test_read_failure_is_off_and_reads_are_cached(self):
    self.assertFalse(OVG.OverlayGate("X", store=FakeStore(fail=True)).get())
    now = [0.0]
    store = FakeStore(raw="1")
    gate = OVG.OverlayGate("X", store=store, clock=lambda: now[0])
    for _ in range(5):
      gate.get()
    self.assertEqual(store.reads, 1)
    now[0] = 2.5
    gate.get()
    self.assertEqual(store.reads, 2)

  def test_real_store_reads_the_stored_key(self):
    with tempfile.TemporaryDirectory() as folder:
      os.environ["BOGPILOT_PARAMS_DIR"] = folder
      try:
        from openpilot.common.bogpilot_store import ParamStore
        store = ParamStore(params=SimpleNamespace(all_keys=lambda: [], get=lambda k: None, get_bool=lambda k: None))
        self.assertFalse(OVG.OverlayGate("FPSCounter", stored_only=True, store=store).get())
        (Path(folder) / "FPSCounter").write_text("1\n")
        self.assertTrue(OVG.OverlayGate("FPSCounter", stored_only=True, store=store).get())
      finally:
        os.environ.pop("BOGPILOT_PARAMS_DIR", None)


class TestHookAndSafety(unittest.TestCase):
  def test_display_only_no_writes_anywhere(self):
    for name in ("fps_counter.py", "overlay_gate.py"):
      src = (ROOT / name).read_text()
      for needle in (".put(", "put_bool", "write_text", "open(", "os.remove", "send("):
        self.assertNotIn(needle, src, f"{name}: {needle}")

  def test_hud_renderer_hooks_the_counter_and_isolates_failures(self):
    src = (ROOT / "bogpilot_hud.py").read_text()
    self.assertIn("self._bp_render_fps(rect)", src)
    self.assertIn('OVG.OverlayGate("FPSCounter", stored_only=True)', src)
    body = src[src.index("def _bp_render_fps"):src.index("def _bp_render_extras")]
    self.assertIn("except Exception", body)
    self.assertIn("self._bp_fps.reset()", body)

  def test_has_a_visuals_row_that_shows_the_stored_value(self):
    layout = (ROOT.parents[1] / "layouts/settings/bogpilot_visuals.py").read_text()
    self.assertIn('"FPSCounter"', layout)


@unittest.skipUnless(importlib.util.find_spec("pyray") is not None, "pyray not installed")
class TestPaint(unittest.TestCase):
  def test_text_is_centred_on_the_bottom_edge(self):
    from openpilot.selfdrive.ui.onroad.bogpilot import style
    calls = []
    saved = style.draw_text, style.text_width
    try:
      style.draw_text = lambda text, x, base, size, color, weight=None: calls.append((text, x, base, size))
      style.text_width = lambda text, size, weight=None: 200.0
      FPS.paint("FPS: 20", SimpleNamespace(x=100.0, y=0.0, width=1000.0, height=600.0))
    finally:
      style.draw_text, style.text_width = saved
    self.assertEqual(calls, [("FPS: 20", 500.0, 595.0, 28)])


if __name__ == "__main__":
  unittest.main()
