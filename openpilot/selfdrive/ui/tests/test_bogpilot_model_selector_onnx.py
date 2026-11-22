"""Driving Model page: an installed model's ONNX id is shown when its manifest declares one; the help text states
the per-drive rule. Pure Python, no raylib."""
import tempfile
import unittest
from pathlib import Path

from openpilot.common.tests import bogpilot_model_fixtures as fx
from openpilot.selfdrive.ui.bogpilot import toggle_help
from openpilot.selfdrive.ui.bogpilot.bogpilot_model_selector import ModelSelectorController, ui_text

ONNX = "c3" * 32


class TestOnnxDetail(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)

  def snap(self):
    return ModelSelectorController(lambda: True, fx.MemStore(), self.root).refresh()

  def test_detail_shows_onnx_id_when_declared(self):
    fx.install_model(self.root, "big", name="Big", extra_manifest={"onnx_sha256": ONNX})
    row = next(r for r in self.snap().rows if r.id == "big")
    self.assertIn(f"| ONNX {ONNX[:12]} |", row.detail)
    self.assertTrue(row.detail.endswith("Compatible with 0.11.2"))
    self.assertTrue(row.selectable)

  def test_missing_onnx_hash_is_not_usable(self):
    import json
    d = fx.install_model(self.root, "plain", name="Plain")
    man = json.loads((d / "manifest.json").read_text())
    man.pop("onnx_sha256")
    (d / "manifest.json").write_text(json.dumps(man))
    row = next(r for r in self.snap().rows if r.id == "plain")
    self.assertFalse(row.selectable)
    self.assertIn("Not usable", row.detail)
    self.assertNotIn("| ONNX ", row.detail)

  def test_page_text_lists_both(self):
    fx.install_model(self.root, "big", name="Big", extra_manifest={"onnx_sha256": ONNX})
    fx.install_model(self.root, "plain", name="Plain")
    text = ui_text(self.snap())
    self.assertEqual([t for t in text if t in ("Default (stock)", "Big", "Plain")], ["Default (stock)", "Big", "Plain"])
    plain = next(r for r in self.snap().rows if r.id == "plain")
    self.assertIn(f"| ONNX {fx.DEFAULT_ONNX_SHA256[:12]} |", plain.detail)
    self.assertTrue(plain.selectable)


class TestHelpText(unittest.TestCase):
  def test_entry_help_states_the_per_drive_rule(self):
    src = Path(toggle_help.__file__).read_text()
    self.assertIn("keeps the model that drive started", src)


if __name__ == "__main__":
  unittest.main()
