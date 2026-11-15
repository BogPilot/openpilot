"""Update splash shows what's-new notes from the incoming build."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpilot.common.release_notes import latest_release_notes_html


UI_ALERTS = Path(__file__).resolve().parents[1] / "widgets/offroad_alerts.py"
MICI_ALERTS = Path(__file__).resolve().parents[1] / "mici/layouts/offroad_alerts.py"
SOFTWARE = Path(__file__).resolve().parents[1] / "layouts/settings/software.py"
HOME = Path(__file__).resolve().parents[1] / "layouts/home.py"

SAMPLE = """What's new
=======================
* Three-bar pedal gauge showing brake, regen power, and acceleration
* Toggle for Pre-AP cars that have swapped in an iBooster
"""


class TestUpdateSplashContract(unittest.TestCase):
  def test_offroad_splash_reads_incoming_notes_and_has_a_fallback(self):
    src = UI_ALERTS.read_text(encoding="utf-8")
    self.assertIn("class UpdateAlert", src)
    self.assertIn('self.params.get("UpdaterNewReleaseNotes")', src)
    self.assertIn("No release notes available.", src)
    self.assertIn("has_reboot_btn=True", src)
    # The splash must not read the running build's notes for the incoming update.
    self.assertNotIn("UpdaterCurrentReleaseNotes", src)

  def test_software_install_row_shows_incoming_notes(self):
    src = SOFTWARE.read_text(encoding="utf-8")
    self.assertIn('ui_state.params.get("UpdaterNewReleaseNotes")', src)
    self.assertIn("self._install_btn.set_description(new_release_notes)", src)

  def test_home_layout_opens_the_update_splash(self):
    src = HOME.read_text(encoding="utf-8")
    self.assertIn("UpdateAlert", src)
    self.assertIn("HomeLayoutState.UPDATE", src)

  def test_compact_update_alert_uses_incoming_notes_not_an_external_blog(self):
    src = MICI_ALERTS.read_text(encoding="utf-8")
    self.assertIn("UpdaterNewReleaseNotes", src)
    self.assertIn("release_notes_plain", src)
    self.assertNotIn("blog.comma.ai", src)


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestUpdateSplashRefresh(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    try:
      with mock.patch("openpilot.common.hardware.comma.hardware.get_device_type", lambda: "tizi"):
        from openpilot.selfdrive.ui.widgets import offroad_alerts as oa
        from openpilot.system.ui.lib.application import gui_app
        import pyray as rl
    except Exception as e:
      raise unittest.SkipTest(f"raylib widgets unavailable: {type(e).__name__}") from e
    cls.oa = oa
    cls.gui_app = gui_app
    cls.rl = rl

  def _alert(self, params):
    with mock.patch.object(self.gui_app, "font", lambda *a: self.rl.Font()):
      alert = self.oa.UpdateAlert()
    alert.params = params
    return alert

  def test_refresh_uses_incoming_notes_when_an_update_is_available(self):
    html = latest_release_notes_html
    with tempfile.TemporaryDirectory() as td:
      incoming = Path(td) / "incoming"
      incoming.mkdir()
      (incoming / "RELEASES.md").write_text(SAMPLE, encoding="utf-8")
      notes = html(str(incoming))

      class P:
        def __init__(self, data):
          self.data = data
        def get_bool(self, key):
          return bool(self.data.get(key))
        def get(self, key):
          return self.data.get(key)

      alert = self._alert(P({"UpdateAvailable": True, "UpdaterNewReleaseNotes": notes}))
      self.assertTrue(alert.refresh())
      self.assertIn("pedal gauge", alert.release_notes)
      self.assertIn("iBooster", alert.release_notes)

      empty = self._alert(P({"UpdateAvailable": True, "UpdaterNewReleaseNotes": b""}))
      self.assertTrue(empty.refresh())
      self.assertEqual(empty.release_notes, "")

      hidden = self._alert(P({"UpdateAvailable": False, "UpdaterNewReleaseNotes": notes}))
      self.assertFalse(hidden.refresh())


# Notes area of the comma 3X update splash at 2160x1080: UpdateAlert's scroll panel is 640 px high and the
# notes are inset 30 px on each side, so 580 px x 1920 px show without scrolling.
SPLASH_NOTES_W, SPLASH_NOTES_H = 1920, 580


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestUpdateSplashFits(unittest.TestCase):
  """Measured with the real fonts: the stored notes fit the 3X splash without scrolling."""
  @classmethod
  def setUpClass(cls):
    with mock.patch("openpilot.common.hardware.comma.hardware.get_device_type", lambda: "tizi"):
      import pyray as rl
      from openpilot.system.ui.lib.application import gui_app
      from openpilot.system.ui.widgets.html_render import HtmlRenderer
      if not rl.is_window_ready():
        gui_app._width, gui_app._height = 2160, 1080
        gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
        gui_app.init_window("update splash fit")
    cls.HtmlRenderer = HtmlRenderer

  def height(self, html: bytes) -> float:
    r = self.HtmlRenderer(text="")
    r.parse_html_content(html.decode("utf-8"))
    return r.get_total_height(SPLASH_NOTES_W)

  def test_tree_notes_fit_without_scrolling(self):
    from openpilot.common.basedir import BASEDIR
    self.assertLessEqual(self.height(latest_release_notes_html(BASEDIR)), SPLASH_NOTES_H)

  def test_update_alert_scroll_range_covers_every_notes_line(self):
    # UpdateAlert renders the notes into its content height minus the 60 px inset, so that height must hold every
    # laid-out line, also for notes that need scrolling.
    import pyray as rl
    from openpilot.common.basedir import BASEDIR
    from openpilot.selfdrive.ui.widgets import offroad_alerts as oa
    item = "AP1: a temporary power steering fault no longer locks out steering for the rest of the drive, " * 3
    cases = {"long": ("<h1>What's new</h1>\n<ul>\n" + "".join(f"<li>{i} {item}</li>\n" for i in range(12)) + "</ul>").encode(),
             "cut": latest_release_notes_html(BASEDIR)}

    class P:
      def __init__(self, notes):
        self.notes = notes
      def get_bool(self, key):
        return key == "UpdateAvailable"
      def get(self, key):
        return self.notes if key == "UpdaterNewReleaseNotes" else None

    for name, html in cases.items():
      alert = oa.UpdateAlert()
      alert.params = P(html)
      self.assertTrue(alert.refresh())
      alert.scroll_panel_rect = rl.Rectangle(0, 0, SPLASH_NOTES_W + 60, SPLASH_NOTES_H + 60)
      self.assertGreaterEqual(alert.get_content_height() - 60, self.height(html), msg=name)

  def test_long_notes_are_cut_to_fit(self):
    item = ("AP1: a temporary power steering fault (code 4) no longer locks out steering for the rest of the drive. "
            "Steering resumes only when the car reports power steering available again and allows it")
    long_notes = "What's new\n=======================\n" + "\n".join(f"* {i} {item}" for i in range(15))
    short_notes = "What's new\n=======================\n" + "\n".join(f"* Item {i}" for i in range(6))
    with tempfile.TemporaryDirectory() as td:
      for name, text in (("long", long_notes), ("short", short_notes)):
        folder = Path(td) / name
        folder.mkdir()
        (folder / "RELEASES.md").write_text(text, encoding="utf-8")
        self.assertLessEqual(self.height(latest_release_notes_html(str(folder))), SPLASH_NOTES_H, msg=name)


if __name__ == "__main__":
  unittest.main()
