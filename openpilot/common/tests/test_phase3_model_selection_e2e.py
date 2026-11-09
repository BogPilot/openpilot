"""Selection -> store -> modeld launcher -> chosen model / fallback, against the REAL stock files and the
REAL feae selector controller + backend. The alternate is a test-only ABI-identical copy of the stock
payload with a different weight byte (never shipped, never a real alternate model); real alternates do
not exist yet (see lanes/modelSelector/HANDOFF.md). Nothing here executes a model.
"""
from __future__ import annotations
import hashlib, importlib.util, json, sys, tempfile, types, unittest
from pathlib import Path

import numpy as np

from openpilot.common import phase3_model_catalog as mc
from openpilot.common import phase3_modeld_launcher as launcher
from openpilot.common.phase3_model_backend import RuntimeModelBackend
from openpilot.common.phase3_model_runtime import STOCK_ID, Runtime, read_abi

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / mc.MODEL_DIR
UI = ROOT / "openpilot/selfdrive/ui/bogpilot/phase3_model_selector.py"


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_ui():
  spec = importlib.util.spec_from_file_location("p3sel_e2e", UI)
  m = importlib.util.module_from_spec(spec); sys.modules["p3sel_e2e"] = m; spec.loader.exec_module(m)
  return m


class FakeState:
  """Stands in for modeld.ModelState: records which pkl the launcher asked for."""
  fail = set()
  def __init__(self, w, h, chestnut):
    self.path = fm.modeld_pkl_path(chestnut); self.chestnut = chestnut
    if str(self.path) in self.fail: raise RuntimeError("load")
    self.out = np.zeros(3, dtype=np.float32)
  def run(self, *a, **k): return {"plan": self.out}
  def warmup(self): self.run()


fm = types.SimpleNamespace(cloudlog=types.SimpleNamespace(exception=lambda *a: None, warning=lambda *a: None),
                           chestnut_compiled=lambda: False, chestnut_present=lambda: False, cable_connected=lambda: False)


class E2E(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.pins_before = {p.name: sha(p) for p in sorted(MODELS.glob("*.pkl"))}
    cls.tmp0 = tempfile.TemporaryDirectory(prefix="p3sel-fixture-")
    d = Path(cls.tmp0.name)
    raw = bytearray((MODELS / "driving_tinygrad.pkl").read_bytes())
    raw[-1] ^= 0x01  # weight byte only; the opcode header (ABI) is untouched
    (d / "driving_tinygrad.pkl").write_bytes(bytes(raw))
    cls.alt_dir = d
    cls.alt_manifest = {"assets": [{"name": "driving_tinygrad.pkl", "sha256": sha(d / "driving_tinygrad.pkl"), "size": len(raw)}]}

  @classmethod
  def tearDownClass(cls):
    after = {p.name: sha(p) for p in sorted(MODELS.glob("*.pkl"))}
    assert after == cls.pins_before, "stock model files changed"
    cls.tmp0.cleanup()

  def setUp(self):
    self.tmp = Path(tempfile.mkdtemp(prefix="p3sel-"))
    self.offroad = True
    self.gate_error = None
    self.rt = Runtime(self.tmp / "rt", runtime_gate=self.gate)  # real stock dir + real pin manifest
    self.ui = load_ui()
    self.be = RuntimeModelBackend(self.rt, lambda: self.offroad, self.ui)
    self.sel = self.ui.ModelSelector(self.be, lambda: self.offroad)
    fm.ModelState = FakeState; FakeState.fail = set()
    fm.modeld_pkl_path = lambda c: MODELS / "driving_tinygrad.pkl"
    self.MS = launcher.install(fm, self.rt)

  def gate(self):
    if self.gate_error: raise RuntimeError(self.gate_error)

  def install_alt(self):
    return self.rt.install("alt-test", self.alt_dir, self.alt_manifest, name="ALT TEST")

  # ---- default / menu
  def test_fresh_install_defaults_to_stock_and_menu_is_honest(self):
    s = self.sel.state
    self.assertEqual([(m.id, m.name) for m in s.models], [(STOCK_ID, "Default (stock)")])
    self.assertEqual(s.capabilities, frozenset())
    self.assertEqual(self.sel.visible_items(), (("select", "Select Driving Model"),))  # no inert rows
    self.assertIsNone(s.active_id)  # nothing acknowledged yet
    self.assertEqual(self.rt.resolve_for_modeld(False).path, MODELS / "driving_tinygrad.pkl")
    ms = self.MS(1, 1, False); ms.warmup(); ms.run()
    self.assertEqual(self.sel.refresh().active_id, STOCK_ID)
    self.assertIn("Default (stock)", self.sel.status())
    self.assertFalse(self.sel.allowed("select", STOCK_ID)[0])  # already active

  # ---- selection -> store -> launcher
  def test_select_writes_store_and_launcher_loads_chosen_model(self):
    self.install_alt(); self.sel.refresh()
    self.assertIn("select", self.sel.state.capabilities)
    self.assertEqual({k for k, _ in self.sel.visible_items()}, {"select", "delete"})
    self.assertTrue(self.sel.execute("select", "alt-test", self.sel.state.revision))
    st = json.loads((self.rt.root / "state.json").read_text())
    self.assertEqual((st["selected_id"], st["pending_id"]), ("alt-test", "alt-test"))
    ms = self.MS(1, 1, False)
    self.assertEqual(ms.path, self.rt.bundles / "alt-test" / "driving_tinygrad.pkl")
    self.assertEqual(fm.modeld_pkl_path(False), MODELS / "driving_tinygrad.pkl")  # global restored
    ms.warmup(); self.assertIsNone(self.sel.refresh().active_id)  # warmup is not confirmation
    ms.run(); self.assertEqual(self.sel.refresh().active_id, "alt-test")
    # back to Default (stock) through the same UI path
    self.assertTrue(self.sel.execute("select", STOCK_ID, self.sel.state.revision))
    self.assertEqual(self.MS(1, 1, False).path, MODELS / "driving_tinygrad.pkl")

  def test_select_is_offroad_only_and_revision_checked(self):
    self.install_alt(); self.sel.refresh()
    rev = self.sel.state.revision
    self.offroad = False
    self.assertFalse(self.sel.execute("select", "alt-test", rev))
    self.assertFalse(self.be.request("select", "alt-test", rev).accepted)
    self.offroad = True
    self.assertFalse(self.be.request("select", "alt-test", "stale").accepted)
    self.assertEqual(json.loads((self.rt.root / "state.json").read_text())["selected_id"] if (self.rt.root / "state.json").exists() else STOCK_ID, STOCK_ID)

  # ---- fallbacks
  def test_corrupt_hash_same_size_falls_back_to_stock(self):
    self.install_alt(); self.sel.refresh()
    self.assertTrue(self.sel.execute("select", "alt-test", self.sel.state.revision))
    p = self.rt.bundles / "alt-test" / "driving_tinygrad.pkl"
    p.chmod(0o644); raw = bytearray(p.read_bytes()); raw[len(raw) // 2] ^= 0xFF; p.write_bytes(bytes(raw))  # same size, bad hash
    r = self.rt.resolve_for_modeld(False)
    self.assertEqual((r.id, r.path), (STOCK_ID, MODELS / "driving_tinygrad.pkl"))
    st = self.rt.status()
    self.assertEqual((st.selected_id, st.pending_id), (STOCK_ID, None)); self.assertIn("hash mismatch", st.failed["alt-test"])
    self.assertEqual(self.MS(1, 1, False).path, MODELS / "driving_tinygrad.pkl")
    self.assertFalse(self.sel.refresh() is None)
    ok, why = self.sel.allowed("select", "alt-test")  # rolled back + corrupt: not offered for selection
    self.assertFalse(ok); self.assertIn("hash mismatch", why)
    self.assertFalse(self.be.request("select", "alt-test", self.sel.state.revision).accepted)  # runtime refuses too

  def test_truncated_or_missing_bundle_falls_back(self):
    self.install_alt(); self.sel.refresh(); self.sel.execute("select", "alt-test", self.sel.state.revision)
    p = self.rt.bundles / "alt-test" / "driving_tinygrad.pkl"
    p.chmod(0o644); p.write_bytes(p.read_bytes()[:1000])
    self.assertEqual(self.rt.resolve_for_modeld(False).id, STOCK_ID)
    self.assertIn("size mismatch", self.rt.status().failed["alt-test"])

  def test_load_failure_on_device_falls_back_in_process_and_is_recorded(self):
    self.install_alt(); self.sel.refresh(); self.sel.execute("select", "alt-test", self.sel.state.revision)
    FakeState.fail = {str(self.rt.bundles / "alt-test" / "driving_tinygrad.pkl")}
    ms = self.MS(1, 1, False)
    self.assertEqual(ms.path, MODELS / "driving_tinygrad.pkl")
    ms.run(); st = self.rt.status()
    self.assertEqual((st.active_id, st.selected_id), (STOCK_ID, STOCK_ID)); self.assertIn("load failed", st.failed["alt-test"])

  def test_abi_mismatch_is_rejected_at_install_and_never_stored(self):
    d = self.tmp / "bad"; d.mkdir()
    raw = bytearray((MODELS / "driving_tinygrad.pkl").read_bytes())
    n = int.from_bytes(raw[:8], "little", signed=True)
    # change the dtype string of one input in the opcode stream: 'float32' -> 'float16' keeps length identical
    i = raw.index(b"float32", 8, 8 + n); raw[i:i + 7] = b"float16"
    (d / "driving_tinygrad.pkl").write_bytes(bytes(raw))
    m = {"assets": [{"name": "driving_tinygrad.pkl", "sha256": sha(d / "driving_tinygrad.pkl"), "size": len(raw)}]}
    with self.assertRaises(Exception) as cm:
      self.rt.install("abi-bad", d, m)
    self.assertIn("incompatible", str(cm.exception))
    self.assertEqual(self.rt.status().installed, ())
    self.assertFalse(list(self.rt.bundles.glob("abi-bad*")))

  def test_non_pickle_container_such_as_sunnypilot_plain_artifact_is_rejected(self):
    d = self.tmp / "sp"; d.mkdir()
    blob = b"SPTGPLN1" + (123).to_bytes(8, "little") + b'{"parts": []}' + b"\0" * 64
    (d / "driving_tinygrad.pkl").write_bytes(blob)
    m = {"assets": [{"name": "driving_tinygrad.pkl", "sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob)}]}
    with self.assertRaises(Exception):
      self.rt.install("sp-plain", d, m)
    self.assertEqual(self.rt.status().installed, ())

  def test_runtime_gate_failure_blocks_alternates_but_never_stock(self):
    self.install_alt(); self.sel.refresh(); self.sel.execute("select", "alt-test", self.sel.state.revision)
    self.gate_error = "compiler/runtime ABI drift: uv.lock"; self.rt._cache.pop("gate", None)
    self.assertEqual(self.rt.resolve_for_modeld(False).id, STOCK_ID)
    self.assertEqual(self.MS(1, 1, False).path, MODELS / "driving_tinygrad.pkl")

  # ---- invariants
  def test_stock_files_never_touched_and_real_abi_readable(self):
    abi = read_abi(MODELS / "driving_tinygrad.pkl")
    self.assertEqual(abi["digest"], "ac623cabcc97a325cb80164b0c971946d39fc884a6de7cd644942518f533b735")
    mc.verify_bundle(mc.load_catalog(ROOT).entries[0], MODELS, root=ROOT)  # all six pins, byte-identical


class RealModeldHook(unittest.TestCase):
  """The launcher must still patch the real feae modeld module (name/signature drift detector)."""
  def test_install_on_real_modeld_module(self):
    try:
      from openpilot.selfdrive.modeld import modeld as real
    except Exception as e:  # no tinygrad/msgq on this host
      self.skipTest(f"real modeld not importable here: {type(e).__name__}")
    tmp = Path(tempfile.mkdtemp(prefix="p3sel-real-"))
    rt = Runtime(tmp / "rt", runtime_gate=lambda: None)
    paths = []
    orig_load, orig_path = real.load_oob, real.modeld_pkl_path
    class Stop(Exception): pass
    def spy(path, chestnut=False):
      paths.append(Path(path)); raise Stop()
    try:
      real.load_oob = spy
      MS = launcher.install(real, rt)
      with self.assertRaises(Stop): MS(1928, 1208, False)
    finally:
      real.load_oob, real.modeld_pkl_path = orig_load, orig_path
      real.ModelState = MS.__mro__[1]
    self.assertEqual(paths, [MODELS / "driving_tinygrad.pkl"])


if __name__ == "__main__":
  unittest.main()
