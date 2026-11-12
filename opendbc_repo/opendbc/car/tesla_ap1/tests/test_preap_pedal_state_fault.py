"""Pre-AP pedal: a fault STATE while the authority is ACTIVE never yields an enabled GAS_COMMAND, and FAILED stays quiet.

GAS_SENSOR STATE values are the ones tesla_ap1_can.dbc defines (VAL_ 1362 STATE): 0 NO_FAULT, 1 FAULT_BAD_CHECKSUM,
2 FAULT_SEND, 3 FAULT_SCE, 4 FAULT_STARTUP, 5 FAULT_TIMEOUT.
BogPilot preap/pedal_authority.py:187-191: in ACTIVE, any STATE other than NO_FAULT is not healthy, so the update restarts
acquisition (_start_acquisition, :140-146) and returns RESET. preap/long_controller.py:167-169: RESET sends
create_pedal_command(0.0, enable=0), which preap/pedal_can.py:59-77 packs as ENABLE=0 with a zero gas command.
FAILED (pedal_authority.py:176-185) returns NONE until its back-off ends; long_controller.py:247-248 sends no frame for NONE.
End-to-end cases feed real GAS_SENSOR frames through PreApCarState and read the real 0x551 frames PreApCarController sends.
Tests only; no behaviour is changed by this file.
"""
import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1.preap.pedal_authority import (
  PEDAL_STATE_NO_FAULT, RETRY_BACKOFF_UPDATES, PedalAuthority, PedalAuthorityState, PedalCommandAction)
from opendbc.car.tesla_ap1.preap.pedal_can import GAS_COMMAND_ID
from opendbc.car.tesla_ap1.tests.ap1_harness import decode
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (  # noqa: F401  (autouse fixture)
  PULL, _act, _params_dir, _pedal_frame, _ready_rig)
from opendbc.car.tesla_ap1.tests.test_preap_pedal_authority import fb

A = PedalCommandAction
FAULT_STATES = [1, 2, 3, 4, 5]          # every non-zero STATE the DBC names
ENABLE_BYTE_BIT = 0x80                  # GAS_COMMAND ENABLE is 39|1: byte 4 bit 7


# ---- PedalAuthority alone ------------------------------------------------------------------------------

def _active_authority():
  auth = PedalAuthority()
  assert auth.update(True, fb(idx=1)) == A.ACQUIRE and auth.state == PedalAuthorityState.ACTIVE
  assert auth.update(True, fb(idx=2)) == A.ENABLE
  return auth


@pytest.mark.parametrize("state", FAULT_STATES)
def test_active_authority_answers_a_fault_state_with_reset(state):
  auth = _active_authority()
  assert auth.update(True, fb(idx=3, state=state)) == A.RESET
  assert auth.state == PedalAuthorityState.ACQUIRING


@pytest.mark.parametrize("state", FAULT_STATES)
def test_authority_never_enables_while_the_fault_state_persists(state):
  auth = _active_authority()
  seen = [auth.update(True, fb(idx=3 + n, state=state)) for n in range(400)]
  assert A.ENABLE not in seen and A.ACQUIRE not in seen, (state, sorted(set(seen)))


def test_failed_authority_is_silent_through_its_back_off():
  auth = _active_authority()
  seen = []
  while auth.state != PedalAuthorityState.FAILED:
    seen.append(auth.update(True, fb(idx=3, state=1)))
    assert len(seen) < 50
  for _ in range(RETRY_BACKOFF_UPDATES[0] - 1):
    assert auth.update(True, fb(idx=3, state=1)) == A.NONE and auth.state == PedalAuthorityState.FAILED


# ---- end to end: GAS_SENSOR -> PreApCarState -> PreApCarController -> 0x551 ----------------------------

class Run:
  """Single pull to engage with a healthy pedal, then GAS_SENSOR STATE follows `self.state`; records each authority step."""

  def __init__(self):
    self.rig, self.ctl = _ready_rig(double=False)
    self.auth = self.ctl.long_ctrl.pedal_authority
    self.calls = []          # (STATE the authority saw, authority state before, action)
    real = self.auth.update

    def spy(requested, feedback):
      before = self.auth.state
      act = real(requested, feedback)
      self.calls.append((int(feedback.interceptor_state), before, act))
      return act

    self.auth.update = spy
    self.state = PEDAL_STATE_NO_FAULT
    self.n = 0
    self.op = False

  def step(self, pull=False):
    """One 10 ms frame; returns the 0x551 frames sent and the authority calls made in it."""
    _pedal_frame(self.rig, self.n // 2, state=self.state)
    out = self.rig.frame(stalk=PULL if pull else 0, op=self.op)
    self.rig.cs.out = out
    enable_req = self.rig.cs.update_button_enable(out.buttonEvents)
    self.op = bool(self.op and out.cruiseState.enabled) or bool(enable_req and out.cruiseState.available)
    cc = structs.CarControl.new_message(enabled=self.op, latActive=self.op, longActive=self.op and not out.bogpilot.preapLatOnly,
                                        actuators=_act(0.3)).as_reader()
    k = len(self.calls)
    _, sends = self.ctl.update(cc, self.rig.cs, self.rig.nanos)
    self.n += 1
    frames = [bytes(s.dat if hasattr(s, "dat") else s[1]) for s in sends if (s.address if hasattr(s, "address") else s[0]) == GAS_COMMAND_ID]
    return frames, self.calls[k:]

  def engage(self):
    enabled = 0
    for i in range(300):
      frames, _ = self.step(pull=(i == 20))
      enabled += sum(1 for d in frames if d[4] & ENABLE_BYTE_BIT)
    assert self.op and self.auth.state == PedalAuthorityState.ACTIVE and enabled > 20, "engaged, pedal enabled before the fault"


def _is_reset_frame(dat):
  name, v = decode(GAS_COMMAND_ID, dat)
  return name == "GAS_COMMAND" and v["ENABLE"] == 0 and dat[0:4] == b"\x00\x00\x00\x00"


@pytest.mark.parametrize("state", FAULT_STATES)
def test_e2e_fault_state_while_active_sends_reset_or_nothing_never_enable(state):
  r = Run()
  r.engage()
  r.state = state
  first = None
  for _ in range(20):                          # the authority runs every other frame; find its first step with this STATE
    frames, calls = r.step()
    hit = [c for c in calls if c[0] == state]
    if hit:
      first = (frames, hit[0])
      break
  assert first is not None, "the authority never saw the new STATE"
  frames, (_, before, act) = first
  assert before == PedalAuthorityState.ACTIVE, before
  assert all(not d[4] & ENABLE_BYTE_BIT for d in frames), (state, act, [d.hex() for d in frames])
  assert all(_is_reset_frame(d) for d in frames), (state, act, [d.hex() for d in frames])
  # and while the fault stays, no enabled frame is ever sent (keepalives, retries and failures included)
  for _ in range(800):
    frames, _ = r.step()
    assert all(not d[4] & ENABLE_BYTE_BIT for d in frames), (state, [d.hex() for d in frames])


def test_e2e_failed_sends_nothing_for_several_updates():
  r = Run()
  r.engage()
  r.state = 1                                  # FAULT_BAD_CHECKSUM: not a keepalive state, so the reset attempts run out
  for _ in range(100):
    r.step()
    if r.auth.state == PedalAuthorityState.FAILED:
      break
  assert r.auth.state == PedalAuthorityState.FAILED
  updates = 0
  while updates < RETRY_BACKOFF_UPDATES[0] - 1:
    frames, calls = r.step()
    updates += len(calls)
    assert frames == [], [d.hex() for d in frames]
    assert all(c[2] == A.NONE for c in calls)


def test_e2e_latched_failure_stays_silent():
  r = Run()
  r.engage()
  r.auth.command_failed()                      # pedal_authority.py:226-230: latched until the driver re-engages
  updates = 0
  while updates < RETRY_BACKOFF_UPDATES[-1] * 2:
    frames, calls = r.step()
    updates += len(calls)
    assert frames == [], [d.hex() for d in frames]
  assert r.auth.state == PedalAuthorityState.FAILED
