"""Developer HUD painter (raylib): the 0.9.7 BogPilot redesign panel, ten cells in two columns.

Pure data and thresholds live in developer_hud_logic. Display only: the panel never takes a tap and never writes anything.
"""
from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui.onroad.bogpilot import developer_hud_logic as L
from openpilot.selfdrive.ui.onroad.bogpilot.style import (
  C, W, PANEL, STROKE, panel, line, draw_text, text_width, cap_height)

PAD = 20
LABEL_PX, VALUE_PX, UNIT_PX = 19, 44, 20
MIN_VALUE_PX = 26
LABEL_COLOR = C(255, 255, 255, 120)
UNIT_COLOR = C(255, 255, 255, 120)
DIVIDER = C(255, 255, 255, 22)


def _color(rgb: tuple) -> rl.Color:
  return C(*rgb, 240) if rgb == L.WHITE else C(*rgb)


def paint(cells: list, box: tuple) -> None:
  """Paint the panel into screen rect `box` = (x, y, w, h); scales the 400 x 430 design to the box width."""
  x, y, w, _h = box
  scale = w / L.HUD_W
  rl.rl_push_matrix()
  rl.rl_translatef(x, y, 0)
  rl.rl_scalef(scale, scale, 1)
  try:
    panel(rl.Rectangle(0, 0, L.HUD_W, L.HUD_H), 26, PANEL, STROKE, 2.0)
    line(L.HUD_W / 2, 30, L.HUD_W / 2, L.HUD_H - 30, 1.5, DIVIDER)
    col_w = (L.HUD_W - 2 * PAD) / 2
    row_h = (L.HUD_H - 2 * PAD) / 5
    for idx, cell in enumerate(cells[:10]):
      c = L.display_cell(cell)
      cx = PAD + (idx % 2) * col_w + 18
      cy = PAD + (idx // 2) * row_h
      max_w = col_w - 26
      draw_text(c.label, cx, cy + 10 + 14 + cap_height(LABEL_PX) / 2, LABEL_PX, LABEL_COLOR, W.DEMI)
      size = VALUE_PX
      need = text_width(c.value, VALUE_PX, W.DEMI) + (6 + text_width(c.unit, UNIT_PX, W.MEDIUM) if c.unit else 0)
      if need > max_w:
        size = max(MIN_VALUE_PX, int(VALUE_PX * max_w / need))
      base = cy + 62 + cap_height(size) / 2
      adv = draw_text(c.value, cx, base, size, _color(c.color), W.DEMI)
      if c.unit:
        draw_text(c.unit, cx + adv + 6, base, UNIT_PX, UNIT_COLOR, W.MEDIUM)
  finally:
    rl.rl_pop_matrix()
