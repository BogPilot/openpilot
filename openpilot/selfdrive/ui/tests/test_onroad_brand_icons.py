"""Onroad BogPilot branding: the top-right Experimental/wheel button never draws (no stock wheel in any startup state)
and the sidebar logo is always the BogPilot mark (never the stock comma logo or the flag/ribbon image)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.onroad import exp_button as m

UI = Path(m.__file__).parents[1]
ASSETS = UI.parent / "assets"


class _NoDraw:
  """Stands in for pyray inside exp_button: any attribute use (a draw call, a texture load) fails the test."""
  def __getattr__(self, name):
    raise AssertionError(f"ExpButton touched pyray.{name}")


def test_render_paints_nothing_in_every_state(monkeypatch):
  b = m.ExpButton.__new__(m.ExpButton)
  b._rect = SimpleNamespace(x=0, y=0, width=192, height=192)
  b._white_color = b._black_bg = None
  monkeypatch.setattr(m, "rl", _NoDraw())
  for exp in (False, True):
    for engageable in (False, True):
      b._experimental_mode, b._engageable = exp, engageable
      b._held_mode, b._hold_end_time = None, None
      assert b._render(None) is None


def test_expbutton_is_disabled_so_taps_pass_through():
  b = m.ExpButton(192, 144)
  assert b.enabled is False
  assert b.is_pressed is False


def test_arc_tap_target_stays_enabled():
  from openpilot.selfdrive.ui.onroad.bogpilot.bogpilot_hud import ArcTapButton
  assert ArcTapButton.__new__(ArcTapButton).enabled is True


def test_no_stock_wheel_or_experimental_icon_loaded_by_onroad_code():
  src = Path(m.__file__).read_text()
  for needle in ("chffr_wheel", "experimental.png", "experimental_white", "icons/", "gui_app", "draw_texture", "draw_circle"):
    assert needle not in src, needle
  for p in (UI / "onroad").rglob("*.py"):
    if "tests" in p.parts:
      continue
    assert "chffr_wheel" not in p.read_text(), p


def test_hud_renderer_fallback_uses_the_hidden_button():
  src = (UI / "onroad/hud_renderer.py").read_text()
  assert "ExpButton(UI_CONFIG.button_size" in src  # the one fallback draw site is the (now silent) ExpButton


def test_sidebar_logo_never_stock():
  src = (UI / "layouts/sidebar.py").read_text()
  assert 'gui_app.texture("bogpilot/button_home.png")' in src
  assert "icons/bogpilot/icon_bogpilot.png" in src  # the only fallback
  for needle in ("images/button_home.png", "images/button_flag.png", "_flag_img"):
    assert needle not in src, needle
  assert "button_img = self._home_img" in src and "if self._home_valid:" in src


def test_brand_assets_exist():
  assert (ASSETS / "bogpilot/button_home.png").is_file()
  assert (ASSETS / "icons/bogpilot/icon_bogpilot.png").is_file()
