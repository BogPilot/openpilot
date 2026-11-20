"""t1401 from-stop rule on Pre-AP with the pedal: a standstill double pull sets the from-stop value on the pull, the accelerator
release keeps it (and any tips made while held), and an up/down tip while steering only engages speed control like the AP1 tap."""
from types import SimpleNamespace as NS

import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1.preap import engagement as eng
from opendbc.car.tesla_ap1.preap.engagement import Mode, PreAPEngagement
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys, set_bool
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_engagement import step
from opendbc.car.tesla_ap1.tests.test_preap_standstill_hold import Car

TIP_UP, TIP_DN = 16, 32   # SpdCtrlLvr_Stat UP_1ST / DN_1ST (tesla_ap1_can.dbc VAL_ 69)
MPH = CV.MPH_TO_KPH
FROM_STOP_KPH = 15 * MPH


def tip(e, t, **kw):
  return e.update(t, pull_edge=False, cancel_edge=False, brake_pressed=kw.get("brake", False),
                                                          op_enabled=kw.get("op", True), pedal=kw.get("pedal", True),
                                                          gear_d=kw.get("gear_d", True), door_open=kw.get("door_open", False),
                                                          epas_drop=False, stale=False, di_engaged=False, v_ego=kw.get("v_ego", 10.0),
                                                          long_allowed=kw.get("long_allowed", True), gas_pressed=kw.get("gas", False),
                                                          tip_edge=True)


def steer_only(e, v_ego=10.0):
  step(e, 0, pull=True, v_ego=v_ego)
  step(e, 10, op=True, v_ego=v_ego)
  d = step(e, 600, op=True, v_ego=v_ego)   # window expired
  assert d.mode == Mode.LAT_ONLY
  return d


# FSM
def test_standstill_double_pull_captures_from_stop_on_the_pull_and_not_on_release():
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0)
  step(e, 10, op=True, v_ego=0.0)
  d = step(e, 250, pull=True, op=True, v_ego=0.0)
  assert d.mode == Mode.FULL and d.standstill_hold and d.capture_edge and d.capture_from_stop and not d.capture_tip
  step(e, 300, op=True, v_ego=0.0, gas=True)
  d = step(e, 310, op=True, v_ego=2.0)
  assert d.mode == Mode.FULL and not d.standstill_hold and not d.capture_edge and not d.capture_from_stop


@pytest.mark.parametrize("v", [0.5, 3.0, 6.0, 10.0, 20.0])
def test_moving_double_pull_asks_for_the_from_stop_raise_and_no_hold(v):
  # t1438: a moving double pull below the from-stop speed is raised to it; the card takes max(rounded vEgo, from-stop), so
  # above it the current speed is kept. Moving: never a standstill hold.
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=v)
  step(e, 10, op=True, v_ego=v)
  d = step(e, 250, pull=True, op=True, v_ego=v, auto_speed=True)   # Pre-AP Auto Speed ON
  assert d.mode == Mode.FULL and d.capture_edge and d.capture_from_stop and not d.capture_tip and not d.standstill_hold


@pytest.mark.parametrize("v", [0.5, 3.0, 6.0, 10.0, 20.0])
def test_moving_double_pull_with_auto_speed_off_is_the_v5_capture(v):
  # Auto Speed OFF (default): exactly the behaviour before the raise existed, the card keeps the rounded current speed.
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=v)
  step(e, 10, op=True, v_ego=v)
  d = step(e, 250, pull=True, op=True, v_ego=v)
  assert d.mode == Mode.FULL and d.capture_edge and not d.capture_from_stop and not d.capture_tip and not d.standstill_hold


def test_moving_double_pull_raise_off_gives_the_v5_capture(monkeypatch):
  monkeypatch.setattr(eng, "PREAP_MOVING_PULL_RAISES_TO_FROM_STOP", False)
  e = PreAPEngagement()
  step(e, 0, pull=True)
  step(e, 10, op=True)
  d = step(e, 250, pull=True, op=True, auto_speed=True)
  assert d.mode == Mode.FULL and d.capture_edge and not d.capture_from_stop and not d.capture_tip


def test_raise_flag_is_one_tick_only():
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=3.0)
  step(e, 10, op=True, v_ego=3.0)
  assert step(e, 250, pull=True, op=True, v_ego=3.0, auto_speed=True).capture_from_stop
  d = step(e, 300, op=True, v_ego=3.0)
  assert d.mode == Mode.FULL and not d.capture_edge and not d.capture_from_stop


@pytest.mark.parametrize("v", [1.0, 4.0, 20.0])
def test_rolling_tip_while_steering_only_engages_speed_control(v):
  e = PreAPEngagement()
  steer_only(e, v)
  d = tip(e, 700, v_ego=v)
  assert d.mode == Mode.FULL and d.long_wanted and d.capture_edge and d.capture_tip and not d.capture_from_stop
  assert not d.standstill_hold


def test_tip_at_a_stop_is_the_from_stop_hold():
  e = PreAPEngagement()
  steer_only(e, 0.0)
  d = tip(e, 700, v_ego=0.0)
  assert d.mode == Mode.FULL and d.standstill_hold and d.capture_edge and d.capture_from_stop and d.capture_tip


def test_tip_inside_the_double_pull_window_does_not_engage():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  step(e, 10, op=True)
  d = tip(e, 100)
  assert d.mode == Mode.LAT_PENDING and not d.capture_edge
  d = tip(e, 450)   # window expired (LAT_PENDING until this step): the tip engages
  assert d.mode == Mode.FULL and d.capture_tip


def test_tip_needs_a_pull_first_and_openpilot_enabled():
  e = PreAPEngagement()
  d = tip(e, 0, op=False)
  assert d.mode == Mode.OFF and not d.engaged and not d.capture_edge
  e = PreAPEngagement()
  step(e, 0, pull=True)
  d = tip(e, 5, op=False)   # openpilot not yet enabled
  assert d.mode == Mode.LAT_PENDING and not d.capture_edge


@pytest.mark.parametrize("kw,mode", [
  (dict(brake=True, v_ego=10.0), Mode.LAT_ONLY),       # brake while moving
  (dict(long_allowed=False), Mode.LAT_ONLY),           # pedal not ready
  (dict(v_ego=float("nan")), Mode.LAT_ONLY),           # unknown speed: never a hold
])
def test_tip_refused_like_a_second_pull(kw, mode):
  e = PreAPEngagement()
  steer_only(e)
  d = tip(e, 700, **kw)
  assert d.mode == mode and not d.long_wanted and not d.capture_edge


def test_tip_out_of_d_or_door_open_ends_the_session_not_full():
  for kw in (dict(gear_d=False), dict(door_open=True)):
    e = PreAPEngagement()
    steer_only(e)
    d = tip(e, 700, **kw)
    assert d.mode == Mode.OFF and not d.long_wanted


def test_tip_in_full_changes_nothing_in_the_fsm():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  step(e, 10, op=True)
  step(e, 250, pull=True, op=True)
  d = tip(e, 400)
  assert d.mode == Mode.FULL and not d.capture_edge


def test_no_pedal_ignores_tips():
  e = PreAPEngagement()
  step(e, 0, pull=True, pedal=False)
  step(e, 10, op=True, pedal=False)
  d = tip(e, 700, pedal=False)
  assert d.mode != Mode.FULL and not d.capture_edge


def test_constants_off_give_v3(monkeypatch):
  monkeypatch.setattr(eng, "PREAP_STOP_SET_AT_PULL", False)
  monkeypatch.setattr(eng, "PREAP_TIP_ENGAGES_LONG", False)
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0)
  step(e, 10, op=True, v_ego=0.0)
  d = step(e, 250, pull=True, op=True, v_ego=0.0)
  assert d.standstill_hold and not d.capture_edge
  step(e, 300, op=True, v_ego=0.0, gas=True)
  d = step(e, 310, op=True, v_ego=2.0)
  assert d.capture_edge and d.capture_from_stop
  e = PreAPEngagement()
  steer_only(e)
  assert tip(e, 700).mode == Mode.LAT_ONLY


# Car rig (real Pre-AP car state + carcontroller) with the card's set-speed order: VCruiseHelper, then the enable-edge init, then
# the capture (selfdrive/car/card.py).
class Card:
  def __init__(self, is_metric=False):
    from openpilot.selfdrive.car.cruise import VCruiseHelper
    self.c = Car()
    self.vc = VCruiseHelper(NS(pcmCruise=False))
    self.is_metric = is_metric
    self.prev_op = False

  def step(self, **kw):
    out = self.c.step(**kw)
    cs = self.c.rig.cs
    self.vc.update_v_cruise(out, self.c.op, self.is_metric)
    if self.c.op and not self.prev_op:
      self.vc.initialize_v_cruise(out, False, 0.0, preap_from_stop_kph=FROM_STOP_KPH, is_metric=self.is_metric)
    self.prev_op = self.c.op
    if cs.preap_capture_edge:
      fs = FROM_STOP_KPH if cs.preap_capture_from_stop else 0.0
      self.vc.capture_preap_full(float(out.vEgo), 0.0, is_metric=self.is_metric, from_stop_kph=fs)
    return out

  def mph(self):
    return self.vc.v_cruise_kph / MPH


def _settle(k, n, **kw):
  for _ in range(n):
    out = k.step(**kw)
  return out


def test_rig_standstill_double_pull_sets_from_stop_tips_down_and_release_keeps_it():
  k = Card()
  _settle(k, 20)
  k.step(stalk=PULL)
  _settle(k, 9)
  k.step(stalk=PULL)
  out = _settle(k, 50)
  assert k.c.mode == Mode.FULL and k.c.rig.cs.preap_standstill_hold and not out.bogpilot.preapLatOnly
  assert abs(k.mph() - 15) < 0.01, "the double pull at a stop set the from-stop value"
  assert not any(any(e["enabled"]) for e in k.c.log), "still held: no pedal ENABLE"
  for _ in range(5):                       # five down tips while held: 15 -> 10 mph
    k.step(stalk=TIP_DN)
    k.step(stalk=0)
  assert abs(k.mph() - 10) < 0.1 and k.c.rig.cs.preap_standstill_hold
  _settle(k, 20, gas=40.0, v_kph=30.0)    # pull away on the accelerator (to ~19 mph)
  _settle(k, 30, gas=0.8, v_kph=30.0)     # lift off while moving: the hold ends
  assert not k.c.rig.cs.preap_standstill_hold and k.c.mode == Mode.FULL
  assert abs(k.mph() - 10) < 0.1, "the release kept the tipped set; no re-capture at release speed"
  assert any(any(e["enabled"]) for e in k.c.log[-10:]), "speed control running after the release"


def test_rig_rolling_tip_from_steering_only_latches_the_current_speed():
  k = Card()
  v_kph = 12 * 1.609344
  _settle(k, 200, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  _settle(k, 60, v_kph=v_kph)              # window expires: steering only
  assert k.c.mode == Mode.LAT_ONLY
  k.step(stalk=TIP_DN, v_kph=v_kph)
  out = k.step(stalk=0, v_kph=v_kph)       # release edge: FULL
  assert k.c.mode == Mode.FULL and not out.bogpilot.preapLatOnly
  assert abs(k.mph() - 12) < 0.01, "latched the rounded current speed; the engaging tip's own -1 is replaced"
  _settle(k, 20, v_kph=v_kph)
  assert any(any(e["enabled"]) for e in k.c.log[-10:]), "pedal ENABLE flows: speed control engaged"
  k.step(stalk=TIP_DN, v_kph=v_kph)
  k.step(stalk=0, v_kph=v_kph)
  assert abs(k.mph() - 11) < 0.1, "a later tip changes the set by 1 mph"


def test_rig_tip_at_a_stop_from_steering_only_is_the_from_stop_hold():
  k = Card()
  _settle(k, 20)
  k.step(stalk=PULL)
  _settle(k, 60)
  k.step(stalk=TIP_UP)
  out = k.step(stalk=0)
  assert k.c.mode == Mode.FULL and k.c.rig.cs.preap_standstill_hold and not out.bogpilot.preapLatOnly
  assert abs(k.mph() - 15) < 0.01
  _settle(k, 100)
  assert not any(any(e["enabled"]) for e in k.c.log), "no drive-off: the hold stays until the accelerator"


def _moving_double_pull(k, mph):
  v_kph = mph * 1.609344
  _settle(k, 200, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  _settle(k, 9, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  return _settle(k, 30, v_kph=v_kph)


@pytest.mark.parametrize("mph", [3, 8, 14])
def test_rig_moving_double_pull_auto_speed_off_keeps_the_current_speed(mph):
  # Auto Speed OFF (the default, key never written): no raise to the from-stop speed, as before the feature.
  k = Card()
  _moving_double_pull(k, mph)
  assert k.c.mode == Mode.FULL and abs(k.mph() - mph) < 0.01


def test_rig_moving_double_pull_auto_speed_explicit_off_keeps_the_current_speed():
  set_bool(PreApParamKeys.AUTO_SPEED, False)
  k = Card()
  _moving_double_pull(k, 8)
  assert k.c.mode == Mode.FULL and abs(k.mph() - 8) < 0.01


@pytest.mark.parametrize("mph", [15, 18, 22])
def test_rig_moving_double_pull_auto_speed_on_at_or_above_from_stop_is_unchanged(mph):
  set_bool(PreApParamKeys.AUTO_SPEED, True)
  k = Card()
  _moving_double_pull(k, mph)
  assert k.c.mode == Mode.FULL and abs(k.mph() - mph) < 0.01


def test_rig_moving_double_pull_below_from_stop_is_raised_to_from_stop():
  set_bool(PreApParamKeys.AUTO_SPEED, True)   # Pre-AP Auto Speed ON
  k = Card()
  v_kph = 8 * 1.609344
  _settle(k, 200, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  _settle(k, 9, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  out = _settle(k, 30, v_kph=v_kph)
  assert k.c.mode == Mode.FULL and not k.c.rig.cs.preap_standstill_hold and not out.bogpilot.preapLatOnly
  assert abs(k.mph() - 15) < 0.01, "8 mph moving double pull: raised to the 15 mph from-stop speed"
  assert any(any(e["enabled"]) for e in k.c.log[-10:]), "moving: no hold, pedal ENABLE flows"


def test_rig_moving_double_pull_above_from_stop_keeps_the_current_speed():
  k = Card()
  v_kph = 22 * 1.609344
  _settle(k, 200, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  _settle(k, 9, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  _settle(k, 30, v_kph=v_kph)
  assert k.c.mode == Mode.FULL and abs(k.mph() - 22) < 0.01


def test_rig_rolling_tip_below_from_stop_still_latches_the_current_speed():
  k = Card()
  v_kph = 8 * 1.609344
  _settle(k, 200, v_kph=v_kph)
  k.step(stalk=PULL, v_kph=v_kph)
  _settle(k, 60, v_kph=v_kph)              # window expires: steering only
  assert k.c.mode == Mode.LAT_ONLY
  k.step(stalk=TIP_UP, v_kph=v_kph)
  k.step(stalk=0, v_kph=v_kph)
  assert k.c.mode == Mode.FULL and abs(k.mph() - 8) < 0.01, "a tip is not raised to the 15 mph from-stop speed"
