"""Pre-AP 0x560 donor config: send in any gear until the radar gateway is open, then re-arm if it closes.

0x560 is host-to-panda only (bus 0). The panda tx hook consumes it and returns false, so it never goes on the car
(tesla_preap.h tesla_preap_tx_hook). No panda C change. Pack replay reads PREAP_TESTER2_PACK_DIR (debug-pack JSON);
those packs stay out of the tree. Synthetic VINs only.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from opendbc.car.tesla_ap1.preap.panda_link import GTW_ECHO_ADDRS, GTW_ECHO_SRC, LinkInput
from opendbc.car.tesla_ap1.preap.radar_donor import LOST_FRAMES, RADAR_VIN_ADDR, RADAR_VIN_BUS, Link, RadarDonorStream, create_radar_vin_msg
from opendbc.car.tesla_ap1.tests.test_preap_radar_advisory import test_gate_has_no_engage_api, test_warning_is_the_only_event_and_only_while_enabled
from opendbc.car.tesla_ap1.tests.test_preap_radar_donor import VIN, _fresh, _link, _run


# ---- stream / mutants ----

def test_drive_start_sends_three_records_on_bus_0_only():
  s = RadarDonorStream(True, VIN, 0)
  sent = _run(s, 30)
  assert [m.dat[0] for m in sent] == [0, 1, 2]
  assert all(m.address == RADAR_VIN_ADDR and m.src == RADAR_VIN_BUS == 0 for m in sent)


def test_never_sends_while_engaged_or_on_a_car_or_radar_bus():
  for kw in ({"enabled": True}, {"steering": True}, {"fsm": True}):
    assert _run(_fresh(), 100, **kw) == []
  assert _run(_fresh(), 100, link=lambda f: _link(sample=f % 10 == 0, ca=True)) == []
  msg = create_radar_vin_msg(0, "", True, 0, 0)
  assert msg.src == 0 and msg.address == 0x560 and msg.src != 1


def test_radar_off_or_ap1_never_sends():
  assert _run(RadarDonorStream(False, VIN, 1), 100) == []
  assert RadarDonorStream(False, VIN, 1).state == Link.OFF


def test_lost_echoes_restart_the_stream_not_one_shot():
  s = _fresh()
  _run(s, 20, link=lambda f: _link(sample=f % 10 == 0, echo=True))
  assert s.state == Link.OPEN
  out = _run(s, LOST_FRAMES + 40, start=20)
  assert s.state == Link.STREAM and len(out) >= 2 and s.rearms >= 2
  assert all(m.address == RADAR_VIN_ADDR and m.src == 0 for m in out)


def test_never_open_gateway_keeps_sending_and_does_not_gate_engage():
  s = _fresh()
  sent = _run(s, 100, link=lambda f: _link(sample=f % 10 == 0, echo=False))
  assert s.state == Link.STREAM and len(sent) == 10
  # Radar health stays advisory: the warning-only / no engage-gate contract (no no-entry, soft disable or disengage).
  test_gate_has_no_engage_api()
  test_warning_is_the_only_event_and_only_while_enabled()


# ---- panda safety model (unchanged C) ----

def test_drive_start_stream_opens_the_gateway_in_the_panda_safety_model():
  """Three 0x560 records from a Drive-start stream make the compiled tesla_preap gateway emit 0x2A9 / 0x2B9."""
  pytest.importorskip("cffi")
  from opendbc.safety.tests.libsafety import libsafety_py
  from opendbc.safety.tests.test_tesla_preap import PREAP, SAFETY_TESLA, pkt
  from opendbc.safety.tests.test_tesla_preap_radar import RADAR, sent

  s = RadarDonorStream(True, VIN, 0)
  records = _run(s, 30)
  assert [m.dat[0] for m in records] == [0, 1, 2]

  l = libsafety_py.libsafety
  assert l.set_safety_hooks(SAFETY_TESLA, PREAP | RADAR) == 0
  l.init_tests()
  l.set_timer(1_000_000)
  l.set_controls_allowed(False)
  l.safety_can_send_log_reset()

  allowed_after = []
  for m in records:
    ok = l.safety_tx_hook(pkt(m.address, bytearray(m.dat), m.src))
    assert ok is False                          # consumed, never placed on a car bus
    allowed_after.append(l.get_controls_allowed())
  assert allowed_after == [False, False, False]

  l.safety_can_send_log_reset()
  l.safety_rx_hook(pkt(0x398, bytes.fromhex("0281555300000000"), 0))
  gtw = [f for f in sent() if f[0] == 0x2A9]
  assert gtw, "gateway stayed closed after a complete 0x560 stream"
  assert gtw[0][1] == 1                         # radar bus only

  l.safety_can_send_log_reset()
  mux = bytes((0x11, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47))
  l.safety_rx_hook(pkt(0x405, mux, 0))
  vin_frames = [f for f in sent() if f[0] == 0x2B9]
  assert vin_frames and vin_frames[0][1] == 1 and len(vin_frames[0][3]) == 8

  # Sending 0x560 while engaged must not drop controls_allowed (apply is skipped; hook still returns false).
  l.set_controls_allowed(True)
  assert l.safety_tx_hook(pkt(0x560, bytearray(records[0].dat), 0)) is False
  assert l.get_controls_allowed() is True


def test_mid_drive_reinit_then_disengage_reopens_the_gateway():
  pytest.importorskip("cffi")
  from opendbc.safety.tests.libsafety import libsafety_py
  from opendbc.safety.tests.test_tesla_preap import PREAP, SAFETY_TESLA, pkt
  from opendbc.safety.tests.test_tesla_preap_radar import RADAR, send_donor_config, sent

  l = libsafety_py.libsafety
  assert l.set_safety_hooks(SAFETY_TESLA, PREAP | RADAR) == 0
  l.init_tests()
  l.set_timer(1_000_000)
  l.set_controls_allowed(False)
  send_donor_config("")
  l.safety_can_send_log_reset()
  l.safety_rx_hook(pkt(0x398, bytes.fromhex("0281555300000000"), 0))
  assert any(f[0] == 0x2A9 for f in sent())

  # Safety re-init (tesla_preap.h tesla_preap_init_config) clears the config and closes the gateway.
  assert l.set_safety_hooks(SAFETY_TESLA, PREAP | RADAR) == 0
  l.init_tests()
  l.set_controls_allowed(False)
  l.safety_can_send_log_reset()
  l.safety_rx_hook(pkt(0x398, bytes.fromhex("0281555300000000"), 0))
  assert all(f[0] != 0x2A9 for f in sent())

  s = RadarDonorStream(True, "", 0)
  # First sample already in the car's mode, as after a same-process re-init in Drive.
  records = _run(s, 30)
  assert [m.dat[0] for m in records] == [0, 1, 2]
  for m in records:
    assert l.safety_tx_hook(pkt(m.address, bytearray(m.dat), m.src)) is False
  l.safety_can_send_log_reset()
  l.safety_rx_hook(pkt(0x398, bytes.fromhex("0281555300000000"), 0))
  assert any(f[0] == 0x2A9 for f in sent())


# ---- Tester 2 Drive-only debug packs (optional; private, not in the tree) ----

def _pack_dir() -> Path | None:
  raw = os.environ.get("PREAP_TESTER2_PACK_DIR", "").strip()
  if not raw:
    return None
  p = Path(raw)
  return p if p.is_dir() else None


def _pack_files(folder: Path) -> list[Path]:
  files = sorted(folder.glob("*Pre-AP_commIssue_92aa9ee-debugpack.json"))
  return files


def _frames(ev):
  body = ev.get("frames")
  if body is None and isinstance(ev.get("kept"), dict):
    body = ev["kept"].get("frames") or ev["kept"].get("can") or ev["kept"].get("sendcan")
  return body or []


def _summarize_pack(path: Path) -> dict:
  data = json.loads(path.read_bytes())
  gears = Counter()
  n_560_send = n_560_can = n_gtw_echo = n_radar_bus1 = 0
  enabled = 0
  n_carstate = n_sendcan = n_can = 0
  safety_models = Counter()
  for ev in data.get("events", []):
    which = ev.get("which")
    if which == "carState":
      n_carstate += 1
      g = ev.get("gearShifter")
      if g is None and isinstance(ev.get("kept"), dict):
        g = ev["kept"].get("gearShifter")
      if g:
        gears[str(g)] += 1
    elif which == "selfdriveState":
      body = ev if "enabled" in ev else ev.get("kept")
      if isinstance(body, dict) and body.get("enabled"):
        enabled += 1
    elif which == "pandaStates":
      pandas = ev.get("pandas") or (ev.get("kept") or {}).get("pandas") or []
      for st in pandas:
        safety_models[str(st.get("safetyModel"))] += 1
    elif which == "sendcan":
      n_sendcan += 1
      for fr in _frames(ev):
        if int(fr.get("addr") or fr.get("address") or 0) == 0x560:
          n_560_send += 1
    elif which == "can":
      n_can += 1
      for fr in _frames(ev):
        addr = int(fr.get("addr") or fr.get("address") or 0)
        src = int(fr.get("src") or 0)
        bus = int(fr.get("bus") or src if not fr.get("txEcho") else -1)
        if addr == 0x560:
          n_560_can += 1
        if src == GTW_ECHO_SRC and addr in GTW_ECHO_ADDRS:
          n_gtw_echo += 1
        if (src == 1 or bus == 1) and addr in GTW_ECHO_ADDRS:
          n_radar_bus1 += 1
  return {
    "gears": dict(gears),
    "n_carstate": n_carstate,
    "n_sendcan": n_sendcan,
    "n_can": n_can,
    "n_560_send": n_560_send,
    "n_560_can": n_560_can,
    "n_gtw_echo": n_gtw_echo,
    "n_radar_bus1": n_radar_bus1,
    "enabled": enabled,
    "safety_models": dict(safety_models),
  }


@pytest.mark.skipif(_pack_dir() is None, reason="PREAP_TESTER2_PACK_DIR is not set")
def test_tester2_drive_packs_open_the_gateway_in_the_safety_model():
  folder = _pack_dir()
  files = _pack_files(folder)
  assert len(files) == 2, "expected both Drive-only debug packs"
  pytest.importorskip("cffi")
  from opendbc.safety.tests.libsafety import libsafety_py
  from opendbc.safety.tests.test_tesla_preap import PREAP, SAFETY_TESLA, pkt
  from opendbc.safety.tests.test_tesla_preap_radar import RADAR, sent

  l = libsafety_py.libsafety
  summaries = []
  for path in files:
    info = _summarize_pack(path)
    summaries.append(info)
    # Packs are Drive-only starts: no 0x560 went out, no src-129 gateway echoes.
    assert info["n_carstate"] > 0
    assert info["gears"].get("drive", 0) == info["n_carstate"] or (
      info["gears"].get("drive", 0) > 0 and info["gears"].get("park", 0) == 0
    )
    assert info["n_560_send"] == 0
    assert info["n_gtw_echo"] == 0

    s = RadarDonorStream(True, "", 0)
    records = _run(s, 30)   # first sample already in the car's mode, as in these packs
    assert [m.dat[0] for m in records] == [0, 1, 2]
    assert all(m.src == 0 for m in records)

    assert l.set_safety_hooks(SAFETY_TESLA, PREAP | RADAR) == 0
    l.init_tests()
    l.set_timer(1_000_000)
    l.set_controls_allowed(False)
    l.safety_can_send_log_reset()
    for m in records:
      assert l.safety_tx_hook(pkt(m.address, bytearray(m.dat), m.src)) is False
    l.safety_can_send_log_reset()
    l.safety_rx_hook(pkt(0x398, bytes.fromhex("0281555300000000"), 0))
    assert any(f[0] == 0x2A9 and f[1] == 1 for f in sent())
    l.safety_can_send_log_reset()
    mux = bytes((0x11, 1, 2, 3, 4, 5, 6, 7))
    l.safety_rx_hook(pkt(0x405, mux, 0))
    assert any(f[0] == 0x2B9 and f[1] == 1 for f in sent())
  # Keep only counts in the default pytest output if a failure message interpolates info.
  assert all(s["n_560_send"] == 0 and s["n_gtw_echo"] == 0 for s in summaries)
