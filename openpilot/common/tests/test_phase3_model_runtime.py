"""Lane2 runtime tests. All model files here are SYNTHETIC fixtures with made-up shapes, used only to
exercise the transaction logic; the runtime itself never hardcodes shapes (it compares to stock)."""
from __future__ import annotations
import base64, hashlib, importlib.util, io, json, os, pickle, struct, sys, tempfile, types, unittest
from pathlib import Path
import numpy as np

from openpilot.common import phase3_model_runtime as rtm
from openpilot.common.phase3_model_runtime import STOCK_ID, Runtime, read_abi, compare_abi, RuntimeErrorBP
from openpilot.common import phase3_modeld_launcher as launcher
from openpilot.common.phase3_model_backend import RuntimeModelBackend


class TinyJit:  # pickled by reference; runtime must stub it, never import it
  def __init__(self, tag): self.tag = tag


class Evil:
  def __reduce__(self): return (os.system, ("touch /tmp/phase3_pwned",))


def make_pkl(path, *, out=24, extra_input=False, tag="w", evil=False, slices=None):
  slices = slices or {"plan": slice(0, 20), "pad": slice(-2, None)}
  ins = {"new_img": ((2, 6, 4, 4), "uint8", "QCOM"), "desire": ((8,), "float32", "QCOM")}
  if extra_input:
    ins["extra"] = ((1, 3), "float32", "QCOM")
  obj = {"metadata": {"metadata": {"output_slices": base64.b64encode(pickle.dumps(slices)).decode(), "model_checkpoint": tag},
                      "input_shapes": {k: v[0] for k, v in ins.items()}, "output_shapes": {"outputs": (1, out)}},
         "run": Evil() if evil else TinyJit(tag), "input_specs": ins, "output_specs": {"outputs": ((1, out), "float32", "QCOM")}}
  ops = pickle.dumps(obj)
  Path(path).write_bytes(struct.pack("<q", len(ops)) + ops + tag.encode() * 64)
  return Path(path)


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Base(unittest.TestCase):
  def setUp(self):
    self.tmp = Path(tempfile.mkdtemp())
    self.stock_dir = self.tmp / "models"; self.stock_dir.mkdir()
    make_pkl(self.stock_dir / "driving_tinygrad.pkl", tag="stock")
    self.pins = self.tmp / "pins.json"
    self.pins.write_text(json.dumps({"assets": {"openpilot/selfdrive/modeld/models/driving_tinygrad.pkl":
                                                {"sha256": sha(self.stock_dir / "driving_tinygrad.pkl")}}}))
    self.gate_error = None
    self.rt = Runtime(self.tmp / "rt", self.stock_dir, self.pins, runtime_gate=self.gate)
    self.offroad = True

  def is_off(self): return self.offroad

  def gate(self):
    if self.gate_error: raise RuntimeErrorBP(self.gate_error)

  def stage(self, name="alt", **kw):
    d = self.tmp / f"stage-{name}"; d.mkdir(exist_ok=True)
    p = make_pkl(d / "driving_tinygrad.pkl", tag=name, **kw)
    return d, {"assets": [{"name": "driving_tinygrad.pkl", "sha256": sha(p), "size": p.stat().st_size}]}

  def install(self, name="alt", **kw):
    d, m = self.stage(name, **kw)
    return self.rt.install(name, d, m, name=name.upper())


class TestAbi(Base):
  def test_static_abi_matches_and_detects_each_difference(self):
    s = read_abi(self.stock_dir / "driving_tinygrad.pkl")
    self.assertEqual(s["input_specs"]["new_img"], [[2, 6, 4, 4], "uint8", "QCOM"])
    self.assertIn(f"{__name__}.TinyJit", s["classes"])
    self.assertTrue(compare_abi(s, read_abi(make_pkl(self.tmp / "a.pkl", tag="a")))[0])
    for kw, key in (({"out": 30}, "output_specs"), ({"extra_input": True}, "input_specs"),
                    ({"slices": {"plan": slice(0, 21), "pad": slice(-2, None)}}, "output_slices")):
      ok, reason = compare_abi(s, read_abi(make_pkl(self.tmp / "b.pkl", **kw)))
      self.assertFalse(ok); self.assertIn(key, reason)

  def test_never_executes_payload_and_rejects_legacy_plain_pickle(self):
    flag = Path("/tmp/phase3_pwned"); flag.unlink(missing_ok=True)
    abi = read_abi(make_pkl(self.tmp / "e.pkl", evil=True))
    self.assertFalse(flag.exists())
    self.assertTrue(abi["run"].endswith(".system"))  # stubbed global (os|posix by Python version), so it also fails ABI equality
    legacy = self.tmp / "legacy.pkl"; legacy.write_bytes(pickle.dumps({"policy": TinyJit("x")}))
    with self.assertRaises(RuntimeErrorBP): read_abi(legacy)
    bad = self.tmp / "slices.pkl"
    obj = {"metadata": {"metadata": {"output_slices": base64.b64encode(pickle.dumps({"x": Evil()})).decode()}},
           "run": 1, "input_specs": {}, "output_specs": {}}
    ops = pickle.dumps(obj); bad.write_bytes(struct.pack("<q", len(ops)) + ops)
    with self.assertRaises(RuntimeErrorBP): read_abi(bad)
    self.assertFalse(flag.exists())


class TestInstall(Base):
  def test_install_verifies_and_is_immutable(self):
    i = self.install()
    self.assertTrue(i.compatible)
    st = self.rt.status()
    self.assertEqual([x.id for x in st.installed], ["alt"]); self.assertEqual(st.limitation, "")
    self.assertEqual(st.active_id, None); self.assertEqual(st.selected_id, STOCK_ID)
    with self.assertRaises(RuntimeErrorBP): self.install()  # same id twice

  def test_rejections_leave_no_bundle(self):
    d, m = self.stage("x")
    bad = json.loads(json.dumps(m)); bad["assets"][0]["sha256"] = "0" * 64
    for args, why in (((("x", d, bad)), "sha256"),
                      ((("x", d, {"assets": m["assets"] + [{"name": "driving_warp_1344x760_tinygrad.pkl"}]})), "substitutes only"),
                      ((("stock-0.11.2-qcom", d, m)), "invalid bundle id"),
                      ((("../x", d, m)), "invalid bundle id")):
      with self.assertRaisesRegex(RuntimeErrorBP, why): self.rt.install(*args)
    d2, m2 = self.stage("inc", out=30)
    with self.assertRaisesRegex(RuntimeErrorBP, "output_specs"): self.rt.install("inc", d2, m2)
    d3 = self.tmp / "dup"; d3.mkdir(); (d3 / "driving_tinygrad.pkl").write_bytes((self.stock_dir / "driving_tinygrad.pkl").read_bytes())
    p = d3 / "driving_tinygrad.pkl"
    with self.assertRaisesRegex(RuntimeErrorBP, "stock model"):
      self.rt.install("dup", d3, {"assets": [{"name": "driving_tinygrad.pkl", "sha256": sha(p), "size": p.stat().st_size}]})
    self.assertEqual(self.rt.status().installed, ())
    self.assertEqual(list(self.rt.bundles.glob(".tmp-*")), [])

  def test_interrupted_install_is_cleaned_and_invisible(self):
    self.rt.bundles.mkdir(parents=True)
    (self.rt.bundles / ".tmp-alt-dead").mkdir()
    self.assertEqual(self.rt.status().installed, ())
    self.install()
    self.assertFalse((self.rt.bundles / ".tmp-alt-dead").exists())


class TestSelectActivate(Base):
  def test_offroad_only_revision_and_race(self):
    self.install(); rev = self.rt.status().revision
    self.assertFalse(self.rt.select("alt", "stale", self.is_off)[0])
    self.offroad = False
    self.assertFalse(self.rt.select("alt", rev, self.is_off)[0])
    calls = iter([True, False])  # offroad at check, onroad right after write
    ok, msg = self.rt.select("alt", rev, lambda: next(calls))
    self.assertFalse(ok); self.assertIn("onroad", msg)
    self.assertEqual(self.rt.status().pending_id, None)

  def test_pending_until_runtime_ack_then_active(self):
    self.install(); ok, msg = self.rt.select("alt", self.rt.status().revision, self.is_off)
    self.assertTrue(ok); self.assertIn("Queued", msg)
    st = self.rt.status(); self.assertEqual((st.pending_id, st.active_id), ("alt", None))
    r = self.rt.resolve_for_modeld(False); self.assertEqual(r.id, "alt")
    self.assertEqual(self.rt.status().active_id, None)
    self.rt.confirm(r.id, r.sha256, False)
    st = self.rt.status(); self.assertEqual((st.pending_id, st.active_id, st.selected_id), (None, "alt", "alt"))
    ok, _ = self.rt.rollback_to_stock(st.revision, self.is_off); self.assertTrue(ok)
    self.assertEqual(self.rt.status().pending_id, STOCK_ID)
    r = self.rt.resolve_for_modeld(False); self.assertEqual(r.id, STOCK_ID)
    self.rt.confirm(STOCK_ID, "", False)
    st = self.rt.status(); self.assertEqual((st.pending_id, st.active_id), (None, STOCK_ID))

  def test_unconfirmed_starts_roll_back(self):
    self.install(); self.rt.select("alt", self.rt.status().revision, self.is_off)
    for _ in range(rtm.MAX_UNCONFIRMED_STARTS):
      self.assertEqual(self.rt.resolve_for_modeld(False).id, "alt")
    self.assertEqual(self.rt.resolve_for_modeld(False).id, STOCK_ID)
    st = self.rt.status()
    self.assertEqual((st.selected_id, st.pending_id), (STOCK_ID, None)); self.assertIn("alt", st.failed)
    self.assertEqual(self.rt.resolve_for_modeld(False).id, STOCK_ID)

  def test_tamper_missing_chestnut_and_stock_change(self):
    self.install(); self.rt.select("alt", self.rt.status().revision, self.is_off)
    self.assertEqual(self.rt.resolve_for_modeld(True).id, STOCK_ID)  # big model: stock only, no attempt
    p = self.rt.bundles / "alt" / "driving_tinygrad.pkl"; os.chmod(p, 0o644)
    data = bytearray(p.read_bytes()); data[-1] ^= 1; p.write_bytes(bytes(data))
    self.assertEqual(self.rt.resolve_for_modeld(False).id, STOCK_ID)
    self.assertIn("hash", self.rt.status().failed["alt"])
    # stock ABI changes (e.g. OTA update) -> previously installed bundle no longer compatible
    self.install("alt2"); make_pkl(self.stock_dir / "driving_tinygrad.pkl", out=30, tag="stock")
    self.assertFalse({i.id: i.compatible for i in self.rt.status().installed}["alt2"])

  def test_power_loss_and_corrupt_state(self):
    self.install(); self.rt.select("alt", self.rt.status().revision, self.is_off)
    (self.rt.root / ".state.json.dead.tmp").write_text("{partial")  # crash before rename
    self.assertEqual(self.rt.status().pending_id, "alt")
    (self.rt.root / "state.json").write_text("{trunc")  # should never happen with rename, still fail safe
    st = self.rt.status(); self.assertEqual((st.selected_id, st.pending_id), (STOCK_ID, None))
    self.assertEqual(self.rt.resolve_for_modeld(False).id, STOCK_ID)

  def test_delete_protections(self):
    self.install(); self.install("b"); rev = self.rt.status().revision
    self.assertFalse(self.rt.delete(STOCK_ID, rev, self.is_off)[0])
    self.rt.select("alt", rev, self.is_off); rev = self.rt.status().revision
    self.assertFalse(self.rt.delete("alt", rev, self.is_off)[0])
    self.offroad = False; self.assertFalse(self.rt.delete("b", rev, self.is_off)[0]); self.offroad = True
    self.assertTrue(self.rt.delete("b", rev, self.is_off)[0])
    self.assertEqual([i.id for i in self.rt.status().installed], ["alt"])
    self.assertTrue((self.stock_dir / "driving_tinygrad.pkl").exists())


class TestRuntimeGate(Base):
  def test_closure_drift_blocks_alternates_fail_closed_stock_unaffected(self):
    self.install(); self.rt.select("alt", self.rt.status().revision, self.is_off)
    self.gate_error = "compiler/runtime ABI drift: pyproject.toml"
    self.rt._cache.pop("gate", None)
    st = self.rt.status()
    self.assertIsNone(st.installed[0].compatible); self.assertIn("pyproject.toml", st.limitation)
    self.assertFalse(self.rt.select("alt", st.revision, self.is_off)[0])
    self.assertEqual(self.rt.resolve_for_modeld(False).id, STOCK_ID)
    st = self.rt.status(); self.assertEqual(st.pending_id, "alt"); self.assertEqual(st.failed, {})  # not blamed, no attempt
    self.assertTrue(self.rt.rollback_to_stock(st.revision, self.is_off)[0])  # stock never gated
    self.gate_error = None; self.rt._cache.pop("gate", None)
    self.assertTrue(self.rt.status().installed[0].compatible)

  def test_default_gate_without_lane1_module_fails_closed(self):
    rt = Runtime(self.tmp / "rt2", self.stock_dir, self.pins)
    ok, why = rt.runtime_gate_result()
    try:
      import openpilot.common.phase3_model_catalog  # noqa: F401  (present only after lane1 integration)
    except ImportError:
      self.assertFalse(ok); self.assertIn("unavailable", why)


class FakeModelState:
  fail_paths = set()
  def __init__(self, cam_w, cam_h, chestnut):
    self.path = fake_modeld.modeld_pkl_path(chestnut); self.chestnut = chestnut
    if str(self.path) in self.fail_paths: raise RuntimeError("load")
    self.out = np.zeros(3, dtype=np.float32)
  def run(self, *a, **k): return {"plan": self.out}
  def warmup(self): self.run()


fake_modeld = types.SimpleNamespace(cloudlog=types.SimpleNamespace(exception=lambda *a: None, warning=lambda *a: None),
                                    chestnut_compiled=lambda: False, chestnut_present=lambda: False, cable_connected=lambda: False)


class TestLauncher(Base):
  def setUp(self):
    super().setUp()
    fake_modeld.ModelState = FakeModelState; FakeModelState.fail_paths = set()
    fake_modeld.modeld_pkl_path = lambda c: self.stock_dir / "driving_tinygrad.pkl"
    self.MS = launcher.install(fake_modeld, self.rt)

  def select_alt(self):
    self.install(); self.rt.select("alt", self.rt.status().revision, self.is_off)

  def test_alternate_loads_confirms_on_real_run_not_warmup(self):
    self.select_alt()
    ms = self.MS(1, 1, False)
    self.assertEqual(ms.path, self.rt.bundles / "alt" / "driving_tinygrad.pkl")
    self.assertEqual(fake_modeld.modeld_pkl_path(False), self.stock_dir / "driving_tinygrad.pkl")  # restored
    ms.warmup(); self.assertIsNone(self.rt.status().active_id)
    ms.run(); self.assertEqual(self.rt.status().active_id, "alt")

  def test_load_failure_falls_back_to_stock_same_process(self):
    self.select_alt(); FakeModelState.fail_paths = {str(self.rt.bundles / "alt" / "driving_tinygrad.pkl")}
    ms = self.MS(1, 1, False)
    self.assertEqual(ms.path, self.stock_dir / "driving_tinygrad.pkl")
    ms.run(); st = self.rt.status()
    self.assertEqual((st.active_id, st.selected_id), (STOCK_ID, STOCK_ID)); self.assertIn("load failed", st.failed["alt"])

  def test_non_finite_alternate_output_records_rollback(self):
    self.select_alt(); ms = self.MS(1, 1, False); ms.out = np.array([np.nan], dtype=np.float32)
    with self.assertRaises(RuntimeError): ms.run()
    self.assertIn("run failed", self.rt.status().failed["alt"])
    self.assertEqual(self.MS(1, 1, False).path, self.stock_dir / "driving_tinygrad.pkl")

  def test_chestnut_mode_keeps_small_fallback_stock(self):
    self.select_alt(); fake_modeld.chestnut_compiled = lambda: True; fake_modeld.cable_connected = lambda: True
    try:
      del fake_modeld.ModelState; fake_modeld.ModelState = FakeModelState
      MS = launcher.install(fake_modeld, self.rt)
      self.assertEqual(MS(1, 1, False).path, self.stock_dir / "driving_tinygrad.pkl")
      self.assertEqual(self.rt.status().pending_id, "alt")  # no attempt consumed
    finally:
      fake_modeld.chestnut_compiled = lambda: False; fake_modeld.cable_connected = lambda: False


def load_ui_types():
  path = os.environ.get("LANE3_SELECTOR") or str(Path(__file__).resolve().parents[2] / "selfdrive/ui/bogpilot/phase3_model_selector.py")
  if not Path(path).is_file(): return None
  spec = importlib.util.spec_from_file_location("lane3_selector", path)
  mod = importlib.util.module_from_spec(spec); sys.modules["lane3_selector"] = mod; spec.loader.exec_module(mod)
  return mod


@unittest.skipIf(load_ui_types() is None, "LANE3_SELECTOR not provided")
class TestLane3Adapter(Base):
  def setUp(self):
    super().setUp(); self.ui = load_ui_types()
    self.be = RuntimeModelBackend(self.rt, self.is_off, self.ui)

  def test_stock_only_is_truthful_and_not_selectable(self):
    s = self.be.snapshot()
    self.assertEqual([m.id for m in s.models], [STOCK_ID]); self.assertEqual(s.capabilities, frozenset())
    self.assertIn("only validated", s.limitation); self.assertIsNone(s.active_id)
    sel = self.ui.ModelSelector(self.be, self.is_off); sel.refresh()
    self.assertFalse(sel.allowed("select", STOCK_ID)[0])
    self.assertFalse(self.be.request("download_all", None, s.revision).accepted)

  def test_alternate_flow_through_lane3_controller(self):
    self.install(); sel = self.ui.ModelSelector(self.be, self.is_off); sel.refresh()
    self.assertIn("select", sel.state.capabilities)
    self.assertTrue(sel.execute("select", "alt", sel.state.revision))
    self.assertEqual((sel.state.pending_id, sel.state.active_id), ("alt", None))
    self.assertIn("Pending", sel.status())
    r = self.rt.resolve_for_modeld(False); self.rt.confirm(r.id, r.sha256, False); sel.refresh()
    self.assertEqual((sel.state.pending_id, sel.state.active_id), (None, "alt"))
    self.offroad = False; sel.refresh()
    self.assertFalse(self.be.request("select", STOCK_ID, sel.state.revision).accepted)


if __name__ == "__main__":
  unittest.main()
