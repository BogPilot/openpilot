import importlib.util
import sys
import unittest
from pathlib import Path

# Direct loading also proves no raylib/Params import is needed for the contract.
SOURCE = Path(__file__).parents[1] / "layouts/settings/phase2_navigation.py"
spec = importlib.util.spec_from_file_location("phase2_navigation_contract", SOURCE)
nav = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = nav
spec.loader.exec_module(nav)


class View:
  def __init__(self):
    self.events = []

  def show_event(self):
    self.events.append("show")

  def hide_event(self):
    self.events.append("hide")


class TestPhase2Navigation(unittest.TestCase):
  def setUp(self):
    self.created = []
    self.menus = []

    def leaf():
      v = View()
      self.created.append(v)
      return v

    def menu(entries, callback):
      v = View()
      v.entries = entries
      self.menus.append(v)
      return v

    self.page = nav.Page("gas_brake", "Gas / Brake", leaf, ("working-control",))
    self.n = nav.Navigation({"driving": [self.page]}, menu)

  def test_lazy(self):
    self.assertEqual(self.created, [])
    self.n.show_event()
    self.n.open("driving")
    self.assertEqual(self.created, [])
    self.n.open("gas_brake")
    self.assertEqual(len(self.created), 1)

  def test_lifecycle_back_and_reopen(self):
    self.n.show_event()
    self.n.show_event()
    root = self.n.current
    self.n.open("driving")
    group = self.n.current
    self.n.open("gas_brake")
    leaf = self.n.current
    self.n.hide_event()
    self.n.hide_event()
    self.n.show_event()
    self.assertEqual(leaf.events, ["show", "hide", "show"])
    self.assertEqual(self.n.path, ("driving", "gas_brake"))
    self.assertTrue(self.n.back())
    self.assertEqual(self.n.title, "Driving Controls")
    self.n.open("gas_brake")
    self.assertIs(self.n.current, leaf)
    self.n.back()
    self.n.back()
    self.assertFalse(self.n.back())
    self.assertEqual(root.events, ["show", "hide", "show"])
    self.assertEqual(group.events, ["show", "hide", "show", "hide", "show", "hide"])

  def test_empty_and_unknown_groups(self):
    self.assertEqual(nav.active_groups({}), ())
    self.assertEqual(nav.active_groups({"vehicle": [nav.Page("inactive", "Unused", View)]}), ())
    with self.assertRaises(ValueError):
      nav.active_groups({"navigation": [self.page]})

  def test_canonical_order(self):
    result = nav.active_groups({"vehicle": [nav.Page("v", "Vehicle Settings", View, ("x",))],
                                "driving": [self.page], "alerts_sounds": []})
    self.assertEqual([g[0] for g in result], ["driving", "vehicle"])

  def test_duplicate_rejected(self):
    with self.assertRaises(ValueError):
      nav.active_groups({"driving": [self.page, self.page]})

  def test_invalid_navigation_preserves_view(self):
    self.n.show_event()
    view = self.n.current
    with self.assertRaises(KeyError):
      self.n.open("not supplied")
    self.assertIs(view, self.n.current)
    self.assertEqual(view.events, ["show"])

  def test_failed_leaf_keeps_group_visible(self):
    def fail():
      raise RuntimeError("factory failure")
    self.n = nav.Navigation({"driving": [nav.Page("broken", "Broken", fail, ("x",))]}, lambda *_: View())
    self.n.show_event()
    self.n.open("driving")
    view = self.n.current
    with self.assertRaises(RuntimeError):
      self.n.open("broken")
    self.assertIs(view, self.n.current)
    self.assertEqual(view.events, ["show"])

  def test_hidden_navigation_has_no_show(self):
    self.n.open("driving")
    self.n.open("gas_brake")
    self.assertEqual(self.n.current.events, [])
    self.n.show_event()
    self.assertEqual(self.n.current.events, ["show"])

  def test_layout_bounds(self):
    for w, h in [(1400, 1030), (300, 100), (0, 0), (-1, -1)]:
      header, body = nav.content_bounds(550, 25, w, h)
      self.assertEqual(header[0], body[0])
      self.assertEqual(header[1] + header[3], body[1])
      self.assertEqual(header[3] + body[3], max(0, h))
      self.assertGreaterEqual(body[2], 0)
      self.assertGreaterEqual(body[3], 0)


if __name__ == "__main__":
  unittest.main()
