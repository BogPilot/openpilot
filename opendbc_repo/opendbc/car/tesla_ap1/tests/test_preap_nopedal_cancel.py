"""Pre-AP without a pedal: the first pull is steering only and a stock cruise it armed is cancelled (0x45 stays cancel-only);
the driver's real second pull re-arms stock cruise and that is speed control. NAP preap/engagement.py:126-173 @ e99f4dc75."""
from types import SimpleNamespace

from opendbc.car.tesla_ap1.preap.engagement import NOPEDAL_CC_CONFIRM_MS, Mode
from opendbc.car.tesla_ap1.preap.stock_cc_spoofer import CANCEL_DELAY_FRAMES, StockCCSpoofer
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, Rig, _inv, _params_dir, params  # noqa: F401


class FakeCan:
  def __init__(self):
    self.calls = []

  def create_action_request(self, msg, cancel, bus, counter):
    self.calls.append(cancel)
    return ("0x45", cancel, bus, counter)


def _cs():
  return SimpleNamespace(preap_cc_cancel_needed=True, msg_stw_actn_req={"MC_STW_ACTN_RQ": 3})


def _spin(sp, cs, can, frames):
  out = []
  for f in range(frames):
    out += sp.update(cs, f, can, 0)
  return out


def test_spoofer_only_builds_cancel_and_stamps_the_tx_time():
  sp, cs, can = StockCCSpoofer(), _cs(), FakeCan()
  sent = _spin(sp, cs, can, CANCEL_DELAY_FRAMES + 20)
  assert len(sent) == 1 and can.calls == [True]
  assert getattr(cs, "preap_cc_cancel_tx_ms", 0) > 0


def test_spoofer_drop_pending_sends_nothing():
  sp, cs, can = StockCCSpoofer(), _cs(), FakeCan()
  sp.update(cs, 0, can, 0)            # pending, inside the delay
  cs.preap_cc_cancel_drop = True
  assert _spin(sp, cs, can, CANCEL_DELAY_FRAMES + 20) == [] and can.calls == []
  assert cs.preap_cc_cancel_drop is False


def _di(r, state):
  r.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", state)


def test_nopedal_first_pull_cancels_when_di_armed():
  r = Rig(long=False)
  r.frame()
  out = r.frame(stalk=PULL)
  assert out.cruiseState.enabled and out.bogpilot.preapLatOnly and not r.cs.preap_cc_cancel_needed
  _di(r, "ENABLED")                   # the first pull armed stock cruise
  out = r.frame(op=True)
  assert r.cs.preap_cc_cancel_needed and out.bogpilot.preapLatOnly
  assert r.cs.preap_fsm_mode in (int(Mode.LAT_PENDING), int(Mode.LAT_ONLY))


def test_nopedal_full_confirmed_by_di_enabled_and_pending_cancel_dropped():
  r = Rig(long=False)
  r.frame()
  r.frame(stalk=PULL)
  _di(r, "ENABLED")
  r.frame(op=True)
  assert r.cs.preap_cc_cancel_needed
  for _ in range(5):
    r.frame(op=True)
  out = r.frame(stalk=PULL, op=True)  # second pull 70 ms after the first, before our CANCEL went out
  assert r.cs.preap_cc_cancel_drop and not r.cs.preap_cc_cancel_needed
  assert r.cs.preap_fsm_mode == int(Mode.FULL) and out.cruiseState.enabled and not out.bogpilot.preapLatOnly


def test_nopedal_not_armed_after_second_pull_stays_steering_only():
  r = Rig(long=False)
  r.frame()
  r.frame(stalk=PULL)
  r.frame()
  r.frame(stalk=PULL, op=True)        # DI stays STANDBY: the second pull did not arm stock cruise
  for _ in range(NOPEDAL_CC_CONFIRM_MS // 10 + 5):
    out = r.frame(op=True)
  assert out.cruiseState.enabled and out.bogpilot.preapLatOnly and r.cs.decision.cc_not_armed


def test_nopedal_brake_keeps_steering():
  r = Rig(long=False)
  r.frame()
  r.frame(stalk=PULL)
  for _ in range(3):
    out = r.frame(op=True, brake=True)
  assert out.cruiseState.enabled and out.bogpilot.preapLatOnly


def test_nopedal_stock_cruise_drop_in_full_leaves_steering_only():
  r = Rig(long=False)
  r.frame()
  r.frame(stalk=PULL)
  r.frame()
  _di(r, "ENABLED")
  r.frame(stalk=PULL, op=True)
  assert r.cs.preap_fsm_mode == int(Mode.FULL)
  _di(r, "STANDBY")                    # the DI dropped stock cruise (brake, its own cancel)
  out = r.frame(op=True)
  assert out.cruiseState.enabled and out.bogpilot.preapLatOnly and r.cs.preap_fsm_mode == int(Mode.LAT_ONLY)
