"""Driving Personalities on the shared value row: existing defaults as hints, highlight, section resets.

Pure part: FollowingEditor defaults come from the existing catalog only, and a section reset touches only its own keys.
Native part (RAYLIB_BACKEND=headless): the real layout keeps every gate and gains the hint, the highlight and one
"Reset section to defaults" row per section (each personality profile, and Lead Detection).
"""
import os
from types import SimpleNamespace

import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib.phase3_following import PROFILES
from openpilot.selfdrive.ui.bogpilot import phase3_following as U
from openpilot.selfdrive.ui.bogpilot.step_defaults import reset_section


HEADLESS = pytest.mark.skipif(os.getenv("RAYLIB_BACKEND") != "headless", reason="requires authorized native headless render")

FOLLOW_DEFAULTS = {"Aggressive": 1.25, "Standard": 1.45, "Relaxed": 1.75}
# Catalog: bogpilot_defaults.py / bogpilot_params.py. Aggressive jerks 50 except Danger 100; Standard/Relaxed 100.
JERK_DEFAULTS = {
  "AggressiveJerkAcceleration": 50, "AggressiveJerkDeceleration": 50, "AggressiveJerkDanger": 100,
  "AggressiveJerkSpeed": 50, "AggressiveJerkSpeedDecrease": 50,
  "StandardJerkAcceleration": 100, "StandardJerkDeceleration": 100, "StandardJerkDanger": 100,
  "StandardJerkSpeed": 100, "StandardJerkSpeedDecrease": 100,
  "RelaxedJerkAcceleration": 100, "RelaxedJerkDeceleration": 100, "RelaxedJerkDanger": 100,
  "RelaxedJerkSpeed": 100, "RelaxedJerkSpeedDecrease": 100,
}
LEAD_DEFAULT = 35


class FakeParams:
  def __init__(self, **vals):
    self.d = dict(vals)
    self.puts = []

  def all_keys(self):
    return list(BOGPILOT_PARAMS)

  def get(self, k, *a, **kw):
    return self.d.get(k)

  def put(self, k, v, *a, **kw):
    self.puts.append((k, v))
    self.d[k] = v

  def put_bool(self, k, v, *a, **kw):
    self.put(k, bool(v))

  def remove(self, k):
    self.d.pop(k, None)


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  return ParamStore(FakeParams())


def CP(long=True):
  return SimpleNamespace(openpilotLongitudinalControl=long, radarUnavailable=False)


def editor(store, offroad=True, long=True):
  return U.FollowingEditor(CP(long=long), store, lambda: offroad)


def test_defaults_are_the_existing_ones(store):
  e = editor(store)
  for profile, value in FOLLOW_DEFAULTS.items():
    key = f"{profile}Follow"
    assert e.default(key) == value
    assert e.default(key) == float(store.default(key)) == float(U._P_FOLLOW_DEFAULT[profile])
    unit = " second" if value == 1 else " seconds"
    assert e.default_shown(key) == f"{value:.2f}{unit}"
  for key, value in JERK_DEFAULTS.items():
    assert e.default(key) == value == float(store.default(key))
    assert e.default_shown(key) == f"{value:.0f}%"
  assert e.default("LeadDetectionThreshold") == LEAD_DEFAULT == float(store.default("LeadDetectionThreshold"))
  assert e.default_shown("LeadDetectionThreshold") == "35%"
  # Toggles and the inventory reset keys are not value rows: no hint.
  for key in ("CustomPersonalities", "RelaxedPersonalityProfile", "HumanFollowing", "LongitudinalTune",
              "ResetRelaxedPersonality"):
    assert e.default(key) is None and e.default_shown(key) is None and e.at_default(key)


def test_highlight_follows_the_value(store):
  e = editor(store)
  assert e.write("CustomPersonalities", True)
  assert e.at_default("RelaxedFollow") and e.at_default("RelaxedJerkAcceleration") and e.at_default("LeadDetectionThreshold")
  assert e.write("RelaxedFollow", 2.00) and e.write("LeadDetectionThreshold", 40)
  assert not e.at_default("RelaxedFollow") and not e.at_default("LeadDetectionThreshold")
  assert e.write("RelaxedFollow", 1.75) and e.write("LeadDetectionThreshold", 35)
  assert e.at_default("RelaxedFollow") and e.at_default("LeadDetectionThreshold")


def test_section_reset_touches_only_that_profiles_keys(store):
  e = editor(store)
  assert e.write("CustomPersonalities", True)
  assert e.write("RelaxedFollow", 2.00) and e.write("RelaxedJerkAcceleration", 150)
  assert e.write("StandardFollow", 2.00) and e.write("LeadDetectionThreshold", 40)
  table = e.section_defaults(U.profile_value_keys("Relaxed"))
  assert set(table) == set(U.profile_value_keys("Relaxed"))
  assert table["RelaxedFollow"] == 1.75 and table["RelaxedJerkAcceleration"] == 100
  reset_section(table, e.write)
  assert e.value("RelaxedFollow") == 1.75 and e.value("RelaxedJerkAcceleration") == 100
  assert e.value("StandardFollow") == 2.00 and e.value("LeadDetectionThreshold") == 40


def test_reset_skips_locked_keys(store):
  box = {"offroad": True}
  e = U.FollowingEditor(CP(), store, lambda: box["offroad"])
  assert e.write("CustomPersonalities", True) and e.write("RelaxedFollow", 2.00)
  box["offroad"] = False
  assert e.section_defaults(U.profile_value_keys("Relaxed")) == {}
  box["offroad"] = True
  store.put("TuningLevel", 2)
  store.put("TuningLevelConfirmed", "1")
  # Follow is level 2, jerk rows are level 3: a Standard-level reset leaves the jerk keys alone.
  table = e.section_defaults(U.profile_value_keys("Relaxed"))
  assert "RelaxedFollow" in table and "RelaxedJerkAcceleration" not in table


@pytest.fixture
def layout_env(store, monkeypatch):
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.selfdrive.ui.bogpilot import gated_actions, tuning_level
  if not rl.is_window_ready():
    if not gui_app.big_ui():
      gui_app._width, gui_app._height = 2160, 1080
      gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
    gui_app.init_window("following section reset")
  asked = []
  monkeypatch.setattr(gated_actions, "_confirm_dialog", lambda text, yes: asked.append((text, yes)))
  tuning_level.set_store(store)
  tuning_level.invalidate()
  return asked


def make(store, section, asked, offroad=True):
  box = {"offroad": offroad}
  widget = U.make_layout(CP(), store, lambda: box["offroad"], section=section)
  widget.asked, widget.box = asked, box
  return widget


def rows_named(layout, title):
  return [i for i in layout.scroller._items if getattr(i, "title", "") == title]


def row(layout, title, index=0):
  found = rows_named(layout, title)
  return found[index]


def resets(layout):
  return rows_named(layout, "Reset section to defaults")


@HEADLESS
def test_value_rows_are_shared_rows_with_hints(layout_env, store):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedValueStepAction
  e = editor(store)
  assert e.write("CustomPersonalities", True)
  layout = make(store, "Relaxed", layout_env)
  layout.show_event()
  follow = row(layout, "Following Distance").action_item
  assert isinstance(follow, GatedValueStepAction)
  assert follow.buttons[0] == "-" and follow.buttons[-1] == "+" and follow.value_index == 1
  assert follow.hint_text == "default: 1.75 seconds" and not follow.highlighted
  jerk = row(layout, "Acceleration Smoothness").action_item
  assert isinstance(jerk, GatedValueStepAction)
  assert jerk.buttons[0] == "-" and jerk.buttons[-1] == "+"
  assert jerk.hint_text == "default: 100%" and not jerk.highlighted
  follow.callback(2)  # plus
  assert store.get_float("RelaxedFollow") == pytest.approx(1.76)
  assert row(layout, "Following Distance").action_item.highlighted


@HEADLESS
def test_section_resets_follow_their_rows_and_ask_first(layout_env, store):
  from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
  e = editor(store)
  assert e.write("CustomPersonalities", True)
  page = make(store, "personalities", layout_env)
  page.show_event()
  found = resets(page)
  assert len(found) == 3
  assert all(item.title == "Reset section to defaults" and item.indent == INDENT for item in found)
  assert all(item.is_visible for item in found)  # profile defaults are on
  e.write("RelaxedFollow", 2.00)
  e.write("StandardFollow", 2.00)
  relaxed = found[PROFILES.index("Relaxed")]
  relaxed.callback()
  assert len(page.asked) == 1 and e.value("RelaxedFollow") == 2.00  # nothing before the yes
  page.asked[0][1]()
  assert e.value("RelaxedFollow") == 1.75 and e.value("StandardFollow") == 2.00
  page.box["offroad"] = False
  assert not relaxed.action_item.enabled
  relaxed.callback()
  assert len(page.asked) == 1
  page.box["offroad"] = True
  relaxed.callback()
  page.box["offroad"] = False
  page.asked[1][1]()
  assert e.value("StandardFollow") == 2.00
  page.box["offroad"] = True
  # Lead Detection is its own section
  long_page = make(store, "longitudinal_tuning", layout_env)
  long_page.show_event()
  lead_reset = resets(long_page)
  assert len(lead_reset) == 1 and lead_reset[0].indent == 0  # parent toggle is on the Gas / Brake page
  assert lead_reset[0].is_visible
  e.write("LeadDetectionThreshold", 40)
  n_asked = len(long_page.asked)
  lead_reset[0].callback()
  assert len(long_page.asked) == n_asked + 1 and e.value("LeadDetectionThreshold") == 40  # nothing before the yes
  long_page.asked[-1][1]()
  assert e.value("LeadDetectionThreshold") == 35 and e.value("StandardFollow") == 2.00


@HEADLESS
@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_section_resets_follow_their_rows_tuning_level(layout_env, store, monkeypatch, level):
  from openpilot.selfdrive.ui.bogpilot import tuning_level
  e = editor(store)
  assert e.write("CustomPersonalities", True)
  store.put("TuningLevel", level)
  store.put("TuningLevelConfirmed", "1")
  monkeypatch.setattr(tuning_level, "effective_level", lambda *a, **k: level)
  tuning_level.set_store(store)
  tuning_level.invalidate()
  assert tuning_level.row_level("RelaxedFollow") == 2
  assert tuning_level.row_level("RelaxedJerkAcceleration") == 3
  assert tuning_level.row_level("LeadDetectionThreshold") == 3
  assert tuning_level.row_level("RelaxedPersonalityProfile") == 2
  assert tuning_level.row_level("LongitudinalTune") == 0
  page = make(store, "personalities", layout_env)
  page.show_event()
  follow_rows = rows_named(page, "Following Distance")
  jerk_rows = rows_named(page, "Acceleration Smoothness")
  found = resets(page)
  if level >= 2:
    assert len(follow_rows) == 3 and all(r.is_visible for r in follow_rows)
    assert len(found) == 3 and all(r.is_visible for r in found)
  else:
    assert follow_rows == [] or not any(r.is_visible for r in follow_rows)
    assert not any(r.is_visible for r in found)
  if level >= 3:
    assert len(jerk_rows) == 3 and all(r.is_visible for r in jerk_rows)
  else:
    assert jerk_rows == [] or not any(r.is_visible for r in jerk_rows)
  long_page = make(store, "longitudinal_tuning", layout_env)
  long_page.show_event()
  lead = rows_named(long_page, "Lead Detection Confidence Threshold")
  lead_reset = resets(long_page)
  if level >= 3:
    assert len(lead) == 1 and lead[0].is_visible
    assert len(lead_reset) == 1 and lead_reset[0].is_visible
  else:
    assert lead == [] or not any(r.is_visible for r in lead)
    assert lead_reset == [] or not any(r.is_visible for r in lead_reset)


@HEADLESS
def test_refused_section_reset_is_reported(layout_env, store, monkeypatch):
  from openpilot.selfdrive.ui.bogpilot import gated_actions
  told = []
  monkeypatch.setattr(gated_actions, "_alert", told.append)
  e = editor(store)
  assert e.write("CustomPersonalities", True) and e.write("RelaxedFollow", 2.00)
  page = make(store, "Relaxed", layout_env)
  page.show_event()
  monkeypatch.setattr(page.editor, "write", lambda *a, **k: False)
  reset = resets(page)[0]
  reset.callback()
  page.asked[-1][1]()
  assert told == [gated_actions.RESET_FAILED_TEXT]
  # The live editor used by the test helper still has the changed value (the layout's writer was the one that refused).
  assert e.value("RelaxedFollow") == 2.00
