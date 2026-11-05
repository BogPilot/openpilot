"""Pre-AP stock-CC cancel (NAP StockCCSpoofer cancel path) + echo filter."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from openpilot.selfdrive.car.tesla.preap.cruise import (
  CANCEL_ECHO_WINDOW_MS,
  SPOOF_ECHO_WINDOW_MS,
  is_preap_cancel_echo,
)
from openpilot.selfdrive.car.tesla.preap.stock_cc_spoofer import (
  CANCEL_DELAY_FRAMES,
  StockCCSpoofer,
)
from openpilot.selfdrive.car.tesla.values import CANBUS

ROOT = Path(__file__).resolve().parents[4]


def make_cs(*, cancel_needed=False, msg_stw_present=True):
  msg = {
    "MC_STW_ACTN_RQ": 3,
    "SpdCtrlLvr_Stat": 0,
    "SpdCtrlLvrStat_Inv": 1,
    "VSL_Enbl_Rq": 1,
  } if msg_stw_present else None
  return SimpleNamespace(
    preap_cc_cancel_needed=cancel_needed,
    msg_stw_actn_req=msg,
  )


def make_can():
  m = MagicMock()
  m.create_action_request.return_value = ("STW_ACTN_RQ_FRAME",)
  return m


def tick_until(spoofer, cs, can, bus, start_frame, n_frames):
  history = []
  for i in range(n_frames):
    frame = start_frame + i
    sends = spoofer.update(cs, frame, can, bus)
    history.append((frame, sends))
  return history


class TestCancelPath:
  def test_cancel_pending_set_on_flag(self):
    s = StockCCSpoofer()
    cs = make_cs(cancel_needed=True)
    s.update(cs, frame=0, tesla_can=make_can(), bus=CANBUS.chassis)
    assert s.cancel_pending is True
    assert cs.preap_cc_cancel_needed is False

  def test_cancel_respects_delay_then_fires(self):
    s = StockCCSpoofer()
    can = make_can()
    cs = make_cs(cancel_needed=True)
    s.update(cs, frame=0, tesla_can=can, bus=CANBUS.chassis)
    cs.preap_cc_cancel_needed = False
    history = tick_until(s, cs, can, CANBUS.chassis, start_frame=1,
                         n_frames=CANCEL_DELAY_FRAMES - 1)
    assert sum(len(sends) for _, sends in history) == 0
    history = tick_until(s, cs, can, CANBUS.chassis,
                         start_frame=CANCEL_DELAY_FRAMES, n_frames=15)
    fired = [f for f, sends in history if sends]
    assert fired, "Cancel should fire at/after delay on a frame%10==0 slot"
    assert fired[0] >= CANCEL_DELAY_FRAMES
    # Our packer API: (msg_stw, cancel=True, bus, counter)
    can.create_action_request.assert_called_with(cs.msg_stw_actn_req, True, CANBUS.chassis, 4)
    assert s.cancel_pending is False

  def test_cancel_no_msg_stw_no_tx(self):
    s = StockCCSpoofer()
    cs = make_cs(cancel_needed=True, msg_stw_present=False)
    can = make_can()
    s.update(cs, frame=0, tesla_can=can, bus=CANBUS.chassis)
    cs.preap_cc_cancel_needed = False
    history = tick_until(s, cs, can, CANBUS.chassis, start_frame=11, n_frames=15)
    assert sum(len(s) for _, s in history) == 0

  def test_counter_increments_modulo_16(self):
    s = StockCCSpoofer()
    can = make_can()
    cs = make_cs(cancel_needed=True)
    cs.msg_stw_actn_req = {"MC_STW_ACTN_RQ": 15}
    s.update(cs, frame=0, tesla_can=can, bus=CANBUS.chassis)
    cs.preap_cc_cancel_needed = False
    tick_until(s, cs, can, CANBUS.chassis, start_frame=11, n_frames=15)
    last_call = can.create_action_request.call_args_list[-1]
    assert last_call.args[3] == 0  # (15+1) % 16

  def test_bus_is_chassis_zero(self):
    assert CANBUS.chassis == 0


class TestEchoFilter:
  def test_spoof_window_suppresses(self):
    assert is_preap_cancel_echo(
      now_ms=1000, last_stalk_non_cancel_ms=0, last_cc_spoof_ms=900,
      cruise_enabled=False) is True

  def test_spoof_window_expires(self):
    assert is_preap_cancel_echo(
      now_ms=1000 + SPOOF_ECHO_WINDOW_MS, last_stalk_non_cancel_ms=0,
      last_cc_spoof_ms=700, cruise_enabled=False) is False

  def test_stalk_window_needs_cruise_enabled(self):
    assert is_preap_cancel_echo(
      now_ms=500, last_stalk_non_cancel_ms=100, last_cc_spoof_ms=0,
      cruise_enabled=False) is False
    assert is_preap_cancel_echo(
      now_ms=500, last_stalk_non_cancel_ms=100, last_cc_spoof_ms=0,
      cruise_enabled=True) is True

  def test_stalk_window_expires(self):
    assert is_preap_cancel_echo(
      now_ms=100 + CANCEL_ECHO_WINDOW_MS, last_stalk_non_cancel_ms=100,
      last_cc_spoof_ms=0, cruise_enabled=True) is False


class TestSourceWiring:
  def test_carcontroller_wires_spoofer_and_triggers(self):
    src = (ROOT / "selfdrive/car/tesla/preap/carcontroller.py").read_text()
    assert "StockCCSpoofer" in src
    assert "preap_cc_cancel_needed" in src
    assert "CANBUS.chassis" in src
    assert "CANCEL_DELAY_FRAMES" not in src  # delay lives in spoofer
    assert "pedal_button_press" in src
    assert "preap_last_cc_spoof_ms" in src

  def test_carstate_echo_filter_wired(self):
    src = (ROOT / "selfdrive/car/tesla/carstate.py").read_text()
    assert "is_preap_cancel_echo" in src
    assert "preap_last_cc_spoof_ms" in src
    assert "last_stalk_non_cancel_ms" in src
    assert "ButtonEvent.Type.unknown" in src or "Type.unknown" in src

  def test_teslacan_packer_copies_inv_and_crc(self):
    src = (ROOT / "selfdrive/car/tesla/teslacan.py").read_text()
    assert "SpdCtrlLvrStat_Inv" in src
    assert "CRC_STW_ACTN_RQ" in src
    assert 'values["SpdCtrlLvr_Stat"] = 1' in src

  def test_panda_tx_whitelist_allows_stw_cancel_bus0(self):
    h = (ROOT / "panda/board/safety/safety_tesla_preap.h").read_text()
    assert "{0x45,  0, 8}" in h or "{0x45, 0, 8}" in h
    assert "PREAP_CANCEL_ECHO_WINDOW_US" in h
    assert "lever == 1" in h

  def test_cancel_delay_is_ten(self):
    assert CANCEL_DELAY_FRAMES == 10
