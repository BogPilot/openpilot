"""comma 4 region picker grid (Maps > Countries / U.S. States): 2 columns x 3 rows of full names.

Pure parts (geometry, paging, label fit, hit test) need no window. The page logic runs on the real MapDataLayout with a fake
Params; the PageHost and the grid page widget need the native runner's built msgq / params like the other comma 4 card tests,
and skip without them."""
import unittest

from openpilot.selfdrive.ui.bogpilot import region_grid as rg
from openpilot.selfdrive.ui.tests import test_bogpilot_maps_page as mp
from openpilot.system.bogpilot.osm import regions


def fake_measure(text, size):
  return len(text) * size * 0.5          # 0.5 em per character


class TestGeometry(unittest.TestCase):
  def test_two_columns_three_rows_fill_one_card_slot(self):
    self.assertEqual((rg.COLS, rg.ROWS, rg.PER_PAGE), (2, 3, 6))
    cw, ch = rg.cell_size()
    self.assertEqual(cw, (496 - 8) / 2)
    self.assertEqual(ch, (180 - 16) / 3)
    ox, oy = rg.cell_origin(5)
    self.assertAlmostEqual(ox + cw, rg.PAGE_W)
    self.assertAlmostEqual(oy + ch, rg.PAGE_H)

  def test_paginate_six_per_page_in_order(self):
    cells = [(f"C{i}", f"Name {i}") for i in range(14)]
    pages = rg.paginate(cells)
    self.assertEqual([len(p) for p in pages], [6, 6, 2])
    self.assertEqual([c for p in pages for c in p], cells)
    self.assertEqual(rg.paginate([]), [])

  def test_us_states_ten_pages_like_the_mockup(self):
    cells = rg.sorted_cells(regions.groups()["states"])
    self.assertEqual(len(rg.paginate(cells)), -(-len(cells) // 6))
    names = [n for _c, n in cells]
    self.assertEqual(names, sorted(names, key=str.casefold))
    self.assertEqual(len({c for c, _n in cells}), len(cells))      # one cell per region

  def test_every_catalog_region_is_in_its_grid(self):
    for kind in ("nations", "states"):
      want = {c for _l, regs in regions.groups()[kind] for c, _n in regs}
      self.assertEqual({c for c, _n in rg.sorted_cells(regions.groups()[kind])}, want)

  def test_a_region_listed_in_two_groups_is_one_cell(self):
    nations = rg.sorted_cells(regions.groups()["nations"])
    codes = [c for c, _n in nations]
    self.assertEqual(len(codes), len(set(codes)))
    self.assertEqual([n for _c, n in nations].count("Kazakhstan"), 1)

  def test_hit_test(self):
    cw, ch = rg.cell_size()
    self.assertEqual(rg.cell_at(5, 5, 6), 0)
    self.assertEqual(rg.cell_at(cw + rg.GAP + 5, 5, 6), 1)
    self.assertEqual(rg.cell_at(5, 2 * (ch + rg.GAP) + 5, 6), 4)
    self.assertEqual(rg.cell_at(rg.PAGE_W - 1, rg.PAGE_H - 1, 6), 5)
    self.assertIsNone(rg.cell_at(cw + 3, 5, 6))                      # the gap between columns
    self.assertIsNone(rg.cell_at(5, ch + 3, 6))                      # the gap between rows
    self.assertIsNone(rg.cell_at(rg.PAGE_W - 1, rg.PAGE_H - 1, 3))   # empty slot on a short last page
    self.assertIsNone(rg.cell_at(-1, 5, 6))


class TestFitLabel(unittest.TestCase):
  W = rg.cell_size()[0] - 2 * rg.PAD_X

  def test_short_name_one_line_at_full_size(self):
    self.assertEqual(rg.fit_label("Maine", self.W, fake_measure), (["Maine"], rg.MAX_FONT))

  def test_longer_name_shrinks_before_wrapping(self):
    lines, size = rg.fit_label("Massachusetts", self.W, fake_measure)    # 13 * 16 = 208 at 32
    self.assertEqual(lines, ["Massachusetts"])
    lines, size = rg.fit_label("Louisiana Purchase", self.W, fake_measure)   # 18 chars: 288 at 32, 216 at 24 -> shrinks
    self.assertEqual(len(lines), 1)
    self.assertLess(size, rg.MAX_FONT)
    self.assertGreaterEqual(size, rg.MIN_FONT)

  def test_too_long_wraps_to_two_lines_at_min_size(self):
    lines, size = rg.fit_label("Northern Mariana Islands", self.W, fake_measure)   # 24 chars: 288 at 24 > 224
    self.assertEqual(size, rg.MIN_FONT)
    self.assertEqual(lines, ["Northern Mariana", "Islands"])
    self.assertEqual(" ".join(lines), "Northern Mariana Islands")

  def test_one_endless_word_is_clipped_with_an_ellipsis(self):
    lines, size = rg.fit_label("W" * 40, self.W, fake_measure)
    self.assertEqual(len(lines), 1)
    self.assertTrue(lines[0].endswith("..."))
    self.assertLessEqual(fake_measure(lines[0], size), self.W)

  def test_every_catalog_name_fits_in_at_most_two_lines(self):
    for kind in ("nations", "states"):
      for _c, name in rg.sorted_cells(regions.groups()[kind]):
        lines, size = rg.fit_label(name, self.W, fake_measure)
        self.assertLessEqual(len(lines), 2, name)
        self.assertTrue(all(fake_measure(ln, size) <= self.W for ln in lines), name)


class TestGridPage(mp.MapsPageCase):
  def open_grid(self, kind):
    self.page.enable_grid_picker()
    self.page.open_screen((kind,))

  def test_grid_is_off_by_default_and_the_3x_keeps_its_group_lists(self):
    self.assertFalse(self.page.grid_picker)
    self.page.open_screen(("states",))
    self.assertIsNone(self.page.grid_cells())
    self.assertIsNone(self.page.grid_kind())
    self.page.open_screen(("states", "United States - Northeast"))
    self.assertEqual(self.page._path, ("states", "United States - Northeast"))    # group screens still open
    self.assertIn("MA", self.page.region_rows)

  def test_grid_lists_every_region_of_the_kind_by_name(self):
    self.open_grid("states")
    cells = self.page.grid_cells()
    want = {c for _l, regs in regions.groups()["states"] for c, _n in regs}
    self.assertEqual({c for c, _n in cells}, want)
    names = [n for _c, n in cells]
    self.assertEqual(names, sorted(names, key=str.casefold))
    self.open_grid("nations")
    self.assertIn("France", [n for _c, n in self.page.grid_cells()])

  def test_grid_has_no_group_screens(self):
    self.open_grid("states")
    self.assertEqual(self.page._path, ("states",))
    self.page.open_screen(("states", "United States - Northeast"))
    self.assertEqual(self.page._path, ("states",))                     # refused in grid mode
    self.assertEqual(self.page.region_rows, {})

  def test_tap_selects_and_unselects_and_saves_at_once(self):
    self.open_grid("states")
    self.assertFalse(self.page.grid_selected("MA"))
    self.page.grid_tap("MA")
    self.assertTrue(self.page.grid_selected("MA"))
    self.assertIn("MA", self.ctl.selection().states)
    self.assertEqual(self.ctl.selection().nations, ())
    self.page.grid_tap("MA")
    self.assertFalse(self.page.grid_selected("MA"))
    self.assertNotIn("MA", self.ctl.selection().states)

  def test_tap_on_the_countries_grid_changes_countries_only(self):
    self.open_grid("nations")
    self.page.grid_tap("FR")
    self.assertIn("FR", self.ctl.selection().nations)
    self.assertEqual(self.ctl.selection().states, ())

  def test_unknown_code_and_closed_grid_do_nothing(self):
    self.page.grid_tap("MA")                                           # no grid open
    self.assertEqual(self.ctl.selection().states, ())
    self.open_grid("states")
    self.page.grid_tap("ZZ")
    self.assertEqual(self.ctl.selection().states, ())

  def test_selection_made_elsewhere_shows_in_the_grid(self):
    self.ctl.set_region("states", "NY", True)
    self.open_grid("states")
    self.page._update_state()
    self.assertTrue(self.page.grid_selected("NY"))
    self.assertFalse(self.page.grid_selected("CA"))

  def test_back_from_the_grid_returns_to_the_main_page(self):
    self.open_grid("states")
    self.assertEqual(self.page.navigation_title, self.P.KIND_TITLES["states"])
    self.assertTrue(self.page.navigation_back())
    self.assertEqual(self.page._path, ())
    self.assertFalse(self.page.navigation_back())

  def test_turning_the_grid_on_while_a_group_is_open_opens_the_grid(self):
    self.page.open_screen(("states", "United States - Northeast"))
    self.page.enable_grid_picker()
    self.assertEqual(self.page._path, ("states",))
    self.assertIsNotNone(self.page.grid_cells())


class TestComma4GridHost(mp.MapsPageCase):
  def host(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.layout import PageHost

    class Menu:
      def open_choice(self, source): pass
      def open_stepper(self, row): pass
      def page_note(self): return ""
    return PageHost(Menu(), ("maps", "maps"), self.page, "Maps")

  def sync(self, h):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    try:
      h._sync_cards(rm.static_rows(self.page))
    except OSError as e:
      self.skipTest(f"needs built msgq / params ({type(e).__name__})")

  def test_page_host_turns_the_grid_picker_on(self):
    try:
      h = self.host()
    except OSError as e:
      self.skipTest(f"needs built msgq / params ({type(e).__name__})")
    self.assertTrue(self.page.grid_picker)

  def test_states_screen_is_pages_of_six_cells_between_header_and_credit(self):
    h = self.host()
    self.page.open_screen(("states",))
    self.sync(h)
    n = len(self.page.grid_cells())
    self.assertEqual(len(h.grid_pages), -(-n // 6))
    self.assertEqual([len(p.cells) for p in h.grid_pages][:-1], [6] * (len(h.grid_pages) - 1))
    items = h._scroller._items
    self.assertIs(items[0], h._header)
    self.assertEqual(items[1:1 + len(h.grid_pages)], h.grid_pages)
    self.assertGreater(len(items), 1 + len(h.grid_pages))               # the OSM credit follows the grid

  def test_grid_pages_go_away_on_the_main_page(self):
    h = self.host()
    self.page.open_screen(("states",))
    self.sync(h)
    self.page.navigation_back()
    self.sync(h)
    self.assertEqual(h.grid_pages, [])

  def test_a_tap_on_a_cell_flips_that_region(self):
    h = self.host()
    self.page.open_screen(("states",))
    self.sync(h)
    pg = next(p for p in h.grid_pages if any(c == "MA" for c, _n in p.cells))
    i = [c for c, _n in pg.cells].index("MA")
    ox, oy = rg.cell_origin(i)
    from openpilot.system.ui.lib.application import MousePos
    pos = MousePos(pg.rect.x + ox + 10, pg.rect.y + oy + 10)
    pg._handle_mouse_press(pos)
    pg._handle_mouse_release(pos)
    self.assertIn("MA", self.ctl.selection().states)
    pg._handle_mouse_press(pos)
    pg._handle_mouse_release(pos)
    self.assertNotIn("MA", self.ctl.selection().states)

  def test_press_on_one_cell_and_release_on_another_taps_nothing(self):
    h = self.host()
    self.page.open_screen(("states",))
    self.sync(h)
    pg = h.grid_pages[0]
    from openpilot.system.ui.lib.application import MousePos
    ox1, oy1 = rg.cell_origin(1)
    pg._handle_mouse_press(MousePos(pg.rect.x + 10, pg.rect.y + 10))
    pg._handle_mouse_release(MousePos(pg.rect.x + ox1 + 10, pg.rect.y + oy1 + 10))
    self.assertEqual(self.ctl.selection().states, ())


if __name__ == "__main__":
  unittest.main()
