"""BogPilot model selection: offroad-only switching, validated resolve for modeld, fallbacks, offroad alert."""
import json
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, alert, registry, resolve, selection
from openpilot.common.tests import bogpilot_model_fixtures as fx

OFF, ON = (lambda: True), (lambda: False)


class Base(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.store = fx.MemStore()

  def tearDown(self):
    self.tmp.cleanup()

  def select(self, mid, offroad=OFF):
    return selection.select(mid, offroad, self.store, self.root)

  def resolve(self):
    return resolve.resolve_for_modeld(self.store, self.root)


class TestSelect(Base):
  def test_fresh_install_resolves_stock_and_writes_nothing(self):
    r = self.resolve()
    self.assertEqual((r.kind, r.fallback, r.entry.id), ("stock", False, STOCK_ID))
    resolve.note_started(self.store, r)
    self.assertEqual(self.store.writes, [])
    self.assertIsNone(alert.current_alert(self.store))

  def test_select_valid_writes_pinned_selection_for_next_drive(self):
    fx.install_model(self.root, "m")
    res = self.select("m")
    self.assertTrue(res.ok, res.message)
    self.assertIn("next drive", res.message)
    sel, corrupt = selection.read_selection(self.store)
    self.assertFalse(corrupt)
    e = registry.get_entry("m", self.root)
    v = registry.validate_entry(e)
    self.assertEqual((sel.id, sel.pin_model, sel.pin_manifest), ("m", v.model_sha256, v.manifest_sha256))

  def test_select_refused_when_not_offroad_or_unknown_and_writes_nothing(self):
    fx.install_model(self.root, "m")
    self.assertFalse(self.select("m", ON).ok)

    def boom():
      raise RuntimeError("no ui state")
    self.assertFalse(self.select("m", boom).ok)
    self.assertFalse(selection.select("m", lambda: None, self.store, self.root).ok)  # not exactly True
    self.assertFalse(selection.select(STOCK_ID, ON, self.store, self.root).ok)  # even Default
    self.assertEqual(self.store.writes, [])
    self.assertFalse(self.select("ghost").ok)

  def test_select_refused_for_invalid_models(self):
    good = fx.driving_pickle_bytes()
    bad = bytearray(good)
    bad[-1] ^= 1
    fx.install_model(self.root, "corrupt", driving=bytes(bad), declared_driving=good)
    fx.install_model(self.root, "shape", driving=fx.driving_pickle_bytes(fx.stock_abi_variant(**{"input_specs.new_img": [[1], "uint8", "QCOM"]})))
    for mid in ("corrupt", "shape"):
      res = self.select(mid)
      self.assertFalse(res.ok, mid)
      self.assertIn("cannot be used", res.message)
    self.assertEqual(self.store.writes, [])

  def test_selecting_default_removes_selection_and_clears_fallback(self):
    fx.install_model(self.root, "m")
    self.select("m")
    selection.record_fallback(self.store, selection.read_selection(self.store)[0], "M", "boom", "load")
    self.assertTrue(self.select(STOCK_ID).ok)
    self.assertIsNone(self.store.raw(selection.KEY_SELECTION))
    self.assertNotIn("fallback", selection.read_state(self.store))
    self.assertEqual(self.resolve().kind, "stock")


class TestResolve(Base):
  def test_valid_selection_resolves_alternate_with_verified_paths(self):
    fx.install_model(self.root, "m", warps={"driving_warp_1344x760": fx.warp_pickle_bytes("driving_warp_1344x760")})
    self.select("m")
    r = self.resolve()
    self.assertEqual((r.kind, r.fallback, r.entry.id), ("alternate", False, "m"))
    self.assertEqual(set(r.paths), {"driving_model", "driving_warp_1344x760"})
    resolve.note_started(self.store, r)
    self.assertEqual(selection.read_state(self.store)["active"]["id"], "m")

  def fell_back(self, contains):
    r = self.resolve()
    self.assertEqual((r.kind, r.fallback), ("stock", True))
    self.assertIn(contains, r.reason)
    a = alert.current_alert(self.store)
    self.assertIsNotNone(a)
    self.assertIn("Default (stock)", a["text"])
    return r

  def test_missing_model_falls_back(self):
    fx.install_model(self.root, "m")
    self.select("m")
    for p in (self.root / "m").iterdir():
      p.unlink()
    (self.root / "m").rmdir()
    self.fell_back("no longer installed")

  def test_corrupted_model_after_selection_falls_back(self):
    d = fx.install_model(self.root, "m")
    self.select("m")
    p = d / "driving.pkl"
    b = bytearray(p.read_bytes())
    b[-1] ^= 1
    p.write_bytes(bytes(b))
    self.fell_back("hash mismatch")

  def test_model_replaced_by_other_valid_files_falls_back_on_pin(self):
    d = fx.install_model(self.root, "m")
    self.select("m")
    other = fx.driving_pickle_bytes() + b"different-but-valid"
    (d / "driving.pkl").write_bytes(other)
    fx.rewrite_manifest(d, files=[{"role": "driving_model", "name": "driving.pkl", "sha256": fx.sha(other), "size": len(other)}])
    self.fell_back("changed after they were selected")

  def test_incompatible_after_selection_and_unreadable_selection(self):
    d = fx.install_model(self.root, "m")
    self.select("m")
    bad = fx.driving_pickle_bytes(fx.stock_abi_variant(**{"output_specs.outputs": [[1, 9], "float32", "QCOM"]}))
    (d / "driving.pkl").write_bytes(bad)
    fx.rewrite_manifest(d, files=[{"role": "driving_model", "name": "driving.pkl", "sha256": fx.sha(bad), "size": len(bad)}])
    self.fell_back("expected")
    self.store.kv[selection.KEY_SELECTION] = "garbage{"
    self.store.kv.pop(selection.KEY_STATE)
    self.fell_back("unreadable")

  def test_failed_start_stays_blocked_until_user_selects_again(self):
    fx.install_model(self.root, "m")
    self.select("m")
    r = self.resolve()
    resolve.note_failed(self.store, r, "inference error (RuntimeError)", "run")
    again = self.resolve()
    self.assertEqual((again.kind, again.fallback), ("stock", True))
    self.assertIn("inference error", again.reason)
    self.assertIsNotNone(alert.current_alert(self.store))
    self.assertTrue(self.select("m").ok)  # explicit retry clears the block and the alert
    self.assertIsNone(alert.current_alert(self.store))
    self.assertEqual(self.resolve().kind, "alternate")

  def test_selector_exceptions_resolve_to_stock(self):
    class Broken(fx.MemStore):
      def raw(self, key):
        raise OSError("disk gone")
    r = resolve.resolve_for_modeld(Broken(), self.root)
    self.assertEqual((r.kind, r.entry.id), ("stock", STOCK_ID))

  def test_resolution_is_a_snapshot_so_later_changes_cannot_switch_a_running_model(self):
    fx.install_model(self.root, "a")
    fx.install_model(self.root, "b")
    self.select("a")
    r = self.resolve()
    self.assertFalse(self.select("b", ON).ok)  # onroad change refused
    self.assertEqual(r.entry.id, "a")
    self.assertEqual(selection.read_selection(self.store)[0].id, "a")


class TestAlert(Base):
  def test_alert_follows_the_selection(self):
    fx.install_model(self.root, "m", name="Fancy")
    self.select("m")
    sel = selection.read_selection(self.store)[0]
    selection.record_fallback(self.store, sel, "Fancy", "hash mismatch (file changed or corrupt)", "validate")
    a = alert.current_alert(self.store)
    self.assertEqual(a["severity"], 1)
    self.assertIn("Fancy", a["text"])
    self.assertIn("hash mismatch", a["text"])
    self.store.remove(selection.KEY_SELECTION)  # user moved on to Default some other way
    self.assertIsNone(alert.current_alert(self.store))

  def test_alert_never_raises(self):
    class Broken(fx.MemStore):
      def raw(self, key):
        raise OSError
    self.assertIsNone(alert.current_alert(Broken()))

  def test_state_json_is_plain_and_bounded(self):
    selection.record_fallback(self.store, None, "x" * 500, "r\n" * 500, "load")
    st = json.loads(self.store.kv[selection.KEY_STATE])
    self.assertLessEqual(len(st["fallback"]["reason"]), 220)
    self.assertNotIn("\n", st["fallback"]["reason"])
    self.assertLessEqual(len(st["fallback"]["requested_name"]), 60)


if __name__ == "__main__":
  unittest.main()
