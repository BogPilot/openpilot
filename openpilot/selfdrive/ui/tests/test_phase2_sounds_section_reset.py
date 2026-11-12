"""Alert Volume on the shared value row: default hint, non-default highlight, and the section reset row.

Pure part: the reset table and writer (file store in a temp dir). Native part (RAYLIB_BACKEND=headless): the real
VolumeLayout keeps its buttons, indices, lock and hide rules, and gains only the hint, the highlight and the reset row."""
import os

import pytest

from openpilot.selfdrive.ui.bogpilot import phase2_sounds as ps

HEADLESS = pytest.mark.skipif(os.getenv("RAYLIB_BACKEND") != "headless", reason="requires authorized native headless render")


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  from openpilot.selfdrive.ui import soundd
  monkeypatch.setattr(soundd, "_bogpilot_params_dir", lambda: tmp_path)
  import openpilot.common.params as p
  monkeypatch.setattr(p, "Params", lambda: type("P", (), {"get": lambda s, k: None})())
  return tmp_path


def files(path):
  return {f.name: f.read_text() for f in sorted(path.iterdir())}


def test_reset_table_is_the_existing_volume_defaults():
  from openpilot.selfdrive.ui.bogpilot.alert_volumes import BOGPILOT_VOLUME_DEFAULTS
  table = ps.volume_defaults()
  assert tuple(table) == ps.VOLUME_KEYS
  assert table == {k: BOGPILOT_VOLUME_DEFAULTS[k] for k in ps.VOLUME_KEYS}
  assert ps.PARENT_KEY not in table


def test_writer_refuses_keys_outside_the_section(store):
  for key in (ps.PARENT_KEY, "EngageVolumePreMute", "SomethingElse"):
    with pytest.raises(KeyError):
      ps.write_volume_default(key, "101")
  assert files(store) == {}


def test_reset_writes_only_volume_keys_with_defaults(store):
  from openpilot.selfdrive.ui.bogpilot.step_defaults import reset_section
  ps.set_controller(True)
  for key in ps.VOLUME_KEYS:
    ps.set_volume(key, 60)
  ps.toggle_mute("EngageVolume")                       # leaves an EngageVolumePreMute restore file
  (store / "OtherSetting").write_text("7")
  before = files(store)
  written = reset_section(ps.volume_defaults, ps.write_volume_default)
  after = files(store)
  assert written == list(ps.VOLUME_KEYS)
  assert {k for k in after if after[k] != before.get(k)} == set(ps.VOLUME_KEYS)
  assert all(after[k] == "101" for k in ps.VOLUME_KEYS)
  assert after[ps.PARENT_KEY] == "1" and after["OtherSetting"] == "7"
  assert after["EngageVolumePreMute"] == before["EngageVolumePreMute"]
  assert not ps.is_muted("EngageVolume")               # back at the default, not at the floor


def test_default_and_highlight_helpers(store):
  assert ps.default_volume("PromptVolume") == 101
  assert ps.label(ps.default_volume("PromptVolume")) == "Auto"
  assert ps.is_default_volume("PromptVolume")
  ps.set_volume("PromptVolume", 60)
  assert not ps.is_default_volume("PromptVolume")
  ps.set_volume("PromptVolume", 101)
  assert ps.is_default_volume("PromptVolume")


@pytest.fixture
def ui_modules():
  # Import the widget stack (and so the UIState singleton) before `store` stubs Params, so this file also passes
  # when it runs on its own and not only after other UI tests have built UIState.
  from openpilot.selfdrive.ui.bogpilot import gated_actions
  return gated_actions


@pytest.fixture
def layout(ui_modules, store, monkeypatch):
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  gated_actions = ui_modules
  if not rl.is_window_ready():
    if not gui_app.big_ui():   # same 2160x1080 window the other native settings tests open
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("Alert Volume section reset")
  asked = []
  monkeypatch.setattr(gated_actions, "_confirm_dialog", lambda text, yes: asked.append((text, yes)))
  widget = ps.create_volume_layout()
  widget.asked = asked
  return widget


@HEADLESS
def test_rows_keep_buttons_indices_and_gain_hint_and_highlight(layout):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedValueStepAction
  for key, row in layout.volumes.items():
    a = row.action_item
    assert isinstance(a, GatedValueStepAction)
    assert [b() if callable(b) else b for b in a.buttons] == [ps.mute_button_title(key), "-", "Auto", "+"]
    assert a.button_width == 150 and a.selected_button == 1 and a.value_index == 2
    assert a.hint_text == "default: Auto"
    assert not a.highlighted
  ps.set_volume("EngageVolume", 60)
  assert layout.volumes["EngageVolume"].action_item.highlighted
  assert not layout.volumes["DisengageVolume"].action_item.highlighted
  layout.volumes["PromptVolume"].action_item.callback(3)   # same index contract: [Mute, -, label, +]
  assert ps.read_volume("PromptVolume") == 101              # already at the top (Auto); clamps like before


@HEADLESS
def test_reset_row_follows_the_controller_and_asks_first(layout, store):
  from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
  items = layout.scroller._items
  assert items[-1] is layout.reset and layout.reset.title == "Reset section to defaults"
  assert layout.reset.indent == INDENT
  layout.refresh(force=True)
  assert not layout.reset.is_visible                         # controller off: hidden with the volume rows
  ps.set_controller(True)
  layout.refresh(force=True)
  assert layout.reset.is_visible and layout.reset.action_item.enabled
  ps.set_volume("EngageVolume", 60)
  layout.reset.callback()
  assert len(layout.asked) == 1 and ps.read_volume("EngageVolume") == 60   # nothing before the yes
  layout.asked[0][1]()
  assert ps.read_volume("EngageVolume") == 101
  assert files(store)[ps.PARENT_KEY] == "1"


@HEADLESS
@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_reset_row_follows_the_controller_tuning_level(layout, monkeypatch, level):
  from openpilot.selfdrive.ui.bogpilot import tuning_level
  monkeypatch.setattr(tuning_level, "effective_level", lambda *a, **k: level)
  assert tuning_level.row_level(ps.PARENT_KEY) == 2       # bogpilot_defaults.py: AlertVolumeControl is level 2
  ps.set_controller(True)                                 # controller on at every level
  layout.refresh(force=True)
  shown = level >= 2
  assert layout.controller.is_visible is shown
  assert all(row.is_visible is shown for row in layout.volumes.values())
  assert layout.reset.is_visible is shown                 # never an orphan reset row at L0/L1
