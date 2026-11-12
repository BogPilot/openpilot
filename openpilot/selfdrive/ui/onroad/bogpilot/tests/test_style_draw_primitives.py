"""fill_circle / polyline draw primitives: one GPU circle per cap, not a 24-seg sector fan."""
from __future__ import annotations
import collections
import sys
import types
import unittest


def _install_pyray_stub():
  # Keep a real pyray if the test env already loaded one; otherwise a tiny stub.
  if "pyray" in sys.modules:
    return sys.modules["pyray"], True
  counts = collections.Counter()

  class Color:
    def __init__(self, r=255, g=255, b=255, a=255):
      self.r, self.g, self.b, self.a = r, g, b, a

  class Vector2:
    def __init__(self, x=0, y=0):
      self.x, self.y = x, y

  class Font:
    def __init__(self):
      self.texture = types.SimpleNamespace(id=1)

  def count(name):
    def fn(*a, **k):
      counts[name] += 1
    fn.__name__ = name
    return fn

  rl = types.ModuleType("pyray")
  rl.Color = Color
  rl.Vector2 = Vector2
  rl.Font = Font
  rl.WHITE = Color()
  for n in ("draw_circle_v", "draw_circle_sector", "draw_line_ex", "draw_text_ex",
            "measure_text_ex", "draw_rectangle_rounded", "draw_rectangle_rounded_lines_ex"):
    setattr(rl, n, count(n))
  rl._counts = counts
  sys.modules["pyray"] = rl
  return rl, False


class TestFillCirclePrimitive(unittest.TestCase):
  def test_fill_circle_uses_draw_circle_v_not_sector(self):
    rl, existed = _install_pyray_stub()
    if existed:
      # Real pyray: just check the source, so this still fails if someone reverts the diet.
      from pathlib import Path
      import openpilot.selfdrive.ui.onroad.bogpilot.style as style
      src = Path(style.__file__).read_text()
      self.assertIn("draw_circle_v", src)
      self.assertNotIn("draw_circle_sector", src)
      return
    # Stub application / text_measure so style can import without a window.
    if "openpilot.system.ui.lib.application" not in sys.modules:
      app = types.ModuleType("openpilot.system.ui.lib.application")
      class FontWeight:
        NORMAL = "n"
        MEDIUM = "m"
        BOLD = "b"
        SEMI_BOLD = "s"
        REGULAR = "n"
        DEMI = "s"
      app.FontWeight = FontWeight
      app.FONT_SCALE = 1.242
      app.font_fallback = lambda font: font
      app.gui_app = types.SimpleNamespace(font=lambda weight=None: rl.Font())
      sys.modules.setdefault("openpilot.system", types.ModuleType("openpilot.system"))
      sys.modules["openpilot.system"].__path__ = []
      sys.modules.setdefault("openpilot.system.ui", types.ModuleType("openpilot.system.ui"))
      sys.modules["openpilot.system.ui"].__path__ = []
      lib = types.ModuleType("openpilot.system.ui.lib")
      lib.__path__ = []
      sys.modules["openpilot.system.ui.lib"] = lib
      sys.modules["openpilot.system.ui.lib.application"] = app
      tm = types.ModuleType("openpilot.system.ui.lib.text_measure")
      tm.measure_text_cached = lambda *a, **k: types.SimpleNamespace(x=10, y=10)
      sys.modules["openpilot.system.ui.lib.text_measure"] = tm
    import importlib
    import openpilot.selfdrive.ui.onroad.bogpilot.style as style
    importlib.reload(style)
    color = style.C(255, 255, 255, 255)
    rl._counts.clear()
    style.fill_circle(10.0, 20.0, 5.0, color)
    self.assertEqual(rl._counts["draw_circle_v"], 1)
    self.assertEqual(rl._counts["draw_circle_sector"], 0)
    # transparent or non-positive radius: no draw
    rl._counts.clear()
    style.fill_circle(0, 0, 5.0, style.C(255, 255, 255, 0))
    style.fill_circle(0, 0, 0.0, color)
    self.assertEqual(rl._counts["draw_circle_v"], 0)

  def test_polyline_round_caps_use_fill_circle(self):
    rl, existed = _install_pyray_stub()
    if existed:
      return  # source assertion already covered above
    import importlib
    import openpilot.selfdrive.ui.onroad.bogpilot.style as style
    importlib.reload(style)
    pts = [(0.0, 0.0), (10.0, 0.0), (20.0, 5.0)]
    rl._counts.clear()
    style.polyline(pts, 5, style.C(255, 255, 255, 255), round_cap=True)
    self.assertEqual(rl._counts["draw_line_ex"], 2)
    self.assertEqual(rl._counts["draw_circle_v"], 3)  # a join/cap at every vertex
    self.assertEqual(rl._counts["draw_circle_sector"], 0)


if __name__ == "__main__":
  unittest.main()
