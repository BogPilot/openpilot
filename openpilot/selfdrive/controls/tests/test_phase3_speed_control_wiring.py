"""gasFollowSpeed wiring: real capnp + compiled long MPC + real LongitudinalPlanner + native Params + the SLC panel editor.

Synthetic deterministic open-loop replays only (no route log, no drive). BASELINE_LONG_PLANNER points at the 4f09d9ff
longitudinal_planner.py so the fresh-install replay is compared bit-for-bit with the planner that is on the bench today.
"""
import importlib.util
import os
import tempfile

import numpy as np
import pytest

from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, ap1_cp, msgs
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss

MPH = sc.MPH_TO_MS
LIMIT = 20.0            # m/s dashboard limit (44.7 mph -> offset band 4, default +5 mph)


class FakePM:
  def __init__(self):
    self.sent = []

  def send(self, name, msg):
    self.sent.append((name, msg))


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
  with tempfile.TemporaryDirectory() as d:
    monkeypatch.setenv("BOGPILOT_PARAMS_DIR", os.path.join(d, "bp"))
    yield d


@pytest.fixture
def adoption_mode(monkeypatch):
  """Earlier stock-equivalent policy (dormant until the panel is used). The shipped default is "default_on" (0.9.7)."""
  monkeypatch.setattr(sc, "ACTIVATION_POLICY", "adoption")


class BlockingParams:
  def __init__(self, p):
    self._p = p

  def put(self, key, value, block=True):
    return self._p.put(key, value, block=True)

  def put_bool(self, key, value, block=True):
    return self._p.put(key, bool(value), block=True)

  def __getattr__(self, name):
    return getattr(self._p, name)


def native_store(**saved):
  from openpilot.common.params import Params
  p = BlockingParams(Params())
  for k in (*sc.SLC_KEYS, "PreviousSpeedLimit", "TuningLevel", "TuningLevelConfirmed", "IsMetric", "SLCPriority1"):
    try:
      p.remove(k)
    except Exception:
      pass
  s = ParamStore(p)
  for k, v in saved.items():
    s.put(k, v)
  return s


def planner(store, cls=LongitudinalPlanner, keep_previous=False):
  if not keep_previous:
    store.remove("PreviousSpeedLimit")   # 0.9.7 quirk (see test_restart_...): a persisted limit equal to the posted one never engages
  cp = ap1_cp()
  p = cls(cp, init_v=0.0)
  if hasattr(p, "speed_control"):
    p.speed_control = sc.Ap1SpeedControl(cp, store=store)
  return p


def baseline_cls():
  path = os.environ.get("BASELINE_LONG_PLANNER")
  if not path:
    pytest.skip("BASELINE_LONG_PLANNER not set")
  spec = importlib.util.spec_from_file_location("baseline_long_planner_feae", path)
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod.LongitudinalPlanner


def drive(p, frames=60, limit=LIMIT, manual_em=False, e2e_accel=0.0, v=20.0, v_cruise=30.0):
  out = []
  for _ in range(frames):
    m = msgs(v, v_cruise, experimental=manual_em, e2e_accel=e2e_accel)
    m['carState'].bogpilot.dashboardSpeedLimit = float(limit)
    p.update(SM(m))
    out.append(float(p.output_a_target))
  return np.array(out)


@pytest.mark.usefixtures("adoption_mode")
def test_fresh_install_replay_equals_feae_baseline():
  """Registry default SpeedLimitController="1" + saved profile rows, nothing adopted: planner == feae planner."""
  assert native_store().get_bool("SpeedLimitController") is True    # registry default really is ON
  s = native_store(Offset4=8, SLCOverride=2, SLCFallback=1)
  new, old = planner(s), planner(s, baseline_cls())
  for limit, em in ((LIMIT, False), (LIMIT, True), (0.0, False), (0.0, True)):
    assert np.array_equal(drive(new, limit=limit, manual_em=em, e2e_accel=-2.0),
                          drive(old, limit=limit, manual_em=em, e2e_accel=-2.0))
  assert new.speed_control.active is False
  from openpilot.cereal import custom
  plan = custom.BogPilotPlan.new_message()
  new.speed_control.fill(plan)
  assert (plan.slcSpeedLimit, plan.slcSpeedLimitSource) == (0.0, "")


def test_panel_toggle_reaches_real_planner_and_saved_offset_is_kept():
  s = native_store(Offset4=8)                                  # saved before the upgrade
  base = drive(planner(s, baseline_cls()), v=24.0)
  ed = ss.SlcEditor(ap1_cp(), s, lambda: True)
  assert ed.write("SpeedLimitController", True)
  assert s.get_int("Offset4") == 8                             # adoption never rewrites saved values
  p = planner(s)
  out = drive(p, v=24.0)
  assert p.speed_control.active
  assert p.speed_control.v_cruise_out == pytest.approx(LIMIT + 8 * MPH, rel=1e-3)
  assert out[-1] < base[-1] - 0.01                             # set speed below v_ego -> braking instead of stock accel
  assert ed.write("Offset4", 0)
  p2 = planner(s)
  drive(p2, v=24.0)
  assert p2.speed_control.v_cruise_out == pytest.approx(LIMIT, rel=1e-3)
  assert ed.write("SpeedLimitController", False)
  p3 = planner(s)
  assert np.array_equal(drive(p3, v=24.0), base)


def test_experimental_fallback_or_default_reaches_planner():
  s = native_store()
  ed = ss.SlcEditor(ap1_cp(), s, lambda: True)
  assert ed.write("SpeedLimitController", True)
  assert ed.write("SLCFallback", ss.FALLBACK_EXPERIMENTAL)     # offered only because the planner consumes it
  p = planner(s)
  assert p.speed_control.experimental_policy == "or"
  # no dashboard limit -> fallback turns Experimental Mode on (e2e candidate brakes) although the manual flag is off
  out = drive(p, limit=0.0, manual_em=False, e2e_accel=-2.0)
  assert p.experimental is True and out[-1] < -1.0
  # a limit is known -> the previous release baseline "or": manual Experimental Mode stays on and is published on bogpilotPlan
  p = planner(s)
  out = drive(p, limit=LIMIT, manual_em=True, e2e_accel=-2.0)
  assert p.experimental is True and out[-1] < -1.0
  pm = FakePM()
  p.publish_bogpilot_plan(pm)
  name, msg = pm.sent[0]
  assert name == 'bogpilotPlan' and msg.bogpilotPlan.experimentalMode is True
  assert msg.bogpilotPlan.slcSpeedLimitSource == "Dashboard" and msg.valid is True
  # "replace" remains selectable and still cancels the manual flag when a limit is known
  p = planner(s)
  p.speed_control.experimental_policy = "replace"
  out = drive(p, limit=LIMIT, manual_em=True, e2e_accel=-2.0)
  assert p.experimental is False and out[-1] > -1.0
  p = planner(s)
  drive(p, limit=0.0, manual_em=False, e2e_accel=-2.0)           # no limit known -> fallback Experimental -> published True
  pm = FakePM()
  p.publish_bogpilot_plan(pm)
  assert pm.sent[0][1].bogpilotPlan.experimentalMode is True


def test_fallback_not_experimental_leaves_manual_flag_alone():
  s = native_store()
  ed = ss.SlcEditor(ap1_cp(), s, lambda: True)
  assert ed.write("SpeedLimitController", True) and ed.write("SLCFallback", 0)
  p = planner(s)
  drive(p, limit=LIMIT, manual_em=True, e2e_accel=-2.0)
  assert p.experimental is True
  p = planner(s)
  drive(p, limit=0.0, manual_em=False)
  assert p.experimental is False


def test_restart_with_unchanged_posted_limit_does_not_engage_0_9_7_parity():
  """FAITHFUL 0.9.7 quirk, documented: target starts 0 and previous_target is restored from PreviousSpeedLimit, so
  when the first posted limit after a restart equals the persisted one nothing engages until the limit changes."""
  s = native_store()
  ed = ss.SlcEditor(ap1_cp(), s, lambda: True)
  assert ed.write("SpeedLimitController", True)
  assert ed.write("SLCFallback", ss.FALLBACK_EXPERIMENTAL)     # default fallback is Previous Limit, which masks the quirk
  p = planner(s)
  drive(p, v=24.0)
  assert p.speed_control.slc.target == pytest.approx(LIMIT) and s.get_float("PreviousSpeedLimit") == pytest.approx(LIMIT)
  p2 = planner(s, keep_previous=True)                          # next drive, same posted limit
  drive(p2, v=24.0)
  assert p2.speed_control.slc.target == 0.0
  drive(p2, limit=LIMIT + 5.0, v=24.0)                         # limit changes -> engages
  assert p2.speed_control.slc.target == pytest.approx(LIMIT + 5.0)


def test_default_on_without_a_posted_limit_equals_feae_baseline():
  """SLC is ON by default (0.9.7). With nothing saved and no limit known the planner is bit-exact stock."""
  s = native_store()
  assert sc.ACTIVATION_POLICY == "default_on"
  new, old = planner(s), planner(s, baseline_cls())
  for em in (False, True):
    assert np.array_equal(drive(new, limit=0.0, manual_em=em, e2e_accel=-2.0), drive(old, limit=0.0, manual_em=em, e2e_accel=-2.0))
  assert new.speed_control.active is True and new.speed_control.slc_target == 0.0


def test_default_on_follows_a_posted_limit_with_no_panel_use():
  s = native_store()
  base = drive(planner(s, baseline_cls()), v=24.0)
  p = planner(s)
  out = drive(p, v=24.0)
  assert p.speed_control.active
  assert p.speed_control.v_cruise_out < 30.0                   # lowered to limit + offset, never raised above the set speed
  assert out[-1] < base[-1] - 0.01
  assert s.raw("SpeedLimitController") is None                 # nothing written by running
