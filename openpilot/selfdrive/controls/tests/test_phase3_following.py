"""Phase3 following: deterministic policy tests (no MPC). Historical source: own 04d560f3."""
import os
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib import phase3_following as F
from openpilot.selfdrive.ui.bogpilot import phase3_following as U
from opendbc.car.tesla_ap1 import stalk_follow as SF


class FakeParams:
  def __init__(self, **vals):
    self.d = dict(vals)
    self.puts = []

  def all_keys(self):
    return list(BOGPILOT_PARAMS) + ["LongitudinalPersonality"]

  def get(self, k, *a, **kw):
    return self.d.get(k)

  def put(self, k, v, *a, **kw):
    self.puts.append((k, v))
    self.d[k] = v

  def put_bool(self, k, v, *a, **kw):
    self.put(k, bool(v))

  def remove(self, k):
    self.d.pop(k, None)


@pytest.fixture(autouse=True)
def files(monkeypatch):
  with tempfile.TemporaryDirectory() as d:
    monkeypatch.setenv("BOGPILOT_PARAMS_DIR", d)
    yield d


def store(**vals):
  return ParamStore(FakeParams(**vals))


def CP(long=True, radar=True):
  return SimpleNamespace(openpilotLongitudinalControl=long, radarUnavailable=not radar)


AP1_PROFILE = dict(CustomPersonalities=True, RelaxedFollow=2.0, HumanFollowing=True, LongitudinalTune=True,
                   LeadDetectionThreshold=25)


def lead(d=30., v_lead=20., v_ego=20., present=True):
  return SimpleNamespace(present=present, dRel=d, vLead=v_lead, vRel=v_lead - v_ego)


def upd(fp, **kw):
  base = dict(enabled=True, v_ego=20., a_ego=0., personality=F.STANDARD, lead=lead(), model_length=200.,
              standstill=False)
  base.update(kw)
  return fp.update(**base)


# ---------- dormant saved tuning stays dormant ----------

@pytest.fixture
def adoption_mode(monkeypatch):
  """The earlier stock-equivalent policy (dormant until a panel row is used); the shipped default is "default_on" (0.9.7)."""
  monkeypatch.setattr(F, "ACTIVATION_POLICY", "adoption")


@pytest.mark.usefixtures("adoption_mode")
def test_dormant_ap1_profile_values_do_not_activate():
  s = store(**AP1_PROFILE)
  t = F.FollowingToggles.read(s, CP())
  assert t == F.FollowingToggles(has_radar=True)
  fp = F.FollowingPlanner(CP(), toggles=t)
  for p in (0, 1, 2):
    for _ in range(40):
      assert upd(fp, personality=p, lead=lead(15, 25)) is None
  assert F.lead_detection_threshold(t) == F.STOCK_LEAD_PROB == 0.5
  assert s._params.puts == []  # read never writes


# ---------- 04d560f3 bogpilot_variables.py:849-869 ----------
def test_custom_follow_and_jerk_formulas():
  s = store(**AP1_PROFILE)
  F.configure(s, "RelaxedJerkDanger", 150.)
  t = F.FollowingToggles.read(s, CP())
  assert t.custom_personalities and t.relaxed_follow == 2.0 and t.relaxed_jerk[2] == 1.5
  assert t.aggressive_follow == 1.25 and t.aggressive_jerk == (0.5, 0.5, 1.0, 0.5, 0.5)
  assert F.get_T_FOLLOW(t, F.RELAXED) == 2.0
  assert F.get_jerk_factor(t, F.RELAXED, True) == (1.0, 1.5, 1.0)
  assert F.get_jerk_factor(t, F.AGGRESSIVE, False) == (0.5, 1.0, 0.5)


def test_clip_bounds_and_invalid_numbers():
  s = store(CustomPersonalities=True, StandardFollow=9.0, StandardJerkAcceleration=10., StandardJerkSpeed=900.,
            AggressiveFollow=float("nan"), RelaxedFollow=0.2)
  F.configure(s, "CustomPersonalities", True)
  t = F.FollowingToggles.read(s, CP())
  assert t.standard_follow == F.MAX_T_FOLLOW == 3.0
  assert t.standard_jerk[0] == 0.25 and t.standard_jerk[3] == 2.0
  assert t.aggressive_follow == 1.25          # NaN -> registry default, not NaN
  assert t.relaxed_follow == 1.0


def test_profile_off_uses_defaults_and_tuning_levels():
  s = store(CustomPersonalities=True, StandardPersonalityProfile=False, StandardFollow=2.5,
            RelaxedJerkAcceleration=150., RelaxedFollow=2.2, TuningLevel=2, TuningLevelConfirmed="1")
  F.configure(s, "CustomPersonalities", True)
  t = F.FollowingToggles.read(s, CP())
  assert t.standard_follow == 1.45                       # profile off -> default
  assert t.relaxed_follow == 2.2                         # level 2 honoured
  assert t.relaxed_jerk[0] == 1.0                        # Jerk rows are level 3 -> default at level 2
  s.put("TuningLevel", 1)
  assert F.FollowingToggles.read(s, CP()).relaxed_follow == 2.0          # level < 2 -> registry default 2.0
  s.put("CustomPersonalities", False)
  assert F.FollowingToggles.read(s, CP()).custom_personalities is True    # level < 2 -> default "1": on at every Tuning Level


def test_no_openpilot_longitudinal_disables_everything():
  s = store(**AP1_PROFILE)
  for k in ("CustomPersonalities", "HumanFollowing", "LeadDetectionThreshold"):
    F.configure(s, k, s.get(k))
  t = F.FollowingToggles.read(s, CP(long=False))
  assert not t.custom_personalities and not t.human_following
  assert t.lead_detection_probability == 0.35            # 04d560f3: not longitudinal_tuning -> default 35/100


def test_lead_detection_formula():
  s = store(LeadDetectionThreshold=40)
  F.configure(s, "LeadDetectionThreshold", 40)
  assert F.lead_detection_threshold(F.FollowingToggles.read(s, CP())) == 0.40
  s.put("LeadDetectionThreshold", 10)
  assert F.FollowingToggles.read(s, CP()).lead_detection_probability == 0.25
  s.put("LeadDetectionThreshold", 90)
  assert F.FollowingToggles.read(s, CP()).lead_detection_probability == 0.50
  s.put("LongitudinalTune", False)
  assert F.FollowingToggles.read(s, CP()).lead_detection_probability == 0.35
  s.put("LongitudinalTune", True); s.put("TuningLevel", 2); s.put("TuningLevelConfirmed", "1")
  assert F.FollowingToggles.read(s, CP()).lead_detection_probability == 0.35   # level 3 row hidden


# ---------- reset / configure ----------
def test_reset_writes_registry_defaults_only():
  s = store(CustomPersonalities=True, AggressivePersonalityProfile=True, AggressiveFollow=2.0,
            AggressiveJerkDanger=180., StandardFollow=2.0)
  F.reset_personality(s, "Aggressive")
  for suf in F.PROFILE_SUFFIXES:
    assert s.get_float(f"Aggressive{suf}") == float(BOGPILOT_PARAMS[f"Aggressive{suf}"][2])
  assert s.get_float("StandardFollow") == 2.0 and s.get_bool("AggressivePersonalityProfile")
  assert s.get_bool(F.PERSONALITY_ACK)
  with pytest.raises(ValueError):
    F.reset_personality(s, "Traffic")
  with pytest.raises(ValueError):
    F.configure(s, "AccelerationProfile", 1)   # Gas/Brake key, not ours


# ---------- 04d560f3 bogpilot_following.py precedence ----------
def custom_fp(**vals):
  s = store(CustomPersonalities=True, **vals)
  F.configure(s, "CustomPersonalities", True)
  return F.FollowingPlanner(CP(), toggles=F.FollowingToggles.read(s, CP()))


def test_personality_plan_and_weights():
  fp = custom_fp(RelaxedFollow=2.0)
  plan = upd(fp, personality=F.RELAXED)
  assert plan.t_follow == 2.0 and plan.mpc_weights() == (200., 100., 5.)
  plan = upd(fp, personality=F.AGGRESSIVE, a_ego=-0.1)
  assert plan.t_follow == 1.25 and plan.mpc_weights() == (100., 100., 2.5)
  assert upd(fp, enabled=False) is None
  with pytest.raises(NotImplementedError):
    upd(fp, personality=7)
  assert F.personality_int(SimpleNamespace(raw=2)) == 2 and F.personality_int("aggressive") == 0


def test_traffic_mode_precedence():
  fp = custom_fp(RelaxedFollow=2.0)
  plan = upd(fp, personality=F.RELAXED, traffic_mode=True, v_ego=2.5)
  assert plan.t_follow == pytest.approx(0.75) and plan.mpc_weights() == (100., 50., 2.5)


@pytest.mark.parametrize("stalk,expect", [(1.75, 2.0), ((1.45 + 1.75) / 2, (1.45 + 2.0) / 2), (1.25, 1.25),
                                          (0.75, 0.75), (1.0, 1.0)])
def test_physical_stalk_wins_over_personality_and_maps_live(stalk, expect):
  fp = custom_fp(RelaxedFollow=2.0)
  plan = upd(fp, personality=F.AGGRESSIVE, stalk_t_follow=stalk)   # screen says aggressive, stalk elsewhere
  assert plan.t_follow == pytest.approx(expect)
  assert plan.mpc_weights()[0] == 100.     # jerk still from the current personality (04d560f3)


def test_weather_added_capped_before_human_following():
  fp = custom_fp(RelaxedFollow=2.8)
  assert upd(fp, personality=F.RELAXED, weather_following_s=0.5).t_follow == 3.0
  stock = F.FollowingPlanner(CP(), toggles=F.FollowingToggles(has_radar=True))
  plan = upd(stock, personality=F.STANDARD, weather_following_s=0.3)
  assert plan.t_follow == pytest.approx(1.75) and plan.mpc_weights() == (200., 100., 5.)


# ---------- human following ----------
REF = '''
def ref(t_follow, acceleration_jerk, speed_jerk, lead_distance, v_ego, v_lead):
  STOP_DISTANCE, COMFORT_BRAKE = 6.0, 2.5
  if v_lead > v_ego:
    distance_factor = max(lead_distance - (v_ego * t_follow), 1)
    accelerating_offset = float(np.clip(STOP_DISTANCE - v_ego, 1, distance_factor))
    acceleration_jerk /= accelerating_offset
    speed_jerk /= accelerating_offset
    t_follow /= accelerating_offset
  if v_lead < v_ego:
    distance_factor = max(lead_distance - (v_lead * t_follow), 1)
    braking_offset = float(np.clip(min(v_ego - v_lead, v_lead) - COMFORT_BRAKE, 1, distance_factor))
    if lead_distance >= 100:
      far_lead_offset = max(lead_distance - (v_ego * t_follow) - STOP_DISTANCE, 0)
      braking_offset += far_lead_offset
    t_follow /= braking_offset
  return t_follow, acceleration_jerk, speed_jerk
'''


def test_human_follow_values_match_04d560f3_verbatim():
  ns = {"np": np}
  exec(REF, ns)  # copy of bogpilot_following.update_follow_values, frozen here
  rng = np.random.default_rng(7)
  for _ in range(5000):
    args = (rng.uniform(0.5, 3), rng.uniform(0.25, 2), rng.uniform(0.25, 2), rng.uniform(0, 200),
            rng.uniform(0, 40), rng.uniform(0, 40))
    assert F.human_follow_values(*args) == ns["ref"](*args)


def human_fp(model_version=None, radar=True):
  s = store(HumanFollowing=True, LongitudinalTune=True)
  F.configure(s, "HumanFollowing", True)
  return F.FollowingPlanner(CP(radar=radar), toggles=F.FollowingToggles.read(s, CP(radar=radar)),
                            model_version=model_version)


def test_tracking_lead_filter_needs_about_one_second():
  fp = human_fp()
  steady = lead(30, 20, 20)
  plans = [upd(fp, v_ego=20, lead=steady) for _ in range(12)]
  assert all(p.t_follow == 1.45 for p in plans)     # equal speeds: neither offset applies
  fp2 = human_fp()
  seen = []
  for i in range(12):
    upd(fp2, v_ego=20, lead=steady)
    seen.append(fp2.lead.tracking)
  assert seen.index(True) == 10  # alpha = .05/.55 -> x >= 0.63 on frame 11 (THRESHOLD 0.63)
  fp3 = human_fp()
  upd(fp3, v_ego=20, lead=lead(30, 10, 20))
  assert fp3.lead.tracking  # closing lead counts immediately


def test_human_following_gates():
  faster = lead(40, 8, 3)   # accelerating_offset = clip(6 - 3, 1, 40 - 3*1.45) = 3
  for fp, expect_change in ((human_fp(), True), (human_fp(model_version="v9"), False), (human_fp(radar=False), False)):
    for _ in range(15):
      plan = upd(fp, v_ego=3, lead=faster)
    assert fp.lead.tracking
    assert plan.t_follow == pytest.approx(1.45 / 3 if expect_change else 1.45)
  fp = human_fp()
  for _ in range(15):
    plan = upd(fp, v_ego=3, lead=faster, traffic_mode=True)
  assert plan.t_follow == pytest.approx(0.8)  # traffic mode: traffic curve, no human following


# ---------- AP1 stalk -> LongitudinalPersonality sync (bogpilot_card.py:124-176) ----------
def decision(raw, prev=None):
  return SF.parse_stalk_raw(raw, prev)


def test_personality_sync_named_detents_and_readback():
  p = FakeParams(LongitudinalPersonality=1)
  sync = F.Ap1PersonalitySync(p)
  d = None
  d = decision(66, d)
  assert sync.update(d) is False and p.puts == [("LongitudinalPersonality", 0)]
  p.d["LongitudinalPersonality"] = 2       # lost write / overtaken
  for _ in range(10):
    sync.update(d)
  assert p.puts[-1] == ("LongitudinalPersonality", 0) and len(p.puts) == 2
  for _ in range(400):
    sync.update(d)
  assert len(p.puts) == 2                   # matched -> stop
  d = decision(0, d)
  assert sync.update(d) is True             # detent 1 = traffic, no personality write
  assert len(p.puts) == 2
  assert sync.update(None) is None


def test_personality_sync_gives_up_after_three_seconds():
  p = FakeParams()
  p.put = lambda k, v, *a, **kw: p.puts.append((k, v))   # write never sticks
  sync = F.Ap1PersonalitySync(p)
  d = decision(200)
  for _ in range(400):
    sync.update(d)
  assert len(p.puts) == 1 + 29              # retries every 10 frames up to frame 300
  p.puts.clear()
  p.d["LongitudinalPersonality"] = 0        # later screen tap is not fought
  for _ in range(100):
    sync.update(d)
  assert p.puts == []


def test_personality_sync_quick_twist_applies_crossed_detent():
  p = FakeParams()
  sync = F.Ap1PersonalitySync(p)
  d = decision(200)
  sync.update(d)
  for raw in (166, 100, 33):               # logged sequence: 66 never reported
    d = decision(raw, d)
    sync.update(d)
  assert [v for _, v in p.puts] == [2, 1, 0]   # relaxed, standard (crossed at 4), aggressive (crossed at 2)


# ---------- UI rows ----------
def test_ui_inventory_matches_04d560f3():
  keys = [r.key for r in U.ROWS]
  assert len(keys) == 27 and len(set(keys)) == 27
  assert [k for k in keys if k.startswith("Reset")] == [f"Reset{p}Personality" for p in F.PROFILES]
  for r in U.ROWS:
    if r.kind != "reset":
      assert r.key in BOGPILOT_PARAMS
  assert U.BY_KEY["AggressiveFollow"].minimum == 1 and U.BY_KEY["AggressiveFollow"].maximum == 3
  assert U.BY_KEY["StandardJerkDanger"].minimum == 25 and U.BY_KEY["StandardJerkDanger"].maximum == 200
  assert (U.BY_KEY["LeadDetectionThreshold"].minimum, U.BY_KEY["LeadDetectionThreshold"].maximum) == (25, 50)
  assert U.BY_KEY["RelaxedJerkSpeed"].title == "Speed-Up Response"
  assert set(F.PERSONALITY_KEYS) == {r.key for r in U.ROWS if r.kind in ("manage", "value") and r.key not in
                                      ("LeadDetectionThreshold",)}


def test_ui_visibility_and_guards():
  s = store(CustomPersonalities=False)
  on = [True]
  ed = U.FollowingEditor(CP(), s, lambda: on[0])
  assert [r.key for r in U.visible_rows(ed)] == ["CustomPersonalities"]
  assert U.visible_rows(ed, "personalities") == []
  assert ed.write("CustomPersonalities", True)
  assert [r.key for r in U.visible_rows(ed, "personalities")] == [f"{p}PersonalityProfile" for p in F.PROFILES]
  assert [r.key for r in U.visible_rows(ed, "Relaxed")][-1] == "ResetRelaxedPersonality"
  assert not ed.write("RelaxedFollow", 3.5) and not ed.write("RelaxedFollow", float("nan"))
  assert not ed.write("RelaxedFollow", True)
  assert ed.write("RelaxedFollow", 2.004) and s.get_float("RelaxedFollow") == 2.0
  on[0] = False
  assert not ed.write("RelaxedFollow", 1.5) and not ed.reset("Relaxed")
  assert s.get_float("RelaxedFollow") == 2.0
  on[0] = True
  s.put("TuningLevel", 2); s.put("TuningLevelConfirmed", "1")
  assert "RelaxedJerkDanger" not in [r.key for r in U.visible_rows(ed, "Relaxed")]
  assert "ResetRelaxedPersonality" in [r.key for r in U.visible_rows(ed, "Relaxed")]
  assert [r.key for r in U.visible_rows(ed, "longitudinal_tuning")] == ["HumanFollowing"]
  assert U.visible_rows(U.FollowingEditor(CP(long=False), s, lambda: True)) == []
  assert ed.label("RelaxedFollow") == "2.00"   # pill shows the number only; the unit stays in the hint
  s.put("RelaxedFollow", 1.0)
  assert ed.label("RelaxedFollow") == "1.00"
  assert ed.default_shown("RelaxedFollow") == "2.00 seconds"


@pytest.mark.usefixtures("adoption_mode")
def test_ui_write_reaches_consumer():
  """Panel write -> adoption marker -> same ParamStore -> FollowingToggles/FollowingPlanner output."""
  s = store()
  ed = U.FollowingEditor(CP(), s, lambda: True)
  fp = F.FollowingPlanner(CP(), store=s)
  assert upd(fp, personality=F.RELAXED) is None
  assert ed.write("CustomPersonalities", True) and ed.write("RelaxedFollow", 2.2)
  fp = F.FollowingPlanner(CP(), store=s)             # next drive
  assert upd(fp, personality=F.RELAXED).t_follow == pytest.approx(2.2)
  assert ed.reset("Relaxed")
  assert upd(F.FollowingPlanner(CP(), store=s), personality=F.RELAXED).t_follow == pytest.approx(2.0)   # Reset to Defaults: 2.0
  assert ed.write("LeadDetectionThreshold", 30)
  assert F.lead_detection_threshold(F.FollowingToggles.read(s, CP())) == pytest.approx(0.30)


# ---------- gasFollowSpeed: stock-equivalent defaults, truthful panel ----------
@pytest.mark.usefixtures("adoption_mode")
def test_adoption_helpers_fail_closed():
  s = store()
  assert F.personality_adopted(s) is False and F.group_adopted(s, "HumanFollowing") is False
  F.configure(s, "RelaxedFollow", 2.0)
  assert F.personality_adopted(s) is True and F.group_adopted(s, "HumanFollowing") is False
  assert F.group_adopted(s, "AccelerationProfile") is False      # not our key -> False, never raises

  class Broken:
    def get_bool(self, *a, **kw):
      raise OSError("boom")
  assert F.personality_adopted(Broken()) is False and F.group_adopted(Broken(), "HumanFollowing") is False


@pytest.mark.usefixtures("adoption_mode")
def test_ui_unadopted_stored_defaults_read_as_stock():
  """AP1-profile / registry defaults are stored but dormant: the panel must show what the planner/radard really do."""
  s = store(**AP1_PROFILE)
  ed = U.FollowingEditor(CP(), s, lambda: True)
  assert not ed.on("CustomPersonalities") and not ed.on("HumanFollowing")
  assert ed.on("LongitudinalTune")                          # Gas/Brake key: plain stored value
  assert U.visible_rows(ed, "personalities") == []          # nested rows stay hidden until it is really on
  assert ed.value("LeadDetectionThreshold") == 50. and ed.label("LeadDetectionThreshold") == "50%"   # stock radard 0.5
  assert [r.key for r in U.visible_rows(ed, "longitudinal_tuning")] == ["HumanFollowing", "LeadDetectionThreshold"]
  assert s._params.puts == []                               # looking never writes
  assert ed.write("CustomPersonalities", True)
  assert ed.on("CustomPersonalities") and F.personality_adopted(s)
  assert [r.key for r in U.visible_rows(ed, "personalities")] == [f"{p}PersonalityProfile" for p in F.PROFILES]
  assert ed.write("LeadDetectionThreshold", 30) and ed.value("LeadDetectionThreshold") == 30.
  assert not ed.on("HumanFollowing")                        # separate group, still dormant
  assert ed.write("HumanFollowing", True) and ed.on("HumanFollowing")


def test_ui_saved_values_survive_adoption():
  s = store(**AP1_PROFILE)
  s.put("StandardFollow", 1.9)
  ed = U.FollowingEditor(CP(), s, lambda: True)
  assert ed.write("CustomPersonalities", True)
  assert s.get_float("RelaxedFollow") == 2.0 and s.get_float("StandardFollow") == 1.9
  assert F.FollowingToggles.read(s, CP()).relaxed_follow == 2.0


@pytest.mark.skipif(os.getenv("RAYLIB_BACKEND") != "headless", reason="requires authorized native headless render")
@pytest.mark.usefixtures("adoption_mode")
def test_native_layout_render_and_toggle_callback_writes():
  """Real raylib widgets (no fakes): render, tap-callback -> adoption marker -> panel + consumer agree."""
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  gui_app.init_window("following native layout")
  s = store(**AP1_PROFILE)
  layout = U.make_layout(CP(), s, lambda: True)
  rect = rl.Rectangle(500, 0, 1660, 1080)

  def render(w):
    rl.begin_drawing()
    try:
      w.render(rect)
    finally:
      rl.end_drawing()
  layout.show_event()
  render(layout)
  assert layout.editor.on("CustomPersonalities") is False          # AP1-profile value stored but dormant
  layout.toggles["CustomPersonalities"].action_item.toggle._callback(True)   # what the Toggle widget calls on a tap
  assert s.get_bool(F.PERSONALITY_ACK) is True
  assert layout.editor.on("CustomPersonalities") is True
  assert F.FollowingToggles.read(s, CP()).custom_personalities is True
  render(layout)
  sub = U.make_layout(CP(), s, lambda: True, section="Relaxed")
  sub.show_event()
  render(sub)
  layout.hide_event()


# ---------- default_on policy (0.9.7 defaults apply, saved prefs preserved) ----------
def test_default_policy_is_default_on():
  assert F.ACTIVATION_POLICY == "default_on"
  assert F.personality_adopted(store()) is True and F.group_adopted(store(), "HumanFollowing") is True


def test_default_on_ap1_profile_values_apply_from_first_drive():
  s = store(**AP1_PROFILE)
  t = F.FollowingToggles.read(s, CP())
  assert t.custom_personalities and t.human_following
  assert t.relaxed_follow == 2.0
  assert t.lead_detection_probability is not None
  assert s._params.puts == []                                # reading never writes


def test_default_on_fresh_install_keeps_registry_defaults():
  t = F.FollowingToggles.read(store(), CP())
  assert t.relaxed_follow == pytest.approx(float(store().default("RelaxedFollow")))


def test_default_on_panel_shows_the_real_state():
  s = store(**AP1_PROFILE)
  ed = U.FollowingEditor(CP(), s, lambda: True)
  assert ed.on("CustomPersonalities") and ed.on("HumanFollowing")
  assert s._params.puts == []
