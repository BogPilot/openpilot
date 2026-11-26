"""comma 4 Software panel "check for update": greyed out onroad (Park included), enabled offroad.

Same rule as the comma 3X Software panel: updated is only_offroad (system/manager/process_config.py), so onroad the
SIGUSR1 / SIGHUP would reach no process. Onroad the button is disabled with "available when offroad" and sends nothing.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

UI = Path(__file__).resolve().parents[1]
MICI_SOFTWARE = UI / "mici/layouts/settings/software.py"


class TestSource(unittest.TestCase):
  def test_greyed_onroad_in_source(self):
    src = MICI_SOFTWARE.read_text()
    self.assertIn('OFFROAD_ONLY_TEXT = "available when offroad"', src)
    self.assertIn("if started or not onroad_policy.downloads_allowed(", src)
    self.assertIn('self.set_visible(lambda: ui_state.is_offroad() and ui_state.params.get_bool("UpdateAvailable"))', src)


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


class _Thread:
  """Runs the target at start() so the pkill call is recorded synchronously."""
  def __init__(self, target=None, daemon=None):
    self.target = target

  def start(self):
    self.target()


class TestComma4CheckUpdateButton(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.tmp = tempfile.mkdtemp(prefix="c4swbtn-")
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
    from openpilot.selfdrive.ui.mici.layouts.settings import software
    for name, value in (("font", lambda *a, **k: rl.Font()), ("texture", lambda *a, **k: rl.Texture())):
      p = mock.patch.object(gui_app, name, value)
      p.start()
      self.addCleanup(p.stop)
    self.params = FakeParams(UpdaterState="idle", UpdateFailedCount=0)
    p = mock.patch.object(ui_state, "params", self.params)
    p.start()
    self.addCleanup(p.stop)
    self.started, self.parked = False, True
    onroad_policy.set_state(onroad_policy.DriveState(started=lambda: self.started, parked=lambda: self.parked,
                                                     engaged=lambda: False))
    self.addCleanup(onroad_policy.set_state, None)
    self.runs = []
    p = mock.patch.object(software.subprocess, "run", lambda cmd, **k: self.runs.append(cmd))
    p.start()
    self.addCleanup(p.stop)
    p = mock.patch.object(software.threading, "Thread", _Thread)
    p.start()
    self.addCleanup(p.stop)
    self.sw = software
    self.btn = software.CheckUpdateButton()

  def _set(self, started, parked=True):
    self.started, self.parked = started, parked
    self.btn._update_state()

  def test_offroad_enabled(self):
    self._set(False)
    self.assertTrue(self.btn.enabled)
    self.assertNotEqual(self.btn.get_value(), self.sw.OFFROAD_ONLY_TEXT)

  def test_onroad_park_greyed_with_text(self):
    self._set(True, parked=True)
    self.assertFalse(self.btn.enabled)
    self.assertEqual(self.btn.get_value(), "available when offroad")

  def test_onroad_driving_greyed(self):
    self._set(True, parked=False)
    self.assertFalse(self.btn.enabled)
    self.assertEqual(self.btn.get_value(), "available when offroad")

  def test_onroad_greyed_even_with_fetch_available_or_failures(self):
    for vals in ({"UpdaterFetchAvailable": True}, {"UpdateFailedCount": 2}):
      self.params.vals.update(vals)
      self._set(True, parked=True)
      self.assertFalse(self.btn.enabled, vals)
      self.assertEqual(self.btn.get_value(), "available when offroad", vals)
      self.params.vals = {"UpdaterState": "idle", "UpdateFailedCount": 0}

  def test_signal_onroad_sends_nothing(self):
    self._set(True, parked=True)
    self.btn.check_for_update()
    self.btn._signal_updater(self.btn.DOWNLOAD_UPDATE)
    self.assertEqual(self.runs, [])
    self.assertEqual(self.btn._state, self.sw.UpdaterState.IDLE)

  def test_signal_offroad_reaches_updated(self):
    self._set(False)
    self.btn.check_for_update()
    self.assertEqual(len(self.runs), 1)
    self.assertIn("-SIGUSR1", self.runs[0])
    self.assertIn("openpilot.system.updated.updated", self.runs[0])

  def test_reenabled_and_text_cleared_after_going_offroad(self):
    self._set(True, parked=True)
    self._set(False)
    self.assertTrue(self.btn.enabled)
    self.assertNotEqual(self.btn.get_value(), self.sw.OFFROAD_ONLY_TEXT)

  def test_offroad_fetch_available_shows_download(self):
    self.params.vals["UpdaterFetchAvailable"] = True
    self._set(False)
    self.assertTrue(self.btn.enabled)
    self.assertEqual(self.btn.get_value(), "download update")

  def test_going_onroad_while_waiting_drops_the_wait(self):
    self._set(False)
    self.btn.check_for_update()
    self.assertEqual(self.btn._state, self.sw.UpdaterState.WAITING_FOR_UPDATER)
    self._set(True, parked=True)
    self.assertEqual(self.btn._state, self.sw.UpdaterState.IDLE)
    self.assertFalse(self.btn.enabled)


if __name__ == "__main__":
  unittest.main()
