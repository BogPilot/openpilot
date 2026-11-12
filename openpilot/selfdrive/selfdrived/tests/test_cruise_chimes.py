import unittest
from pathlib import Path
from types import SimpleNamespace

from openpilot.selfdrive.selfdrived.cruise_chimes import (
  BRAND, PARAM_KEY, CruiseChimeRuntime, chimes_allowed, long_only_edge, tesla_ap1_visible)


class TestCruiseChimes(unittest.TestCase):
  def test_param_key_and_default(self):
    self.assertEqual(PARAM_KEY, "CruiseEngageDisengageChimes")
    self.assertTrue(chimes_allowed("toyota"))
    self.assertTrue(chimes_allowed("tesla"))
    self.assertTrue(chimes_allowed(None))
    self.assertTrue(chimes_allowed(BRAND))
    self.assertTrue(chimes_allowed(BRAND, enabled=True))
    self.assertFalse(chimes_allowed(BRAND, enabled=False))
    # other brands ignore the tesla toggle
    self.assertTrue(chimes_allowed("toyota", enabled=False))

  def test_reader_used_only_for_tesla_ap1(self):
    calls = []

    def reader():
      calls.append(1)
      return False

    self.assertFalse(chimes_allowed(BRAND, reader=reader))
    self.assertTrue(chimes_allowed("honda", reader=reader))
    self.assertEqual(len(calls), 1)

  def test_long_only_edges(self):
    # rise: long drops, steering stays
    self.assertEqual(long_only_edge(False, True, True, BRAND, enabled=True), "disengage")
    # fall: long returns
    self.assertEqual(long_only_edge(True, False, True, BRAND, enabled=True), "engage")
    # steady
    self.assertIsNone(long_only_edge(False, False, True, BRAND, enabled=True))
    self.assertIsNone(long_only_edge(True, True, True, BRAND, enabled=True))

  def test_long_only_skipped_when_toggle_off_or_not_tesla(self):
    self.assertIsNone(long_only_edge(False, True, True, BRAND, enabled=False))
    self.assertIsNone(long_only_edge(False, True, True, "toyota", enabled=True))
    self.assertIsNone(long_only_edge(False, True, True, None, enabled=True))

  def test_long_only_skipped_when_openpilot_drops_or_stock_chimes(self):
    # cancel: lat_only falls and cruise is no longer enabled -> stock disengage will sound
    self.assertIsNone(long_only_edge(True, False, False, BRAND, enabled=True))
    self.assertIsNone(long_only_edge(False, True, False, BRAND, enabled=True))
    self.assertIsNone(long_only_edge(False, True, True, BRAND, enabled=True, stock_chime=True))

  def test_runtime_tracks_edges_and_reset(self):
    rt = CruiseChimeRuntime(reader=lambda: True)
    cp = SimpleNamespace(brand=BRAND)

    def cs(enabled, lat_only):
      return SimpleNamespace(cruiseState=SimpleNamespace(enabled=enabled),
                             bogpilot=SimpleNamespace(preapLatOnly=lat_only))

    self.assertIsNone(rt.update(cp, cs(True, False)))
    self.assertEqual(rt.update(cp, cs(True, True)), "disengage")
    self.assertIsNone(rt.update(cp, cs(True, True)))
    self.assertEqual(rt.update(cp, cs(True, False)), "engage")
    # cancel frame: enabled falls with lat_only
    self.assertIsNone(rt.update(cp, cs(False, False), stock_chime=True))
    rt.reset()
    self.assertIsNone(rt.update(cp, cs(True, False)))

  def test_menu_visible_only_for_tesla_ap1(self):
    self.assertFalse(tesla_ap1_visible(None))
    self.assertFalse(tesla_ap1_visible(SimpleNamespace(brand="toyota")))
    self.assertFalse(tesla_ap1_visible(SimpleNamespace(brand="tesla")))
    self.assertTrue(tesla_ap1_visible(SimpleNamespace(brand=BRAND)))


class TestEngagementCallback(unittest.TestCase):
  def _alert(self, brand, kind="engage"):
    from openpilot.selfdrive.selfdrived.events import tesla_engagement_alert, AudibleAlert
    audible = AudibleAlert.engage if kind == "engage" else AudibleAlert.disengage
    cb = tesla_engagement_alert(audible)
    return cb(type("CP", (), {"brand": brand})(), None, None, False, 0, None)

  def test_non_tesla_always_plays(self):
    from openpilot.selfdrive.selfdrived.events import AudibleAlert
    from unittest.mock import patch
    # Even a saved OFF is ignored for other brands (chimes_allowed short-circuits).
    with patch("openpilot.selfdrive.selfdrived.cruise_chimes._read_enabled", return_value=False):
      a = self._alert("toyota", "engage")
      d = self._alert("honda", "disengage")
    self.assertEqual(a.audible_alert, AudibleAlert.engage)
    self.assertEqual(d.audible_alert, AudibleAlert.disengage)

  def test_tesla_ap1_follows_the_toggle(self):
    from openpilot.selfdrive.selfdrived.events import AudibleAlert
    from unittest.mock import patch
    with patch("openpilot.selfdrive.selfdrived.cruise_chimes._read_enabled", return_value=True):
      on = self._alert("tesla_ap1", "engage")
    with patch("openpilot.selfdrive.selfdrived.cruise_chimes._read_enabled", return_value=False):
      off = self._alert("tesla_ap1", "engage")
      off_d = self._alert("tesla_ap1", "disengage")
    self.assertEqual(on.audible_alert, AudibleAlert.engage)
    self.assertEqual(off.audible_alert, AudibleAlert.none)
    self.assertEqual(off_d.audible_alert, AudibleAlert.none)

  def test_events_table_uses_the_callback(self):
    from openpilot.selfdrive.selfdrived.events import EVENTS, EventName, ET
    for ev, et in ((EventName.pcmEnable, ET.ENABLE), (EventName.buttonEnable, ET.ENABLE),
                   (EventName.pcmDisable, ET.USER_DISABLE), (EventName.buttonCancel, ET.USER_DISABLE),
                   (EventName.parkBrake, ET.USER_DISABLE), (EventName.pedalPressed, ET.USER_DISABLE),
                   (EventName.steerDisengage, ET.USER_DISABLE), (EventName.wrongCarMode, ET.USER_DISABLE),
                   (EventName.wrongCruiseMode, ET.USER_DISABLE)):
      self.assertTrue(callable(EVENTS[ev][et]), ev)


class TestFreshInstallAudible(unittest.TestCase):
  """A fresh tesla_ap1 install must play engage/disengage chimes at a nonzero volume.

  0.9.7 muted EngageVolume/DisengageVolume to 0 in the AP1 profile. This tree
  dropped that mute: the profile never writes volume keys, and shipping
  defaults are controller off / 101 (auto). The toggle defaults to on.
  """

  AMBIENT = 0.3  # representative cabin level; soundd also floors ambient at MIN_VOLUME 0.1

  def setUp(self):
    import os
    import tempfile
    from unittest.mock import patch
    import openpilot.selfdrive.selfdrived.cruise_chimes as cc
    self._tmp = tempfile.TemporaryDirectory()
    self.params_dir = Path(self._tmp.name) / "params_bogpilot"
    self.markers = Path(self._tmp.name) / "markers"
    self.params_dir.mkdir()
    self.markers.mkdir()
    self._env = patch.dict(os.environ, {"BOGPILOT_PARAMS_DIR": str(self.params_dir)})
    self._env.start()
    cc._store = None

  def tearDown(self):
    import openpilot.selfdrive.selfdrived.cruise_chimes as cc
    cc._store = None
    self._env.stop()
    self._tmp.cleanup()

  def _store(self):
    from openpilot.common.bogpilot_store import ParamStore

    class FileOnlyParams:
      def check_key(self, key):
        raise KeyError(key)

      def get(self, key, *a, **k):
        return None

    return ParamStore(FileOnlyParams())

  def _gains(self, store):
    from openpilot.common.bogpilot_alert_volumes import resolve_alert_gain
    control = store.get_bool("AlertVolumeControl", default=False)
    out = {}
    for key in ("EngageVolume", "DisengageVolume"):
      out[key] = resolve_alert_gain(alert_volume_control=control, percent=store.get_int(key),
                                    ambient=self.AMBIENT, key=key)
    return control, out

  def _fresh_applies(self, car_model):
    from openpilot.common.bogpilot_ap1_profile import apply_ap1_defaults_once
    store = self._store()
    store.put("CarModel", car_model)
    written = apply_ap1_defaults_once(store, bogpilot_dir=self.markers, refresh=False)
    return store, written

  def test_fresh_ap1_install_is_audible(self):
    from openpilot.common.bogpilot_ap1_profile import AP1_CAR_MODEL, AP1_PARAM_PROFILE, _NEVER_PROFILE_VOLUME_KEYS
    from openpilot.common.bogpilot_alert_volumes import is_muted_engage_disengage
    from openpilot.selfdrive.selfdrived.cruise_chimes import PARAM_KEY, chimes_allowed

    for key in ("AlertVolumeControl", "EngageVolume", "DisengageVolume", PARAM_KEY):
      self.assertNotIn(key, AP1_PARAM_PROFILE)
    self.assertIn("EngageVolume", _NEVER_PROFILE_VOLUME_KEYS)
    self.assertIn("DisengageVolume", _NEVER_PROFILE_VOLUME_KEYS)

    store, written = self._fresh_applies(AP1_CAR_MODEL)
    self.assertTrue(written, "the AP1 profile should run once on a fresh Model S")
    self.assertNotIn("EngageVolume", written)
    self.assertNotIn("DisengageVolume", written)
    self.assertNotIn("AlertVolumeControl", written)
    self.assertNotIn(PARAM_KEY, written)

    self.assertTrue(store.get_bool(PARAM_KEY, default=True))
    self.assertTrue(chimes_allowed("tesla_ap1", reader=lambda: store.get_bool(PARAM_KEY, default=True)))
    self.assertFalse(store.get_bool("AlertVolumeControl", default=False))
    self.assertEqual(store.get_int("EngageVolume"), 101)
    self.assertEqual(store.get_int("DisengageVolume"), 101)
    self.assertFalse(is_muted_engage_disengage({
      "AlertVolumeControl": "0" if not store.get_bool("AlertVolumeControl") else "1",
      "EngageVolume": str(store.get_int("EngageVolume")),
      "DisengageVolume": str(store.get_int("DisengageVolume")),
    }))

    control, gains = self._gains(store)
    self.assertFalse(control)
    self.assertGreater(gains["EngageVolume"], 0.0)
    self.assertGreater(gains["DisengageVolume"], 0.0)
    self.assertEqual(gains["EngageVolume"], self.AMBIENT)
    self.assertEqual(gains["DisengageVolume"], self.AMBIENT)

  def test_fresh_preap_install_is_audible(self):
    from opendbc.car.tesla_ap1.values import CAR
    from openpilot.selfdrive.selfdrived.cruise_chimes import PARAM_KEY, chimes_allowed

    store, written = self._fresh_applies(str(CAR.TESLA_PREAP_MODELS))
    self.assertEqual(written, [], "Pre-AP does not take the Model S AP1 profile")
    self.assertTrue(store.get_bool(PARAM_KEY, default=True))
    self.assertTrue(chimes_allowed("tesla_ap1", reader=lambda: store.get_bool(PARAM_KEY, default=True)))
    self.assertEqual(store.get_int("EngageVolume"), 101)
    self.assertEqual(store.get_int("DisengageVolume"), 101)
    _, gains = self._gains(store)
    self.assertGreater(gains["EngageVolume"], 0.0)
    self.assertGreater(gains["DisengageVolume"], 0.0)

  def test_saved_volume_zero_is_preserved(self):
    from openpilot.common.bogpilot_ap1_profile import AP1_CAR_MODEL, apply_ap1_defaults_once
    store = self._store()
    store.put("CarModel", AP1_CAR_MODEL)
    store.put("AlertVolumeControl", "1")
    store.put("EngageVolume", "0")
    store.put("DisengageVolume", "0")
    written = apply_ap1_defaults_once(store, bogpilot_dir=self.markers, refresh=False)
    self.assertNotIn("EngageVolume", written)
    self.assertNotIn("DisengageVolume", written)
    self.assertNotIn("AlertVolumeControl", written)
    self.assertTrue(store.get_bool("AlertVolumeControl"))
    self.assertEqual(store.get_int("EngageVolume"), 0)
    self.assertEqual(store.get_int("DisengageVolume"), 0)
    _, gains = self._gains(store)
    self.assertEqual(gains["EngageVolume"], 0.0)
    self.assertEqual(gains["DisengageVolume"], 0.0)

  def test_saved_toggle_off_is_preserved(self):
    from openpilot.common.bogpilot_ap1_profile import AP1_CAR_MODEL, apply_ap1_defaults_once
    from openpilot.selfdrive.selfdrived.cruise_chimes import PARAM_KEY, chimes_allowed
    store = self._store()
    store.put("CarModel", AP1_CAR_MODEL)
    store.put_bool(PARAM_KEY, False)
    written = apply_ap1_defaults_once(store, bogpilot_dir=self.markers, refresh=False)
    self.assertNotIn(PARAM_KEY, written)
    self.assertFalse(store.get_bool(PARAM_KEY, default=True))
    self.assertFalse(chimes_allowed("tesla_ap1", reader=lambda: store.get_bool(PARAM_KEY, default=True)))
    # volumes stay at the audible default; only the toggle silences the chime
    _, gains = self._gains(store)
    self.assertGreater(gains["EngageVolume"], 0.0)


if __name__ == "__main__":
  unittest.main()
