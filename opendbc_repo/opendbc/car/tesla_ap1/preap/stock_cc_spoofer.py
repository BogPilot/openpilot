"""Stock cruise cancel spoofer for Pre-AP + comma pedal.

Ports NAP (NotAutopilot nap-release e99f4dc75) StockCCSpoofer cancel path (opendbc/car/tesla/preap/stock_cc_spoofer.py:29-63): when pedal longitudinal engages or
disengages, or the stalk moves while pedal long is allowed, TX one
STW_ACTN_RQ CANCEL (SpdCtrlLvr_Stat=1) so stock DI cruise cannot run
alongside the pedal for long.

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


class StockCCSpoofer:
  """Cancel-only stalk-spoof state machine. One TX slot per frame % 10 == 0."""

  def __init__(self):
    self.cancel_pending = False
    self.cancel_frame = -1_000_000

  def drop_pending(self):
    """Forget a CANCEL that has not been sent yet (no pedal: the driver's second pull beat it, so stock cruise must stay on)."""
    self.cancel_pending = False

  def update(self, CS, frame, tesla_can, bus):
    can_sends = []

    if getattr(CS, "preap_cc_cancel_drop", False):
      self.drop_pending()
      CS.preap_cc_cancel_drop = False
    if getattr(CS, "preap_cc_cancel_needed", False):
      self.cancel_pending = True
      self.cancel_frame = frame
      CS.preap_cc_cancel_needed = False

    cancel_ready = (frame - self.cancel_frame) >= CANCEL_DELAY_FRAMES
    if self.cancel_pending and cancel_ready and frame % 10 == 0:
      sent = self._send_cancel(CS, tesla_can, bus)
      if sent is not None:
        can_sends.append(sent)
        self.cancel_pending = False
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
