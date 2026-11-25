"""Pedal path: the stock cruise CANCEL (STW_ACTN_RQ 0x45) goes on the bus only while stock DI cruise is engaged.

A pedal trigger (long engage, long release, lever change) waits up to DI_WAIT_FRAMES for DI_cruiseState to read engaged and is
dropped if it never does. The no-pedal FSM keeps its own timing and is not gated here.
"""
from types import SimpleNamespace

import pytest

from opendbc.car.tesla_ap1.preap.stock_cc_spoofer import CANCEL_DELAY_FRAMES, DI_WAIT_FRAMES, StockCCSpoofer
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (PULL, Rig, _inv, _params_dir, params)  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_spoof_echo_window import TIP, _ready_rig, _step


class FakeCan:
  def __init__(self):
    self.calls = []

  def create_action_request(self, msg, cancel, bus, counter):
    self.calls.append((cancel, counter))
    return ("0x45", cancel, bus, counter)


def _cs(di=False):
  return SimpleNamespace(preap_cc_cancel_needed=False, preap_cc_cancel_wait_di=False, preap_di_cc_engaged=di,
                         msg_stw_actn_req={"MC_STW_ACTN_RQ": 3})


def _trigger(cs, gated=True):
  cs.preap_cc_cancel_needed = True
  cs.preap_cc_cancel_wait_di = gated


def _run(sp, cs, can, start, stop, di_at=None):
  sent = []
  for f in range(start, stop):
    if di_at is not None and f >= di_at:
      cs.preap_di_cc_engaged = True
    for s in sp.update(cs, f, can, 0):
      sent.append((f, s))
  return sent


def test_cruise_off_sends_nothing_and_drops():
  sp, cs, can = StockCCSpoofer(), _cs(di=False), FakeCan()
  _trigger(cs)
  assert _run(sp, cs, can, 0, 3 * DI_WAIT_FRAMES) == []
  assert can.calls == [] and not sp.cancel_pending and sp.dropped_di_off == 1


def test_cruise_engages_inside_the_window_sends_exactly_one_cancel():
  sp, cs, can = StockCCSpoofer(), _cs(di=False), FakeCan()
  _trigger(cs)
  sent = _run(sp, cs, can, 0, 3 * DI_WAIT_FRAMES, di_at=45)
  assert len(sent) == 1 and can.calls == [(True, 4)]
  assert sent[0][0] == 50                                   # first 10-frame TX slot once the DI reads engaged
  assert getattr(cs, "preap_cc_cancel_tx_ms", 0) > 0 and cs.preap_last_cc_spoof_ms == cs.preap_cc_cancel_tx_ms
  assert sp.dropped_di_off == 0


def test_cruise_already_engaged_keeps_the_old_timing():
  sp, cs, can = StockCCSpoofer(), _cs(di=True), FakeCan()
  _trigger(cs)
  sent = _run(sp, cs, can, 0, 3 * DI_WAIT_FRAMES)
  assert [f for f, _ in sent] == [CANCEL_DELAY_FRAMES]


def test_cruise_never_engages_is_dropped_and_a_late_engage_sends_nothing():
  sp, cs, can = StockCCSpoofer(), _cs(di=False), FakeCan()
  _trigger(cs)
  assert _run(sp, cs, can, 0, DI_WAIT_FRAMES + 1) == []
  assert not sp.cancel_pending and sp.dropped_di_off == 1
  assert _run(sp, cs, can, DI_WAIT_FRAMES + 1, 4 * DI_WAIT_FRAMES, di_at=DI_WAIT_FRAMES + 20) == []
  assert can.calls == []


def test_a_new_trigger_restarts_the_window():
  sp, cs, can = StockCCSpoofer(), _cs(di=False), FakeCan()
  _trigger(cs)
  assert _run(sp, cs, can, 0, 80) == []
  _trigger(cs)                                              # e.g. a lever change 0.8 s later
  sent = _run(sp, cs, can, 80, 400, di_at=170)              # 0.9 s after the second trigger
  assert [f for f, _ in sent] == [170]


@pytest.mark.parametrize("di", [False, True])
def test_no_pedal_request_is_not_gated(di):
  sp, cs, can = StockCCSpoofer(), _cs(di=di), FakeCan()
  _trigger(cs, gated=False)
  assert [f for f, _ in _run(sp, cs, can, 0, 3 * DI_WAIT_FRAMES)] == [CANCEL_DELAY_FRAMES]


def test_a_gated_trigger_never_weakens_a_pending_ungated_cancel():
  sp, cs, can = StockCCSpoofer(), _cs(di=False), FakeCan()
  _trigger(cs, gated=False)
  _run(sp, cs, can, 0, 3)
  _trigger(cs, gated=True)
  assert len(_run(sp, cs, can, 3, 3 * DI_WAIT_FRAMES)) == 1


def test_drop_pending_clears_the_gate():
  sp, cs, can = StockCCSpoofer(), _cs(di=False), FakeCan()
  _trigger(cs)
  _run(sp, cs, can, 0, 3)
  cs.preap_cc_cancel_drop = True
  _run(sp, cs, can, 3, 4)
  assert not sp.cancel_pending and not sp.wait_di


@pytest.mark.parametrize("di_on, expected", [(False, 0), (True, 68)])
def test_drive_shaped_sequence_68_triggers(di_on, expected):
  """68 pedal triggers spread over a 45 minute drive (the count from a logged Pre-AP drive with stock cruise off the whole time).
  Before the gate every trigger put one CANCEL on the bus; now none do while stock cruise is off."""
  sp, cs, can = StockCCSpoofer(), _cs(di=di_on), FakeCan()
  triggers = {1000 + i * 3900 for i in range(68)}           # 39 s apart, well outside any window
  sent = 0
  for f in range(0, 1000 + 68 * 3900 + 500):
    if f in triggers:
      _trigger(cs)
    sent += len(sp.update(cs, f, can, 0))
  assert sent == expected
  assert sp.dropped_di_off == (68 - expected)


@pytest.mark.parametrize("state, engaged", [("OFF", False), ("STANDBY", False), ("ENABLED", True), ("STANDSTILL", True),
                                            ("OVERRIDE", True), ("PRE_CANCEL", True), ("PRE_FAULT", True), ("FAULT", False)])
def test_carstate_exposes_stock_cruise_engaged(state, engaged):
  r = Rig()
  r.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", state)
  r.frame()
  assert r.cs.preap_di_cc_engaged is engaged


def _stw(sends):
  return [s for s in sends if (s.address if hasattr(s, "address") else s[0]) == 0x45]


def _drive(rig, ctl, start, stop, op, stalk_at=None):
  n_stw = 0
  for n in range(start, stop):
    op, out, stw = _step(rig, ctl, n, (stalk_at or {}).get(n, 0), op)
    n_stw += len(stw)
  return op, out, n_stw


def test_controller_stock_cruise_off_engage_and_tip_put_no_0x45_on_the_bus():
  rig, ctl = _ready_rig(double=False)
  rig.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", "OFF")
  op, out, n_stw = _drive(rig, ctl, 0, 150, False, stalk_at={20: PULL, 45: PULL})
  assert op and not out.bogpilot.preapLatOnly, "speed control engaged with stock cruise off"
  op, out, n2 = _drive(rig, ctl, 150, 400, op, stalk_at={150: TIP})
  assert n_stw == 0 and n2 == 0
  assert ctl.stock_cc.dropped_di_off >= 1


def test_controller_stock_cruise_engaged_by_the_pull_is_cancelled_once():
  rig, ctl = _ready_rig(double=False)
  op, out, _ = _drive(rig, ctl, 0, 150, False, stalk_at={20: PULL, 45: PULL})
  assert op and not out.bogpilot.preapLatOnly
  rig.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", "ENABLED")   # stock cruise armed by the stalk
  op, out, n_stw = _drive(rig, ctl, 150, 300, op, stalk_at={150: TIP})
  assert n_stw == 1
