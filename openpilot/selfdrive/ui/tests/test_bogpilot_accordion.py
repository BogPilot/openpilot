"""Inline accordion: one row open at a time, tap again to close, nothing pushed (pure, no raylib)."""
import gc
import unittest

from openpilot.selfdrive.ui.bogpilot import accordion


class FakeRow:
  def __init__(self):
    self.description_visible = False
    self.opened = None

  def set_description_opened_callback(self, cb):
    self.opened = cb

  def _set_description_visible(self, visible):
    if self.description_visible != visible:
      self.description_visible = visible
      if visible and self.opened is not None:
        self.opened()

  def tap(self):
    self._set_description_visible(not self.description_visible)


class TestAccordion(unittest.TestCase):
  def setUp(self):
    accordion._open = None

  def rows(self, n=3):
    rows = [FakeRow() for _ in range(n)]
    for row in rows:
      accordion.attach(row)
    return rows

  def test_tap_expands_and_second_tap_collapses(self):
    a, = self.rows(1)
    a.tap()
    self.assertTrue(a.description_visible)
    self.assertIs(accordion.open_row(), a)
    a.tap()
    self.assertFalse(a.description_visible)
    self.assertIsNone(accordion.open_row())

  def test_opening_another_row_collapses_the_previous_one(self):
    a, b, c = self.rows()
    a.tap()
    b.tap()
    self.assertEqual((a.description_visible, b.description_visible, c.description_visible), (False, True, False))
    c.tap()
    self.assertEqual((a.description_visible, b.description_visible, c.description_visible), (False, False, True))
    self.assertIs(accordion.open_row(), c)

  def test_reopening_the_same_row_keeps_exactly_one_open(self):
    a, b, _ = self.rows()
    a.tap()
    a.tap()
    a.tap()
    b.tap()
    self.assertEqual([r.description_visible for r in (a, b)], [False, True])

  def test_a_row_that_is_gone_does_not_break_the_next_open(self):
    a, b, _ = self.rows()
    a.tap()
    del a
    gc.collect()
    b.tap()
    self.assertTrue(b.description_visible)


if __name__ == "__main__":
  unittest.main()
