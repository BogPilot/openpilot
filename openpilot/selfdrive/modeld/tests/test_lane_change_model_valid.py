"""modeld lane change input gate: the real SubMaster at the 20 Hz model rate, driving the real DesireHelper.

modeld polls carState and carControl (100 Hz) once per model frame on conflated sockets, so it gets at most
20 Hz. SubMaster's average-frequency floor for those services is 40 Hz, so all_checks() never passes there
and the automatic lane change gate could never open. The gate now uses alive + valid only.
"""
import ast
from pathlib import Path

import pytest

from openpilot.cereal import log, messaging
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper, LANE_CHANGE_INPUTS, lane_change_inputs_ok
from openpilot.selfdrive.controls.lib.phase3_lanechange import LaneChangeSettings

LCS = log.LaneChangeState
MODELD = Path(__file__).resolve().parents[1] / "modeld.py"
# Same service list as modeld.main(); no poll service, as in modeld.
MODELD_SERVICES = ["deviceState", "carState", "narrowRoadCameraState", "extrinsicsCalibration", "driverMonitoringState",
                   "carControl", "controlsState", "lateralDelay"]
V_EGO = 30.0
WARMUP_S = 12.0


class FixedSettings:
  def __init__(self, settings):
    self.settings = settings

  def read(self, now=None):
    return self.settings


def car_state(blinker=False, valid=True):
  msg = messaging.new_message("carState")
  msg.valid = valid
  cs = msg.carState
  cs.vEgo = V_EGO
  cs.leftBlinker = blinker
  return msg


def car_control(valid=True):
  msg = messaging.new_message("carControl")
  msg.valid = valid
  msg.carControl.latActive = True
  return msg


def other_msgs():
  return [messaging.new_message(s) for s in MODELD_SERVICES if s not in LANE_CHANGE_INPUTS]


def make_sm():
  return messaging.SubMaster(MODELD_SERVICES)


def tick(sm, t, blinker=False, cs_valid=True, send_cs=True, send_cc=True):
  """One model frame: conflated sockets deliver at most one message per service."""
  msgs = other_msgs()
  if send_cs:
    msgs.append(car_state(blinker, cs_valid))
  if send_cc:
    msgs.append(car_control())
  sm.update_msgs(t, msgs)


def make_dh(delay=1.0):
  dh = DesireHelper()
  dh.lane_change_settings = FixedSettings(LaneChangeSettings(nudgeless=True, delay=delay, one_per_signal=True))
  return dh


def warm(sm, dh, t=0.0):
  while t < WARMUP_S:
    tick(sm, t)
    dh.update(sm["carState"], sm["carControl"].latActive, 0.0, None, model_valid=lane_change_inputs_ok(sm))
    t += DT_MDL
  return t


def signal(sm, dh, t, seconds, gate, **kw):
  """Hold the left blinker for `seconds`; return (first laneChangeStarting time after blinker on, states)."""
  t0, started, states = t, None, []
  while t < t0 + seconds:
    tick(sm, t, blinker=True, **kw)
    dh.update(sm["carState"], sm["carControl"].latActive, 0.0, None, model_valid=gate(sm))
    states.append(dh.lane_change_state)
    if started is None and dh.lane_change_state == LCS.laneChangeStarting:
      started = t - t0
    t += DT_MDL
  return started, states


def old_gate(sm):
  return sm.all_checks(list(LANE_CHANGE_INPUTS))


def test_20hz_polling_fails_freq_check_but_passes_alive_valid():
  sm = make_sm()
  dh = make_dh()
  warm(sm, dh)
  assert sm.freq_tracker["carState"].min_freq == pytest.approx(40.0)
  assert not sm.all_freq_ok(list(LANE_CHANGE_INPUTS))
  assert not old_gate(sm)
  assert sm.all_alive(list(LANE_CHANGE_INPUTS)) and sm.all_valid(list(LANE_CHANGE_INPUTS))
  assert lane_change_inputs_ok(sm)


def test_auto_lane_change_starts_after_delay_at_20hz():
  sm = make_sm()
  dh = make_dh(delay=1.0)
  t = warm(sm, dh)
  started, states = signal(sm, dh, t, 3.0, lane_change_inputs_ok)
  assert LCS.preLaneChange in states
  assert started is not None and 1.0 - 1e-6 <= started <= 1.0 + 3 * DT_MDL, started


def test_old_all_checks_gate_never_starts_at_20hz():
  sm = make_sm()
  dh = make_dh(delay=1.0)
  t = warm(sm, dh)
  started, states = signal(sm, dh, t, 5.0, old_gate)
  assert started is None
  assert states[-1] == LCS.preLaneChange


def test_invalid_car_state_blocks_auto():
  sm = make_sm()
  dh = make_dh(delay=1.0)
  t = warm(sm, dh)
  started, _ = signal(sm, dh, t, 3.0, lane_change_inputs_ok, cs_valid=False)
  assert not lane_change_inputs_ok(sm)
  assert started is None


def test_dead_car_state_blocks_auto():
  sm = make_sm()
  dh = make_dh(delay=1.0)
  t = warm(sm, dh)
  # carState arrives with the blinker on, then stops: alive window for 100 Hz is 0.1 s.
  tick(sm, t, blinker=True)
  dh.update(sm["carState"], sm["carControl"].latActive, 0.0, None, model_valid=lane_change_inputs_ok(sm))
  t += DT_MDL
  started, _ = signal(sm, dh, t, 3.0, lane_change_inputs_ok, send_cs=False)
  assert not sm.alive["carState"]
  assert not lane_change_inputs_ok(sm)
  assert started is None


def test_dead_car_control_blocks_auto():
  sm = make_sm()
  dh = make_dh(delay=1.0)
  t = warm(sm, dh)
  started, _ = signal(sm, dh, t, 3.0, lane_change_inputs_ok, send_cc=False)
  assert not sm.alive["carControl"]
  assert started is None


def test_one_dead_frame_resets_delay():
  sm = make_sm()
  dh = make_dh(delay=1.0)
  t = warm(sm, dh)
  started, _ = signal(sm, dh, t, 0.6, lane_change_inputs_ok)
  assert started is None
  t += 0.6
  # 0.15 s without carState (blinker held in the last reading): alive drops, delay resets.
  for _ in range(3):
    tick(sm, t, send_cs=False)
    dh.update(sm["carState"], sm["carControl"].latActive, 0.0, None, model_valid=lane_change_inputs_ok(sm))
    t += DT_MDL
  assert dh.lane_change_policy.wait == 0.0
  started, _ = signal(sm, dh, t, 3.0, lane_change_inputs_ok)
  # Already in preLaneChange, so the first resumed frame counts: a full 1.0 s again (no carry-over from the 0.6 s).
  assert started is not None and started >= 1.0 - DT_MDL - 1e-6


def test_modeld_uses_alive_valid_gate():
  tree = ast.parse(MODELD.read_text())
  calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "update"
           and getattr(n.func.value, "id", None) == "DH"]
  assert len(calls) == 1
  kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
  assert kw["model_valid"] == "modelv2_send.valid and lane_change_inputs_ok(sm)"
  assert "all_checks" not in ast.unparse(calls[0])
