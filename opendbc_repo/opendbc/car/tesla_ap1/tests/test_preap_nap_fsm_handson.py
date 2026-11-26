"""Pre-AP hands-on / EPAS drop through the real CarState: the pull FSM goes to LOCKOUT on the same tick as the panda model's
need_fresh_pull (tesla_preap.h tesla_preap_epas_state) and only a fresh pull leaves it. NAP drops steering on hands-on too
(NAP opendbc preap/carstate.py:60-68 @ cc39c7fa); a no-pedal stock cruise is left alone unless Q3 says otherwise."""
import pytest

from opendbc.car.tesla_ap1.preap import engagement
from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, _params_dir  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import EAC_ACTIVE, EAC_FAULT, EAC_INHIBITED, Drive

DROPS = [("hands", (3, EAC_ACTIVE, 0)), ("refusal7", (0, EAC_INHIBITED, 7)), ("fault", (0, EAC_FAULT, 0))]


def _engaged(pedal):
  d = Drive(pedal=pedal)
  for _ in range(3):
    d.step(op=False)
  d.step(stalk=PULL, op=False)
  for _ in range(5):
    out = d.step()
  assert out.cruiseState.enabled and d.rig.cs.preap_fsm_mode != int(Mode.OFF)
  return d


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "nopedal"])
@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_drop_locks_out_with_the_panda_and_a_fresh_pull_re_engages_steering_only(pedal, cause, epas):
  d = _engaged(pedal)
  d.epas(*epas)
  out = d.step()
  cs = d.rig.cs
  assert cs.preap_fsm_mode == int(Mode.LOCKOUT) and not out.cruiseState.enabled
  assert d.panda.need_fresh_pull and cs.preap_fresh_pull_pending
  d.epas(0, EAC_ACTIVE, 0)
  for _ in range(10):
    out = d.step(op=False)
    assert cs.preap_fsm_mode == int(Mode.LOCKOUT) and d.panda.need_fresh_pull and not out.cruiseState.enabled
  out = d.step(stalk=PULL, op=False)
  assert cs.preap_fsm_mode == int(Mode.LAT_PENDING) and not d.panda.need_fresh_pull and out.cruiseState.enabled
  assert out.bogpilot.preapLatOnly
  assert d.mirror_mismatch == 0


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "nopedal"])
def test_pull_held_through_the_drop_does_not_re_engage(pedal):
  d = _engaged(pedal)
  d.step(stalk=PULL)
  d.epas(3, EAC_ACTIVE, 0)
  for _ in range(3):
    d.step(stalk=PULL)
  d.epas(0, EAC_ACTIVE, 0)
  for _ in range(5):
    out = d.step(stalk=PULL, op=False)
    assert d.rig.cs.preap_fsm_mode == int(Mode.LOCKOUT) and not out.cruiseState.enabled
  for _ in range(3):
    d.step(op=False)
  out = d.step(stalk=PULL, op=False)
  assert out.cruiseState.enabled and d.mirror_mismatch == 0


def test_nopedal_hands_on_leaves_stock_cruise_by_default():
  d = _engaged(False)
  d.rig.cs.preap_cc_cancel_needed = False
  d.epas(3, EAC_ACTIVE, 0)
  d.step()
  assert not d.rig.cs.preap_cc_cancel_needed            # Q3 default: NAP parity


def test_nopedal_hands_on_cancel_when_q3_says_so(monkeypatch):
  monkeypatch.setattr(engagement, "PREAP_NOPEDAL_CANCEL_ON_HANDS_ON", True)
  d = _engaged(False)
  d.rig.cs.preap_cc_cancel_needed = False
  d.epas(3, EAC_ACTIVE, 0)
  d.step()
  assert d.rig.cs.preap_cc_cancel_needed and d.rig.cs.preap_fsm_mode == int(Mode.LOCKOUT)
