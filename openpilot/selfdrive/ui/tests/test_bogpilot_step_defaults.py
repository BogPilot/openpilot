"""Default hint, non-default highlight and section reset helpers (selfdrive/ui/bogpilot/step_defaults.py). No UI imports."""
import math
import unittest

from openpilot.selfdrive.ui.bogpilot.step_defaults import default_hint, differs_from_default, reset_section


class TestDefaultHint(unittest.TestCase):
  def test_text(self):
    self.assertEqual(default_hint("Auto"), "default: Auto")
    self.assertEqual(default_hint(3), "default: 3")
    self.assertEqual(default_hint(lambda: "15 mph"), "default: 15 mph")

  def test_nothing_to_show(self):
    self.assertEqual(default_hint(None), "")
    self.assertEqual(default_hint(""), "")
    self.assertEqual(default_hint(lambda: None), "")

  def test_translated_prefix(self):
    self.assertEqual(default_hint("Auto", translate=lambda s: s.upper()), "DEFAULT: Auto")


class TestDiffersFromDefault(unittest.TestCase):
  def test_numbers_compare_by_value(self):
    self.assertFalse(differs_from_default("101", 101))
    self.assertFalse(differs_from_default(101.0, "101"))
    self.assertFalse(differs_from_default("15.01", 15.01))
    self.assertTrue(differs_from_default(60, "101"))
    self.assertTrue(differs_from_default("0", 101))

  def test_text_compares_as_text(self):
    self.assertFalse(differs_from_default("Auto", "Auto"))
    self.assertTrue(differs_from_default("Muted", "Auto"))

  def test_unknown_is_never_highlighted(self):
    self.assertFalse(differs_from_default(None, 101))
    self.assertFalse(differs_from_default(101, None))

  def test_nan_is_unknown_and_not_highlighted(self):
    self.assertFalse(differs_from_default(math.nan, 1))
    self.assertFalse(differs_from_default(1, math.nan))
    self.assertFalse(differs_from_default("nan", "nan"))


class MockParams:
  def __init__(self, data):
    self.data = dict(data)
    self.writes = []

  def put(self, key, value):
    self.writes.append((key, value))
    self.data[key] = value


class TestResetSection(unittest.TestCase):
  def test_writes_only_listed_keys_with_their_defaults(self):
    p = MockParams({"A": "1", "B": "2", "Other": "9"})
    keys = reset_section({"A": "10", "B": "20"}, p.put)
    self.assertEqual(keys, ["A", "B"])
    self.assertEqual(p.writes, [("A", "10"), ("B", "20")])
    self.assertEqual(p.data, {"A": "10", "B": "20", "Other": "9"})

  def test_defaults_resolved_when_reset_runs(self):
    table = {"A": "1"}
    p = MockParams({})
    source = lambda: dict(table)  # noqa: E731
    table["A"] = "5"
    reset_section(source, p.put)
    self.assertEqual(p.writes, [("A", "5")])

  def test_failing_writer_stops_at_that_key(self):
    p = MockParams({})

    def write(key, value):
      if key == "B":
        raise OSError("refused")
      p.put(key, value)
    with self.assertRaises(OSError):
      reset_section({"A": "1", "B": "2", "C": "3"}, write)
    self.assertEqual(p.writes, [("A", "1")])

  def test_empty_section_writes_nothing(self):
    p = MockParams({"A": "1"})
    self.assertEqual(reset_section({}, p.put), [])
    self.assertEqual(p.writes, [])


if __name__ == "__main__":
  unittest.main()
