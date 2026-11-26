"""Onroad Custom Log Upload Stats panel (display only, no touch).

Draws the View from selfdrive/ui/bogpilot/upload_stats.py in the bottom corner away from the driver (bottom right on a
left-hand-drive car), inset past the confidence ball edge, and moves up out of anything already drawn there (the
keepouts the HUD collects). Nothing is drawn when there is no View: toggle off, no uploader, or stale status.
"""
from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui.bogpilot.upload_stats import TONE_GOOD, TONE_WARN, View
from openpilot.selfdrive.ui.onroad.bogpilot.style import C, PANEL, W, draw_text, text_width

SIDE_INSET = 70      # screen px from the far edge: clear of a confidence ball on that edge
BOTTOM_INSET = 40    # screen px above the content bottom (the FPS line sits lower, centred)
PAD_X, PAD_Y, LINE_GAP = 22, 16, 8
STACK_GAP = 18
TITLE_PX, VALUE_PX, BODY_PX, NOTE_PX = 22, 44, 28, 24

DIM = C(255, 255, 255, 190)
WHITE = C(255, 255, 255, 245)
GOOD = C(61, 220, 151, 255)
WARN = C(255, 196, 60, 255)


def lines(view: View) -> list[tuple[str, int, object, rl.Color]]:
  out = [("UPLOAD", TITLE_PX, W.DEMI, DIM), (view.rate + " \u2191", VALUE_PX, W.BOLD, WHITE)]
  if view.workers:
    out.append((view.workers, NOTE_PX, W.DEMI, DIM))
  if view.backlog_size is not None:
    out.append((f"PENDING {view.backlog_size} \u00b7 {view.backlog_segments}", BODY_PX, W.DEMI, WHITE))
    if view.backlog_note:
      tone = GOOD if view.note_tone == TONE_GOOD else WARN if view.note_tone == TONE_WARN else DIM
      out.append((view.backlog_note, NOTE_PX, W.DEMI, tone))
  return out


def panel_rect(content: rl.Rectangle, w: float, h: float, rhd: bool, keepouts) -> rl.Rectangle:
  x = content.x + SIDE_INSET if rhd else content.x + content.width - SIDE_INSET - w
  r = rl.Rectangle(x, content.y + content.height - BOTTOM_INSET - h, w, h)
  for _ in range(4):
    moved = False
    for k in keepouts or ():
      if rl.check_collision_recs(r, k):
        r.y = k.y - STACK_GAP - h
        moved = True
    if not moved:
      break
  return r


def paint(view: View | None, content: rl.Rectangle, rhd: bool, keepouts=()) -> rl.Rectangle | None:
  if view is None:
    return None
  ls = lines(view)
  w = max(text_width(t, px, wt) for t, px, wt, _ in ls) + 2 * PAD_X
  h = sum(px for _, px, _, _ in ls) + LINE_GAP * (len(ls) - 1) + 2 * PAD_Y
  r = panel_rect(content, w, h, rhd, keepouts)
  if r.y < content.y:
    return None   # no free room on this screen: draw nothing rather than cover other widgets
  rl.draw_rectangle_rounded(r, 0.18, 10, PANEL)
  y = r.y + PAD_Y
  for t, px, wt, color in ls:
    y += px
    draw_text(t, r.x + PAD_X, y - px * 0.2, px, color, wt)
    y += LINE_GAP
  return r
