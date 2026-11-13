"""CarController level: the 300 ms spoof-echo window opens only on our own CANCEL frame (StockCCSpoofer TX) and never
swallows a cancel the panda counts as real (tesla_preap.h:114-120, more than 600 ms after the last pull)."""
from opendbc.car import structs
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (CANCEL, PULL, _act, _params_dir, _pedal_frame,  # noqa: F401
                                                                       _ready_rig, params)

ButtonType = structs.CarState.ButtonEvent.Type
TIP = 4          # SpdCtrlLvr_Stat accel tip (values.py BUTTONS)


def _step(rig, ctl, n, stalk, op):
  _pedal_frame(rig, n)
  out = rig.frame(stalk=stalk, op=op)
  rig.cs.out = out
  req = rig.cs.update_button_enable(out.buttonEvents)
  op = bool(op and out.cruiseState.enabled) or bool(req and out.cruiseState.available)
  cc = structs.CarControl.new_message(enabled=op, latActive=op, longActive=op and not out.bogpilot.preapLatOnly,
                                      actuators=_act(0.3)).as_reader()
  _, sends = ctl.update(cc, rig.cs, rig.nanos)
  stw = [s for s in sends if (s.address if hasattr(s, "address") else s[0]) == 0x45]
  return op, out, stw


def _engage_full(rig, ctl):
  op = False
  for n in range(150):
    op, out, _ = _step(rig, ctl, n, PULL if n in (20, 45) else 0, op)
  assert op and not out.bogpilot.preapLatOnly, "FULL before the tip"
  return op


def test_driver_cancel_100ms_after_a_tip_spoof_is_real():
  rig, ctl = _ready_rig(double=False)
  op = _engage_full(rig, ctl)
  # up tip, long after the last pull: StockCCSpoofer queues one CANCEL (long_controller pedal_button_press)
  op, out, stw = _step(rig, ctl, 150, TIP, op)
  stamp_before = int(rig.cs.preap_last_cc_spoof_ms or 0)
  tx_n = None
  for n in range(151, 200):
    op, out, stw = _step(rig, ctl, n, 0, op)
    if stw:
      tx_n = n
      break
    assert int(rig.cs.preap_last_cc_spoof_ms or 0) == stamp_before, "no stamp before our CANCEL is on the bus"
  assert tx_n is not None, "the tip must produce one CANCEL spoof"
  assert int(rig.cs.preap_last_cc_spoof_ms) == int(rig.cs.preap_cc_cancel_tx_ms) > stamp_before
  assert op and not out.bogpilot.preapLatOnly
  for n in range(tx_n + 1, tx_n + 10):
    op, out, _ = _step(rig, ctl, n, 0, op)
  # driver cancel 100 ms after our spoof frame: the panda drops controls (> 600 ms since the pull), so must openpilot
  op, out, _ = _step(rig, ctl, tx_n + 10, CANCEL, op)
  assert any(e.type == ButtonType.cancel and e.pressed for e in out.buttonEvents)
  assert not out.cruiseState.enabled and not op


def test_cancel_flag_without_a_sent_frame_does_not_open_the_window():
  rig, ctl = _ready_rig(double=False)
  op = _engage_full(rig, ctl)
  stamp = int(rig.cs.preap_last_cc_spoof_ms or 0)
  rig.cs.msg_stw_actn_req = None            # nothing to copy: StockCCSpoofer cannot send
  rig.cs.preap_cc_cancel_needed = True
  assert ctl.stock_cc.update(rig.cs, 1000, ctl.tesla_can, 0) == []
  assert ctl.stock_cc.update(rig.cs, 1010, ctl.tesla_can, 0) == []
  assert int(rig.cs.preap_last_cc_spoof_ms or 0) == stamp
