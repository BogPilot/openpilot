"""Pre-AP: re-engaging after a steerDisengage (hands on level 3 or an EPAS refusal), stock cruise (pcmCruise) vs pedal mode.

Same harness as test_preap_steer_disengage.py: the real PreApCarState from CAN, the real CarEvents and the selfdrived StateMachine,
with the panda mirror of tesla_preap.h (need_fresh_pull included). Not a full selfdrived process run.

- stock cruise (pcmCruise True): openpilot engages only on a rising edge of cruiseState.enabled (pcmEnable, car_events.py), and
  cruiseState.enabled follows DI_cruiseState (preap/carstate.py, no-pedal branch). After a steerDisengage the stock TACC is still on,
  so a fresh pull alone does NOT re-engage openpilot (the panda re-arms on it). Stock TACC must be cycled (cancel, then a pull that
  turns it back on) for pcmEnable; the panda re-arms on that same pull. While the panda waits for a fresh pull, carstate sets
  blockPcmEnable, so a TACC rising edge without that pull does not engage openpilot at all (silently, no new alert).
- pedal (pcmCruise False): a fresh pull edge raises buttonEnable (update_button_enable) and re-engages on that tick.
- in both, a pull held through the drop never re-engages either side.
"""
import pytest

from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import CANCEL, PULL, _inv, _params_dir  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import EAC_ACTIVE, EAC_FAULT, EAC_INHIBITED
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
def test_stock_cruise_fresh_pull_alone_does_not_reengage_tacc_must_be_cycled(cause, epas):
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  drop_with_pull_held(s, epas)
  # fresh pull with stock TACC still on: the panda re-arms, openpilot does not (no cruiseState rising edge, no buttonEnable)
  names, cs = s.step(stalk=PULL)
  assert cs.cruiseState.enabled and not names & ENABLE_EVENTS
  assert s.d.panda.controls_allowed and not s.d.panda.need_fresh_pull, "the panda re-arms on the fresh pull"
  for _ in range(100):
    names, _ = s.step()
    assert not names & ENABLE_EVENTS and s.sm.state == State.disabled, "openpilot stays off while TACC stays on"
  assert s.not_armed_frames == 0
  # cycle stock TACC: cancel (TACC off), then a pull that turns it back on
  tacc(s, False)
  names, _ = s.step(stalk=CANCEL)
  assert not s.d.panda.controls_allowed, "the cancel drops the panda too (outside its 600 ms echo window)"
  for _ in range(20):
    names, _ = s.step()
    assert s.sm.state == State.disabled
  tacc(s, True)
  names, _ = s.step(stalk=PULL)
  assert "pcmEnable" in names and s.sm.state in ENABLED_STATES, "pcmEnable on the TACC rising edge"
  assert s.d.panda.controls_allowed, "the panda re-arms on the same tick"
  stays_engaged(s)


@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_pedal_fresh_pull_reengages_on_that_tick(cause, epas):
  s = Selfdrive(pedal=True)
  engage_from_off(s)
  drop_with_pull_held(s, epas)
  names, _ = s.step(stalk=PULL)
  assert "buttonEnable" in names and s.sm.state in ENABLED_STATES, "a fresh pull re-engages openpilot"
  assert s.d.panda.controls_allowed, "the panda re-arms on the same tick"
  stays_engaged(s)


def _drop_then_tacc_cycle_without_a_pull(s):
  s.d.epas(3, EAC_ACTIVE, 0)
  names, _ = s.step()
  assert "steerDisengage" in names and s.sm.state == State.disabled
  s.d.epas(0, EAC_ACTIVE, 0)
  tacc(s, False)
  for _ in range(20):
    s.step()
  tacc(s, True)                                 # stock TACC back on with no lever pull the panda saw
  names, cs = s.step()
  assert cs.cruiseState.enabled and cs.blockPcmEnable
  assert not names & ENABLE_EVENTS and s.sm.state == State.disabled, "no pcmEnable while the panda waits for a fresh pull"
  for _ in range(100):
    names, _ = s.step()
    assert not names & ENABLE_EVENTS and s.sm.state == State.disabled
  assert not s.d.panda.controls_allowed and s.d.panda.need_fresh_pull
  assert s.not_armed_frames == 0, "openpilot never enabled, so no preapNotArmed"


def test_stock_cruise_tacc_edge_without_a_fresh_pull_does_not_engage():
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  _drop_then_tacc_cycle_without_a_pull(s)
  assert s.d.mirror_mismatch == 0


def test_stock_cruise_fresh_pull_and_tacc_cycle_engage_on_the_tick_the_panda_rearms():
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  _drop_then_tacc_cycle_without_a_pull(s)
  tacc(s, False)
  for _ in range(20):
    s.step()
  tacc(s, True)
  assert not s.d.panda.controls_allowed
  names, cs = s.step(stalk=PULL)                # the pull that turns TACC on is the fresh pull
  assert s.d.panda.controls_allowed and not s.d.panda.need_fresh_pull, "the panda re-arms on this tick"
  assert not cs.blockPcmEnable and "pcmEnable" in names and s.sm.state in ENABLED_STATES, "and openpilot engages on the same tick"
  stays_engaged(s)
  assert s.d.mirror_mismatch == 0


def test_stock_cruise_fresh_pull_with_tacc_already_on_still_needs_a_tacc_cycle():
  # TACC came on while blocked: the fresh pull clears the block and re-arms the panda, but there is no new cruiseState rising edge.
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  _drop_then_tacc_cycle_without_a_pull(s)
  names, cs = s.step(stalk=PULL)
  assert s.d.panda.controls_allowed and not cs.blockPcmEnable
  assert not names & ENABLE_EVENTS and s.sm.state == State.disabled
  tacc(s, False)
  s.step(stalk=CANCEL)
  for _ in range(20):
    s.step()
  tacc(s, True)
  names, _ = s.step(stalk=PULL)
  assert "pcmEnable" in names and s.sm.state in ENABLED_STATES and s.d.panda.controls_allowed
  stays_engaged(s)


@pytest.mark.parametrize("cause,epas", DROPS + [("fault", (0, EAC_FAULT, 0))], ids=[c for c, _ in DROPS] + ["fault"])
def test_stock_cruise_pending_pull_never_delays_a_disengage(cause, epas):
  s = Selfdrive(pedal=False)
  engage_from_off(s)
  s.d.epas(*epas)
  names, cs = s.step()
  assert s.sm.state == State.disabled, "disengaged on the drop frame"
  assert cs.blockPcmEnable and cs.cruiseState.enabled, "cruiseState still follows the car (no extra pcmDisable)"
  assert ("steerUnavailable" if cause == "fault" else "steerDisengage") in names
  assert "pcmDisable" not in names
  # TACC cancelled while the pull is pending: cruiseState drops on that tick
  s.d.epas(0, EAC_ACTIVE, 0)
  tacc(s, False)
  names, cs = s.step(stalk=CANCEL)
  assert not cs.cruiseState.enabled and "pcmDisable" in names


@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_pedal_mode_never_blocks_pcm_enable(cause, epas):
  s = Selfdrive(pedal=True)
  engage_from_off(s)
  drop_with_pull_held(s, epas)
  names, cs = s.step(stalk=PULL)
  assert not cs.blockPcmEnable and "buttonEnable" in names and s.sm.state in ENABLED_STATES
  assert s.d.mirror_mismatch == 0
