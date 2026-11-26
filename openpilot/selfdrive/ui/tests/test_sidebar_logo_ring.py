"""Sidebar home mark: button_home_ring.png is derived from the shipped button_home.png only, and drawn at the sidebar's
2:1 scale (HOME_BTN 180 px from a 360 px asset) it is complete, keeps a margin on all four sides and its ring top
matches its bottom (the shipped ring top is thinner and hard-edged)."""
from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parents[2] / "assets/bogpilot"
SIDEBAR = Path(__file__).resolve().parents[1] / "layouts/sidebar.py"
RING_R = 140      # the road art ends at r 136.9 px, the ring spans r 143.8-156.1 px (centre 180, 180)


def rgba(name):
  return np.array(Image.open(ASSETS / name).convert("RGBA"))


def coverage_at_half(a):
  """What the sidebar draws: the 360 px asset at scale 0.5 with bilinear filtering = a 2x2 box, on black."""
  lum = a[..., :3].astype(float).mean(-1) * a[..., 3] / 255
  return lum.reshape(180, 2, 180, 2).mean((1, 3)) / 255


def test_ring_asset_is_derived_from_the_shipped_asset_only():
  src, new = rgba("button_home.png"), rgba("button_home_ring.png")
  assert src.shape == new.shape == (360, 360, 4)
  yy, xx = np.mgrid[0:360, 0:360] + 0.5
  band = (np.hypot(xx - 180, yy - 180) >= RING_R) & (yy < 180)
  assert (new[~band] == src[~band]).all()                # art and the whole bottom half: the shipped pixels
  assert (new[band] == src[::-1][band]).all()            # ring top: the mirror of the shipped ring bottom


def test_logo_is_complete_with_a_margin_on_every_side_at_the_sidebar_scale():
  c = coverage_at_half(rgba("button_home_ring.png"))
  ys, xs = np.nonzero(c > 0.002)
  margins = dict(left=xs.min(), top=ys.min(), right=179 - xs.max(), bottom=179 - ys.max())
  assert min(margins.values()) >= 10, margins


def test_ring_top_matches_its_bottom_at_the_sidebar_scale():
  def widths(c):
    cols = range(80, 101)
    return (np.mean([c[:30, x].sum() for x in cols]), np.mean([c[150:, x].sum() for x in cols]))
  top, bottom = widths(coverage_at_half(rgba("button_home_ring.png")))
  assert abs(top - bottom) < 0.05
  old_top, old_bottom = widths(coverage_at_half(rgba("button_home.png")))
  assert old_bottom - old_top > 0.3                      # the defect this file fixes
  outer = coverage_at_half(rgba("button_home_ring.png"))[:30, 90]
  assert int(np.argmax(outer >= .9)) - int(np.argmax(outer >= .1)) >= 2   # soft outer edge at the top, like the bottom


def test_sidebar_draws_the_ring_asset_with_the_shipped_one_as_fallback():
  src = SIDEBAR.read_text()
  ring, shipped = src.index('gui_app.texture("bogpilot/button_home_ring.png")'), src.index('gui_app.texture("bogpilot/button_home.png")')
  assert ring < shipped
