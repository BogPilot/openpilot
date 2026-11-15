"""Pedals on Screen is the one switch for the 3-bar pedal gauge (UI toggle -> store -> pedals consumer). The former
Dynamic / Static mode keys stay registered (backup, restore, resets) but are not read or offered."""
from __future__ import annotations

import unittest

from openpilot.selfdrive.ui.tests.test_phase2_visuals_theme import FakeParams

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED


def visuals_write(store, key, state):
  """Same write path as BogPilotVisualsLayout._write (put_bool + invalidate)."""
  store.put_bool(key, bool(state))
  store.invalidate(key)


class StoreHarness:
  def __init__(self, **initial):
    typed = {k: ("1" if v is True else "0" if v is False else str(v)) for k, v in initial.items()}
    self.params = FakeParams(typed)
    self.store = ParamStore(self.params)

  def write(self, key, state):
    visuals_write(self.store, key, state)

  def policy(self, longitudinal=True):
    self.store.invalidate()
    return PED.policy_from_store(self.store, longitudinal)

  def raw(self, key):
    return self.store.raw(key)


class TestPedalsOnScreen(unittest.TestCase):
  def test_registry_defaults(self):
    self.assertEqual(BOGPILOT_PARAMS["PedalsOnUI"][2], "1")
    # kept registered so a stored choice survives backup / restore; nothing reads them
    self.assertIn("DynamicPedalsOnUI", BOGPILOT_PARAMS)
    self.assertIn("StaticPedalsOnUI", BOGPILOT_PARAMS)

  def test_default_shows_with_the_parent_on(self):
    h = StoreHarness(CustomUI=True)
    self.assertIsNone(h.raw("PedalsOnUI"))
    self.assertTrue(h.policy(True).show)

  def test_old_mode_values_do_not_hide_or_get_rewritten(self):
    h = StoreHarness(CustomUI=True, PedalsOnUI=True, DynamicPedalsOnUI=False, StaticPedalsOnUI=False)
    self.assertTrue(h.policy(True).show)
    self.assertEqual((h.raw("DynamicPedalsOnUI"), h.raw("StaticPedalsOnUI")), ("0", "0"))
    h = StoreHarness(CustomUI=True, PedalsOnUI=True, DynamicPedalsOnUI=True, StaticPedalsOnUI=True)
    self.assertEqual(h.policy(True), PED.PedalPolicy(show=True))

  def test_toggle_via_visuals_write_hides_and_shows(self):
    h = StoreHarness(CustomUI=True, PedalsOnUI=True)
    self.assertTrue(h.policy(True).show)
    h.write("PedalsOnUI", False)
    self.assertEqual(h.raw("PedalsOnUI"), "0")
    self.assertFalse(h.policy(True).show)
    h.write("PedalsOnUI", True)
    self.assertTrue(h.policy(True).show)

  def test_parent_off_or_no_longitudinal_hides(self):
    self.assertFalse(StoreHarness(CustomUI=False, PedalsOnUI=True).policy(True).show)
    self.assertFalse(StoreHarness(CustomUI=True, PedalsOnUI=True).policy(False).show)

  def test_help_and_menu(self):
    from openpilot.selfdrive.ui.bogpilot import toggle_help
    from openpilot.selfdrive.ui.bogpilot import toggle_metadata as TM
    self.assertNotIn("DynamicPedalsOnUI", toggle_help.HELP)
    what = toggle_help.HELP["PedalsOnUI"].what.lower()
    for word in ("three", "brake", "regen", "acceleration", "55 kw", "ibooster"):
      self.assertIn(word, what)
    params = {d.param for v in vars(TM).values() if isinstance(v, tuple) for d in v if isinstance(d, TM.ToggleDefinition)}
    self.assertIn("BlindSpotPath", params)
    self.assertIn("PedalsOnUI", params)
    self.assertNotIn("DynamicPedalsOnUI", params)
    self.assertNotIn("StaticPedalsOnUI", params)

  def test_visuals_write_matches_layout_method(self):
    import inspect
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    src = inspect.getsource(BogPilotVisualsLayout._write)
    self.assertIn("put_bool", src)
    self.assertIn("invalidate", src)


if __name__ == "__main__":
  unittest.main()
