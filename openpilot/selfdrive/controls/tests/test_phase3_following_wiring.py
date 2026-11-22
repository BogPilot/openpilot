"""Following wiring: real capnp + compiled long MPC + real LongitudinalPlanner / radard get_lead / native Params.

Synthetic deterministic closed-loop replays only (no route log, no drive). BASELINE_LONG_PLANNER points at the
committed c6582fc3e longitudinal_planner.py so the no-adoption replay is compared to the real old planner.
"""
import importlib.util
import os
import tempfile
import time

import numpy as np
import pytest

import openpilot.cereal.messaging as messaging
from openpilot.common.bogpilot_store import ParamStore
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls import radard
from openpilot.selfdrive.controls.lib import phase3_following as F
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, ap1_cp, msgs
from openpilot.selfdrive.ui.bogpilot import phase3_following as U


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
  with tempfile.TemporaryDirectory() as d:
    monkeypatch.setenv("BOGPILOT_PARAMS_DIR", os.path.join(d, "bp"))
    yield d


@pytest.fixture
def adoption_mode(monkeypatch):
  """Earlier stock-equivalent policy (dormant until a panel row is used). The shipped default is "default_on" (0.9.7)."""
  monkeypatch.setattr(F, "ACTIVATION_POLICY", "adoption")


class BlockingParams:
  """Real native Params; writes flushed synchronously so a same-process read-back in the test is deterministic.
  (0.11 Params.put is async by default; on device the UI write is read by the consumer at its next process start.)"""
  def __init__(self, p):
    self._p = p

  def put(self, key, value, block=True):
    return self._p.put(key, value, block=True)

  def put_bool(self, key, value, block=True):
    return self._p.put(key, bool(value), block=True)

  def __getattr__(self, name):
    return getattr(self._p, name)


def native_store():
  from openpilot.common.params import Params
  p = BlockingParams(Params())
  for k in ("CustomPersonalities", "RelaxedFollow", "HumanFollowing", "LeadDetectionThreshold", "LongitudinalTune",
            "TuningLevel", "TuningLevelConfirmed", "LongitudinalPersonality"):
    try:
      p.remove(k)
    except Exception:
      pass
  return ParamStore(p)


def make(planner_cls, cp, store):
  p = planner_cls(cp, init_v=0.0)
  if hasattr(p, "following"):
    p.following = F.FollowingPlanner(cp, store=store)
  return p


def scenario(p, frames=200, personality=None, stalk=None, log=None):
  v, gap, a, out = 18.0, 45.0, 0.0, []
  for i in range(frames):
    v_lead = 12.0 if i < 120 else 16.0
    m = msgs(v, 25.0, lead=(gap, v_lead), a_ego=a)
    if personality is not None:
      m['selfdriveState'].personality = personality
    if stalk is not None:
      m['carState'].bogpilot.ap1StalkFollowS = stalk
    p.update(SM(m))
    if log is not None:
      log.append((float(p.mpc.params[0, 4]), tuple(p.mpc.params[0, 5:6])))
    a = float(p.output_a_target)
    out.append(a)
    v = max(0.0, v + a * DT_MDL)
    gap += (v_lead - v) * DT_MDL
  return np.array(out)


def baseline_cls():
  path = os.environ.get("BASELINE_LONG_PLANNER")
  if not path:
    pytest.skip("BASELINE_LONG_PLANNER not set")
  spec = importlib.util.spec_from_file_location("baseline_long_planner_c6582fc3e", path)
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod.LongitudinalPlanner


@pytest.mark.usefixtures("adoption_mode")
@pytest.mark.parametrize("personality,stalk", [("standard", None), ("aggressive", None), ("relaxed", 1.75), ("standard", 1.25)])
def test_no_adoption_replay_equals_c6582fc3e(personality, stalk):
  s = native_store()
  for k, v in dict(CustomPersonalities=True, RelaxedFollow=2.0, HumanFollowing=True, LeadDetectionThreshold=25).items():
    s.put(k, v)  # dormant AP1-profile style tuning, never adopted
  new = scenario(make(LongitudinalPlanner, ap1_cp(), s), personality=personality, stalk=stalk)
  old = scenario(make(baseline_cls(), ap1_cp(), s), personality=personality, stalk=stalk)
  assert np.array_equal(new, old)


@pytest.mark.usefixtures("adoption_mode")
def test_ui_adopted_relaxed_follow_reaches_mpc_and_changes_output():
  s = native_store()
  ed = U.FollowingEditor(ap1_cp(), s, lambda: True)
  stock_log, stock = [], None
  stock = scenario(make(LongitudinalPlanner, ap1_cp(), s), personality="relaxed", log=stock_log)
  assert ed.write("CustomPersonalities", True) and ed.write("RelaxedFollow", 2.4)
  assert ed.write("RelaxedJerkDanger", 150)
  log = []
  p = make(LongitudinalPlanner, ap1_cp(), s)
  weights = []
  orig = p.mpc.set_cost_weights
  p.mpc.set_cost_weights = lambda cw, ccw: (weights.append((tuple(cw), tuple(ccw))), orig(cw, ccw))[1]
  out = scenario(p, personality="relaxed", log=log)
  assert {x[0] for x in stock_log} == {1.75}
  assert all(x[0] == pytest.approx(2.4) for x in log)
  assert p.effective_t_follow == pytest.approx(2.4)
  assert all(ccw[3] == pytest.approx(150.) for _, ccw in weights)
  assert out.min() < stock.min() - 0.05       # larger gap -> brakes harder toward the slower lead
  assert out.min() >= -3.5 - 1e-6             # stock ACCEL_MIN clip retained


@pytest.mark.usefixtures("adoption_mode")
def test_physical_stalk_maps_to_live_profile_seconds():
  s = native_store()
  F.configure(s, "CustomPersonalities", True)
  F.configure(s, "RelaxedFollow", 2.0)
  log = []
  scenario(make(LongitudinalPlanner, ap1_cp(), s), frames=20, personality="aggressive", stalk=1.75, log=log)
  assert all(x[0] == pytest.approx(2.0) for x in log[1:])
  log = []
  scenario(make(LongitudinalPlanner, ap1_cp(), s), frames=20, personality="relaxed", stalk=1.60, log=log)
  assert all(x[0] == pytest.approx((1.45 + 2.0) / 2) for x in log[1:])


def test_human_following_changes_real_planner_t_follow():
  s = native_store()
  F.configure(s, "HumanFollowing", True)
  p = make(LongitudinalPlanner, ap1_cp(), s)
  v = 3.0
  ts = []
  for _ in range(15):
    m = msgs(v, 25.0, lead=(25.0, 8.0))   # lead inside model_length (x[-1] ~ 30 m at 3 m/s) + STOP_DISTANCE
    m['selfdriveState'].personality = "standard"
    p.update(SM(m))
    ts.append(float(p.mpc.params[0, 4]))
  assert ts[0] == pytest.approx(1.45)           # tracking filter not yet >= 0.63
  assert ts[-1] == pytest.approx(1.45 / 3)      # accelerating_offset = clip(STOP_DISTANCE - v_ego, 1, ..) = 3
  assert p.effective_t_follow == pytest.approx(1.45 / 3)


def lead_msg(prob, x=30.0, v=15.0):
  m = messaging.new_message('modelV2').modelV2
  m.init('leadsV3', 2)
  for ld in m.leadsV3:
    ld.prob = prob
    ld.x = [x] * 6; ld.y = [0.0] * 6; ld.v = [v] * 6; ld.a = [0.0] * 6
    ld.xStd = [1.0] * 6; ld.yStd = [1.0] * 6; ld.vStd = [1.0] * 6; ld.aStd = [1.0] * 6
  return m.leadsV3[0]


@pytest.mark.usefixtures("adoption_mode")
def test_radard_lead_detection_gate():
  lm = lead_msg(0.4)
  assert not radard.get_lead(15.0, True, {}, lm, 15.0, 0.4)['present']                 # stock .5
  assert radard.get_lead(15.0, True, {}, lm, 15.0, 0.4, lead_threshold=0.35)['present']
  s = native_store()
  assert F.lead_detection_threshold(F.FollowingToggles.read(s, ap1_cp())) == 0.5       # not adopted
  assert U.FollowingEditor(ap1_cp(), s, lambda: True).write("LeadDetectionThreshold", 35)
  th = F.lead_detection_threshold(F.FollowingToggles.read(s, ap1_cp()))
  assert th == pytest.approx(0.35)
  rd = radard.RadarD(0.0, ap1_lead_filter=True, lead_threshold=th)
  assert rd.lead_threshold == th


def test_native_params_personality_sync_roundtrip():
  from opendbc.car.tesla_ap1.stalk_follow import parse_stalk_raw
  from openpilot.common.params import Params
  p = Params()                     # real async (non-blocking) native puts, 100 Hz card cadence
  p.put("LongitudinalPersonality", 1, block=True)
  sync = F.Ap1PersonalitySync(p)
  d = parse_stalk_raw(200, None)
  for _ in range(40):
    sync.update(d)
    time.sleep(0.01)
  assert p.get("LongitudinalPersonality", return_default=True) == 2    # what selfdrived.params_thread reads
  d = parse_stalk_raw(66, d)
  for _ in range(40):
    sync.update(d)
    time.sleep(0.01)
  assert p.get("LongitudinalPersonality", return_default=True) == 0


def test_default_on_uses_097_registry_defaults():
  """Defaults apply from the first drive (HumanFollowing ON, Lead Detection 35 %, Driving Personalities ON with Relaxed 2.0 s:
  the defaults)."""
  s = native_store()
  assert F.ACTIVATION_POLICY == "default_on"
  t = F.FollowingToggles.read(s, ap1_cp())
  assert t.human_following is True
  assert t.custom_personalities is True and t.relaxed_follow == pytest.approx(2.0)
  assert (t.aggressive_follow, t.standard_follow) == (pytest.approx(1.25), pytest.approx(1.45))
  assert F.lead_detection_threshold(t) == pytest.approx(0.35)
  p = LongitudinalPlanner(ap1_cp(), init_v=0.0)
  assert p.following.active is True
  assert [k for k in ("CustomPersonalities", "HumanFollowing", "LeadDetectionThreshold") if s.raw(k) is not None] == []   # reading never writes
