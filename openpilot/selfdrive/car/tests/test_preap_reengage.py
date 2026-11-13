"""Pre-AP: re-engaging after a steerDisengage (hands on level 3 or an EPAS refusal), stock cruise (pcmCruise) vs pedal mode.

Same harness as test_preap_steer_disengage.py: the real PreApCarState from CAN, the real CarEvents and the selfdrived StateMachine,
with the panda mirror of tesla_preap.h (need_fresh_pull included). Not a full selfdrived process run.

- stock cruise (pcmCruise True): openpilot engages only on a rising edge of cruiseState.enabled (pcmEnable, car_events.py). With the
  NAP-style double pull (preap/engagement.py), the no-pedal cruiseState.enabled is the engagement FSM's `engaged`, set only from a
  stalk pull, as NAP does (NAP opendbc preap/carstate.py:139, preap/engagement.py:67-78,126-173 @ cc39c7fa / NotAutopilot e99f4dc75).
  It no longer mirrors DI_cruiseState: that was the single-pull behavior of 0.9.7 na-preap, which the double pull replaced
  (rc9 pre-AP engagement design). A first pull engages STEERING ONLY and cancels stock cruise if that pull armed it; a second pull within
  400 ms is FULL (stock cruise armed by the driver's own pull). Every EPAS drop puts the FSM in LOCKOUT on the drop frame, so openpilot
  disengages on that frame and cruiseState.enabled drops with it. A fresh pull re-arms the panda and re-engages steering only on that
  tick; a pull held through the drop, or a stock TACC edge without a fresh pull (blockPcmEnable), never re-engages either side.
- pedal (pcmCruise False): a fresh pull edge raises buttonEnable (update_button_enable) and re-engages on that tick.
- in both, a pull held through the drop never re-engages either side.
"""
import pytest

from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import CANCEL, PULL, _inv, _params_dir  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import EAC_ACTIVE, EAC_FAULT, EAC_INHIBITED
from opendbc.car.tesla_ap1.preap.engagement import Mode
from openpilot.cereal import log
from openpilot.selfdrive.car.tests.test_preap_steer_disengage import Selfdrive
from openpilot.selfdrive.selfdrived.state import ENABLED_STATES

State = log.SelfdriveState.OpenpilotState
ENABLE_EVENTS = {"pcmEnable", "buttonEnable"}
DROPS = [("hands", (3, EAC_ACTIVE, 0))] + [(f"refusal{e}", (0, EAC_INHIBITED, e)) for e in (6, 7, 8, 9)]


def tacc(s, on):
  s.d.rig.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", "ENABLED" if on else "STANDBY")


def engage_from_off(s):
  if not s.d.pedal:
    tacc(s, False)
  for _ in range(20):
    s.step()
  if not s.d.pedal:
    tacc(s, True)                               # the pull turns stock TACC on (same tick)
  names, _ = s.step(stalk=PULL)
  assert names & ENABLE_EVENTS and s.sm.state in ENABLED_STATES and s.d.panda.controls_allowed
  for _ in range(30):
    s.step()
  assert s.sm.state in ENABLED_STATES


def drop_with_pull_held(s, epas):
  s.step(stalk=PULL)                            # the driver is holding the stalk pulled
  s.d.epas(*epas)
  names, _ = s.step(stalk=PULL)
  assert "steerDisengage" in names and s.sm.state == State.disabled and not s.d.panda.controls_allowed
  for _ in range(50):
    names, _ = s.step(stalk=PULL)               # condition still on, pull held
    assert not names & ENABLE_EVENTS and s.sm.state == State.disabled and not s.d.panda.controls_allowed
  s.d.epas(0, EAC_ACTIVE, 0)
  for _ in range(50):
    names, _ = s.step(stalk=PULL)               # condition gone, pull still held: neither side re-arms
    assert not names & ENABLE_EVENTS and s.sm.state == State.disabled and not s.d.panda.controls_allowed
  assert s.d.panda.need_fresh_pull
  for _ in range(5):
    s.step()                                    # release


def stays_engaged(s, frames=200):
  for _ in range(frames):
    names, _ = s.step()
    assert s.sm.state in ENABLED_STATES, names
    assert "steerDisengage" not in names
  assert s.d.panda.controls_allowed
  assert s.not_armed_frames == 0, "no preapNotArmed after the re-engage"


@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_pedal_fresh_pull_reengages_on_that_tick(cause, epas):
  s = Selfdrive(pedal=True)
  engage_from_off(s)
  drop_with_pull_held(s, epas)
  names, _ = s.step(stalk=PULL)
  assert "buttonEnable" in names and s.sm.state in ENABLED_STATES, "a fresh pull re-engages openpilot"
  assert s.d.panda.controls_allowed, "the panda re-arms on the same tick"
  stays_engaged(s)


def _lat_only(cs):
  # steering only: LAT_PENDING while the 400 ms second-pull window is open, LAT_ONLY after it
  return cs.bogpilot.preapLatOnly and cs.bogpilot.preapFsmMode in (int(Mode.LAT_PENDING), int(Mode.LAT_ONLY))


@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_stock_cruise_fresh_pull_reengages_steering_only_then_second_pull_is_full(cause, epas):
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  drop_with_pull_held(s, epas)
  names, cs = s.step()
  assert s.sm.state == State.disabled and not cs.cruiseState.enabled and cs.blockPcmEnable
  assert cs.bogpilot.preapFsmMode == int(Mode.LOCKOUT)
  # fresh pull with stock TACC still on: the panda re-arms and openpilot re-engages STEERING ONLY on the same tick (first pull)
  names, cs = s.step(stalk=PULL)
  assert s.d.panda.controls_allowed and not s.d.panda.need_fresh_pull, "the panda re-arms on the fresh pull"
  assert "pcmEnable" in names and s.sm.state in ENABLED_STATES and not cs.blockPcmEnable, "openpilot re-engages on the same tick"
  assert _lat_only(cs), "a first pull is steering only"
  names, cs = s.step()
  assert s.d.rig.cs.preap_cc_cancel_needed, "stock cruise left on by the first pull is cancelled (steering only)"
  # a second pull inside the 400 ms window: FULL
  names, cs = s.step(stalk=PULL)
  assert cs.bogpilot.preapFsmMode == int(Mode.FULL) and not cs.bogpilot.preapLatOnly
  stays_engaged(s)
  assert s.d.mirror_mismatch == 0


def _drop_then_tacc_cycle_without_a_pull(s):
  s.d.epas(3, EAC_ACTIVE, 0)
  names, cs = s.step()
  assert "steerDisengage" in names and s.sm.state == State.disabled
  assert not cs.cruiseState.enabled and cs.bogpilot.preapFsmMode == int(Mode.LOCKOUT)
  s.d.epas(0, EAC_ACTIVE, 0)
  tacc(s, False)
  for _ in range(20):
    s.step()
  tacc(s, True)                                 # stock TACC back on with no lever pull the panda saw
  names, cs = s.step()
  assert cs.blockPcmEnable and not cs.cruiseState.enabled, "a TACC edge alone does not raise cruiseState.enabled"
  assert not names & ENABLE_EVENTS and s.sm.state == State.disabled, "no pcmEnable while the panda waits for a fresh pull"
  for _ in range(100):
    names, cs = s.step()
    assert not names & ENABLE_EVENTS and s.sm.state == State.disabled and not cs.cruiseState.enabled
  assert not s.d.panda.controls_allowed and s.d.panda.need_fresh_pull
  assert s.not_armed_frames == 0, "openpilot never enabled, so no preapNotArmed"


def test_stock_cruise_tacc_edge_without_a_fresh_pull_does_not_engage():
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  _drop_then_tacc_cycle_without_a_pull(s)
  assert s.d.mirror_mismatch == 0


def test_stock_cruise_fresh_pull_after_a_tacc_cycle_engages_on_the_tick_the_panda_rearms():
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  _drop_then_tacc_cycle_without_a_pull(s)
  tacc(s, False)
  for _ in range(20):
    s.step()
  tacc(s, True)
  assert not s.d.panda.controls_allowed
  names, cs = s.step(stalk=PULL)                # the fresh pull
  assert s.d.panda.controls_allowed and not s.d.panda.need_fresh_pull, "the panda re-arms on this tick"
  assert not cs.blockPcmEnable and "pcmEnable" in names and s.sm.state in ENABLED_STATES, "and openpilot engages on the same tick"
  assert _lat_only(cs)
  stays_engaged(s)
  assert s.d.mirror_mismatch == 0


def test_stock_cruise_fresh_pull_with_tacc_already_on_engages_steering_only():
  # TACC came on while blocked: the fresh pull clears the block, re-arms the panda and engages steering only (first pull).
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  _drop_then_tacc_cycle_without_a_pull(s)
  names, cs = s.step(stalk=PULL)
  assert s.d.panda.controls_allowed and not cs.blockPcmEnable
  assert "pcmEnable" in names and s.sm.state in ENABLED_STATES and _lat_only(cs)
  stays_engaged(s)


@pytest.mark.parametrize("cause,epas", DROPS + [("fault", (0, EAC_FAULT, 0))], ids=[c for c, _ in DROPS] + ["fault"])
def test_stock_cruise_pending_pull_never_delays_a_disengage(cause, epas):
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  # a first pull opens the 400 ms second-pull window; a drop inside that window still disengages on the drop frame
  for _ in range(5):
    s.step()
  names, cs = s.step(stalk=PULL)
  assert s.sm.state in ENABLED_STATES
  s.d.epas(*epas)
  names, cs = s.step()
  assert s.sm.state == State.disabled, "disengaged on the drop frame"
  assert not s.d.panda.controls_allowed and s.d.panda.need_fresh_pull
  assert not cs.cruiseState.enabled and cs.blockPcmEnable and cs.bogpilot.preapFsmMode == int(Mode.LOCKOUT)
  assert ("steerUnavailable" if cause == "fault" else "steerDisengage") in names
  assert "pcmDisable" in names, "cruiseState drops with the FSM on the drop frame (NAP preap/carstate.py:139), so pcmDisable fires too"
  # the rest of the window (and well past it) never brings it back without a fresh pull
  s.d.epas(0, EAC_ACTIVE, 0)
  for _ in range(60):
    names, cs = s.step()
    assert not names & ENABLE_EVENTS and s.sm.state == State.disabled and not cs.cruiseState.enabled
  # TACC cancelled: still off
  tacc(s, False)
  names, cs = s.step(stalk=CANCEL)
  assert not cs.cruiseState.enabled and s.sm.state == State.disabled and "pcmDisable" in names


@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_pedal_mode_never_blocks_pcm_enable(cause, epas):
  s = Selfdrive(pedal=True)
  engage_from_off(s)
  drop_with_pull_held(s, epas)
  names, cs = s.step(stalk=PULL)
  assert not cs.blockPcmEnable and "buttonEnable" in names and s.sm.state in ENABLED_STATES
  assert s.d.mirror_mismatch == 0
