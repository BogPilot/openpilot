"""Stock cruise cancel spoofer for Pre-AP + comma pedal.

Ports NAP (NotAutopilot nap-release e99f4dc75) StockCCSpoofer cancel path (opendbc/car/tesla/preap/stock_cc_spoofer.py:29-63): when pedal longitudinal engages or
disengages, or the stalk moves while pedal long is allowed, TX one
STW_ACTN_RQ CANCEL (SpdCtrlLvr_Stat=1) so stock DI cruise cannot run
alongside the pedal for long.

Pedal path only: the CANCEL goes out only while stock DI cruise is really engaged (CS.preap_di_cc_engaged, from
DI_state.DI_cruiseState). A pedal trigger waits up to DI_WAIT_FRAMES for stock cruise to engage and is dropped if it
never does. A CANCEL to a DI whose cruise is off does nothing, and every extra STW_ACTN_RQ frame on the bus is one more
frame the steering column module did not send (with the wipers in Auto it can give a single wipe). The no-pedal FSM
(preap/engagement.py) is unchanged: it decides itself when stock cruise needs a CANCEL.

Counter: the frame copies the newest live STW_ACTN_RQ and uses its counter + 1, as NAP, Tinkla and upstream Tesla do. The
steering column module keeps counting on its own, so its next frame repeats that counter. With no relay on Pre-AP the
real frame cannot be held back, so a repeat is unavoidable for any counter choice; the fix is to send fewer frames.

Uses BogPilot TeslaCAN.create_action_request (live-frame copy including
SpdCtrlLvrStat_Inv / VSL_Enbl_Rq, counter, CRC-8). Bus must be
CANBUS.chassis (0) — SAFETY_TESLA_PREAP TX-whitelists 0x45 only on bus 0.

Credit: NotAutopilot (NAP) nap-release e99f4dc75, via BogPilot 0.9.7 na-preap 568fea947. Product name: BogPilot.
"""
from __future__ import annotations

import time

# Delay between cancel-pending and CANCEL on the bus. Lets pedal mode
# establish control before the DI drops stock CC.
CANCEL_DELAY_FRAMES = 10  # 100 ms at 100 Hz

# Pedal path: how long a pending CANCEL waits for stock DI cruise to engage before it is dropped.
DI_WAIT_FRAMES = 100  # 1 s at 100 Hz


class StockCCSpoofer:
  """Cancel-only stalk-spoof state machine. One TX slot per frame % 10 == 0."""

  def __init__(self):
    self.cancel_pending = False
    self.cancel_frame = -1_000_000
    self.wait_di = False      # pedal path: send only while stock cruise is engaged
    self.dropped_di_off = 0   # pedal CANCELs dropped because stock cruise never engaged

  def drop_pending(self):
    """Forget a CANCEL that has not been sent yet (no pedal: the driver's second pull beat it, so stock cruise must stay on)."""
    self.cancel_pending = False
    self.wait_di = False

  def update(self, CS, frame, tesla_can, bus):
    can_sends = []

    if getattr(CS, "preap_cc_cancel_drop", False):
      self.drop_pending()
      CS.preap_cc_cancel_drop = False
    if getattr(CS, "preap_cc_cancel_needed", False):
      wait_di = bool(getattr(CS, "preap_cc_cancel_wait_di", False))
      # A request without the DI gate (no-pedal FSM) is never weakened by a later gated one.
      self.wait_di = wait_di if not self.cancel_pending else (self.wait_di and wait_di)
      self.cancel_pending = True
      self.cancel_frame = frame
      CS.preap_cc_cancel_needed = False
    CS.preap_cc_cancel_wait_di = False

    di_engaged = bool(getattr(CS, "preap_di_cc_engaged", False))
    if self.cancel_pending and self.wait_di and not di_engaged and (frame - self.cancel_frame) >= DI_WAIT_FRAMES:
      # Stock cruise never engaged: nothing to cancel, so nothing goes on the bus.
      self.drop_pending()
      self.dropped_di_off += 1

    cancel_ready = (frame - self.cancel_frame) >= CANCEL_DELAY_FRAMES and (di_engaged or not self.wait_di)
    if self.cancel_pending and cancel_ready and frame % 10 == 0:
      sent = self._send_cancel(CS, tesla_can, bus)
      if sent is not None:
        can_sends.append(sent)
        self.cancel_pending = False
        self.wait_di = False
        # When the CANCEL really went out: the no-pedal FSM uses it to tell our cancel from the DI state it left behind.
        CS.preap_cc_cancel_tx_ms = int(time.monotonic() * 1000)
        # The spoof-echo window (preap/cruise.py) opens only on our own frame, never on a tip or a pending flag.
        CS.preap_last_cc_spoof_ms = CS.preap_cc_cancel_tx_ms

    return can_sends

  def _send_cancel(self, CS, tesla_can, bus):
    msg_stw = getattr(CS, "msg_stw_actn_req", None)
    if msg_stw is None:
      return None
    counter = (int(msg_stw.get("MC_STW_ACTN_RQ", 0)) + 1) % 16
    # cancel=True → SpdCtrlLvr_Stat=1; packer copies SpdCtrlLvrStat_Inv + CRC
    return tesla_can.create_action_request(msg_stw, True, bus, counter)
