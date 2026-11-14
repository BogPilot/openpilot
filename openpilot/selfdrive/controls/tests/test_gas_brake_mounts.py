"""Gas / Brake mounts: Driving Personalities, Longitudinal Tuning following rows and Speed Limit Controller pages.

Real compiled-Params ParamStore, real widgets (font stubbed, no rendered-frame claim). Each test drives the real rows and
reads the result back through the consumer's own reader (FollowingToggles.read / onroad_toggles path), so a row that is
mounted but writes nothing the planner reads fails here.
"""
import pytest
import pyray as rl
from opendbc.car.structs import car
from openpilot.common.bogpilot_store import ParamStore
from openpilot.common.params import Params
from openpilot.selfdrive.controls.lib import phase3_following as F
from openpilot.selfdrive.controls.lib.phase3_long_accel import CEM_REMOVED
from openpilot.selfdrive.controls.lib.phase3_long_accel import PROFILE_ACK
from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake as GB
from openpilot.selfdrive.ui.bogpilot.nesting import INDENT
from openpilot.system.ui.lib.application import gui_app


@pytest.fixture(scope="module", autouse=True)
def window():
  original = gui_app.font
  gui_app.font = lambda *a, **kw: rl.Font()
  yield
  gui_app.font = original


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "prefs"))
  s = ParamStore(params=Params(str(tmp_path / "native")))
  s.put_bool("TuningLevelConfirmed", True, block=True)
  s.put("TuningLevel", 3, block=True)
  return s


GENERIC = "TESLA_MODEL_3"     # not a legacy tesla_ap1 platform: the Longitudinal Tuning group starts OFF until the owner flips it
                              # (on TESLA_AP1_MODELS/MODELX/PREAP it starts ON, see test_gas_brake_profiles_default_on.py)

PREAP = "TESLA_PREAP_MODELS"

def make_cp(long=True, fingerprint="TESLA_AP1_MODELS", radar=False):
  cp = car.CarParams.new_message()
  cp.openpilotLongitudinalControl = long
  cp.brand = "tesla"
  cp.carFingerprint = fingerprint
  cp.radarUnavailable = not radar
  cp.longitudinalTuning.kiBP = [0.0]
  cp.longitudinalTuning.kiV = [0.2]
  return cp


def page_for(store, cp=None, offroad=True):
  cp = make_cp() if cp is None else cp
  flag = [offroad]
  page = GB.create_gas_brake_layout(store, cp_source=lambda: cp, can_edit=lambda: flag[0])
  page.show_event()
  return page, flag


def rows(widget):
  w = widget
  while True:
    if w.__class__.__name__ == "GasBrakeLayout":
      w = w.root
    elif hasattr(w, "_current"):          # nested panel -> its current inner page
      w = w._current
    elif hasattr(w, "scroller"):
      w = w.scroller
    else:
      return list(w._items)


class _Manage:
  def __init__(self, item):
    self.item = item

  def callback(self):
    self.item.action_item.manage._click_callback()


def manage(widget, title):
  """A combined switch + MANAGE row (the 0.9.7 manage control), on the Gas / Brake root or a profile."""
  item = titled(widget, title)
  assert hasattr(item.action_item, "toggle") and hasattr(item.action_item, "manage")
  return _Manage(item)


def ensure_on(store, widget, title, key):
  """Profile switches ship on: only tap when off, so the page below stays open."""
  store.invalidate()
  if not store.get_bool(key):
    switch(widget, title)
  assert store.get_bool(key)


def titled(widget, title):
  found = [i for i in rows(widget) if i.title == title]
  assert found, (title, [i.title for i in rows(widget)])
  return found[0]


def switch(widget, title):
  titled(widget, title).action_item.toggle._handle_mouse_release(None)


def titles(widget):
  return [i.title for i in rows(widget)]


# ------------------------------------------------------------------------------------------------------------ root menu
def test_root_entries_follow_the_097_order(store):
  cp = make_cp()
  assert [(k, t) for k, t, _ in GB.root_entries(store, cp)] == [
    ("advanced", "Advanced Longitudinal Tuning"),   # no Conditional Experimental Mode: removed
    ("personalities", "Driving Personalities"), ("profiles", "Longitudinal Tuning"),
    ("qol", "Quality of Life"), ("slc", "Speed Limit Controller")]


def test_speed_limit_controller_is_hidden_for_a_car_its_consumer_does_not_drive(store):
  keys = [k for k, _, _ in GB.root_entries(store, make_cp(fingerprint="TESLA_MODEL_3"))]
  assert "slc" not in keys and "personalities" in keys
  # no CarParams yet: the entry is listed (greyed like the others), never hidden by an unknown car
  assert "slc" in [k for k, _, _ in GB.root_entries(store, None)]


def test_speed_limit_controller_page_on_preap_with_the_pedal_only(store):
  def keys(cp):
    return [k for k, _, _ in GB.root_entries(store, cp)]
  assert "slc" in keys(make_cp(fingerprint=PREAP))                        # Pre-AP with the pedal: openpilot longitudinal
  assert "slc" not in keys(make_cp(long=False, fingerprint=PREAP))        # Pre-AP on stock cruise: the consumer does not run
  assert "slc" not in keys(make_cp(long=False, fingerprint="TESLA_AP1_MODELX"))
  assert "slc" in keys(make_cp(long=False))                               # AP1 Model S unchanged (listed, greyed)
  assert not GB.tap_from_zero_visible(store, make_cp(fingerprint=PREAP))  # the standstill tap row stays AP1 Model S only

def test_tuning_level_hides_rows_like_the_stock_menu(store):
  store.put("TuningLevel", 0, block=True)
  store.invalidate()
  keys = [k for k, _, _ in GB.root_entries(store, make_cp())]
  assert ("personalities" in keys) == store.honoured("CustomPersonalities")
  assert ("slc" in keys) == store.honoured("SpeedLimitController")


def test_new_entries_are_greyed_without_openpilot_longitudinal(store):
  page, _ = page_for(store, make_cp(long=False))
  for title in ("Driving Personalities", "Speed Limit Controller"):
    assert titled(page, title).action_item.enabled is False


# ------------------------------------------------------------------------------------------------- Driving Personalities
def test_personalities_toggle_and_profile_values_reach_the_planner_reader(store):
  cp = make_cp()
  page, _ = page_for(store, cp)
  root = titled(page, "Driving Personalities")
  assert hasattr(root.action_item, "toggle") and hasattr(root.action_item, "manage")
  assert root.action_item.manage_enabled() is False                    # MANAGE only while the switch is on
  assert F.FollowingToggles.read(store, cp).custom_personalities is False
  switch(page, "Driving Personalities")
  assert store.get_bool("CustomPersonalities") is True
  assert F.FollowingToggles.read(store, cp).custom_personalities is True
  assert root.action_item.manage_enabled() is True

  # MANAGE on the Gas / Brake root opens ONE inline page: Aggressive, Standard, Relaxed, each followed by its own rows
  manage(page, "Driving Personalities").callback()
  panel = page.panel
  assert page.navigation_title == "Driving Personalities"
  ensure_on(store, panel, "Standard", "StandardPersonalityProfile")
  own = ["Following Distance", "Acceleration Smoothness", "Braking Smoothness", "Safety Gap Bias",
         "Slowdown Response", "Speed-Up Response", "Reset section to defaults"]   # one section reset per profile
  assert [x for x in titles(panel) if x] == ["Aggressive", *own, "Standard", *own, "Relaxed", *own]
  standard = titled(panel, "Standard")
  at = rows(panel).index(standard)
  assert standard.indent == 0 and all(i.indent == INDENT for i in rows(panel)[at + 1:at + 1 + 7])   # 6 value rows + section reset
  follow = [i for i in rows(panel)[at:] if i.title == "Following Distance"][0]   # Standard's own shared value row
  before = F.FollowingToggles.read(store, cp).standard_follow
  press(follow, +1)
  assert F.FollowingToggles.read(store, cp).standard_follow == pytest.approx(before + 0.01)


def test_a_profile_switch_shows_and_hides_only_its_own_rows(store):
  cp = make_cp()
  page, _ = page_for(store, cp)
  switch(page, "Driving Personalities")
  manage(page, "Driving Personalities").callback()
  ensure_on(store, page.panel, "Aggressive", "AggressivePersonalityProfile")
  assert len([i for i in rows(page.panel) if i.title == "Aggressive"]) == 1
  saved = store.get_float("AggressiveFollow")
  switch(page.panel, "Aggressive")                               # the row's own switch writes the profile key
  assert store.get_bool("AggressivePersonalityProfile") is False
  t = [x for x in titles(page.panel) if x]
  assert t[0] == "Aggressive" and t[1] == "Standard"                    # Aggressive's rows are gone, the row stays
  assert t.count("Following Distance") == 2                            # Standard and Relaxed keep theirs
  assert store.get_float("AggressiveFollow") == saved                   # hidden, not reset
  switch(page.panel, "Aggressive")
  assert [x for x in titles(page.panel) if x][1] == "Following Distance"


def test_back_hands_the_inline_page_back_to_the_gas_brake_page(store):
  page, _ = page_for(store)
  switch(page, "Driving Personalities")
  manage(page, "Driving Personalities").callback()
  assert page.navigation_title == "Driving Personalities"            # header stays on the group name
  assert page.navigation_back() is True and page.panel is None       # no inner pages: the Gas / Brake page closes the panel
  assert page.navigation_title == ""
  assert page.navigation_back() is False


def test_reset_to_defaults_only_runs_after_the_confirmation_says_yes(store, monkeypatch):
  cp = make_cp()
  asked = []
  monkeypatch.setattr("openpilot.selfdrive.ui.bogpilot.phase3_gas_brake_mounts._request_confirm",
                      lambda text, on_yes: asked.append((text, on_yes)))   # the section reset asks through the mount
  page, _ = page_for(store, cp)
  switch(page, "Driving Personalities")
  manage(page, "Driving Personalities").callback()
  panel = page.panel
  ensure_on(store, panel, "Aggressive", "AggressivePersonalityProfile")
  store.put("AggressiveFollow", 2.5, block=True)
  store.invalidate()
  reset_rows(panel)[0].callback()                                       # Aggressive's section reset comes first
  assert len(asked) == 1 and "<b>" not in asked[0][0]
  assert store.get_float("AggressiveFollow") == pytest.approx(2.5)        # nothing yet
  asked[0][1]()
  assert store.get_float("AggressiveFollow") == pytest.approx(1.25)


def test_personality_writes_are_refused_while_the_car_is_on(store):
  page, flag = page_for(store)
  flag[0] = False
  switch(page, "Driving Personalities")
  assert store.raw("CustomPersonalities") in (None, "0") and not store.get_bool("CustomPersonalities")


# ---------------------------------------------------------------------------------------------- Longitudinal Tuning rows
def test_longitudinal_tuning_shows_following_rows_only_once_the_group_is_on(store):
  cp = make_cp(fingerprint=GENERIC)
  page, _ = page_for(store, cp)
  page.open_panel("profiles")
  assert titles(page.panel)[0] == "Longitudinal Tuning"
  assert "Human-Like Following" not in titles(page.panel)            # group still off: saved values stay, nothing shown
  switch(page.panel, "Longitudinal Tuning")
  t = titles(page.panel)
  assert t[:5] == ["Longitudinal Tuning", "Acceleration Profile", "Deceleration Profile", "Human-Like Acceleration",
                   "Human-Like Following"]
  assert "Lead Detection Confidence Threshold" in t
  assert "Human-Like Lane Changes" not in t                           # no radar on this car

  before = F.FollowingToggles.read(store, cp).human_following
  switch(page.panel, "Human-Like Following")
  assert F.FollowingToggles.read(store, cp).human_following is (not before)
  assert store.get_bool("HumanFollowing") is (not before)

  press(titled(page.panel, "Lead Detection Confidence Threshold"), +1)   # shared value row, + button
  assert F.FollowingToggles.read(store, cp).lead_detection_probability == pytest.approx(0.36)


def test_human_lane_change_row_appears_with_radar_and_writes_its_own_key(store):
  cp = make_cp(radar=True, fingerprint=GENERIC)
  page, _ = page_for(store, cp)
  page.open_panel("profiles")
  switch(page.panel, "Longitudinal Tuning")
  t = titles(page.panel)
  assert t.index("Human-Like Lane Changes") == t.index("Human-Like Following") + 1
  switch(page.panel, "Human-Like Lane Changes")
  import time
  for _ in range(50):                       # that row's own module writes without the blocking keyword
    store.invalidate()
    if store.get_bool("HumanLaneChanges"):
      break
    time.sleep(0.02)
  assert store.get_bool("HumanLaneChanges") is True


def test_human_lane_change_row_is_on_by_default_on_the_ap1_model_s_and_a_tap_turns_it_off(store):
  from openpilot.selfdrive.controls.lib.phase3_lanechange import read_settings
  cp = make_cp(radar=True)                     # AP1 Model S: radar and openpilot longitudinal; Longitudinal Tuning starts on
  page, _ = page_for(store, cp)
  page.open_panel("profiles")
  t = titles(page.panel)
  assert t.index("Human-Like Lane Changes") == t.index("Human-Like Following") + 1
  assert titled(page.panel, "Human-Like Lane Changes").action_item.toggle.get_state() is True
  assert read_settings(store, cp).human is True
  switch(page.panel, "Human-Like Lane Changes")
  import time
  for _ in range(50):                          # that row's own module writes without the blocking keyword
    store.invalidate()
    if not store.get_bool("HumanLaneChanges"):
      break
    time.sleep(0.02)
  assert store.get_bool("HumanLaneChanges") is False
  assert read_settings(store, cp).human is False

def test_following_rows_follow_the_tuning_level_and_the_longitudinal_lock(store):
  page, flag = page_for(store, make_cp(long=False))
  page.open_panel("profiles")
  assert "Human-Like Following" not in titles(page.panel)


# ----------------------------------------------------------------------------------------------- Speed Limit Controller
def test_speed_limit_controller_rows_write_what_the_planner_reads(store):
  from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss
  page, _ = page_for(store)
  page.open_panel("slc")
  panel = page.panel
  assert titles(panel)[0] == "Speed Limit Controller"
  t = titles(panel)
  assert "Fallback Speed" in t and "Override Speed" in t
  assert {"Speed Limit Offsets", "Quality of Life", "Visual Settings"} <= set(t)
  # Override Speed choice -> SLCOverride (the buttons are None / Set With Gas Pedal / Max Set Speed)
  titled(panel, "Override Speed").action_item.callback(2)
  assert store.get_int("SLCOverride") == 2
  # sub page: offsets
  [i for i in rows(panel) if i.title == "Speed Limit Offsets"][0].callback()
  assert page.navigation_title == "Speed Limit Controller"           # header stays on the group name
  offset = [i for i in rows(panel) if i.title.startswith("Speed Offset (")][0]   # the shared value row
  before = store.get_int("Offset1")
  press(offset, +1)
  assert store.get_int("Offset1") == before + 1
  from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
  assert sc.slc_adopted(store)
  assert page.navigation_back() is True and page.navigation_title == "Speed Limit Controller"
  # quality of life: confirmation toggle
  [i for i in rows(panel) if i.title == "Quality of Life"][0].callback()
  switch(panel, "Confirm New Speed Limits")
  assert store.get_bool("SLCConfirmation") is True
  assert "Lower Limits" in titles(panel) and "Higher Limits" in titles(panel)


def test_speed_limit_controller_toggle_off_hides_its_children(store):
  page, _ = page_for(store)
  page.open_panel("slc")
  switch(page.panel, "Speed Limit Controller")
  assert store.get_bool("SpeedLimitController") is False
  assert titles(page.panel) == ["Speed Limit Controller"]


def test_speed_limit_controller_page_on_preap_hides_the_source_rows_and_turns_off(store):
  from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
  cp = make_cp(fingerprint=PREAP)                     # pcmCruise stays False: the pedal
  page, _ = page_for(store, cp)
  page.open_panel("slc")
  t = titles(page.panel)
  assert t[0] == "Speed Limit Controller" and "Fallback Speed" in t and "Override Speed" in t
  assert not {"Priority 1", "Priority 2", "Priority 3", "Look-ahead"} & set(t)
  assert {"Speed Limit Offsets", "Quality of Life", "Visual Settings"} <= set(t)
  [i for i in rows(page.panel) if i.title == "Quality of Life"][0].callback()
  assert "Match Speed Limit on Engage" in titles(page.panel)
  assert page.navigation_back() is True
  assert onroad_toggles(store, cp).speed_limit_controller is True        # on by default
  switch(page.panel, "Speed Limit Controller")
  assert store.get_bool("SpeedLimitController") is False
  assert onroad_toggles(store, cp).speed_limit_controller is False       # the planner's switch is off
  assert titles(page.panel) == ["Speed Limit Controller"]

def test_speed_limit_controller_writes_are_refused_while_the_car_is_on(store):
  page, flag = page_for(store)
  page.open_panel("slc")
  flag[0] = False
  before = store.get_bool("SpeedLimitController")
  switch(page.panel, "Speed Limit Controller")
  assert store.get_bool("SpeedLimitController") is before


# -------------------------------------------------------------------------------------------------- no writes on open
def test_opening_every_new_page_never_writes_a_preference_or_marker(store, tmp_path):
  watched = ("CustomPersonalities", "HumanFollowing", "HumanLaneChanges", "LeadDetectionThreshold", "SpeedLimitController",
             "SLCFallback", "SLCOverride", "SLCConfirmation", "ShowSLCOffset", "LongitudinalTune", PROFILE_ACK,
             F.PERSONALITY_ACK, F.HUMAN_FOLLOWING_ACK, F.LEAD_DETECTION_ACK, "Phase3SpeedLimitEnabled",
             *(f"Offset{i}" for i in range(1, 8)), *(f"{p}Follow" for p in F.PROFILES))
  before = {k: store.raw(k) for k in watched}
  page, _ = page_for(store, make_cp(radar=True))
  for key in ("personalities", "profiles", "slc"):
    page.open_panel(key)
    page.show_event()
    page.hide_event()
    page.show_event()
  page.close_panel()
  assert {k: store.raw(k) for k in watched} == before


# ------------------------------------------------------------------------------------------------------------- nesting
def test_longitudinal_tuning_rows_and_human_lane_changes_sit_under_the_group_switch(store):
  """Human-Like Lane Changes lives here (gated by Longitudinal Tuning plus radar), not on the Lane Changes page."""
  page, _ = page_for(store, make_cp(radar=True, fingerprint=GENERIC))
  page.open_panel("profiles")
  switch(page.panel, "Longitudinal Tuning")
  assert titled(page.panel, "Longitudinal Tuning").indent == 0
  for title in ("Acceleration Profile", "Deceleration Profile", "Human-Like Acceleration", "Human-Like Following",
                "Human-Like Lane Changes", "Lead Detection Confidence Threshold"):
    assert titled(page.panel, title).indent == INDENT, title
  after = rows(page.panel)[rows(page.panel).index(titled(page.panel, "Lead Detection Confidence Threshold")):]
  assert all(i.indent == INDENT for i in after)                 # its value and -1 / +1 rows too


@pytest.mark.skipif(CEM_REMOVED, reason="Conditional Experimental Mode is removed (the full port is maintained separately)")
def test_conditional_experimental_children_nest_under_the_switch_and_their_own_parent(store):
  page, _ = page_for(store, make_cp())
  page.open_panel("conditional")
  switch(page.panel, "Conditional Experimental Mode")
  if not store.get_bool("CECurves"):
    switch(page.panel, "Curve Detected Ahead")
  t = titles(page.panel)
  assert not any(x.startswith(" ") for x in t)                  # indentation is the row's, not leading spaces
  assert titled(page.panel, "Conditional Experimental Mode").indent == 0
  assert titled(page.panel, "Below").indent == INDENT
  assert titled(page.panel, "Curve Detected Ahead").indent == INDENT
  with_lead = [i for i in rows(page.panel) if i.title == "With Lead"]
  assert sorted(i.indent for i in with_lead) == [2 * INDENT] * len(with_lead) and len(with_lead) == 2   # speed with a lead, curve with a lead
  switch(page.panel, "Curve Detected Ahead")                    # off: its child goes, the sibling "With Lead" stays
  assert [i.indent for i in rows(page.panel) if i.title == "With Lead"] == [2 * INDENT]
  assert store.get_bool("CECurvesLead") in (True, False)        # saved value left alone


def test_the_advanced_longitudinal_rows_sit_under_their_switch(store):
  page, _ = page_for(store, make_cp())
  page.open_panel("advanced")
  switch(page.panel, "Advanced Longitudinal Tuning")
  rs = rows(page.panel)
  assert rs[0].indent == 0 and len(rs) > 1 and all(i.indent == INDENT for i in rs[1:])


# ------------------------------------------------------------------------------------- value rows and section resets
def press(item, step):
  """A tap on the shared value row's - (step -1) or + (step +1) button: the same callback a tap dispatches."""
  action = item.action_item
  action.callback(action.value_index + step)


def confirm_yes(monkeypatch):
  """The section reset asks first; answer yes straight away and record the question."""
  from openpilot.selfdrive.ui.bogpilot import gated_actions
  asked = []

  def ask(text, on_yes):
    asked.append(text)
    on_yes()
  monkeypatch.setattr(gated_actions, "_confirm_dialog", ask)
  return asked


def reset_rows(widget):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import RESET_SECTION_TITLE
  return [i for i in rows(widget) if i.title == RESET_SECTION_TITLE]


def test_standstill_tap_speed_is_one_value_row_with_its_default_and_a_reset(store, monkeypatch):
  from openpilot.selfdrive.ui.bogpilot.gated_actions import GatedValueStepAction
  asked = confirm_yes(monkeypatch)
  page, flag = page_for(store)
  tap = titled(page, GB.TAP_FROM_ZERO_TITLE)
  assert isinstance(tap.action_item, GatedValueStepAction)
  assert tap.action_item.hint_text == "default: 15 mph" and not tap.action_item.highlighted
  assert "" not in [i.title for i in rows(page) if i.is_visible]  # no blank button row under the value any more
  press(tap, +1)
  assert store.get_int(GB.TAP_FROM_ZERO_KEY) == 16 and tap.action_item.highlighted
  (reset,) = reset_rows(page)
  assert rows(page).index(reset) == rows(page).index(tap) + 1 and reset.is_visible and reset.action_item.enabled
  flag[0] = False                                                # onroad: locked, nothing written, nothing asked
  assert not reset.action_item.enabled and not tap.action_item.enabled
  reset.callback()
  assert asked == [] and store.get_int(GB.TAP_FROM_ZERO_KEY) == 16
  flag[0] = True
  reset.callback()
  assert len(asked) == 1 and store.get_int(GB.TAP_FROM_ZERO_KEY) == 15 and not tap.action_item.highlighted


def test_standstill_tap_speed_reset_follows_the_tap_row(store):
  # greyed (shown, locked) without openpilot longitudinal or with no car yet; hidden on a known non-AP1 car
  for cp in (make_cp(long=False), None):
    page = GB.create_gas_brake_layout(store, cp_source=lambda cp=cp: cp, can_edit=lambda: True)
    page.show_event()
    tap, (reset,) = titled(page, GB.TAP_FROM_ZERO_TITLE), reset_rows(page)
    assert tap.is_visible and reset.is_visible
    assert not tap.action_item.enabled and not reset.action_item.enabled
    # only the actions are locked; the rows stay enabled like the old text and button rows (help still opens)
    assert tap.enabled and reset.enabled
  page, _ = page_for(store, make_cp(fingerprint="TESLA_MODEL_3"))
  assert GB.TAP_FROM_ZERO_TITLE not in titles(page) and reset_rows(page) == []
  # below the tap row's Tuning Level both rows are gone
  store.put("TuningLevel", 0, block=True)
  store.invalidate()
  page, _ = page_for(store)
  assert GB.TAP_FROM_ZERO_TITLE not in titles(page) and reset_rows(page) == []


def test_standstill_tap_speed_reset_writes_only_its_own_key(store):
  with pytest.raises(PermissionError):
    GB.reset_tap_from_zero(store, "SpeedLimitController", 15)
  with pytest.raises(PermissionError):
    GB.reset_tap_from_zero(store, GB.TAP_FROM_ZERO_KEY, 20)     # never a value other than the existing default
  with pytest.raises(PermissionError):
    GB.reset_tap_from_zero(store, GB.TAP_FROM_ZERO_KEY, 15, can_edit=lambda: False)
  assert store.raw(GB.TAP_FROM_ZERO_KEY) is None
  GB.reset_tap_from_zero(store, GB.TAP_FROM_ZERO_KEY, 15, can_edit=lambda: True, long_on=lambda: True)
  store.invalidate()
  assert store.raw(GB.TAP_FROM_ZERO_KEY) == "15"


def slc_page(store, cp=None, offroad=True):
  page, flag = page_for(store, cp, offroad)
  page.open_panel("slc")
  return page, flag


def test_speed_limit_controller_value_rows_show_the_panels_unsaved_values_as_defaults(store):
  page, _ = slc_page(store)
  panel = page.panel
  hints = {t: titled(panel, t).action_item.hint_text for t in ("Priority 1", "Priority 2", "Priority 3", "Look-ahead")}
  # exactly what each row shows while nothing is saved (registry default, parsed by the panel's own reader)
  assert hints == {"Priority 1": "default: Navigation", "Priority 2": "default: Map Data", "Priority 3": "default: Dashboard",
                   "Look-ahead": "default: 5 seconds"}
  assert [titled(panel, t).action_item.value_index for t in hints] == [1] * 4
  assert not any(titled(panel, t).action_item.highlighted for t in hints)
  [i for i in rows(panel) if i.title == "Speed Limit Offsets"][0].callback()
  offsets = [i for i in rows(panel) if i.title.startswith("Speed Offset (")]
  assert [i.action_item.hint_text for i in offsets] == ["default: +5 mph"] * 4 + ["default: +10 mph"] * 3
  assert "" not in titles(panel)                                    # no blank button rows any more


def test_speed_limit_controller_resets_write_only_their_own_section(store, monkeypatch):
  asked = confirm_yes(monkeypatch)
  page, flag = slc_page(store)
  panel = page.panel
  press(titled(panel, "Look-ahead"), +1)
  press(titled(panel, "Priority 2"), +1)
  assert store.get_int("SLCLookaheadLower") == 6 and titled(panel, "Look-ahead").action_item.highlighted
  before_offset = store.raw("Offset1")
  (reset,) = reset_rows(panel)
  assert reset.indent == INDENT and titled(panel, "Look-ahead").indent == INDENT
  assert titled(panel, "Speed Limit Controller").indent == 0
  flag[0] = False                                                   # onroad: locked, nothing asked, nothing written
  assert not reset.action_item.enabled
  reset.callback()
  assert asked == [] and store.get_int("SLCLookaheadLower") == 6
  flag[0] = True
  reset_rows(panel)[0].callback()
  store.invalidate()
  assert len(asked) == 1
  assert (store.get_int("SLCLookaheadLower"), store.get("SLCPriority2")) == (5, "Map Data")
  assert store.raw("Offset1") == before_offset                       # another section's keys are left alone
  # the offsets page has its own reset, for the seven offsets only
  [i for i in rows(panel) if i.title == "Speed Limit Offsets"][0].callback()
  press([i for i in rows(panel) if i.title.startswith("Speed Offset (")][6], -1)
  assert store.get_int("Offset7") == 9
  (offset_reset,) = reset_rows(panel)
  offset_reset.callback()
  store.invalidate()
  assert [store.get_int(f"Offset{i}") for i in range(1, 8)] == [5, 5, 5, 5, 10, 10, 10]
  assert store.get_int("SLCLookaheadLower") == 5
  # the toggle-only sub pages have no value rows and no reset
  assert page.navigation_back() is True
  for sub in ("Quality of Life", "Visual Settings"):
    [i for i in rows(panel) if i.title == sub][0].callback()
    assert reset_rows(panel) == []
    assert page.navigation_back() is True


def test_speed_limit_controller_reset_hides_with_its_rows(store):
  # Speed Limit Controller off: only the switch, no value rows and no reset
  page, _ = slc_page(store)
  switch(page.panel, "Speed Limit Controller")
  assert titles(page.panel) == ["Speed Limit Controller"] and reset_rows(page.panel) == []
  # openpilot longitudinal off: the page lists nothing (no rows, no reset)
  page, _ = slc_page(store, make_cp(long=False))
  assert reset_rows(page.panel) == []
  # below the rows' Tuning Level (Priority / Look-ahead are level 2): no value rows on the page, no reset
  store.put("SpeedLimitController", True, block=True)
  store.put("TuningLevel", 1, block=True)
  store.invalidate()
  page, _ = slc_page(store)
  assert "Look-ahead" not in titles(page.panel) and reset_rows(page.panel) == []


def test_speed_limit_controller_reset_leaves_hidden_priorities_alone(store, monkeypatch):
  confirm_yes(monkeypatch)
  page, _ = slc_page(store)
  panel = page.panel
  press(titled(panel, "Priority 3"), +1)
  p3 = store.get("SLCPriority3")
  while store.get("SLCPriority1") != "Highest":                    # Highest hides Priority 2 and 3
    press(titled(panel, "Priority 1"), +1)
    store.invalidate()
  assert "Priority 3" not in titles(panel)
  reset_rows(panel)[0].callback()
  store.invalidate()
  assert store.get("SLCPriority1") == "Navigation" and store.get("SLCPriority3") == p3   # hidden row: not written
  assert "Priority 3" in titles(panel)                                                    # the page follows the reset
