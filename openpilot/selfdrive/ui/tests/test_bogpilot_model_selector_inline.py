"""Driving Model page: the inline [-] model [+] row (Alert Volume style) and the download rows."""
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, STOCK_NAME
from openpilot.common.tests import bogpilot_model_fixtures as fx
from openpilot.selfdrive.ui.bogpilot import toggle_help
from openpilot.selfdrive.ui.bogpilot.bogpilot_model_selector import (
  DOWNLOAD_LABEL, INLINE_TITLE, ModelSelectorController, create_driving_model_layout, inline_text, step_target)

URL = "https://github.com/BogPilot/openpilot-models/releases/download/v1/driving_tinygrad.pkl"


def hosted_item(model_id="hosted", name="Hosted"):
  b = fx.driving_pickle_bytes()
  return {"id": model_id, "name": name, "version": "1.0", "openpilot": "0.11.2", "license": "MIT",
          "onnx_sha256": fx.DEFAULT_ONNX_SHA256, "url": URL,
          "files": [{"role": "driving_model", "name": "driving_tinygrad.pkl", "sha256": fx.sha(b), "size": len(b), "url": URL}]}


class Base(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)
    self.store = fx.MemStore()
    self.offroad = True

  def ctrl(self, **kw):
    return ModelSelectorController(lambda: self.offroad, self.store, self.root, **kw)


class TestInline(Base):
  def test_only_default_has_no_inline_row_and_no_step(self):
    c = self.ctrl()
    snap = c.refresh()
    self.assertTrue(snap.only_default)
    self.assertEqual(inline_text(snap), [])
    self.assertEqual(snap.choices, ((STOCK_ID, STOCK_NAME),))
    self.assertIsNone(c.step(1))
    self.assertIsNone(c.step(-1))
    self.assertEqual(snap.downloads, ())   # the shipped catalog is empty

  def test_steps_through_usable_models_only_without_wrapping(self):
    fx.install_model(self.root, "a-model", name="A")
    fx.install_model(self.root, "b-model", name="B")
    fx.install_model(self.root, "broken", name="Broken", declared_driving=b"other bytes")
    c = self.ctrl()
    snap = c.refresh()
    self.assertEqual([i for i, _ in snap.choices], [STOCK_ID, "a-model", "b-model"])
    self.assertEqual(inline_text(snap), [INLINE_TITLE, f"- {STOCK_NAME} +"])
    self.assertIsNone(c.step(-1))
    self.assertEqual(c.step(1), "a-model")
    self.assertEqual(self.store.writes, [])   # stepping alone never writes
    self.assertTrue(c.select("a-model").ok)
    snap = c.snapshot
    self.assertEqual(snap.pick, "a-model")
    self.assertEqual(inline_text(snap), [INLINE_TITLE, "- A +"])
    self.assertEqual(step_target(snap, 1), "b-model")
    self.assertEqual(step_target(snap, -1), STOCK_ID)
    self.assertTrue(c.select("b-model").ok)
    self.assertIsNone(c.step(1))
    self.assertIsNone(step_target(c.snapshot, 0))

  def test_blocked_choice_shows_default(self):
    from openpilot.common.bogpilot_models import selection
    fx.install_model(self.root, "a-model", name="A")
    c = self.ctrl()
    self.assertTrue(c.select("a-model").ok)
    sel, _ = selection.read_selection(self.store)
    selection.record_fallback(self.store, sel, "A", "load failed", "load")
    snap = c.refresh()
    self.assertTrue(snap.notice)
    self.assertEqual(snap.pick, STOCK_ID)
    self.assertEqual(inline_text(snap)[1], f"- {STOCK_NAME} +")

  def test_download_rows_list_hosted_models_not_installed(self):
    c = self.ctrl(catalog=(hosted_item(), {"id": "bad-license", **{k: v for k, v in hosted_item().items() if k != "id"},
                                                    "license": "unknown"}), download_gate=lambda: True)
    snap = c.refresh()
    self.assertEqual([d[0] for d in snap.downloads], ["hosted"])
    self.assertTrue(snap.can_download)
    self.assertIn("License MIT", snap.downloads[0][2])
    fx.install_model(self.root, "hosted", name="Hosted")
    self.assertEqual(c.refresh().downloads, ())

  def test_help_keys_exist(self):
    for key in ("driving_model.inline", "driving_model.download"):
      self.assertIn(key, toggle_help.HELP)


class TestLayout(Base):
  def _gui(self):
    from unittest import mock
    try:
      with mock.patch("openpilot.common.hardware.comma.hardware.get_device_type", lambda: "tizi"):
        import pyray as rl
        from openpilot.system.ui.lib.application import gui_app
    except Exception as e:
      self.skipTest(f"raylib widgets unavailable: {type(e).__name__}")
    return rl, gui_app, mock

  def test_inline_row_and_download_row_are_built(self):
    rl, gui_app, mock = self._gui()
    fx.install_model(self.root, "a-model", name="A")
    with mock.patch.object(gui_app, "font", lambda *a: rl.Font()):
      c = self.ctrl(catalog=(hosted_item(),), download_gate=lambda: True)
      layout = create_driving_model_layout(c)
      layout.show_event()
      titles = [item.title for item in layout.scroller._items]
      self.assertEqual(titles[1], INLINE_TITLE)
      inline = layout.scroller._items[1].action_item
      self.assertEqual(inline.value_index, 1) if hasattr(inline, "value_index") else None
      self.assertIn("Hosted", titles)
      labels = [getattr(item.action_item, "text", "") for item in layout.scroller._items]
      self.assertIn(DOWNLOAD_LABEL, labels)

  def test_only_default_layout_has_no_inline_row(self):
    rl, gui_app, mock = self._gui()
    with mock.patch.object(gui_app, "font", lambda *a: rl.Font()):
      layout = create_driving_model_layout(self.ctrl())
      layout.show_event()
      self.assertNotIn(INLINE_TITLE, [item.title for item in layout.scroller._items][1:])


if __name__ == "__main__":
  unittest.main()
