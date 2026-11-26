"""Real native raylib navigation shell regression; no fake ListItem/Scroller."""
import os
import unittest


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestNativeNavigationRender(unittest.TestCase):
  def test_full_shell_root_groups_leaves_back_and_reshow(self):
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import working_pages
    from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import build_layout
    gui_app.init_window("BogPilot real native navigation regression")
    widget = build_layout(working_pages())
    rect = rl.Rectangle(500, 0, 1660, 1080)
    def render():
      rl.begin_drawing()
      try:
        widget.render(rect)
      finally:
        rl.end_drawing()
      self.assertIsNotNone(widget._header._parent_rect)
      self.assertEqual(widget._header._parent_rect.x, rect.x)
      self.assertEqual(widget._header._parent_rect.width, rect.width)
    widget.show_event()
    render()
    groups = tuple(widget.navigation.entries())
    self.assertTrue(groups)
    for group, _ in groups:
      widget.navigation.open(group)
      render()
      for page, _ in tuple(widget.navigation.entries()):
        widget.navigation.open(page)
        render()
        self.assertTrue(widget.navigation.back())
        render()
      self.assertTrue(widget.navigation.back())
      render()
    widget.hide_event()
    widget.show_event()
    render()
    widget.hide_event()


if __name__ == "__main__":
  unittest.main()
