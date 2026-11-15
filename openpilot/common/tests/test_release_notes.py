"""What's-new notes for the offroad update splash.

Notes are the first section of RELEASES.md in a given build directory. The
updater stores the incoming build's notes in UpdaterNewReleaseNotes and the
running build's notes in UpdaterCurrentReleaseNotes.
"""
import tempfile
import unittest
from pathlib import Path

from openpilot.common.basedir import BASEDIR
from openpilot.common.release_notes import (
  latest_release_notes_html,
  latest_release_notes_markdown,
  release_notes_plain,
)


RUNNING = """What's new
=======================
* Notes that belong to the running build only

Older section
=======================
* Should not appear
"""

INCOMING = """What's new
=======================
* Three-bar pedal gauge showing brake, regen power, and acceleration
* Toggle for Pre-AP cars that have swapped in an iBooster
* Lead and nearby-lead boxes stay visible, including under alerts
* iBooster comments in the car signal database

Older section
=======================
* Should not appear
"""


def write_releases(folder: Path, text: str) -> None:
  folder.mkdir(parents=True, exist_ok=True)
  (folder / "RELEASES.md").write_text(text, encoding="utf-8")


class TestReleaseNotes(unittest.TestCase):
  def test_notes_come_from_the_incoming_build_not_the_running_one(self):
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      running = root / "running"
      incoming = root / "incoming"
      write_releases(running, RUNNING)
      write_releases(incoming, INCOMING)

      current_md = latest_release_notes_markdown(str(running))
      new_md = latest_release_notes_markdown(str(incoming))
      current_html = latest_release_notes_html(str(running)).decode("utf-8")
      new_html = latest_release_notes_html(str(incoming)).decode("utf-8")

      self.assertIn("running build only", current_md)
      self.assertIn("running build only", current_html)
      self.assertNotIn("running build only", new_md)
      self.assertNotIn("running build only", new_html)

      self.assertIn("pedal gauge", new_md)
      self.assertIn("pedal gauge", new_html)
      self.assertNotIn("pedal gauge", current_md)
      self.assertNotIn("Should not appear", new_md)
      self.assertNotIn("Should not appear", current_md)
      self.assertIn("<h1>What's new</h1>", new_html)
      self.assertIn("<li>Three-bar pedal gauge", new_html)

  def test_missing_and_empty_notes_are_empty(self):
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      missing = root / "missing"
      missing.mkdir()
      empty = root / "empty"
      write_releases(empty, "")
      blank = root / "blank"
      write_releases(blank, "\n\n\n")
      self.assertEqual(latest_release_notes_markdown(str(missing)), "")
      self.assertEqual(latest_release_notes_html(str(missing)), b"")
      self.assertEqual(latest_release_notes_markdown(str(empty)), "")
      self.assertEqual(latest_release_notes_html(str(empty)), b"")
      self.assertEqual(latest_release_notes_markdown(str(blank)), "")
      self.assertEqual(latest_release_notes_html(str(blank)), b"")

  def test_leading_blank_lines_do_not_drop_the_notes(self):
    with tempfile.TemporaryDirectory() as td:
      folder = Path(td) / "build"
      write_releases(folder, "\n\nWhat's new\n=======================\n* Visible notes\n")
      md = latest_release_notes_markdown(str(folder))
      self.assertIn("Visible notes", md)
      self.assertTrue(md.startswith("What's new"))

  def test_unreadable_file_is_empty(self):
    with tempfile.TemporaryDirectory() as td:
      folder = Path(td) / "bad"
      folder.mkdir()
      (folder / "RELEASES.md").write_bytes(b"\xff\xfe not text \xff")
      self.assertEqual(latest_release_notes_markdown(str(folder)), "")
      self.assertEqual(latest_release_notes_html(str(folder)), b"")

  def test_plain_text_strips_markup(self):
    html = latest_release_notes_html
    with tempfile.TemporaryDirectory() as td:
      folder = Path(td) / "build"
      write_releases(folder, INCOMING)
      plain = release_notes_plain(html(str(folder)))
      self.assertIn("What's new", plain)
      self.assertIn("Three-bar pedal gauge", plain)
      self.assertNotIn("<h1>", plain)
      self.assertNotIn("<li>", plain)

  def test_tree_notes_describe_this_update(self):
    md = latest_release_notes_markdown(BASEDIR)
    low = md.lower()
    self.assertIn("what's new", low)
    for phrase in (
      "pedal gauge",
      "brake",
      "regen",
      "acceleration",
      "pre-ap",
      "ibooster",
      "lead",
      "alerts",
    ):
      self.assertIn(phrase, low, msg=f"missing {phrase!r}")
    # First section is this fork's notes, not the older upstream block.
    self.assertNotIn("CUPRA", md)
    self.assertNotIn("blog.comma.ai", low)
    self.assertNotIn("880M", md)

  def test_updater_stores_incoming_notes_from_the_finalized_build(self):
    # Contract: the updater process writes new notes from the incoming tree
    # (FINALIZED) and current notes from the running tree (BASEDIR).
    src = (Path(__file__).resolve().parents[2] / "system/updated/updated.py").read_text(encoding="utf-8")
    self.assertIn("from openpilot.common.release_notes import latest_release_notes_html", src)
    self.assertIn('self.params.put("UpdaterCurrentReleaseNotes", parse_release_notes(BASEDIR)', src)
    self.assertIn('self.params.put("UpdaterNewReleaseNotes", parse_release_notes(FINALIZED)', src)
    self.assertIn("def parse_release_notes(basedir: str) -> bytes:", src)
    self.assertIn("return latest_release_notes_html(basedir)", src)


if __name__ == "__main__":
  unittest.main()
