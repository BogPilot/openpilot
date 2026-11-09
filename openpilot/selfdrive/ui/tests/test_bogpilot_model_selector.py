"""Driving Model selector: temp model dirs, in-memory store, no GPU.

Stock weights are hard-linked (or copied) once per class. A one-byte variant must be a real copy.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from openpilot.common.bogpilot_models import STOCK_ID, alert, registry, selection
from openpilot.common.bogpilot_models.stock import ROLE_STOCK_FILES, STOCK_HASHES
from openpilot.selfdrive.ui.bogpilot.bogpilot_model_selector import (
  ONLY_DEFAULT_TEXT,
  SELECT_LABEL,
  ModelSelectorController,
  Snapshot,
  create_driving_model_layout,
  ui_text,
)

DEFAULT_DETAIL = "Built in | License MIT (openpilot) | model 6398a4b0e474 | Ships with openpilot 0.11.2"


class MemStore:
  def __init__(self):
    self.kv = {}

  def raw(self, key):
    return self.kv.get(key)

  def put(self, key, value):
    self.kv[key] = value if isinstance(value, str) else str(value)

  def remove(self, key):
    self.kv.pop(key, None)


def _link(src: Path, dst: Path):
  try:
    os.link(src, dst)
  except OSError:
    shutil.copyfile(src, dst)


def _flip_last_byte(path: Path):
  with open(path, "r+b") as handle:
    handle.seek(-1, os.SEEK_END)
    last = handle.read(1)
    handle.seek(-1, os.SEEK_END)
    handle.write(bytes([last[0] ^ 0x01]))


def _install(root: Path, model_id: str, name: str, flip_model: bool):
  src_dir = registry.stock_models_dir()
  dest = root / model_id
  dest.mkdir(parents=True)
  files = []
  for role, fname in ROLE_STOCK_FILES.items():
    src = src_dir / fname
    dst = dest / fname
    if flip_model and role == "driving_model":
      shutil.copyfile(src, dst)
      _flip_last_byte(dst)
    else:
      _link(src, dst)
    files.append({
      "role": role,
      "name": fname,
      "sha256": STOCK_HASHES[fname],
      "size": src.stat().st_size,
    })
  manifest = {
    "schema": 1,
    "id": model_id,
    "name": name,
    "version": "1.0",
    "openpilot": "0.11.2",
    "license": {"name": "MIT"},
    "files": files,
  }
  (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestOnlyDefault(unittest.TestCase):
  def test_fresh_ui_text_is_status_explanation_and_default_row(self):
    with tempfile.TemporaryDirectory() as tmp:
      old = os.environ.get("BOGPILOT_MODELS_DIR")
      os.environ["BOGPILOT_MODELS_DIR"] = tmp
      try:
        ctrl = ModelSelectorController(lambda: True, MemStore(), tmp)
        snap = ctrl.refresh()
        via_env = ModelSelectorController(lambda: True, MemStore(), None).refresh()
      finally:
        if old is None:
          os.environ.pop("BOGPILOT_MODELS_DIR", None)
        else:
          os.environ["BOGPILOT_MODELS_DIR"] = old
    self.assertTrue(snap.only_default)
    self.assertTrue(snap.offroad)
    self.assertEqual(snap.notice, "")
    self.assertEqual([row.id for row in snap.rows], [STOCK_ID])
    self.assertTrue(snap.rows[0].selected)
    self.assertTrue(snap.rows[0].active)
    self.assertFalse(snap.rows[0].selectable)
    self.assertEqual(snap.rows[0].detail, DEFAULT_DETAIL)
    self.assertEqual(STOCK_HASHES["driving_tinygrad.pkl"][:12], "6398a4b0e474")
    text = ui_text(snap)
    self.assertEqual(text, [
      "Active: Default (stock)",
      ONLY_DEFAULT_TEXT,
      "Default (stock)",
      DEFAULT_DETAIL,
    ])
    self.assertNotIn("SELECT", "\n".join(text))
    self.assertEqual(ui_text(via_env), text)

  def test_onroad_status_still_has_no_select(self):
    with tempfile.TemporaryDirectory() as tmp:
      snap = ModelSelectorController(lambda: False, MemStore(), tmp).refresh()
    self.assertTrue(snap.only_default)
    self.assertFalse(snap.offroad)
    self.assertFalse(snap.rows[0].selectable)
    text = ui_text(snap)
    self.assertEqual(text[0], "Active: Default (stock) | Changes apply offroad only")
    self.assertEqual(text[1], ONLY_DEFAULT_TEXT)
    self.assertNotIn("SELECT", "\n".join(text))

  def test_missing_saved_id_shows_default_selected(self):
    store = MemStore()
    store.put(selection.KEY_SELECTION, json.dumps({
      "v": 1, "id": "gone", "pin_model": "ab" * 32, "pin_manifest": "cd" * 32,
    }))
    with tempfile.TemporaryDirectory() as tmp:
      snap = ModelSelectorController(lambda: True, store, tmp).refresh()
    self.assertTrue(snap.only_default)
    self.assertEqual(snap.rows[0].id, STOCK_ID)
    self.assertTrue(snap.rows[0].selected)
    self.assertNotIn("Next drive:", snap.status)
    self.assertNotIn("SELECT", "\n".join(ui_text(snap)))

  def test_corrupt_selection_shows_default_and_does_not_raise(self):
    store = MemStore()
    store.put(selection.KEY_SELECTION, "garbage{")
    with tempfile.TemporaryDirectory() as tmp:
      snap = ModelSelectorController(lambda: True, store, tmp).refresh()
    self.assertTrue(snap.rows[0].selected)
    self.assertEqual(snap.rows[0].id, STOCK_ID)

  def test_store_errors_become_status_text(self):
    class Boom:
      def raw(self, key):
        raise OSError("disk")

      def put(self, key, value):
        raise OSError("disk")

      def remove(self, key):
        raise OSError("disk")

    ctrl = ModelSelectorController(lambda: True, Boom(), "/tmp/bogpilot-models-missing")
    snap = ctrl.refresh()
    self.assertIsInstance(snap, Snapshot)
    self.assertIn("failed", snap.status)
    self.assertIn("OSError", snap.status)
    result = ctrl.select(STOCK_ID)
    self.assertFalse(result.ok)
    self.assertIn("OSError", ctrl.message)
    self.assertEqual(ctrl.message, result.message)


class TestInstalledModels(unittest.TestCase):
  root: Path
  cache: dict

  @classmethod
  def setUpClass(cls):
    cls._tmp = tempfile.TemporaryDirectory()
    cls.root = Path(cls._tmp.name)
    cls.cache = {}
    _install(cls.root, "alternate", "Alternate", flip_model=False)
    _install(cls.root, "flipped", "Flipped", flip_model=True)
    broken = cls.root / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")

  @classmethod
  def tearDownClass(cls):
    cls._tmp.cleanup()

  def setUp(self):
    self.store = MemStore()
    self.ctrl = ModelSelectorController(lambda: True, self.store, self.root, self.cache)

  def _rows(self, snap):
    return {row.id: row for row in snap.rows}

  def test_default_first_and_alternate_selectable_only_offroad(self):
    snap = self.ctrl.refresh()
    self.assertFalse(snap.only_default)
    self.assertEqual([row.id for row in snap.rows], ["default", "alternate", "broken", "flipped"])
    self.assertEqual(snap.rows[0].title, "Default (stock)")
    self.assertEqual(snap.rows[0].detail, DEFAULT_DETAIL)
    alt = self._rows(snap)["alternate"]
    self.assertEqual(alt.title, "Alternate")
    self.assertEqual(alt.detail, "Version 1.0 | License MIT | model 6398a4b0e474 | Compatible with 0.11.2")
    self.assertTrue(alt.selectable)
    self.assertFalse(alt.selected)
    self.assertEqual(alt.problem, "")
    self.assertTrue(snap.rows[0].selected)
    self.assertFalse(snap.rows[0].selectable)
    text = ui_text(snap)
    self.assertNotIn(ONLY_DEFAULT_TEXT, text)
    body = text[1:]
    self.assertEqual(body[0], "Default (stock)")
    self.assertTrue(body[1].endswith(" | Active"))
    self.assertEqual(body[2], "SELECTED")
    self.assertEqual(body[3], "Alternate")
    self.assertIn("Compatible with 0.11.2", body[4])
    self.assertEqual(body[5], SELECT_LABEL)

    onroad = ModelSelectorController(lambda: False, MemStore(), self.root, self.cache).refresh()
    self.assertTrue(all(not row.selectable for row in onroad.rows))
    self.assertIn("Changes apply offroad only", onroad.status)
    self.assertIn("Compatible with 0.11.2", self._rows(onroad)["alternate"].detail)

    def boom():
      raise RuntimeError("no ui state")

    raised = ModelSelectorController(boom, MemStore(), self.root, self.cache).refresh()
    self.assertTrue(all(not row.selectable for row in raised.rows))
    self.assertFalse(raised.offroad)
    self.assertIn("Changes apply offroad only", raised.status)
    not_true = ModelSelectorController(lambda: 1, MemStore(), self.root, self.cache).refresh()
    self.assertFalse(any(row.selectable for row in not_true.rows))

  def test_flipped_byte_is_not_usable_and_not_selectable(self):
    snap = self.ctrl.refresh()
    flipped = self._rows(snap)["flipped"]
    self.assertIn("Not usable:", flipped.detail)
    self.assertIn("hash mismatch", flipped.detail)
    self.assertIn("hash mismatch", flipped.problem)
    self.assertFalse(flipped.selectable)
    result = self.ctrl.select("flipped")
    self.assertFalse(result.ok)
    self.assertIsNone(self.store.raw(selection.KEY_SELECTION))
    self.assertIn("cannot be used", result.message)

  def test_invalid_manifest_is_not_usable(self):
    snap = self.ctrl.refresh()
    broken = self._rows(snap)["broken"]
    self.assertEqual(broken.title, "broken")
    self.assertTrue(broken.detail.startswith("Not usable:"))
    self.assertIn("not valid JSON", broken.detail)
    self.assertFalse(broken.selectable)
    self.assertTrue(broken.problem)

  def test_select_writes_key_and_next_drive_then_default_removes_it(self):
    result = self.ctrl.select("alternate")
    self.assertTrue(result.ok, result.message)
    self.assertEqual(self.ctrl.message, result.message)
    raw = self.store.raw(selection.KEY_SELECTION)
    self.assertIsNotNone(raw)
    saved = json.loads(raw)
    self.assertEqual(saved["v"], 1)
    self.assertEqual(saved["id"], "alternate")
    self.assertEqual(len(saved["pin_model"]), 64)
    self.assertEqual(len(saved["pin_manifest"]), 64)
    snap = self.ctrl.snapshot
    self.assertIn("Active: Default (stock)", snap.status)
    self.assertIn("Next drive: Alternate", snap.status)
    rows = self._rows(snap)
    self.assertTrue(rows["alternate"].selected)
    self.assertFalse(rows["alternate"].selectable)
    self.assertFalse(rows["default"].selected)
    self.assertTrue(rows["default"].selectable)
    self.assertIn("SELECTED", ui_text(snap))
    self.assertIn("Next drive: Alternate", ui_text(snap)[0])

    back = self.ctrl.select(STOCK_ID)
    self.assertTrue(back.ok, back.message)
    self.assertIsNone(self.store.raw(selection.KEY_SELECTION))
    self.assertNotIn("Next drive:", self.ctrl.snapshot.status)
    self.assertTrue(self.ctrl.snapshot.rows[0].selected)

  def test_onroad_select_does_not_write(self):
    ctrl = ModelSelectorController(lambda: False, self.store, self.root, self.cache)
    result = ctrl.select("alternate")
    self.assertFalse(result.ok)
    self.assertIsNone(self.store.raw(selection.KEY_SELECTION))
    self.assertIn("offroad", result.message)

  def test_is_offroad_exception_refuses_select(self):
    def boom():
      raise RuntimeError("no ui state")

    ctrl = ModelSelectorController(boom, self.store, self.root, self.cache)
    result = ctrl.select("alternate")
    self.assertFalse(result.ok)
    self.assertIsNone(self.store.raw(selection.KEY_SELECTION))
    self.assertTrue(all(not row.selectable for row in ctrl.snapshot.rows))
    self.assertIn("not changed", result.message)

  def test_notice_shows_fallback_text(self):
    self.assertTrue(self.ctrl.select("alternate").ok)
    chosen = selection.read_selection(self.store)[0]
    selection.record_fallback(self.store, chosen, "Alternate", "hash mismatch (file changed or corrupt)", "validate")
    snap = self.ctrl.refresh()
    found = alert.current_alert(self.store)
    self.assertIsNotNone(found)
    self.assertEqual(snap.notice, found["text"])
    self.assertIn("Alternate", snap.notice)
    self.assertIn("was not used", snap.notice)
    self.assertIn("Default (stock)", snap.notice)
    self.assertEqual(ui_text(snap)[1], snap.notice)
    rows = self._rows(snap)
    # blocked after a failed start: Default is in use, nothing shows as selected, and every valid row can be chosen again
    self.assertNotIn("Next drive:", snap.status)
    self.assertFalse(any(row.selected for row in snap.rows))
    self.assertTrue(rows["alternate"].selectable)
    self.assertTrue(rows["default"].selectable)
    self.assertTrue(rows["default"].active)
    self.assertTrue(self.ctrl.select("alternate").ok)  # retry clears the block and the notice
    self.assertEqual(self.ctrl.snapshot.notice, "")
    self.assertTrue(self._rows(self.ctrl.snapshot)["alternate"].selected)

  def test_second_refresh_reuses_validation_cache(self):
    self.ctrl.refresh()
    before = len(self.cache)
    self.assertGreater(before, 0)
    again = self.ctrl.refresh()
    self.assertEqual(again, self.ctrl.snapshot)
    self.assertGreaterEqual(len(self.cache), before)


class TestLayoutShowEvent(unittest.TestCase):
  def test_construct_and_show_event_without_rendering(self):
    pytest = __import__("pytest")
    pytest.importorskip("pyray")
    with tempfile.TemporaryDirectory() as tmp:
      ctrl = ModelSelectorController(lambda: True, MemStore(), tmp)
      layout = create_driving_model_layout(ctrl)
      layout.show_event()
      self.assertIsNotNone(layout.scroller)
      self.assertIsNotNone(layout._snapshot)
      self.assertTrue(layout._snapshot.only_default)
      self.assertGreaterEqual(len(layout.scroller._items), 3)
      shown = [item.title for item in layout.scroller._items]
      self.assertIn(ONLY_DEFAULT_TEXT, shown)
      labels = [getattr(item.action_item, "text", "") for item in layout.scroller._items]
      self.assertNotIn(SELECT_LABEL, labels)


if __name__ == "__main__":
  unittest.main()
