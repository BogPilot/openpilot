"""Required `onnx_sha256` manifest field, ONNX file match, and the large-model host param shape built from it."""
import json
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import big_model_param as bmp
from openpilot.common.bogpilot_models import registry
from openpilot.common.tests import bogpilot_model_fixtures as fx

ONNX_A = "a1" * 32
ONNX_B = "b2" * 32


def manifest_bytes(**edits):
  data = fx.driving_pickle_bytes()
  m = {"schema": 1, "id": "m1", "name": "M One", "version": "1", "openpilot": "0.11.2", "license": "MIT",
       "onnx_sha256": ONNX_A,
       "files": [{"role": "driving_model", "name": "d.pkl", "sha256": fx.sha(data), "size": len(data)}]}
  m.update(edits)
  return json.dumps(m).encode()


class TestOnnxField(unittest.TestCase):
  def test_absent_field_rejects_the_manifest(self):
    data = fx.driving_pickle_bytes()
    raw = json.dumps({"schema": 1, "id": "m1", "name": "M One", "version": "1", "openpilot": "0.11.2",
                      "license": "MIT",
                      "files": [{"role": "driving_model", "name": "d.pkl", "sha256": fx.sha(data), "size": len(data)}]}).encode()
    with self.assertRaises(registry.ManifestError) as ctx:
      registry.parse_manifest(raw)
    self.assertIn("onnx_sha256", str(ctx.exception))

  def test_valid_field_is_kept(self):
    self.assertEqual(registry.parse_manifest(manifest_bytes(onnx_sha256=ONNX_A)).onnx_sha256, ONNX_A)

  def test_bad_field_rejects_the_manifest(self):
    for bad in ("A1" * 32, "a1" * 31, 5, "", [], None):
      with self.subTest(bad=bad), self.assertRaises(registry.ManifestError):
        registry.parse_manifest(manifest_bytes(onnx_sha256=bad))

  def test_matching_onnx_file_validates(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      onnx = b"onnx-bytes-A"
      d = fx.install_model(root, "m1", extra_manifest={"onnx_sha256": fx.sha(onnx)})
      (d / "model.onnx").write_bytes(onnx)
      fx.rewrite_manifest(d, onnx_sha256=fx.sha(onnx), files=[
        {"role": "driving_model", "name": "driving.pkl", "sha256": fx.sha((d / "driving.pkl").read_bytes()),
         "size": (d / "driving.pkl").stat().st_size},
        {"role": "driving_onnx", "name": "model.onnx", "sha256": fx.sha(onnx), "size": len(onnx)},
      ])
      e = registry.get_entry("m1", root)
      self.assertEqual(e.onnx_sha256, fx.sha(onnx))
      v = registry.validate_entry(e)
      self.assertTrue(v.ok, v.reason)
      self.assertEqual(e.directory, d)

  def test_mismatched_onnx_file_is_not_usable(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      onnx, other = b"onnx-bytes-A", b"onnx-bytes-B"
      d = fx.install_model(root, "m1", extra_manifest={"onnx_sha256": fx.sha(onnx)})
      (d / "model.onnx").write_bytes(other)
      fx.rewrite_manifest(d, onnx_sha256=fx.sha(onnx), files=[
        {"role": "driving_model", "name": "driving.pkl", "sha256": fx.sha((d / "driving.pkl").read_bytes()),
         "size": (d / "driving.pkl").stat().st_size},
        {"role": "driving_onnx", "name": "model.onnx", "sha256": fx.sha(other), "size": len(other)},
      ])
      v = registry.validate_entry(registry.get_entry("m1", root))
      self.assertFalse(v.ok)
      self.assertIn("ONNX hash mismatch", v.reason)

  def test_stock_entry_has_no_onnx_hash(self):
    self.assertEqual(registry.stock_entry().onnx_sha256, "")
    self.assertTrue(registry.validate_entry(registry.stock_entry()).ok)


class TestBigModelParam(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)

  def entry(self, mid, **manifest):
    fx.install_model(self.root, mid, name=f"Model {mid}", extra_manifest=manifest)
    return registry.get_entry(mid, self.root)

  def test_default_means_remove(self):
    self.assertIsNone(bmp.value_for_entry(registry.stock_entry()))
    self.assertIsNone(bmp.value_for_entry(None))
    self.assertIsNone(bmp.encode(None))

  def test_model_without_onnx_hash_means_remove(self):
    d = fx.install_model(self.root, "plain", name="Model plain")
    man = json.loads((d / "manifest.json").read_text())
    man.pop("onnx_sha256")
    (d / "manifest.json").write_text(json.dumps(man))
    e = registry.get_entry("plain", self.root)
    self.assertTrue(e.problem)
    self.assertIsNone(bmp.value_for_entry(e))

  def test_model_with_onnx_hash_gives_exact_shape(self):
    v = bmp.value_for_entry(self.entry("big", onnx_sha256=ONNX_A))
    self.assertEqual(v, {"sha256": ONNX_A, "displayName": "Model big"})
    self.assertEqual(json.loads(bmp.encode(v)), v)
    self.assertEqual(bmp.encode(v), '{"displayName":"Model big","sha256":"' + ONNX_A + '"}')

  def test_broken_install_means_remove(self):
    d = self.root / "broken"
    d.mkdir()
    (d / "manifest.json").write_text("{not json")
    e = registry.get_entry("broken", self.root)
    self.assertTrue(e.problem)
    self.assertIsNone(bmp.value_for_entry(e))

  def test_parse_accepts_host_write_back_with_ref(self):
    v = bmp.parse_value(json.dumps({"sha256": ONNX_B, "displayName": "  Big   B ", "ref": "abc123"}))
    self.assertEqual(v, {"sha256": ONNX_B, "displayName": "Big B", "ref": "abc123"})

  def test_parse_rejects_unreadable_or_hashless_values(self):
    for raw in (None, "", "   ", "{", "[]", '{"ref": "abc"}', '{"sha256": "XYZ"}', b'{"sha256": 1}', 7):
      with self.subTest(raw=raw):
        self.assertIsNone(bmp.parse_value(raw))

  def test_entry_for_value_maps_back_by_onnx_hash_only(self):
    a = self.entry("a", onnx_sha256=ONNX_A)
    self.entry("b")
    entries = registry.list_entries(self.root)
    self.assertEqual(bmp.entry_for_value(bmp.encode(bmp.value_for_entry(a)), entries).id, "a")
    self.assertIsNone(bmp.entry_for_value(json.dumps({"sha256": ONNX_B}), entries))
    self.assertIsNone(bmp.entry_for_value("garbage", entries))

  def test_ambiguous_hash_maps_to_nothing(self):
    self.entry("a", onnx_sha256=ONNX_A)
    self.entry("a2", onnx_sha256=ONNX_A)
    self.assertIsNone(bmp.entry_for_value(json.dumps({"sha256": ONNX_A}), registry.list_entries(self.root)))

  def test_agreed_param_key_is_jetlink_big_model(self):
    self.assertEqual(bmp.KEY, "JetlinkBigModel")

  def test_module_imports_no_host_package(self):
    src = Path(bmp.__file__).read_text()
    self.assertNotIn("import jetlink", src)
    self.assertNotIn("from jetlink", src)


if __name__ == "__main__":
  unittest.main()
