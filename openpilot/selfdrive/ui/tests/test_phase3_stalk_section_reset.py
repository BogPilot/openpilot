"""Stalk hold rows on the shared value row: DEFAULT_HOLD_S hint, highlight, and one section reset.

Pure part: the reset table is the existing DEFAULT_HOLD_S for both hold keys only.
Native part (RAYLIB_BACKEND=headless): the real layout keeps the experimental_supported / offroad gate
and gains the hint, the highlight and one "Reset section to defaults" row for the two hold keys."""
import os
from types import SimpleNamespace as NS

import pytest

from opendbc.car.tesla_ap1.phase3_stalk_controls import AP1, DEFAULT_HOLD_S, Store
from openpilot.selfdrive.ui.bogpilot.step_defaults import default_hint, differs_from_default, reset_section

HEADLESS = pytest.mark.skipif(os.getenv("RAYLIB_BACKEND") != "headless", reason="requires authorized native headless render")


def test_hold_default_is_the_existing_engine_constant():
  assert DEFAULT_HOLD_S == 1.23
  assert default_hint(f"{DEFAULT_HOLD_S:.2f} s") == "default: 1.23 s"
  assert not differs_from_default(1.23, DEFAULT_HOLD_S)
  assert differs_from_default(1.24, DEFAULT_HOLD_S)


def test_reset_writes_only_the_two_hold_keys(tmp_path):
  store = Store(tmp_path / "settings")
  store.write("pull_hold_s", 1.10)
  store.write("push_hold_s", 5.00)
  written = reset_section({"pull_hold_s": DEFAULT_HOLD_S, "push_hold_s": DEFAULT_HOLD_S}, store.write)
  assert written == ["pull_hold_s", "push_hold_s"]
  settings = store.read()
  assert settings.pull_hold_s == DEFAULT_HOLD_S
  assert settings.push_hold_s == DEFAULT_HOLD_S


@pytest.fixture
def ui_modules():
  from openpilot.selfdrive.ui.bogpilot import gated_actions
  return gated_actions


@pytest.fixture
def layout(ui_modules, tmp_path, monkeypatch):
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.selfdrive.ui.bogpilot.phase3_stalk_controls import create_stalk_controls_layout
  gated_actions = ui_modules
  if not rl.is_window_ready():
    if not gui_app.big_ui():
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("Stalk hold section reset")
  asked = []
  monkeypatch.setattr(gated_actions, "_confirm_dialog", lambda text, yes: asked.append((text, yes)))
  car = NS(carFingerprint=AP1, dashcamOnly=False, passive=False, openpilotLongitudinalControl=True)
  monkeypatch.setattr(ui_state, "CP", car, raising=False)
  monkeypatch.setattr(ui_state, "is_offroad", lambda: True, raising=False)
  widget = create_stalk_controls_layout(Store(tmp_path / "settings"))
  widget.asked = asked
  widget.car = car
  return widget


@HEADLESS
def test_hold_rows_use_the_shared_value_row_with_hint_and_highlight(layout):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedValueStepAction
  for row in layout.delays.values():
    a = row.action_item
    assert isinstance(a, GatedValueStepAction)
    assert [b() if callable(b) else b for b in a.buttons] == ["-", "1.23 s", "+"]
    assert a.value_index == 1
    assert a.hint_text == "default: 1.23 s"
    assert not a.highlighted
    assert row.is_visible
  layout.model.write("pull_hold_s", 1.10)
  layout.refresh()
  assert layout.delays["pull_hold_s"].action_item.highlighted
  assert not layout.delays["push_hold_s"].action_item.highlighted


@HEADLESS
def test_reset_row_follows_the_hold_rows_and_asks_first(layout):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import RESET_SECTION_TITLE
  items = layout.scroller._items
  assert items[-2] is layout.reset and layout.reset.title == RESET_SECTION_TITLE
  assert layout.reset.is_visible and layout.reset.action_item.enabled
  assert layout.model.write("pull_hold_s", 1.10)
  assert layout.model.write("push_hold_s", 5.00)
  layout.refresh()
  layout.reset.callback()
  assert len(layout.asked) == 1
  assert layout.model.store.read().pull_hold_s == 1.10   # nothing before the yes
  layout.asked[0][1]()
  settings = layout.model.store.read()
  assert settings.pull_hold_s == DEFAULT_HOLD_S
  assert settings.push_hold_s == DEFAULT_HOLD_S


@HEADLESS
def test_reset_row_hides_when_the_hold_rows_hide(layout):
  # Same capability gate as the hold rows: experimental_supported requires openpilot longitudinal control.
  layout.car.openpilotLongitudinalControl = False
  layout.refresh()
  assert not layout.delays["pull_hold_s"].is_visible
  assert not layout.delays["push_hold_s"].is_visible
  assert not layout.reset.is_visible
  layout.car.openpilotLongitudinalControl = True
  layout.refresh()
  assert layout.delays["pull_hold_s"].is_visible
  assert layout.reset.is_visible


@HEADLESS
def test_reset_is_locked_onroad(layout, ui_modules, monkeypatch):
  from openpilot.selfdrive.ui.ui_state import ui_state
  monkeypatch.setattr(ui_state, "is_offroad", lambda: False, raising=False)
  # The menu reads offroad through the callable captured at layout construction; step through the model instead.
  layout.model.offroad = lambda: False
  layout.refresh()
  assert not layout.reset.action_item.enabled
  layout.reset.callback()
  # A locked tap must not open the confirm dialog.
  assert layout.asked == []
