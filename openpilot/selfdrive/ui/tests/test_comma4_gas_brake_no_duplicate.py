"""comma 4 Gas / Brake: 'Driving Personalities' is one card title, not two.

The 3X row is one switch + MANAGE row (0.9.7 manage control). The comma 4 splits it into a switch card and a MANAGE card;
the MANAGE card is now the switch's indented child ("Customize"), so the page lists the title once.
"""
import unittest

from openpilot.selfdrive.ui.tests.test_comma4_menu_parity import NoWindow, _cp


def _plain(title: str) -> str:
  from openpilot.selfdrive.ui.bogpilot import row_model as rm
  return title.replace(rm.INDENT_MARK, "").strip().lower()


class TestManageToggleLabels(NoWindow):
  def test_switch_card_has_the_title_and_manage_card_is_its_child(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.selfdrive.ui.bogpilot.phase3_following import _manage_toggle_item
    on = {"v": True}
    row = rm.Row(_manage_toggle_item("Driving Personalities", "d", True, lambda s: on.update(v=s), lambda: True,
                                     lambda: None, lambda: on["v"]))
    self.assertEqual(row.kind, rm.MANAGE_TOGGLE)
    labels = rm.card_labels(row)
    self.assertEqual(labels, [("Driving Personalities", ""), (rm.INDENT_MARK + rm.MANAGE_CHILD_TITLE, "MANAGE")])
    self.assertEqual([_plain(t) for t, _ in labels].count("driving personalities"), 1)

  def test_cards_for_draw_the_title_once(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.selfdrive.ui.bogpilot.phase3_following import _manage_toggle_item
    from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import cards_for
    row = rm.Row(_manage_toggle_item("Driving Personalities", "d", True, lambda s: None, lambda: True,
                                     lambda: None, lambda: True))
    cards = cards_for(row, lambda *_: None, lambda *_: None)
    self.assertEqual(len(cards), 2)                 # the switch and MANAGE stay separate taps
    texts = [_plain(c.text) for c in cards]
    self.assertEqual(texts.count("driving personalities"), 1, texts)
    self.assertEqual(cards[1].value, "MANAGE")


class TestGasBrakePage(NoWindow):
  NATIVE = True

  def test_gas_brake_page_lists_driving_personalities_once(self):
    from openpilot.selfdrive.ui.bogpilot import row_model as rm
    from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.ui_state import ui_state
    tl.invalidate()
    self.assertTrue(tl.set_level(tl.DEVELOPER))
    page = next(p for s in menu_sections() for pl in s.pills for p in pl.pages if p.key == "gas_brake")
    checked = 0
    try:
      for car in (None, "ap1", "preap"):
        ui_state.CP = _cp(car)
        widget = page.factory()
        widget.show_event()
        titles = [_plain(t) for r in rm.static_rows(widget) if r is not None
                  for t, _v in rm.card_labels(rm.Row(r)) if rm.Row(r).kind != rm.UNSUPPORTED]
        widget.hide_event()
        self.assertIn("driving personalities", titles, (car, titles))
        self.assertEqual(titles.count("driving personalities"), 1, (car, titles))
        checked += 1
    finally:
      ui_state.CP = None
    self.assertEqual(checked, 3)


if __name__ == "__main__":
  unittest.main()
