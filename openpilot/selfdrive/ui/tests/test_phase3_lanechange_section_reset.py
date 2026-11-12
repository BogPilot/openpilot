"""Lane Changes on the shared value row: existing defaults as hints, non-default highlight, section reset rows.

Pure part: the reset tables are the existing defaults only, and a section reset writes only its own keys.
Native part (RAYLIB_BACKEND=headless): the real layout keeps every gate and gains the hint, the highlight and one
"Reset section to defaults" row per section (Automatic Lane Changes, Lane Changes speed)."""
import os

import pytest

from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib.phase3_lanechange import LANE_CHANGE_ACK, configure
from openpilot.selfdrive.ui.bogpilot import phase3_lanechange as LC
from openpilot.selfdrive.ui.bogpilot.step_defaults import default_hint, differs_from_default, reset_section

HEADLESS = pytest.mark.skipif(os.getenv("RAYLIB_BACKEND") != "headless", reason="requires authorized native headless render")


class MemoryParams:
  def __init__(self): self.data = {}
  def all_keys(self): return []
  def get(self, key): return self.data.get(key)
  def put(self, key, value): self.data[key] = str(value)
  def remove(self, key): self.data.pop(key, None)


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  return ParamStore(MemoryParams())


def adopt(store, *, nudgeless=True, enabled=True):
  store.put_bool(LANE_CHANGE_ACK, True)
  store.put_bool("LaneChanges", enabled)
  store.put_bool("NudgelessLaneChange", nudgeless)
  if hasattr(store, "invalidate"):
    store.invalidate()
  return store


def test_defaults_are_the_existing_ones(store):
  # Sources: bogpilot_defaults.py / BOGPILOT_PARAMS, plus the consumer fallback at controls/lib/phase3_lanechange.py:134.
  assert LC.STEP_DEFAULTS == {
    "LaneChangeTime": "1.0",
    "LaneDetectionWidth": "0",
    "MinimumLaneChangeSpeed": "20.0",
  }
  assert LC.format_step_value(LC.STEP_DEFAULTS["LaneChangeTime"]) == "1"
  assert LC.format_step_value(LC.STEP_DEFAULTS["LaneDetectionWidth"]) == "0"
  assert LC.format_step_value(LC.STEP_DEFAULTS["MinimumLaneChangeSpeed"]) == "20"
  adopt(store)
  assert LC.step_is_default(store, "LaneChangeTime")
  assert LC.step_is_default(store, "LaneDetectionWidth")
  assert LC.step_is_default(store, "MinimumLaneChangeSpeed")
  store.put("LaneChangeTime", "2.0")
  assert not LC.step_is_default(store, "LaneChangeTime")
  assert LC.step_is_default(store, "LaneDetectionWidth")
  store.put("LaneChangeTime", "1.0")
  assert LC.step_is_default(store, "LaneChangeTime")
  assert default_hint(LC.format_step_value("1.0")) == "default: 1"
  assert not differs_from_default("1", "1.0")


def test_nudgeless_reset_writes_only_delay_and_width(store):
  adopt(store)
  store.put("LaneChangeTime", "2.5")
  store.put("LaneDetectionWidth", "3.0")
  store.put("MinimumLaneChangeSpeed", "30.0")
  store.put_bool("OneLaneChange", False)
  written = reset_section({k: LC.STEP_DEFAULTS[k] for k in LC.NUDGELESS_STEP_KEYS}, store.put)
  assert written == list(LC.NUDGELESS_STEP_KEYS)
  assert store.get("LaneChangeTime") == "1.0"
  assert store.get("LaneDetectionWidth") == "0"
  assert store.get("MinimumLaneChangeSpeed") == "30.0"   # other section unchanged
  assert store.get_bool("OneLaneChange") is False


def test_speed_reset_writes_only_the_speed_key(store):
  adopt(store)
  store.put("LaneChangeTime", "2.5")
  store.put("MinimumLaneChangeSpeed", "30.0")
  written = reset_section({k: LC.STEP_DEFAULTS[k] for k in LC.SPEED_STEP_KEYS}, store.put)
  assert written == ["MinimumLaneChangeSpeed"]
  assert store.get("MinimumLaneChangeSpeed") == "20.0"
  assert store.get("LaneChangeTime") == "2.5"


@pytest.fixture
def ui_modules():
  from openpilot.selfdrive.ui.bogpilot import gated_actions
  return gated_actions


@pytest.fixture
def layout(ui_modules, store, monkeypatch):
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  gated_actions = ui_modules
  if not rl.is_window_ready():
    if not gui_app.big_ui():
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("Lane Changes section reset")
  asked = []
  monkeypatch.setattr(gated_actions, "_confirm_dialog", lambda text, yes: asked.append((text, yes)))
  adopt(store)
  widget = LC.LaneChangeLayout(store, runtime_integrated=True, offroad=lambda: True)
  widget.asked = asked
  return widget


@HEADLESS
def test_rows_use_the_shared_value_row_with_hint_and_highlight(layout, store):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedValueStepAction
  from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
  expected_hint = {
    "LaneChangeTime": "default: 1",
    "LaneDetectionWidth": "default: 0",
    "MinimumLaneChangeSpeed": "default: 20",
  }
  for key, row in layout.steps.items():
    a = row.action_item
    assert isinstance(a, GatedValueStepAction)
    shown = [b() if callable(b) else b for b in a.buttons]
    assert shown == ["-", LC.format_step_value(store.get_float(key)), "+"]
    assert a.value_index == 1
    assert a.hint_text == expected_hint[key]
    assert not a.highlighted
  store.put("LaneChangeTime", "2.0")
  if hasattr(store, "invalidate"):
    store.invalidate()
  assert layout.steps["LaneChangeTime"].action_item.highlighted
  assert not layout.steps["LaneDetectionWidth"].action_item.highlighted
  # Delay and width sit under Automatic Lane Changes; speed under Lane Changes.
  assert layout.steps["LaneChangeTime"].indent == 2 * INDENT
  assert layout.steps["LaneDetectionWidth"].indent == 2 * INDENT
  assert layout.steps["MinimumLaneChangeSpeed"].indent == INDENT


@HEADLESS
def test_reset_rows_follow_their_value_rows_and_ask_first(layout, store):
  from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
  from openpilot.selfdrive.ui.bogpilot.gated_actions import RESET_SECTION_TITLE
  nudge = layout.resets["NudgelessLaneChange"]
  speed = layout.resets["LaneChanges"]
  assert nudge is not None and speed is not None
  assert nudge.title == RESET_SECTION_TITLE and speed.title == RESET_SECTION_TITLE
  assert nudge.indent == 2 * INDENT and speed.indent == INDENT
  assert nudge.is_visible and speed.is_visible
  store.put("LaneChangeTime", "2.5")
  store.put("MinimumLaneChangeSpeed", "30.0")
  if hasattr(store, "invalidate"):
    store.invalidate()
  nudge.callback()
  assert len(layout.asked) == 1 and store.get("LaneChangeTime") == "2.5"   # nothing before the yes
  layout.asked[0][1]()
  assert store.get("LaneChangeTime") == "1.0"
  assert store.get("MinimumLaneChangeSpeed") == "30.0"   # other section left alone
  speed.callback()
  assert len(layout.asked) == 2 and store.get("MinimumLaneChangeSpeed") == "30.0"
  layout.asked[1][1]()
  assert store.get("MinimumLaneChangeSpeed") == "20.0"


@HEADLESS
def test_nudgeless_reset_hides_when_automatic_lane_changes_is_off(layout, store):
  # Turning the parent off rebuilds the page (same as a toggle); the delay/width reset must not be left behind.
  configure(store, "NudgelessLaneChange", False)
  layout._build()
  layout.scroller.show_event()
  assert "LaneChangeTime" not in layout.steps
  assert layout.resets["NudgelessLaneChange"] is None
  assert "MinimumLaneChangeSpeed" in layout.steps
  assert layout.resets["LaneChanges"] is not None and layout.resets["LaneChanges"].is_visible


@HEADLESS
@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_reset_rows_follow_their_rows_tuning_level(layout, monkeypatch, level):
  from openpilot.selfdrive.ui.bogpilot import tuning_level
  monkeypatch.setattr(tuning_level, "effective_level", lambda *a, **k: level)
  # Delay/width are level 1; speed is level 2 (bogpilot_defaults.py / BOGPILOT_PARAMS).
  delay_shown = level >= 1
  speed_shown = level >= 2
  assert layout.steps["LaneChangeTime"].is_visible is delay_shown
  assert layout.steps["LaneDetectionWidth"].is_visible is delay_shown
  assert layout.steps["MinimumLaneChangeSpeed"].is_visible is speed_shown
  assert layout.resets["NudgelessLaneChange"].is_visible is delay_shown
  assert layout.resets["LaneChanges"].is_visible is speed_shown
