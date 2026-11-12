"""Steering Tuning > Override Sensitivity: legacy-Tesla-only visibility, offroad-only edit, validation, reset, and that the saved file is
exactly what the car code reads. Pure tests (no window) plus one layout placement check when the UI toolkit is available."""
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

from openpilot.selfdrive.ui.tests.test_bogpilot_menu_097 import MenuCase, NativeCase

HEADLESS = unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")

KEY = "OverrideSensitivity"


class TestOverrideSensitivityRow(MenuCase):
  def editor(self, brand="tesla_ap1", offroad=True):
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import TuningEditor
    cp = None if brand is None else SimpleNamespace(brand=brand)
    return TuningEditor(cp, self.store, lambda: offroad)

  def file(self):
    return Path(os.environ["BOGPILOT_PARAMS_DIR"]) / KEY

  def test_row_is_registered_and_not_a_compiled_param(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import ACTIVE_CONTROLS, DESCRIPTIONS
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    self.assertIn(KEY, ACTIVE_CONTROLS)
    self.assertIn(KEY, DESCRIPTIONS)
    self.assertNotIn(KEY, BOGPILOT_PARAMS, "file-backed: the car code cannot read Params and a new compiled key is not allowed")
    header = Path(__file__).resolve().parents[3] / "common" / "params_keys_bogpilot.h"
    if header.exists():
      self.assertNotIn(KEY, header.read_text())

  def test_visible_only_for_a_legacy_tesla(self):
    self.assertTrue(self.editor("tesla_ap1").visible(KEY))
    for brand in ("toyota", "honda", "tesla", "mock", None):
      self.assertFalse(self.editor(brand).visible(KEY), brand)

  def test_visible_without_any_parent_toggle(self):
    self.store.put_bool("QOLLateral", False)
    self.store.put_bool("AdvancedLateralTune", False)
    self.store.invalidate()
    self.assertTrue(self.editor().visible(KEY))

  def test_default_is_three_and_reads_back(self):
    e = self.editor()
    self.assertEqual(e.value(KEY), 3)
    self.assertEqual(e.shown(KEY), "3 of 5 (default)")
    self.assertTrue(e.write(KEY, 5))
    self.assertEqual(e.value(KEY), 5)
    self.assertEqual(e.shown(KEY), "5 of 5")

  def test_only_whole_levels_one_to_five_can_be_written(self):
    e = self.editor()
    for bad in (0, 6, -1, 2.5, 3.0, "3", None, True, False, float("nan"), float("inf"), [3]):
      self.assertFalse(e.write(KEY, bad), repr(bad))
    self.assertFalse(self.file().exists())
    for good in (1, 2, 3, 4, 5):
      self.assertTrue(e.write(KEY, good))
      self.assertEqual(e.value(KEY), good)

  def test_offroad_only(self):
    e = self.editor(offroad=False)
    self.assertFalse(e.can_edit(KEY))
    self.assertFalse(e.write(KEY, 4))
    self.assertFalse(e.step(KEY, 1))
    self.assertFalse(e.reset(KEY))
    self.assertFalse(self.file().exists())

  def test_hidden_for_other_cars_cannot_be_written(self):
    e = self.editor("toyota")
    self.assertFalse(e.write(KEY, 4))
    self.assertFalse(self.file().exists())

  def test_steps_stop_at_the_ends(self):
    e = self.editor()
    self.assertTrue(e.step(KEY, 1))
    self.assertEqual(e.value(KEY), 4)
    self.assertTrue(e.step(KEY, 1))
    self.assertFalse(e.step(KEY, 1))
    self.assertEqual(e.value(KEY), 5)
    for _ in range(4):
      self.assertTrue(e.step(KEY, -1))
    self.assertFalse(e.step(KEY, -1))
    self.assertEqual(e.value(KEY), 1)

  def test_reset_returns_to_the_default_and_removes_the_file(self):
    e = self.editor()
    e.write(KEY, 1)
    self.assertTrue(self.file().exists())
    self.assertTrue(e.reset(KEY))
    self.assertFalse(self.file().exists())
    self.assertEqual(e.value(KEY), 3)

  def test_a_bad_stored_value_shows_and_acts_as_the_default(self):
    e = self.editor()
    for text in ("", "0", "9", "abc", "2.5", "-1"):
      self.file().write_text(text)
      self.store.invalidate()
      self.assertEqual(e.value(KEY), 3, text)
      self.assertEqual(e.shown(KEY), "3 of 5 (default)", text)

  def test_the_saved_file_is_what_the_car_code_reads(self):
    from opendbc.car.tesla_ap1 import override as ov
    from opendbc.car.tesla_ap1.preap import params
    e = self.editor()
    old = params._params_dir
    params._params_dir = Path(os.environ["BOGPILOT_PARAMS_DIR"])
    try:
      for level in (1, 2, 3, 4, 5):
        self.assertTrue(e.write(KEY, level))
        self.assertEqual(ov.read_sensitivity_level(), level)
      e.reset(KEY)
      self.assertEqual(ov.read_sensitivity_level(), 3)
    finally:
      params._params_dir = old

  def test_the_ui_and_the_car_share_one_validator(self):
    from opendbc.car.tesla_ap1 import override as ov
    from openpilot.selfdrive.ui.bogpilot import phase3_steering_tuning as st
    self.assertIs(st.sanitize_level, ov.sanitize_level)
    self.assertEqual(st.SENSITIVITY_LEVELS, (1, 2, 3, 4, 5))
    self.assertEqual(st.SENSITIVITY_DEFAULT, 3)

  def test_help_entry_is_plain_and_ascii(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
    entry = HELP[KEY]
    text = " ".join((entry.title, entry.what, entry.when, entry.note, entry.default, entry.range))
    self.assertTrue(text.isascii())
    self.assertNotIn("<", text)
    self.assertNotIn(">", text)
    self.assertEqual(entry.range, "1 to 5")
    self.assertTrue(entry.default.startswith("3"))
    for word in ("Nm", "deg", "panda", "EPAS"):
      self.assertNotIn(word, text, "plain help text")


@HEADLESS
class TestLayoutRow(NativeCase):
  """The rows sit after Pause Steering Below (after its Turn Signal Only child) and show for a legacy Tesla only."""

  def titles(self, brand):
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import make_layout
    from opendbc.car import structs
    cp = None
    if brand is not None:
      cp = structs.CarParams()
      cp.brand = brand
    layout = make_layout(cp, self.store, lambda: True)
    return [getattr(i, "title", "") for i in layout.scroller._items if i.is_visible]

  def test_rows_are_in_the_layout_after_pause_steering_below(self):
    titles = self.titles("tesla_ap1")
    self.assertIn("Pause Steering Below", titles)
    self.assertIn("Override Sensitivity", titles)
    # Option B: no per-row RESET; Override Sensitivity is not in a section Reset either.
    self.assertNotIn("Reset Override Sensitivity", titles)
    self.assertFalse(any(t.startswith("Reset ") and t != "Reset section to defaults" for t in titles))
    self.assertGreater(titles.index("Override Sensitivity"), titles.index("Pause Steering Below"))
    self.assertNotIn("Override Sensitivity", self.titles("toyota"))
    self.assertNotIn("Override Sensitivity", self.titles(None))


if __name__ == "__main__":
  unittest.main()
