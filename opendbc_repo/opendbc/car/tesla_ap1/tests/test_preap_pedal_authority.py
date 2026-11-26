"""Pre-AP PedalAuthority: a failed acquisition retries with back-off and names its real cause; it is never a permanent latch."""
from types import SimpleNamespace

from opendbc.car import Bus, structs
from opendbc.car.tesla_ap1.preap import calib
from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
from opendbc.car.tesla_ap1.preap.pedal_authority import (
  MISMATCH_DISTINCT_STATES, RECOVERABLE_GIVE_UP_UPDATES, PEDAL_STATE_FAULT_STARTUP, PEDAL_STATE_FAULT_TIMEOUT, PEDAL_STATE_NO_FAULT, RETRY_BACKOFF_UPDATES,
  PedalAuthority, PedalAuthorityState, PedalCommandAction, PedalFailCause)
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (  # noqa: F401  (autouse fixture)
  PULL, Rig, _act, _params_dir, _pedal_frame, params)
from opendbc.car.tesla_ap1.values import CAR, DBC

A = PedalCommandAction
BAD = 9          # a state value that is neither healthy nor one the zero-gas keepalives can clear


def fb(idx=0, state=PEDAL_STATE_NO_FAULT, available=True):
  return SimpleNamespace(idx=idx, interceptor_state=state, available=available)


def acquire_until_exhausted(auth, make_feedback):
  """Run requested updates until the authority gives up; returns (actions, number of updates)."""
  actions = []
  for n in range(1, 40):
    act = auth.update(True, make_feedback(n))
    actions.append(act)
    if act == A.FAILURE:
      return actions, n
  raise AssertionError(f"never failed: {actions}")


def test_first_acquisition_still_works_and_is_unchanged():
  auth = PedalAuthority()
  assert auth.update(True, fb(idx=3)) == A.ACQUIRE                           # a healthy pedal is taken at once
  auth = PedalAuthority()
  assert auth.update(True, fb(idx=3, state=PEDAL_STATE_FAULT_TIMEOUT)) == A.RESET
  assert auth.update(True, fb(idx=4)) == A.ACQUIRE and auth.state == PedalAuthorityState.ACTIVE
  assert auth.update(True, fb(idx=5)) == A.ENABLE
  assert auth.fail_cause == PedalFailCause.NONE


def test_four_resets_no_longer_latch_failure_it_retries_with_back_off():
  auth = PedalAuthority()
  acquire_until_exhausted(auth, lambda n: fb(idx=0, state=BAD))
  assert auth.state == PedalAuthorityState.FAILED
  for gap in RETRY_BACKOFF_UPDATES + (RETRY_BACKOFF_UPDATES[-1],):          # every wait, then the capped 3 s one again
    for _ in range(gap - 1):
      assert auth.update(True, fb(state=BAD)) == A.NONE and auth.state == PedalAuthorityState.FAILED
    assert auth.update(True, fb(state=BAD)) == A.RESET, f"retry after {gap} updates"
    assert auth.state == PedalAuthorityState.ACQUIRING
    acquire_until_exhausted(auth, lambda n: fb(state=BAD))
  assert auth.retries == len(RETRY_BACKOFF_UPDATES) + 1


def test_a_retry_that_works_clears_everything():
  auth = PedalAuthority()
  acquire_until_exhausted(auth, lambda n: fb(idx=7, state=BAD))
  assert auth.fail_cause == PedalFailCause.STATE_FAULT
  for _ in range(RETRY_BACKOFF_UPDATES[0] - 1):
    assert auth.update(True, fb(idx=7, state=BAD)) == A.NONE
  assert auth.update(True, fb(idx=7, state=BAD)) == A.RESET                   # the first retry, after 0.5 s
  assert auth.update(True, fb(idx=8)) == A.ACQUIRE
  assert auth.fail_cause == PedalFailCause.NONE and auth.retries == 0 and auth.state == PedalAuthorityState.ACTIVE


def test_releasing_the_request_resets_back_off_and_cause():
  auth = PedalAuthority()
  acquire_until_exhausted(auth, lambda n: fb(state=BAD))
  for _ in range(5):
    auth.update(True, fb())
  auth.update(False, fb())
  assert auth.state == PedalAuthorityState.INACTIVE and auth.fail_cause == PedalFailCause.NONE and auth.retries == 0
  assert auth.update(True, fb()) == A.ACQUIRE                                # a fresh engage retries at once, no leftover wait


def test_cause_state_fault():
  auth = PedalAuthority()
  acquire_until_exhausted(auth, lambda n: fb(idx=5, state=BAD))
  assert auth.fail_cause == PedalFailCause.STATE_FAULT


def test_a_pedal_stuck_in_a_clearable_fault_is_reported_after_three_seconds_instead_of_silently_forever():
  auth = PedalAuthority()
  for state in (PEDAL_STATE_FAULT_TIMEOUT, PEDAL_STATE_FAULT_STARTUP):
    auth = PedalAuthority()
    acts = [auth.update(True, fb(idx=2, state=state)) for _ in range(RECOVERABLE_GIVE_UP_UPDATES)]
    assert set(acts) == {A.RESET} and auth.state == PedalAuthorityState.ACQUIRING        # keepalives all the way, as before
    assert auth.update(True, fb(idx=2, state=state)) == A.FAILURE and auth.fail_cause == PedalFailCause.STATE_FAULT
    assert auth.update(True, fb(idx=2, state=state)) == A.NONE                            # then it waits and retries


def test_cause_no_stream():
  auth = PedalAuthority()
  acquire_until_exhausted(auth, lambda n: fb(idx=5, available=False))
  assert auth.fail_cause == PedalFailCause.NO_STREAM


def test_cause_counter_stuck():
  auth = PedalAuthority()
  acquire_until_exhausted(auth, lambda n: fb(idx=5, available=(n > 1)))      # acquisition starts, then a healthy state with a counter that never moves
  assert auth.fail_cause == PedalFailCause.COUNTER_STUCK


def test_cause_data_mismatch_when_the_state_nibble_is_really_the_counter():
  """The shape from a drive log: the nibble read as STATE walks 0,1,2,3 like a counter, so the pedal never looks healthy and the counter never 'moves'."""
  auth = PedalAuthority()
  acquire_until_exhausted(auth, lambda n: fb(idx=0, state=n % 16))
  assert MISMATCH_DISTINCT_STATES <= 3
  assert auth.fail_cause == PedalFailCause.DATA_MISMATCH


def test_command_error_latches_until_the_driver_re_engages():
  auth = PedalAuthority()
  auth.update(True, fb(idx=1))
  auth.command_failed()
  assert auth.fail_cause == PedalFailCause.COMMAND_ERROR
  for _ in range(RETRY_BACKOFF_UPDATES[-1] * 3):
    assert auth.update(True, fb(idx=2)) == A.NONE
  assert auth.state == PedalAuthorityState.FAILED
  auth.update(False, fb())
  assert auth.update(True, fb(idx=3)) == A.ACQUIRE and auth.fail_cause == PedalFailCause.NONE and auth.state == PedalAuthorityState.ACTIVE


# ---- end to end through CarState + CarController: no latch, cause published, alert event, the engage that clears it is allowed ----
def _drive(rig, ctl, frames, state_at, pulls=(), idx0=0, long_on=True):
  enabled_frames, outs, op_enabled = 0, [], False
  for n in range(frames):
    _pedal_frame(rig, idx0 + n // 2, state=state_at(n))
    out = rig.frame(stalk=PULL if n in pulls else 0, op=op_enabled)
    rig.cs.out = out
    enable_req = rig.cs.update_button_enable(out.buttonEvents)
    op_enabled = bool(op_enabled and out.cruiseState.enabled) or bool(enable_req and out.cruiseState.available)
    cc = structs.CarControl.new_message(enabled=op_enabled, latActive=op_enabled, longActive=op_enabled and not out.bogpilot.preapLatOnly,
                                        actuators=_act(0.3)).as_reader()
    _, sends = ctl.update(cc, rig.cs, rig.nanos)
    for sd in sends:
      addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
      if addr == 0x551 and dat[4] & 0x80:
        enabled_frames += 1
    outs.append((op_enabled, out))
  return enabled_frames, outs


def _ready():
  calib.apply_calibration_result(calib.compute_calibration(0.8, 107.0))
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, False)
  rig = Rig()
  return rig, PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP)


def test_e2e_a_stuck_pedal_stays_engaged_reports_the_cause_and_recovers_when_it_heals():
  rig, ctl = _ready()
  heal_at = 700
  enabled, outs = _drive(rig, ctl, 1200, lambda n: BAD if n < heal_at else PEDAL_STATE_NO_FAULT, pulls={20, 45})
  # while the pedal is stuck: still engaged, cruise still "available" (the old latch dropped it), unavailable + the real cause published
  op, out = outs[500]
  assert op and out.cruiseState.enabled and out.cruiseState.available
  assert out.bogpilot.preapPedalUnavailable and out.bogpilot.preapPedalFailCause == int(PedalFailCause.STATE_FAULT)
  # after it heals the retry takes authority and the alert state clears on its own
  op, out = outs[-1]
  assert op and not out.bogpilot.preapPedalUnavailable and out.bogpilot.preapPedalFailCause == 0
  assert enabled > 20
