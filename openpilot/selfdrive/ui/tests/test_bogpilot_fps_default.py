"""FPS Display (FPSCounter) ships off everywhere the default is declared. Saved choices are not rewritten."""
import re
import unittest
from pathlib import Path

from openpilot.common import bogpilot_params as P

ROOT = Path(P.__file__).resolve().parents[1]


class TestFpsDefault(unittest.TestCase):
  def test_registered_default_is_off(self):
    self.assertEqual(P.BOGPILOT_PARAMS["FPSCounter"][2], "0")
    self.assertIn('{"FPSCounter", {PERSISTENT, BOOL, "0"}}', (ROOT / "common/params_keys_bogpilot.h").read_text())

  def test_generated_header_matches_the_table(self):
    self.assertEqual(P.render_header(), (ROOT / "common/params_keys_bogpilot.h").read_text())

  def test_defaults_table_and_feature_spec_say_off(self):
    defaults = (ROOT / "selfdrive/ui/bogpilot/bogpilot_defaults.py").read_text()
    self.assertIn("('FPSCounter', '0', 3, '0'),", defaults)
    specs = (ROOT / "selfdrive/ui/bogpilot/phase3_system_settings_feature_specs.py").read_text()
    self.assertRegex(specs, re.compile(r'"FPSCounter": \{\n\s+"declared_default": "0",'))

  def test_no_other_default_declaration_still_says_on(self):
    for rel in ("common/bogpilot_params.py", "common/params_keys_bogpilot.h", "selfdrive/ui/bogpilot/bogpilot_defaults.py"):
      for line in (ROOT / rel).read_text().splitlines():
        if "FPSCounter" in line:
          self.assertNotRegex(line, r'["\']1["\']', f"{rel}: {line}")


if __name__ == "__main__":
  unittest.main()
