"""The UI font atlas must carry the glyphs BogPilot text uses: the infinity sign (startup alert "Your m∞v") and the em dash
(unavailable values). Both are in the shipped Inter files, so the fix is the atlas codepoint set, not a new font."""
import unittest
from pathlib import Path

from openpilot.system.ui.lib import application

FONT_DIR = Path(str(application.FONT_DIR))
GLYPHS = {"\u221e": "INFINITY", "\u2014": "EM DASH"}


class TestFontAtlasGlyphs(unittest.TestCase):
  def test_atlas_codepoints_include_infinity_and_em_dash(self):
    for char, name in GLYPHS.items():
      self.assertIn(char, application.EXTRA_FONT_CHARS, name)

  def test_inter_files_have_the_glyphs(self):
    try:
      from fontTools.ttLib import TTFont
    except ImportError:
      self.skipTest("fontTools not installed")
    for weight in (application.FontWeight.NORMAL, application.FontWeight.MEDIUM, application.FontWeight.SEMI_BOLD,
                   application.FontWeight.BOLD):
      cmap = TTFont(str(FONT_DIR / str(weight))).getBestCmap()
      for char, name in GLYPHS.items():
        self.assertIn(ord(char), cmap, f"{weight} lacks {name}")

  def test_the_atlas_font_files_are_the_open_font_licensed_inter(self):
    self.assertTrue((FONT_DIR / "OFL-Inter.txt").is_file())
    self.assertIn("SIL Open Font License", (FONT_DIR / "OFL-Inter.txt").read_text())


if __name__ == "__main__":
  unittest.main()
