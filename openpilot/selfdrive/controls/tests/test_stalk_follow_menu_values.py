"""The AP1 / Pre-AP stalk follow distance uses the follow times set in the Driving Personalities menu: positions 7 / 5 / 3
are the saved Relaxed / Standard / Aggressive follow times, 6 and 4 the exact midpoints of their neighbors, 2 the midpoint
of traffic (1.0 s, no menu value) and Aggressive, and 1 the traffic curve. With Custom Personalities off the stalk gives
the stock times, the same as the on-screen personality, so the two never disagree."""
import tempfile
from types import SimpleNamespace

import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib import phase3_following as F
from opendbc.car.tesla_ap1 import stalk_follow as SF

# the stalk publishes the stock seconds for each position; the planner maps them to the menu values
POS = {1: 1.0, 2: (1.0 + 1.25) / 2, 3: 1.25, 4: (1.25 + 1.45) / 2, 5: 1.45, 6: (1.45 + 1.75) / 2, 7: 1.75}


class FakeParams:
  def __init__(self, **vals):
    self.d = dict(vals)

  def all_keys(self):
    return list(BOGPILOT_PARAMS) + ["LongitudinalPersonality"]

  def get(self, k, *a, **kw):
    return self.d.get(k)

  def put(self, k, v, *a, **kw):
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


def CP():
  return SimpleNamespace(openpilotLongitudinalControl=True, radarUnavailable=False)


def toggles(**vals):
  return F.FollowingToggles.read(ParamStore(FakeParams(**vals)), CP())


def lead():
  return SimpleNamespace(present=True, dRel=30., vLead=20., vRel=0.)


def plan_t(tg, stalk, personality=F.STANDARD):
  fp = F.FollowingPlanner(CP(), toggles=tg)
  plan = fp.update(enabled=True, v_ego=20., a_ego=0., personality=personality, lead=lead(), model_length=200.,
                   standstill=False, stalk_t_follow=stalk)
  return plan.t_follow


CUSTOM = dict(CustomPersonalities=True, AggressiveFollow=1.1, StandardFollow=1.6, RelaxedFollow=2.4, HumanFollowing=False)


@pytest.mark.parametrize("pos,want", [(7, 2.4), (6, (1.6 + 2.4) / 2), (5, 1.6), (4, (1.1 + 1.6) / 2), (3, 1.1),
                                      (2, (1.0 + 1.1) / 2), (1, 1.0)])
def test_custom_saved_values_and_midpoints(pos, want):
  tg = toggles(**CUSTOM)
  assert (tg.aggressive_follow, tg.standard_follow, tg.relaxed_follow) == (1.1, 1.6, 2.4)
  assert SF.live_follow_seconds(POS[pos], tg) == pytest.approx(want)
  assert plan_t(tg, POS[pos]) == pytest.approx(want)


def test_example_default_times():
  tg = toggles(CustomPersonalities=True, HumanFollowing=False)          # shipped 1.25 / 1.45 / 2.0
  assert SF.live_follow_seconds(POS[7], tg) == pytest.approx(2.0)
  assert SF.live_follow_seconds(POS[6], tg) == pytest.approx(1.725)
  assert SF.live_follow_seconds(POS[5], tg) == pytest.approx(1.45)
  assert SF.live_follow_seconds(POS[4], tg) == pytest.approx(1.35)
  assert SF.live_follow_seconds(POS[3], tg) == pytest.approx(1.25)


@pytest.mark.parametrize("personality,pos", [(F.RELAXED, 7), (F.STANDARD, 5), (F.AGGRESSIVE, 3)])
def test_stalk_matches_the_personality_menu_value(personality, pos):
  tg = toggles(**CUSTOM)
  assert plan_t(tg, POS[pos], personality=F.STANDARD) == pytest.approx(plan_t(tg, None, personality=personality))


def test_traffic_curve_passes_through():
  tg = toggles(**CUSTOM)
  assert SF.live_follow_seconds(0.75, tg) == 0.75 and plan_t(tg, 0.75) == pytest.approx(0.75)


@pytest.mark.parametrize("pos", list(POS))
def test_custom_personalities_off_uses_stock_times_like_the_personality(pos):
  # saved menu values are not in use with Custom Personalities off; the personality then gives 1.25 / 1.45 / 1.75
  tg = toggles(CustomPersonalities=False, RelaxedFollow=2.4, HumanFollowing=True, LongitudinalTune=True)
  assert not tg.custom_personalities
  assert SF.live_follow_seconds(POS[pos], tg) == pytest.approx(POS[pos])
  assert plan_t(tg, POS[pos]) == pytest.approx(POS[pos])
  assert plan_t(tg, None, personality=F.RELAXED) == pytest.approx(1.75)
  assert plan_t(tg, POS[7]) == pytest.approx(plan_t(tg, None, personality=F.RELAXED))


def test_profile_row_off_uses_its_default_on_both_paths():
  tg = toggles(**CUSTOM, RelaxedPersonalityProfile=False)
  assert tg.relaxed_follow == 2.0                                     # the shipped Relaxed time
  assert plan_t(tg, POS[7]) == pytest.approx(plan_t(tg, None, personality=F.RELAXED)) == pytest.approx(2.0)


def test_tuning_level_below_advanced_uses_defaults_on_both_paths():
  tg = toggles(**CUSTOM, TuningLevelConfirmed=True, TuningLevel=1)
  assert (tg.aggressive_follow, tg.standard_follow, tg.relaxed_follow) == (1.25, 1.45, 2.0)
  assert plan_t(tg, POS[7]) == pytest.approx(plan_t(tg, None, personality=F.RELAXED)) == pytest.approx(2.0)
  assert plan_t(tg, POS[6]) == pytest.approx(1.725)


def test_unconfirmed_tuning_level_honours_saved_values():
  assert toggles(**CUSTOM).relaxed_follow == 2.4


def test_none_toggles_and_zero_pass_through():
  assert SF.live_follow_seconds(1.75, None) == 1.75
  assert SF.live_follow_seconds(0.0, toggles(**CUSTOM)) == 0.0
