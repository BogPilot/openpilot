"""Pre-AP: a stalk tap (UP/DN) never engages speed control or SLC, disengaged or steering-only.

Pre-AP engages only from a stalk pull (NAP-style double pull: the first pull is steering only, a second pull inside
the window adds speed control; NAP preap/engagement.py:126-173 @cc39c7fa). A tap is not a pull, so it can neither
engage openpilot nor turn a steering-only engagement into speed control, with or without a pedal. The double-pull
path itself is unchanged.
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
  assert all(o[2].bogpilot.preapLatOnly for o in after_pull)
  assert not any(o[1] for o in outs), "a tap added speed control"


@pytest.mark.parametrize("tap", TAPS)
def test_preap_tap_inside_the_double_pull_window_is_not_a_second_pull(tap):
  rig = _rig(True)
  seq = [0] * 20 + [PULL] + [0] * 5 + [tap] * 2 + [0] * 60
  outs = run_seq(rig, seq)
  assert outs[-1][0] and outs[-1][2].bogpilot.preapLatOnly
  assert not any(o[1] for o in outs)


def test_preap_double_pull_still_adds_speed_control():
  rig = _rig(True)
  seq = [0] * 20 + [PULL] + [0] * 5 + [PULL] + [0] * 60
  outs = run_seq(rig, seq)
  assert outs[-1][0] and outs[-1][1] and not outs[-1][2].bogpilot.preapLatOnly
