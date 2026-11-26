"""Pre-AP stalk tap (UP/DN) rules, v6: a tap never engages openpilot from disengaged and never takes SLC; with the
pedal, a tap while steering only (after the first pull, or after a brake override ended speed control) engages speed control at the
current speed rounded to a whole display unit; with no pedal a tap never adds speed control (unchanged).

History: the original rule ("a tap never engages speed control or SLC", commit 7cab7e66f) came from copying NAP's engagement
(NAP preap/engagement.py:126-173 @cc39c7fa: only a second pull adds speed control). It was later replaced (from-stop tip rule; identical tip behaviour on AP1 and Pre-AP, following the AP1 tap latch: tesla_ap1/op_long_set_speed.py rules 2-3).
Pre-AP engages from a stalk pull: the first pull is steering only, a second pull inside the window adds speed control. The tip entry
is engagement.py PREAP_TIP_ENGAGES_LONG; it needs a first pull (the panda's controls_allowed) and a closed double-pull window.
"""
import pytest

from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (PULL, Rig, _inv, _params_dir,  # noqa: F401
                                                                        _pedal_frame, _ready_rig)

TAPS = [4, 16, 8, 32]   # SpdCtrlLvr_Stat UP_2ND, UP_1ST, DN_2ND, DN_1ST


def run_seq(rig, seq, pedal=True):
  """seq: stalk value per 10 ms frame. Returns [(op_enabled, long_active, out)] the way controlsd sees it."""
  op_enabled, outs = False, []
  for n, stalk in enumerate(seq):
    if pedal:
      _pedal_frame(rig, n)
    out = rig.frame(stalk=stalk, op=op_enabled)
    rig.cs.out = out
    enable_req = rig.cs.update_button_enable(out.buttonEvents)
    if pedal:   # pcmCruise False: buttonEnable
      op_enabled = bool(op_enabled and out.cruiseState.enabled) or bool(enable_req and out.cruiseState.available)
    else:       # no pedal (pcmCruise True): openpilot follows cruiseState.enabled (pcmEnable on its rising edge)
      op_enabled = bool(out.cruiseState.enabled)
    long_active = op_enabled and not out.bogpilot.preapLatOnly
    outs.append((op_enabled, long_active, out))
  return outs


def _rig(pedal):
  return _ready_rig(double=True)[0] if pedal else Rig(long=False)


@pytest.mark.parametrize("pedal", [True, False])
@pytest.mark.parametrize("tap", TAPS)
def test_preap_tap_while_disengaged_never_engages(pedal, tap):
  rig = _rig(pedal)
  outs = run_seq(rig, [0] * 20 + [tap] * 3 + [0] * 50, pedal=pedal)
  assert not any(o[0] for o in outs), "a tap engaged openpilot"
  assert not any(o[1] for o in outs), "a tap engaged speed control"
  assert not any(o[2].cruiseState.enabled for o in outs)


@pytest.mark.parametrize("tap", TAPS)
def test_preap_no_pedal_tap_that_arms_stock_cruise_does_not_engage_openpilot(tap):
  rig = Rig(long=False)
  run_seq(rig, [0] * 10, pedal=False)
  rig.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", "ENABLED")   # stock TACC on from the tap
  outs = run_seq(rig, [tap] * 3 + [0] * 50, pedal=False)
  assert not any(o[0] or o[2].cruiseState.enabled for o in outs)


@pytest.mark.parametrize("pedal", [True, False])
@pytest.mark.parametrize("tap", TAPS)
def test_preap_tap_while_steering_only_never_adds_speed_control(pedal, tap):
  rig = _rig(pedal)
  seq = [0] * 20 + [PULL] + [0] * 60 + [tap] * 3 + [0] * 60
  outs = run_seq(rig, seq, pedal=pedal)
  after_pull = outs[21:]
  assert all(o[0] for o in after_pull), "steering-only engagement dropped"
  if pedal:
    # the tap (released at frame 84) latches speed control; never before it
    assert all(o[2].bogpilot.preapLatOnly for o in outs[21:84])
    assert outs[-1][1] and not outs[-1][2].bogpilot.preapLatOnly, "the tap latched speed control"
    return
  assert all(o[2].bogpilot.preapLatOnly for o in after_pull)
  assert not any(o[1] for o in outs), "a tap added speed control"


@pytest.mark.parametrize("tap", TAPS)
def test_preap_tap_inside_the_double_pull_window_is_not_a_second_pull(tap):
  rig = _rig(True)
  seq = [0] * 20 + [PULL] + [0] * 5 + [tap] * 2 + [0] * 60
  outs = run_seq(rig, seq)
  assert outs[-1][0] and outs[-1][2].bogpilot.preapLatOnly
  assert not any(o[1] for o in outs)


def test_preap_tap_from_steering_only_latches_the_rounded_current_speed_pedal_only():
  from opendbc.car.common.conversions import Conversions as CV
  from opendbc.car.tesla_ap1.preap.engagement import Mode
  from opendbc.car.tesla_ap1.tests.test_preap_from_stop_v5 import Card, _settle
  k = Card()
  v = 12.6 * CV.MPH_TO_KPH
  _settle(k, 200, v_kph=v)
  k.step(stalk=PULL, v_kph=v)
  _settle(k, 60, v_kph=v)
  assert k.c.mode == Mode.LAT_ONLY
  k.step(stalk=4, v_kph=v)
  k.step(stalk=0, v_kph=v)
  assert k.c.mode == Mode.FULL and abs(k.mph() - 13) < 0.01, "whole mph (12.6 -> 13); never SLC, never the engaging tip's own step"


def test_preap_double_pull_still_adds_speed_control():
  rig = _rig(True)
  seq = [0] * 20 + [PULL] + [0] * 5 + [PULL] + [0] * 60
  outs = run_seq(rig, seq)
  assert outs[-1][0] and outs[-1][1] and not outs[-1][2].bogpilot.preapLatOnly
