"""SLC offset badge geometry: 40 px font (2x the old 20 px), box and padding scaled with it, same anchor, inside the pill."""
from openpilot.selfdrive.ui.onroad.bogpilot import redesign as R
from openpilot.selfdrive.ui.onroad.bogpilot import speed_limit_display as SL
import pytest

from openpilot.selfdrive.ui.onroad.bogpilot.style import speed_row_top


def text_width(text, size, weight=None):
  return 0.6 * size * len(text)     # fixed advance: no window or font is needed for the geometry


@pytest.fixture(autouse=True)
def fixed_text_width(monkeypatch):
  monkeypatch.setattr(R, "text_width", text_width)


def geometry(offset, limit="65"):
  return R.speed_row_geometry(R.SpeedRowInputs(show_limit=True, limit=limit, offset=offset))


def test_badge_is_2x_the_old_size():
  assert (R.OFFSET_BADGE_PX, R.OFFSET_BADGE_H, R.OFFSET_BADGE_PAD) == (40, 60, 36)
  for off in ("+5", "+10"):
    g = geometry(off)
    assert g.badge.height == 60
    assert abs(g.badge.width - (text_width(off, 40) + 36)) < 1e-3


def test_badge_keeps_the_old_anchor():
  g = geometry("+5")
  cx, cy = g.badge.x + g.badge.width / 2, g.badge.y + g.badge.height / 2
  assert abs(cx - (g.tile.x + g.tile.width - 4)) < 1e-3
  assert abs(cy - max(g.tile.y + 2, speed_row_top(False) + 22)) < 1e-3


def test_badge_stays_inside_the_pill_for_every_limit_width():
  for limit in ("5", "65", "120", "130"):
    for off in ("+5", "+10", "-10"):
      g = geometry(off, limit)
      assert g.badge.x + g.badge.width <= g.capsule.x + g.capsule.width - R.OFFSET_BADGE_INSET + 1e-6
      assert g.badge.x >= g.tile.x          # never pushed off the sign's own span


def test_no_badge_without_an_offset_string():
  assert geometry("").badge is None


def test_badge_follows_the_setting():
  class Plan:
    valid = True
    speed_limit_changed = False
    slc_overridden_speed = 0.0
    slc_speed_limit = 29.0
    slc_speed_limit_offset = 2.2352
  on = SL.LimitPolicy(show_speed_limits=True, speed_limit_controller=True, show_speed_limit_offset=True)
  off = SL.LimitPolicy(show_speed_limits=True, speed_limit_controller=True, show_speed_limit_offset=False)
  assert SL.speed_limit_view(on, 0, Plan, 2.23694).offset == "+5"
  assert SL.speed_limit_view(off, 0, Plan, 2.23694).offset == ""
