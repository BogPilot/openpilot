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


if __name__ == "__main__":
  unittest.main()
