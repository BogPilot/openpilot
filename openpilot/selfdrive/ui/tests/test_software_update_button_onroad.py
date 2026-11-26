"""Software panel CHECK / DOWNLOAD: greyed out onroad (Park included), enabled offroad.

updated is only_offroad (system/manager/process_config.py), so onroad the button's SIGUSR1 / SIGHUP would reach no
process. The row keeps the 0.9.7 layout (shown offroad or onroad in Park) but is disabled onroad with
"available when offroad", and a press onroad sends nothing.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

UI = Path(__file__).resolve().parents[1]
SOFTWARE = UI / "layouts/settings/software.py"
PROCESS_CONFIG = UI.parents[1] / "system/manager/process_config.py"


class TestSource(unittest.TestCase):
  def test_updated_is_offroad_only(self):
    src = PROCESS_CONFIG.read_text()
    self.assertIn('PythonProcess("updated", "openpilot.system.updated.updated", only_offroad', src)

  def test_button_greyed_onroad_in_source(self):
    src = SOFTWARE.read_text()
    self.assertIn('tr("available when offroad")', src)
    self.assertIn("if started:", src)
    self.assertIn("self._download_btn.set_visible(can_download)", src)   # 0.9.7 layout kept
    self.assertIn("self._install_btn.set_visible(ui_state.is_offroad() and update_available)", src)


def _native_missing() -> str | None:
  try:
    from openpilot.common.params import Params
    Params()
    from openpilot.selfdrive.ui.ui_state import ui_state  # noqa: F401
  except (ImportError, OSError) as e:
    return f"needs built msgq / params ({type(e).__name__})"
  return None


class FakeParams:
  def __init__(self, **vals):
    self.vals = vals

  def get(self, key, *a, **k):
    return self.vals.get(key)

  def get_bool(self, key, *a, **k):
    return bool(self.vals.get(key, False))

  def put(self, *a, **k):
    pass

  def put_bool(self, *a, **k):
    pass


class TestSoftwareButton(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.tmp = tempfile.mkdtemp(prefix="swbtn-")
    os.environ["BOGPILOT_PARAMS_DIR"] = os.path.join(cls.tmp, "bp")
    os.environ.setdefault("PARAMS_ROOT", os.path.join(cls.tmp, "params"))
    os.makedirs(os.environ["BOGPILOT_PARAMS_DIR"], exist_ok=True)
    os.makedirs(os.environ["PARAMS_ROOT"], exist_ok=True)
    if not os.path.exists("/sys/firmware/devicetree/base/model"):
      import openpilot.common.hardware.comma.hardware as comma_hw
      comma_hw.get_device_type = lambda: "pc"

  def setUp(self):
    if why := _native_missing():
      self.skipTest(why)
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.selfdrive.ui.bogpilot import onroad_policy
    from openpilot.selfdrive.ui.layouts.settings import software
    for name, value in (("font", lambda *a, **k: rl.Font()), ("texture", lambda *a, **k: rl.Texture())):
      p = mock.patch.object(gui_app, name, value)
      p.start()
      self.addCleanup(p.stop)
    self.params = FakeParams(UpdaterState="idle", UpdateFailedCount=0)
    p = mock.patch.object(ui_state, "params", self.params)
    p.start()
    self.addCleanup(p.stop)
    self.started, self.parked = False, True
    onroad_policy.set_state(onroad_policy.DriveState(started=lambda: self.started, parked=lambda: self.parked))
    self.addCleanup(onroad_policy.set_state, None)
    p = mock.patch.object(ui_state, "is_offroad", lambda: not self.started)
    p.start()
    self.addCleanup(p.stop)
    self.runs = []
    p = mock.patch.object(software.subprocess, "run", lambda cmd, **k: self.runs.append(cmd))
    p.start()
    self.addCleanup(p.stop)
    self.tr = software.tr
    self.sw = software.SoftwareLayout()
    self.btn = self.sw._download_btn

  def _set(self, started, parked=True):
    self.started, self.parked = started, parked
    self.sw._update_state()

  def test_offroad_enabled_check(self):
    self._set(False)
    self.assertTrue(self.btn.is_visible)
    self.assertTrue(self.btn.action_item.enabled)
    self.assertEqual(self.btn.action_item.text, self.tr("CHECK"))
    self.assertNotEqual(self.btn.action_item.value, self.tr("available when offroad"))

  def test_onroad_park_visible_but_greyed(self):
    self._set(True, parked=True)
    self.assertTrue(self.btn.is_visible)
    self.assertFalse(self.btn.action_item.enabled)
    self.assertEqual(self.btn.action_item.value, self.tr("available when offroad"))

  def test_onroad_driving_hidden_and_greyed(self):
    self._set(True, parked=False)
    self.assertFalse(self.btn.is_visible)          # 0.9.7 layout: the row only shows offroad or in Park
    self.assertFalse(self.btn.action_item.enabled)

  def test_onroad_greyed_even_with_fetch_available_or_failures(self):
    for vals in ({"UpdaterFetchAvailable": True}, {"UpdateFailedCount": 2}, {"UpdaterState": "checking..."}):
      self.params.vals.update(vals)
      self._set(True, parked=True)
      self.assertFalse(self.btn.action_item.enabled, vals)
      self.assertEqual(self.btn.action_item.value, self.tr("available when offroad"), vals)
      self.params.vals = {"UpdaterState": "idle", "UpdateFailedCount": 0}

  def test_press_onroad_sends_nothing(self):
    self._set(True, parked=True)
    self.sw._on_download_update()
    self.assertEqual(self.runs, [])
    self.assertFalse(self.sw._waiting_for_updater)

  def test_press_offroad_signals_updated(self):
    self._set(False)
    self.sw._on_download_update()
    self.assertEqual(len(self.runs), 1)
    self.assertIn("-SIGUSR1", self.runs[0])
    self.assertIn("openpilot.system.updated.updated", self.runs[0])

  def test_reenabled_after_going_offroad(self):
    self._set(True, parked=True)
    self.assertFalse(self.btn.action_item.enabled)
    self._set(False)
    self.assertTrue(self.btn.action_item.enabled)
    self.assertNotEqual(self.btn.action_item.value, self.tr("available when offroad"))

  def test_offroad_fetch_available_shows_download(self):
    self.params.vals["UpdaterFetchAvailable"] = True
    self._set(False)
    self.assertTrue(self.btn.action_item.enabled)
    self.assertEqual(self.btn.action_item.text, self.tr("DOWNLOAD"))


if __name__ == "__main__":
  unittest.main()
