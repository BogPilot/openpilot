"""Override Sensitivity ships at 2 on every path, and a saved value is never rewritten.

The key is file-backed (/data/params_bogpilot/OverrideSensitivity), not a compiled Params key. No install, profile, section
Reset or full Reset path writes it: a device without the file reads the default (2), and a device that saved a level (3
included) keeps it. Paths covered: the car code and UI defaults, the one-time first-install profiles (AP1 profile, legacy
SLC defaults, legacy long defaults, legacy CE off), the Steering Tuning section Resets and car-type overrides, and both
full Reset tables plus the full Reset apply step.
"""
import os
import tempfile
import unittest
from pathlib import Path

from opendbc.car.tesla_ap1 import override as ov
from opendbc.car.tesla_ap1.preap import params as preap_params
from openpilot.selfdrive.ui.tests.test_bogpilot_menu_097 import MenuCase

KEY = "OverrideSensitivity"
LEGACY = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS")


class ProfileParams:
  """Minimal Params stand-in for the one-time profile functions (same shape as test_legacy_slc_defaults.FakeParams)."""

  def __init__(self, **vals):
    self.vals = dict(vals)
    self.puts = []

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value):
    self.vals[key] = value
    self.puts.append(key)

  def put_bool(self, key, value):
    self.put(key, value)

  def invalidate(self):
    pass


def _read_level(directory):
  old = preap_params._params_dir
  preap_params._params_dir = Path(directory)
  try:
    return ov.read_sensitivity_level()
  finally:
    preap_params._params_dir = old


class TestDefaultSources(unittest.TestCase):
  def test_every_default_source_is_two(self):
    from openpilot.selfdrive.ui.bogpilot import phase3_steering_tuning as st
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
    self.assertEqual(ov.SENSITIVITY_DEFAULT, 2)
    self.assertEqual(preap_params.DEFAULTS[preap_params.PreApParamKeys.OVERRIDE_SENSITIVITY], 2)
    self.assertEqual(st.SENSITIVITY_DEFAULT, 2)
    self.assertEqual(ov.DriverOverrideDetector().level, 2)
    for help_key in ("OverrideSensitivity", "OverrideSensitivityPreAp"):
      self.assertTrue(HELP[help_key].default.startswith("2 "), help_key)
    self.assertIn("default is 2", st.DESCRIPTIONS[KEY])

  def test_levels_keep_their_meaning(self):
    # the change is the default only: level 3 is still the unscaled numbers, and 1..5 keep their scale
    self.assertEqual(ov.SENSITIVITY_SCALE, {1: 1.25, 2: 1.125, 3: 1.0, 4: 0.875, 5: 0.75})
    self.assertEqual(ov.override_thresholds(3).as_tuple(), (2.0, 1.0, 30.0, 1.0, 30.0))
    self.assertEqual(ov.override_thresholds(2).as_tuple(), (2.25, 1.125, 31.875, 1.125, 31.875))

  def test_no_file_reads_two_and_a_saved_level_is_kept(self):
    with tempfile.TemporaryDirectory(prefix="oversens-") as d:
      self.assertEqual(_read_level(d), 2)
      for text, want in (("3", 3), ("1", 1), ("5", 5), ("2", 2), ("junk", 2)):
        (Path(d) / KEY).write_text(text)
        self.assertEqual(_read_level(d), want, text)


class TestNoProfileWritesIt(unittest.TestCase):
  def test_key_is_in_no_profile_or_registry_table(self):
    from openpilot.common import bogpilot_ap1_profile as P
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    from openpilot.common.bogpilot_shipping_defaults import PARAM_OVERRIDES
    self.assertNotIn(KEY, BOGPILOT_PARAMS)
    self.assertNotIn(KEY, PARAM_OVERRIDES)
    for name in ("AP1_PARAM_PROFILE", "AP1_FILE_TOGGLE_PROFILE", "LEGACY_SLC_PROFILE", "LEGACY_TESLA_CE_OFF"):
      self.assertNotIn(KEY, getattr(P, name), name)
    for car, table in P.LEGACY_TESLA_LONG_PROFILE.items():
      self.assertNotIn(KEY, table, car)

  def test_first_install_profiles_never_write_it(self):
    from openpilot.common import bogpilot_ap1_profile as P
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    table = {k: v[2] for k, v in BOGPILOT_PARAMS.items()}
    for car in LEGACY:
      for saved in (None, "3", "4"):
        with self.subTest(car=car, saved=saved), tempfile.TemporaryDirectory(prefix="oversens-") as d:
          if saved is not None:
            (Path(d) / KEY).write_text(saved)
          p = ProfileParams(CarModel=car)
          written = []
          written += P.apply_ap1_defaults_once(p, bogpilot_dir=Path(d), default_table=table, refresh=False)
          written += P.apply_legacy_slc_defaults_once(p, bogpilot_dir=Path(d), default_table=table, refresh=False)
          written += P.apply_legacy_tesla_long_defaults_once(p, bogpilot_dir=Path(d), default_table=table, refresh=False)
          written += P.apply_legacy_tesla_ce_off_once(p, bogpilot_dir=Path(d), default_table=table, refresh=False)
          self.assertNotIn(KEY, written)
          self.assertNotIn(KEY, p.puts)
          if saved is None:
            self.assertFalse((Path(d) / KEY).exists())
            self.assertEqual(_read_level(d), 2)
          else:
            self.assertEqual((Path(d) / KEY).read_text(), saved)
            self.assertEqual(_read_level(d), int(saved))


class TestNoResetWritesIt(unittest.TestCase):
  def test_full_reset_tables_leave_it_out(self):
    from openpilot.system.bogpilot import toggle_reset
    from openpilot.selfdrive.ui.bogpilot import phase3_system_utilities as util
    self.assertNotIn(KEY, toggle_reset.reset_defaults())
    self.assertNotIn(KEY, toggle_reset.shipping_defaults())
    self.assertNotIn(KEY, util.shipping_defaults())

  def test_full_reset_apply_keeps_the_saved_file(self):
    from openpilot.system.bogpilot.toggle_reset import REQUEST_KEY, reset_requested
    from openpilot.system.bogpilot.tests.test_toggle_reset import TypedParams
    for saved in (None, "3", "4"):
      with self.subTest(saved=saved), tempfile.TemporaryDirectory(prefix="oversens-") as d:
        if saved is not None:
          (Path(d) / KEY).write_text(saved)
        result = reset_requested(TypedParams({REQUEST_KEY: True}), d, backup=lambda: True)
        self.assertEqual(result.status, "completed", result.error)
        if saved is None:
          self.assertFalse((Path(d) / KEY).exists())
          self.assertEqual(_read_level(d), 2)
        else:
          self.assertEqual((Path(d) / KEY).read_text(), saved)


class TestSteeringSectionResets(MenuCase):
  def editor(self, model="TESLA_AP1_MODELS"):
    from opendbc.car.tesla_ap1.interface import CarInterface
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import TuningEditor
    return TuningEditor(CarInterface.get_non_essential_params(model), self.store, lambda: True)

  def test_ui_default_is_two_and_section_resets_leave_it_out(self):
    from openpilot.selfdrive.ui.bogpilot import phase3_steering_tuning as st
    from openpilot.selfdrive.ui.bogpilot.step_defaults import car_type_overrides
    for model in LEGACY:
      with self.subTest(model=model):
        self.store.put("CarModel", model)
        self.store.invalidate()
        e = self.editor(model)
        self.assertEqual(e.default(KEY), 2)
        self.assertEqual(e.value(KEY), 2)
        self.assertNotIn(KEY, e.section_defaults(st.NUMERIC_ORDER))
        self.assertNotIn(KEY, e.section_defaults(("PauseLateralSpeed", "PauseLateralOnSignal")))
        self.assertEqual(car_type_overrides(self.store, (KEY,)), {})


class TestRealParamsStore(unittest.TestCase):
  """The real ParamStore over the real Params library: the key is not compiled, so it is read from the file. Skips where the
  native params library cannot load (macOS dev hosts)."""

  def test_real_store_reads_the_file_and_defaults_to_two(self):
    try:
      from openpilot.common.params import Params
      real = Params()
    except Exception as exc:   # noqa: BLE001
      self.skipTest(f"real Params unavailable here: {type(exc).__name__}")
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import TuningEditor
    from types import SimpleNamespace
    with tempfile.TemporaryDirectory(prefix="oversens-") as d:
      old = os.environ.get("BOGPILOT_PARAMS_DIR")
      os.environ["BOGPILOT_PARAMS_DIR"] = d
      try:
        store = ParamStore(real)
        self.assertFalse(store.is_param_key(KEY))
        e = TuningEditor(SimpleNamespace(brand="tesla_ap1"), store, lambda: True)
        self.assertEqual(e.value(KEY), 2)
        self.assertEqual(_read_level(d), 2)
        self.assertTrue(e.write(KEY, 3))
        self.assertEqual((Path(d) / KEY).read_text().strip(), "3")
        self.assertEqual(_read_level(d), 3)
      finally:
        if old is None:
          os.environ.pop("BOGPILOT_PARAMS_DIR", None)
        else:
          os.environ["BOGPILOT_PARAMS_DIR"] = old


if __name__ == "__main__":
  unittest.main()
