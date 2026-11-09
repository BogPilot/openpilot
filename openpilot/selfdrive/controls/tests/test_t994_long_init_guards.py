"""t994 INT: Gas/Brake planner + LongControl init/import failures fall back to the stock behaviour (never crash)."""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import pytest

from opendbc.car.structs import car
from openpilot.selfdrive.controls.lib import longitudinal_planner as lp
from openpilot.selfdrive.controls.lib.longcontrol import LongControl, LongCtrlState
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import planner, SM, msgs


def make_cp():
  cp = car.CarParams.new_message()
  cp.openpilotLongitudinalControl = True
  cp.stopAccel = -2
  cp.brand = "tesla"
  cp.carFingerprint = "TESLA_AP1_MODELS"
  cp.longitudinalTuning.kiBP = [0.0]
  cp.longitudinalTuning.kiV = [0.2]
  return cp


def stock_longcontrol(cp):
  path = os.environ.get("BASELINE_LONGCONTROL")
  if path:
    source = Path(path).read_text()
  else:
    source = subprocess.check_output(["git", "show", "feae029245e281e37667457a74387671458d716f:openpilot/selfdrive/controls/lib/longcontrol.py"], text=True)
  ns = {"__name__": "int_stock_longcontrol"}
  exec(compile(source, "stock_longcontrol.py", "exec"), ns)
  return ns["LongControl"](cp)


def cs(v=5.0, a=-0.3):
  return NS(brakePressed=False, cruiseState=NS(standstill=False), aEgo=a, vEgo=v)


@pytest.mark.parametrize("which", ["accel", "stopping"])
def test_planner_init_failure_falls_back_to_stock_and_keeps_running(which):
  target = "LongAccelPort" if which == "accel" else "LongStoppingRuntime"
  with mock.patch.object(lp, target, side_effect=RuntimeError("settings store broken")):
    p = planner(toggle=False)
  assert p.long_accel is None and p.long_stopping is None
  for _ in range(60):
    p.update(SM(msgs(10, 20)))
  assert p.output_a_target == p.output_a_target  # finite, no exception
  assert p.force_stop_result is None
  pm = mock.MagicMock()
  p.publish_frogpilot_plan(pm)
  pm.send.assert_called_once()
  msg = pm.send.call_args[0][1]
  assert msg.frogpilotPlan.experimentalMode is False and msg.frogpilotPlan.redLight is False


def test_planner_module_import_failure_is_survivable():
  # simulates the guarded top-level import falling back (LongAccelPort/LongStoppingRuntime None)
  with mock.patch.object(lp, "LongAccelPort", None), mock.patch.object(lp, "LongStoppingRuntime", None):
    p = planner(toggle=False)
  assert p.long_accel is None
  p.update(SM(msgs(10, 20)))


def test_longcontrol_store_failure_matches_stock_stopping_and_pid():
  cp = make_cp()
  with mock.patch("openpilot.common.bogpilot_store.ParamStore", side_effect=RuntimeError("no store")):
    lc = LongControl(cp)
  assert lc.long_accel_store is None
  stock = stock_longcontrol(cp)
  limits = (-3.5, 2.0)
  for active, should_stop, a_t in [(True, False, 0.4)] * 20 + [(True, True, -1.0)] * 40 + [(False, False, 0.0)]:
    got = lc.update(active, cs(), a_t, should_stop, limits)
    want = stock.update(active, cs(), a_t, should_stop, limits)
    assert got == pytest.approx(want)
  assert lc.long_control_state == stock.long_control_state == LongCtrlState.off


def test_longcontrol_stopping_module_failure_matches_stock():
  cp = make_cp()
  lc = LongControl(cp, stopping_store=NS())  # store object is not usable by the real reader either
  stock = stock_longcontrol(cp)
  limits = (-3.5, 2.0)
  with mock.patch.dict(sys.modules, {"openpilot.selfdrive.controls.lib.phase3_long_stopping": None}):
    for should_stop in [False] * 10 + [True] * 50:
      got = lc.update(True, cs(), -1.0 if should_stop else 0.3, should_stop, limits)
      want = stock.update(True, cs(), -1.0 if should_stop else 0.3, should_stop, limits)
      assert got == pytest.approx(want)
