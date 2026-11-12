"""Steering Tuning on the shared value row: existing defaults as hints, non-default highlight, section reset rows.

Pure part: TuningEditor defaults come from the existing tables only, and a section reset touches only its own keys.
Native part (RAYLIB_BACKEND=headless): the real layout keeps every gate and gains the hint, the highlight and one
"Reset section to defaults" row per section (Advanced, Quality of Life)."""
import math
import os

import pytest

from opendbc.car.tesla_ap1.override import SENSITIVITY_DEFAULT
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib.phase3_steering_tuning import numeric_rows
from openpilot.selfdrive.ui.bogpilot import phase3_steering_tuning as st
from openpilot.selfdrive.ui.bogpilot.step_defaults import reset_section

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


@pytest.fixture
def cp():
  from opendbc.car.tesla_ap1.values import CAR
  from opendbc.car.tesla_ap1.interface import CarInterface
  return CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS)


def test_defaults_are_the_existing_ones(store, cp):
  e = st.TuningEditor(cp, store, lambda: True)
  rows = {r.key: r for r in numeric_rows(cp)}
  for key in st.NUMERIC_ORDER:
    if key in rows:
      assert e.default(key) == rows[key].default
      assert e.default_shown(key) == f"{rows[key].default:.2f}"
  assert e.default("SteerRatio") == cp.steerRatio
  assert e.default(st.OVERRIDE_SENSITIVITY) == SENSITIVITY_DEFAULT
  assert e.default("PauseLateralSpeed") == float(ParamStore.default("PauseLateralSpeed")) == 0
  assert e.default_shown("PauseLateralSpeed") == "0 mph"
  assert e.default("QOLLateral") is None and e.default("AdvancedLateralTune") is None   # toggles get no hint


def test_no_car_shows_no_numeric_default(store):
  e = st.TuningEditor(lambda: None, store, lambda: True)
  for key in st.NUMERIC_ORDER:
    assert e.default(key) is None and e.default_shown(key) is None and e.at_default(key)
  assert e.section_defaults(st.NUMERIC_ORDER) == {}
  assert e.default("PauseLateralSpeed") == 0


def test_highlight_follows_the_value(store, cp):
  e = st.TuningEditor(cp, store, lambda: True)
  assert e.write("AdvancedLateralTune", True) and e.write("QOLLateral", True)
  assert all(e.at_default(k) for k in ("SteerRatio", "PauseLateralSpeed", st.OVERRIDE_SENSITIVITY))
  assert e.write("SteerRatio", cp.steerRatio + 1) and e.write("PauseLateralSpeed", 20)
  assert not e.at_default("SteerRatio") and not e.at_default("PauseLateralSpeed")
  assert e.write("SteerRatio", round(cp.steerRatio, 2))     # saved but equal to the default: not highlighted
  assert e.at_default("SteerRatio")


def test_advanced_reset_touches_only_numeric_keys(store, cp):
  e = st.TuningEditor(cp, store, lambda: True)
  for key, value in (("AdvancedLateralTune", True), ("QOLLateral", True), ("SteerRatio", cp.steerRatio + 1),
                     ("PauseLateralSpeed", 20)):
    assert e.write(key, value)
  table = e.section_defaults(st.NUMERIC_ORDER)
  assert set(table) <= set(st.NUMERIC_ORDER) and "SteerRatio" in table
  reset_section(table, lambda k, _d: e.reset(k))
  assert store.raw("SteerRatio") is None and math.isclose(e.value("SteerRatio"), cp.steerRatio)
  assert store.get_int("PauseLateralSpeed") == 20 and store.get_bool("AdvancedLateralTune") and store.get_bool("QOLLateral")


def test_reset_refused_onroad(store, cp):
  box = {"offroad": True}
  e = st.TuningEditor(cp, store, lambda: box["offroad"])
  assert e.write("AdvancedLateralTune", True) and e.write("SteerRatio", cp.steerRatio + 1)
  box["offroad"] = False
  assert e.section_defaults(st.NUMERIC_ORDER) == {}           # locked keys are left out of the reset table
  reset_section(e.section_defaults(st.NUMERIC_ORDER), lambda k, _d: e.reset(k))
  assert store.raw("SteerRatio") is not None


@pytest.fixture
def layout(store, cp, monkeypatch):
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.selfdrive.ui.bogpilot import gated_actions
  if not rl.is_window_ready():
    if not gui_app.big_ui():
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("Steering Tuning section reset")
  asked = []
  monkeypatch.setattr(gated_actions, "_confirm_dialog", lambda text, yes: asked.append((text, yes)))
  box = {"cp": None, "offroad": True}
  widget = st.make_layout(lambda: box["cp"], store, lambda: box["offroad"])
  widget.asked, widget.box, widget.cp = asked, box, cp
  return widget


def row(layout, title):
  return next(i for i in layout.scroller._items if getattr(i, "title", "") == title)


@HEADLESS
def test_value_rows_are_shared_rows_with_hints(layout, store):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedValueStepAction
  layout.box["cp"] = layout.cp
  store.put_bool("AdvancedLateralTune", True)
  store.put_bool("QOLLateral", True)
  for title, minus, plus in (("Steer Ratio", "-0.01", "+0.01"), ("Actuator Delay", "-0.01", "+0.01"),
                             ("Pause Steering Below", "-1", "+1"), ("Override Sensitivity", "-", "+")):
    a = row(layout, title).action_item
    assert isinstance(a, GatedValueStepAction)
    assert a.buttons[0] == minus and a.buttons[-1] == plus and a.value_index == 1
    assert a.hint_text.startswith("default: ") and not a.highlighted
  assert row(layout, "Override Sensitivity").action_item.hint_text == f"default: {SENSITIVITY_DEFAULT}"
  assert row(layout, "Pause Steering Below").action_item.hint_text == "default: 0 mph"
  row(layout, "Pause Steering Below").action_item.callback(2)
  assert store.get_int("PauseLateralSpeed") == 1 and row(layout, "Pause Steering Below").action_item.highlighted


@HEADLESS
def test_section_resets_follow_their_rows_and_ask_first(layout, store):
  from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
  adv, qol = layout.advanced_reset, layout.qol_reset
  assert adv.title == qol.title == "Reset section to defaults"
  titles = [getattr(i, "title", "") or "" for i in layout.scroller._items]
  assert all(t == "Reset section to defaults" or not t.startswith("Reset ") for t in titles)
  assert adv.indent == qol.indent == INDENT
  assert not adv.is_visible                                   # no car: hidden with the Advanced rows
  store.put_bool("QOLLateral", True)
  assert qol.is_visible
  layout.box["cp"] = layout.cp
  assert not adv.is_visible                                   # parent off
  store.put_bool("AdvancedLateralTune", True)
  assert adv.is_visible and adv.action_item.enabled
  e = layout.editor
  assert e.write("SteerRatio", layout.cp.steerRatio + 1) and e.write("PauseLateralSpeed", 20) and e.write(st.OVERRIDE_SENSITIVITY, 4)
  adv.callback()
  assert len(layout.asked) == 1 and store.raw("SteerRatio") is not None   # nothing before the yes
  layout.asked[0][1]()
  assert store.raw("SteerRatio") is None
  assert store.get_int("PauseLateralSpeed") == 20 and e.level() == 4
  layout.box["offroad"] = False                               # onroad: dimmed, and a late yes writes nothing
  assert not qol.action_item.enabled
  qol.callback()
  assert len(layout.asked) == 1
  layout.box["offroad"] = True
  qol.callback()
  layout.box["offroad"] = False
  layout.asked[1][1]()
  assert store.get_int("PauseLateralSpeed") == 20
  layout.box["offroad"] = True
  qol.callback()
  layout.asked[2][1]()
  assert store.get_int("PauseLateralSpeed") == 0 and e.level() == 4 and store.get_bool("QOLLateral")


@HEADLESS
@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_section_resets_follow_their_rows_tuning_level(layout, store, monkeypatch, level):
  from openpilot.selfdrive.ui.bogpilot import tuning_level
  monkeypatch.setattr(tuning_level, "effective_level", lambda *a, **k: level)
  assert tuning_level.row_level("AdvancedLateralTune") == tuning_level.row_level("SteerRatio") == 3   # bogpilot_params.py
  assert tuning_level.row_level("QOLLateral") == tuning_level.row_level("PauseLateralSpeed") == 1
  layout.box["cp"] = layout.cp
  store.put_bool("AdvancedLateralTune", True)                 # both parents on at every level
  store.put_bool("QOLLateral", True)
  for title in ("Actuator Delay", "Steer Ratio"):
    assert row(layout, title).is_visible is (level >= 3)
  assert layout.advanced_reset.is_visible is (level >= 3)    # never an orphan reset row below Developer
  assert row(layout, "Pause Steering Below").is_visible is (level >= 1)
  assert layout.qol_reset.is_visible is (level >= 1)


@HEADLESS
def test_refused_section_reset_is_reported(layout, store, monkeypatch):
  from openpilot.selfdrive.ui.bogpilot import gated_actions
  from openpilot.system.ui.widgets import confirm_dialog
  told = []                                                   # the row's default reporter: an OK dialog pushed on the app
  monkeypatch.setattr(confirm_dialog, "alert_dialog", lambda text: ("alert", text))
  monkeypatch.setattr(gated_actions.gui_app, "push_widget", told.append)
  layout.box["cp"] = layout.cp
  store.put_bool("AdvancedLateralTune", True)
  e = layout.editor
  assert e.write("SteerRatio", layout.cp.steerRatio + 1)
  monkeypatch.setattr(e, "reset", lambda key: False)         # the store refuses the write
  layout.advanced_reset.callback()
  layout.asked[-1][1]()
  assert told == [("alert", gated_actions.RESET_FAILED_TEXT)] and store.raw("SteerRatio") is not None
