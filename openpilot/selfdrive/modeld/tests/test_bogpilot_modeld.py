"""bogpilot_modeld launcher: stock equivalence, validated alternate loading, every fallback path, no mid-drive switching."""
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

from openpilot.common.bogpilot_models import alert, resolve, selection
from openpilot.common.tests import bogpilot_model_fixtures as fx
from openpilot.selfdrive.modeld import bogpilot_modeld as launcher

MODELD_SRC = Path(__file__).resolve().parents[1] / "modeld.py"
STOCK_DIR = Path("/stock/models")
OFF = lambda: True  # noqa: E731


class FakeModeld(types.SimpleNamespace):
  """The slice of openpilot.selfdrive.modeld.modeld the launcher touches, with switchable failures."""

  def __init__(self, chestnut=False, **behave):
    super().__init__()
    m = self
    m.MODELS_DIR = STOCK_DIR
    m.behave = dict(behave)  # fail_load, fail_warmup, fail_run, nan_run, applies to the ALTERNATE only
    m.constructed = []
    m.main_calls = 0
    m.chestnut_compiled = lambda: chestnut
    m.chestnut_present = lambda: chestnut
    m.cable_connected = lambda: chestnut
    m.modeld_pkl_path = lambda c: STOCK_DIR / ("big_" if c else "") / "driving_tinygrad.pkl"

    class ModelState:
      def __init__(self, cam_w, cam_h, chestnut):
        self.pkl = m.modeld_pkl_path(chestnut)
        self.warp = m.MODELS_DIR / f"driving_warp_{cam_w}x{cam_h}_tinygrad.pkl"
        self.is_stock = self.pkl == STOCK_DIR / "driving_tinygrad.pkl"
        self.chestnut = chestnut
        if not self.is_stock and m.behave.get("fail_load"):
          raise RuntimeError("compile failed")
        m.constructed.append(self)

      def warmup(self):
        if not self.is_stock and m.behave.get("fail_warmup"):
          raise RuntimeError("warmup kernel fault")
        self.run({}, {}, {})

      def run(self, bufs, transforms, inputs, after_enqueue=None):
        if not self.is_stock and m.behave.get("fail_run"):
          raise RuntimeError("kernel fault")
        v = np.full(4, np.nan if (not self.is_stock and m.behave.get("nan_run")) else 1.0, dtype=np.float32)
        return {"plan": v}

    m.ModelState = ModelState
    m.OriginalModelState = ModelState

    def main(demo=False):
      m.main_calls += 1
      m.live = m.ModelState(1928, 1208, False)  # what modeld.main() does for the small model
      return m.live.run({}, {}, {})
    m.main = main


class Base(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.store = fx.MemStore()
    import os
    self._old = os.environ.get("BOGPILOT_MODELS_DIR")
    os.environ["BOGPILOT_MODELS_DIR"] = str(self.root)
    self.addCleanup(lambda: os.environ.pop("BOGPILOT_MODELS_DIR") if self._old is None else os.environ.__setitem__("BOGPILOT_MODELS_DIR", self._old))
    self.addCleanup(self.tmp.cleanup)

  def install_and_select(self, mid="m", **kw):
    d = fx.install_model(self.root, mid, **kw)
    self.assertTrue(selection.select(mid, OFF, self.store, self.root).ok)
    return d

  def run_launcher(self, m):
    return launcher.run(m, self.store)


class TestStockEquivalence(Base):
  def test_default_selected_leaves_modeld_completely_unpatched(self):
    m = FakeModeld()
    original = (m.ModelState, m.modeld_pkl_path, m.MODELS_DIR)
    self.run_launcher(m)
    self.assertEqual((m.ModelState, m.modeld_pkl_path, m.MODELS_DIR), original)
    self.assertEqual(m.main_calls, 1)
    self.assertEqual((m.live.pkl, m.live.warp), (STOCK_DIR / "driving_tinygrad.pkl", STOCK_DIR / "driving_warp_1928x1208_tinygrad.pkl"))
    self.assertEqual(self.store.writes, [])  # no file IO of any kind for a stock start

  def test_stock_start_after_alternate_only_updates_the_active_note(self):
    self.install_and_select()
    self.run_launcher(FakeModeld())
    self.assertEqual(selection.read_state(self.store)["active"]["id"], "m")
    selection.select("default", OFF, self.store, self.root)
    m = FakeModeld()
    self.run_launcher(m)
    self.assertIs(m.ModelState, m.OriginalModelState)
    self.assertEqual(selection.read_state(self.store)["active"]["id"], "default")

  def test_selector_crash_still_runs_stock_modeld(self):
    class Broken(fx.MemStore):
      def raw(self, key):
        raise OSError("boom")
    m = FakeModeld()
    launcher.run(m, Broken())
    self.assertEqual(m.main_calls, 1)
    self.assertTrue(m.live.is_stock)

  def test_install_failure_still_runs_stock_modeld(self):
    self.install_and_select()
    m = FakeModeld()
    m.ModelState = None  # subclassing None raises inside install(); modeld must still start
    m.main = lambda demo=False: setattr(m, "main_calls", m.main_calls + 1)
    launcher.run(m, self.store)
    self.assertEqual(m.main_calls, 1)


class TestAlternate(Base):
  def test_validated_alternate_is_loaded_with_its_own_model_and_warp_and_stock_warp_otherwise(self):
    warp = fx.warp_pickle_bytes("driving_warp_1928x1208")
    d = self.install_and_select(warps={"driving_warp_1928x1208": warp})
    m = FakeModeld()
    self.run_launcher(m)
    live = m.live
    self.assertFalse(live.is_stock)
    self.assertEqual(live.pkl, d / "driving.pkl")
    self.assertEqual(live.warp, d / "driving_warp_1928x1208.pkl")
    small = m.ModelState(1344, 760, False)  # a camera size the model has no warp for -> stock warp
    self.assertEqual(small.warp, STOCK_DIR / "driving_warp_1344x760_tinygrad.pkl")
    self.assertEqual(selection.read_state(self.store)["active"]["id"], "m")
    self.assertIsNone(alert.current_alert(self.store))

  def test_modeld_globals_restored_after_load(self):
    self.install_and_select()
    m = FakeModeld()
    stock_fn = m.modeld_pkl_path
    self.run_launcher(m)
    self.assertIs(m.modeld_pkl_path, stock_fn)
    self.assertEqual(m.MODELS_DIR, STOCK_DIR)

  def test_selection_changed_after_start_does_not_affect_running_modeld(self):
    self.install_and_select("a")
    fx.install_model(self.root, "b")
    m = FakeModeld()
    self.run_launcher(m)
    first = m.live
    self.assertFalse(selection.select("b", lambda: False, self.store, self.root).ok)  # onroad: refused
    selection.select("b", OFF, self.store, self.root)  # (offroad write from another process; modeld never re-reads)
    self.assertIs(m.live, first)
    self.assertEqual(first.pkl.parent.name, "a")


class TestFallbacks(Base):
  def assert_stock_with_alert(self, m, contains):
    self.assertTrue(m.live.is_stock if hasattr(m, "live") else True)
    a = alert.current_alert(self.store)
    self.assertIsNotNone(a)
    self.assertIn(contains, a["text"])
    self.assertIn("Default (stock)", a["text"])
    fb = selection.read_state(self.store)["fallback"]
    self.assertEqual(fb["requested_id"], "m")

  def test_load_failure_falls_back_to_exact_stock_in_process(self):
    self.install_and_select()
    m = FakeModeld(fail_load=True)
    self.run_launcher(m)
    self.assertEqual((m.live.pkl, m.live.warp), (STOCK_DIR / "driving_tinygrad.pkl", STOCK_DIR / "driving_warp_1928x1208_tinygrad.pkl"))
    self.assertEqual(m.modeld_pkl_path(False), STOCK_DIR / "driving_tinygrad.pkl")
    self.assert_stock_with_alert(m, "load or first inference failed")

  def test_warmup_inference_failure_falls_back_to_stock(self):
    self.install_and_select()
    m = FakeModeld(fail_warmup=True)
    self.run_launcher(m)
    self.assertTrue(m.live.is_stock)
    self.assert_stock_with_alert(m, "failed")

  def test_nonfinite_output_at_warmup_falls_back_to_stock(self):
    self.install_and_select()
    m = FakeModeld(nan_run=True)
    self.run_launcher(m)
    self.assertTrue(m.live.is_stock)
    self.assert_stock_with_alert(m, "failed")

  def test_inference_error_while_driving_records_fallback_and_next_start_is_stock(self):
    self.install_and_select()
    m = FakeModeld()
    self.run_launcher(m)
    self.assertFalse(m.live.is_stock)
    m.behave["fail_run"] = True
    with self.assertRaises(RuntimeError):
      m.live.run({}, {}, {})
    self.assertIn("inference error", alert.current_alert(self.store)["text"])
    m2 = FakeModeld()
    self.run_launcher(m2)  # the restart modeld gets from the manager
    self.assertTrue(m2.live.is_stock)
    self.assertIs(m2.ModelState, m2.OriginalModelState)  # blocked: not even patched

  def test_nonfinite_output_while_driving_is_treated_as_an_inference_error(self):
    self.install_and_select()
    m = FakeModeld()
    self.run_launcher(m)
    m.behave["nan_run"] = True
    with self.assertRaises(RuntimeError):
      m.live.run({}, {}, {})
    self.assertIn("inference error", alert.current_alert(self.store)["text"])

  def test_validation_failures_never_reach_modeld_patching(self):
    d = self.install_and_select()
    p = d / "driving.pkl"
    b = bytearray(p.read_bytes())
    b[-1] ^= 1
    p.write_bytes(bytes(b))
    m = FakeModeld()
    self.run_launcher(m)
    self.assertIs(m.ModelState, m.OriginalModelState)
    self.assertTrue(m.live.is_stock)
    self.assertIn("hash mismatch", alert.current_alert(self.store)["text"])

  def test_chestnut_gpu_setups_stay_stock_and_say_why(self):
    self.install_and_select()
    m = FakeModeld(chestnut=True)
    self.run_launcher(m)
    self.assertTrue(m.live.is_stock)
    self.assertIn("Chestnut", alert.current_alert(self.store)["text"])

  def test_chestnut_big_model_is_never_replaced(self):
    self.install_and_select()
    m = FakeModeld()
    self.run_launcher(m)
    big = m.ModelState(1928, 1208, True)
    self.assertEqual(big.pkl, STOCK_DIR / "big_" / "driving_tinygrad.pkl")


class TestRealModeldContract(unittest.TestCase):
  """The launcher patches names inside the real modeld.py; fail loudly if those names move."""

  def test_real_modeld_exposes_every_name_the_launcher_uses(self):
    src = MODELD_SRC.read_text()
    for needle in ("from openpilot.selfdrive.modeld.helpers import MODELS_DIR, chestnut_present, chestnut_compiled, modeld_pkl_path",
                   "class ModelState:", "def warmup(self)", "def run(self, bufs", "jits = load_oob(modeld_pkl_path(chestnut), chestnut)",
                   "MODELS_DIR / f'{\"big_\" if chestnut else \"\"}driving_warp_{cam_w}x{cam_h}_tinygrad.pkl'",
                   "ModelState(vipc_client_main.width, vipc_client_main.height, False)", "cable_connected", "def main(demo=False):"):
      self.assertIn(needle, src)

  def test_real_modeld_hook_installs_when_importable(self):
    try:
      from openpilot.selfdrive.modeld import modeld as real
    except Exception as e:  # not importable on hosts without the device stack
      self.skipTest(f"modeld not importable here: {type(e).__name__}")
    original = real.ModelState
    res = resolve.Resolution("alternate", None, None, {})
    try:
      patched = launcher.install(real, res, fx.MemStore())
      self.assertTrue(issubclass(patched, original))
      self.assertIs(real.ModelState, patched)
      self.assertIs(launcher.install(real, res, fx.MemStore()), patched)  # idempotent
    finally:
      real.ModelState = original

  def test_process_config_runs_the_launcher_when_registered(self):
    pc = (Path(__file__).resolve().parents[3] / "system/manager/process_config.py").read_text()
    self.assertIn('PythonProcess("modeld", "openpilot.selfdrive.modeld.bogpilot_modeld", only_onroad)', pc)


if __name__ == "__main__":
  unittest.main()
