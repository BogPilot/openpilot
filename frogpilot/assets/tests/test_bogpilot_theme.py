#!/usr/bin/env python3
"""BogPilot theme pack and one-time FrogPilot -> BogPilot migration."""
import shutil
import tempfile
import unittest
from pathlib import Path

from openpilot.frogpilot.common.frogpilot_variables import (
  BOGPILOT_THEME, FROGPILOT_THEME_DEFAULTS, migrate_theme_params,
)

BOGPILOT_THEME_PATH = Path(__file__).resolve().parents[1] / "bogpilot_theme"
BOGPILOT_THEME_COMPONENTS = ("colors", "distance_icons", "icons", "signals", "sounds")


class FakeParams:
  def __init__(self, values=None):
    self.values = dict(values or {})

  def get(self, key, encoding=None):
    value = self.values.get(key)
    if value is None:
      return None
    if encoding:
      return value if isinstance(value, str) else value.decode(encoding)
    return value.encode() if isinstance(value, str) else value

  def put(self, key, value):
    self.values[key] = value if isinstance(value, str) else value.decode()


def copy_bogpilot_theme(theme_save_path):
  theme_pack_destination = theme_save_path / "theme_packs" / BOGPILOT_THEME
  shutil.rmtree(theme_pack_destination, ignore_errors=True)
  for component in BOGPILOT_THEME_COMPONENTS:
    source_folder_path = BOGPILOT_THEME_PATH / component
    if source_folder_path.is_dir():
      shutil.copytree(source_folder_path, theme_pack_destination / component, dirs_exist_ok=True)

  steering_wheel_save_path = theme_save_path / "steering_wheels" / f"{BOGPILOT_THEME}.png"
  steering_wheel_save_path.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(BOGPILOT_THEME_PATH / "steering_wheel/wheel.png", steering_wheel_save_path)


class TestBogPilotTheme(unittest.TestCase):
  def test_bogpilot_theme_assets_exist(self):
    for component in BOGPILOT_THEME_COMPONENTS:
      self.assertTrue((BOGPILOT_THEME_PATH / component).is_dir(), component)
    self.assertTrue((BOGPILOT_THEME_PATH / "steering_wheel" / "wheel.png").is_file())
    self.assertTrue((BOGPILOT_THEME_PATH / "colors" / "colors.json").is_file())

  def test_copy_bogpilot_theme_installs_pack(self):
    with tempfile.TemporaryDirectory() as tmp:
      save_path = Path(tmp)
      copy_bogpilot_theme(save_path)

      pack = save_path / "theme_packs" / BOGPILOT_THEME
      for component in BOGPILOT_THEME_COMPONENTS:
        self.assertTrue((pack / component).is_dir(), component)
      self.assertTrue((save_path / "steering_wheels" / f"{BOGPILOT_THEME}.png").is_file())

  def test_migrate_theme_params_moves_frogpilot_defaults_once(self):
    with tempfile.TemporaryDirectory() as tmp:
      marker = Path(tmp) / ".bogpilot_theme_migrated"
      store = FakeParams(dict(FROGPILOT_THEME_DEFAULTS))

      self.assertTrue(migrate_theme_params(store, marker_path=marker))
      for key in FROGPILOT_THEME_DEFAULTS:
        self.assertEqual(store.values[key], BOGPILOT_THEME)
      self.assertTrue(marker.exists())

      # Going back to FrogPilot after the one-time migration must stick
      store.put("CustomColors", "frog")
      self.assertFalse(migrate_theme_params(store, marker_path=marker))
      self.assertEqual(store.values["CustomColors"], "frog")

  def test_migrate_theme_params_leaves_custom_theme_alone(self):
    with tempfile.TemporaryDirectory() as tmp:
      marker = Path(tmp) / ".bogpilot_theme_migrated"
      store = FakeParams({
        "CustomColors": "cyberpunk",
        "CustomDistanceIcons": "stock",
        "CustomIcons": "frog-animated",
        "CustomSignals": "frog",
        "CustomSounds": "frog",
        "WheelIcon": "frog",
      })
      migrate_theme_params(store, marker_path=marker)
      self.assertEqual(store.values["CustomColors"], "cyberpunk")
      self.assertEqual(store.values["CustomIcons"], BOGPILOT_THEME)

  def test_migrate_theme_params_normalizes_lowercase_bogpilot(self):
    with tempfile.TemporaryDirectory() as tmp:
      marker = Path(tmp) / ".bogpilot_theme_migrated"
      marker.write_text("1\n")
      store = FakeParams({"CustomColors": "bogpilot"})
      migrate_theme_params(store, marker_path=marker)
      self.assertEqual(store.values["CustomColors"], BOGPILOT_THEME)


if __name__ == "__main__":
  unittest.main()
