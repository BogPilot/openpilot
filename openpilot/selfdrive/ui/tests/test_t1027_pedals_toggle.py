"""t1027: Dynamic Pedals off hides the overlay (UI toggle -> store -> pedals consumer)."""
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


class TestDynamicPedalsOffHides(unittest.TestCase):
  def test_registry_default_dynamic_is_on(self):
    # Default stays ON; PedalsOnUI still defaults Off so a fresh device hides until that parent is on.
    self.assertEqual(BOGPILOT_PARAMS["DynamicPedalsOnUI"][2], "1")
    self.assertEqual(BOGPILOT_PARAMS["PedalsOnUI"][2], "0")
    self.assertEqual(BOGPILOT_PARAMS["StaticPedalsOnUI"][2], "0")

  def test_default_on_shows_dynamic_when_parent_is_on(self):
    # Unset DynamicPedalsOnUI follows the registry default (On). With Pedals on Screen on, the overlay is dynamic.
    h = StoreHarness(CustomUI=True, PedalsOnUI=True)
    self.assertIsNone(h.raw("DynamicPedalsOnUI"))
    pol = h.policy(True)
    self.assertTrue(pol.show)
    self.assertTrue(pol.dynamic)
    self.assertFalse(pol.static)
    brake, gas = PED.daily_opacity(pol, 0.5, False, False)
    self.assertGreater(gas, brake)

  def test_saved_off_hides_even_if_pedals_on_screen_is_on(self):
    h = StoreHarness(CustomUI=True, PedalsOnUI=True, DynamicPedalsOnUI=False, StaticPedalsOnUI=False)
    pol = h.policy(True)
    self.assertFalse(pol.show)
    self.assertFalse(pol.dynamic)
    self.assertFalse(pol.static)

  def test_toggle_off_via_visuals_write_hides_consumer(self):
    h = StoreHarness(CustomUI=True, PedalsOnUI=True, DynamicPedalsOnUI=True, StaticPedalsOnUI=False)
    self.assertTrue(h.policy(True).show)
    h.write("DynamicPedalsOnUI", False)
    self.assertEqual(h.raw("DynamicPedalsOnUI"), "0")
    pol = h.policy(True)
    self.assertFalse(pol.show)
    self.assertFalse(pol.dynamic)

  def test_toggle_on_via_visuals_write_shows_dynamic(self):
    h = StoreHarness(CustomUI=True, PedalsOnUI=True, DynamicPedalsOnUI=False, StaticPedalsOnUI=False)
    self.assertFalse(h.policy(True).show)
    h.write("DynamicPedalsOnUI", True)
    self.assertEqual(h.raw("DynamicPedalsOnUI"), "1")
    pol = h.policy(True)
    self.assertTrue(pol.show)
    self.assertTrue(pol.dynamic)
    self.assertFalse(pol.static)

  def test_static_saved_on_still_shows_when_dynamic_is_off(self):
    h = StoreHarness(CustomUI=True, PedalsOnUI=True, DynamicPedalsOnUI=False, StaticPedalsOnUI=True)
    pol = h.policy(True)
    self.assertTrue(pol.show)
    self.assertFalse(pol.dynamic)
    self.assertTrue(pol.static)

  def test_parent_off_or_no_longitudinal_still_hides(self):
    h = StoreHarness(CustomUI=True, PedalsOnUI=False, DynamicPedalsOnUI=True)
    self.assertFalse(h.policy(True).show)
    h = StoreHarness(CustomUI=True, PedalsOnUI=True, DynamicPedalsOnUI=True)
    self.assertFalse(h.policy(False).show)

  def test_help_text_says_off_hides(self):
    from openpilot.selfdrive.ui.bogpilot import toggle_help
    entry = toggle_help.HELP["DynamicPedalsOnUI"]
    self.assertIn("hides", entry.what.lower())
    self.assertNotIn("full strength", entry.what.lower())
    self.assertEqual(entry.default, "On")
    self.assertEqual(entry.default_param, "DynamicPedalsOnUI")

  def test_visuals_write_matches_layout_method(self):
    import inspect
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    src = inspect.getsource(BogPilotVisualsLayout._write)
    self.assertIn("put_bool", src)
    self.assertIn("invalidate", src)


if __name__ == "__main__":
  unittest.main()
