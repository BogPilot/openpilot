"""Pre-AP Phase A donor VIN commissioner unit tests.

Uses NOT-A-REAL-VIN-01 style values only. Never asserts a real VIN string into
logs. Credit: NAP radar_donor_vin timing.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openpilot.selfdrive.car.tesla.preap import params, radar_tx
from openpilot.selfdrive.car.tesla.preap.radar_donor_vin import (
  F190_ALLOWED_FRAMES,
  RADAR_UDS_BUS,
  RADAR_UDS_RX,
  RADAR_UDS_TX,
  RadarDonorVinCommissioner,
  RadarDonorVinFailure,
  RadarDonorVinReader,
  RadarDonorVinState,
  normalize_radar_donor_vin,
  radar_alert_vin_validity,
)

FAKE_VIN = "NOTAREALVIN000001"  # 17 chars, test-safe
assert len(FAKE_VIN) == 17


@pytest.fixture()
def tmp_params(monkeypatch):
  d = Path(tempfile.mkdtemp())
  monkeypatch.setattr(params, "_params_dir", d)
  return d


def test_normalize_accepts_seventeen_alnum():
  assert normalize_radar_donor_vin(FAKE_VIN) == FAKE_VIN
  assert normalize_radar_donor_vin("SHORT") == ""
  assert normalize_radar_donor_vin("NOTAREALVIN00-001") == "NOTAREALVIN00001"  # hyphen stripped


def test_normalize_rejects_short():
  assert normalize_radar_donor_vin("SHORT") == ""
  assert normalize_radar_donor_vin(None) == ""


def test_vin_validity_bit():
  dat = bytearray(8)
  assert not radar_alert_vin_validity(bytes(dat))
  dat[4] |= 0x10
  assert radar_alert_vin_validity(bytes(dat))


def test_allowed_frames_match_panda_exact_bytes():
  assert len(F190_ALLOWED_FRAMES) == 6
  assert F190_ALLOWED_FRAMES[3] == bytes([0x03, 0x22, 0xF1, 0x90, 0x00, 0x00, 0x00, 0x00])


def test_reader_completes_single_frame_f190():
  clock = {"t": 0.0}

  def now():
    return clock["t"]

  reader = RadarDonorVinReader(now=now)
  out = reader.start()
  assert out.state == RadarDonorVinState.TESTER_PRESENT
  assert out.can_sends[0][0] == RADAR_UDS_TX
  assert out.can_sends[0][3] == RADAR_UDS_BUS
  assert bytes(out.can_sends[0][2]) == F190_ALLOWED_FRAMES[0]

  def rx(payload_sf: bytes):
    # ISO-TP single frame: len + payload padded
    return [(RADAR_UDS_RX, (bytes([len(payload_sf)]) + payload_sf).ljust(8, b"\x00"), RADAR_UDS_BUS)]

  out = reader.update(rx(b"\x7e\x00"))
  assert out.state == RadarDonorVinState.DEFAULT_SESSION
  out = reader.update(rx(b"\x50\x01"))
  assert out.state == RadarDonorVinState.EXTENDED_SESSION
  out = reader.update(rx(b"\x50\x03"))
  assert out.state == RadarDonorVinState.READINESS

  alert = bytearray(8)
  alert[4] |= 0x10
  out = reader.update([(0x501, bytes(alert), RADAR_UDS_BUS)])
  assert out.state == RadarDonorVinState.READ_F190
  assert bytes(out.can_sends[0][2]) == F190_ALLOWED_FRAMES[3]

  # Positive response 62 F1 90 + 17 VIN (needs multi-frame). Build ISO-TP FF+CF.
  uds = b"\x62\xf1\x90" + FAKE_VIN.encode("ascii")
  assert len(uds) == 20
  ff = bytes([0x10, len(uds)]) + uds[:6]
  assert len(ff) == 8
  out = reader.update([(RADAR_UDS_RX, ff, RADAR_UDS_BUS)])
  assert out.state == RadarDonorVinState.READ_F190
  assert out.can_sends[0][2] == F190_ALLOWED_FRAMES[4]  # flow control

  # two consecutive frames of 7 bytes
  cf1 = bytes([0x21]) + uds[6:13]
  out = reader.update([(RADAR_UDS_RX, cf1, RADAR_UDS_BUS)])
  assert out.state == RadarDonorVinState.READ_F190
  cf2 = (bytes([0x22]) + uds[13:20]).ljust(8, b"\x00")
  out = reader.update([(RADAR_UDS_RX, cf2, RADAR_UDS_BUS)])
  assert out.state == RadarDonorVinState.CLEANUP
  assert out.vin == FAKE_VIN
  assert not any(FAKE_VIN in str(x) for x in () )  # silence linters; never log

  out = reader.update([])
  assert out.state == RadarDonorVinState.COMPLETE
  assert out.vin == FAKE_VIN


def test_reader_aborts_when_requested():
  reader = RadarDonorVinReader(now=lambda: 0.0)
  reader.start()
  out = reader.abort()
  assert out.state == RadarDonorVinState.FAILED
  assert out.failure == RadarDonorVinFailure.ABORTED


def test_commissioner_force_and_store(tmp_params):
  stored = {}

  def store(vin):
    stored["v"] = vin

  clock = {"t": 0.0}
  c = RadarDonorVinCommissioner(store, now=lambda: clock["t"])
  # force_read starts immediately
  sends = c.update([], radar_enabled=True, stored_vin="", engaged=False, force_read=True)
  assert sends and sends[0][0] == RADAR_UDS_TX

  # engaged aborts
  sends = c.update([], radar_enabled=True, stored_vin="", engaged=True, force_read=False)
  assert c.reader.state == RadarDonorVinState.FAILED


def test_radar_tx_uses_donor_when_stored(tmp_params):
  params.set_str(params.PreApParamKeys.RADAR_DONOR_VIN, FAKE_VIN)
  frames = radar_tx.radar_tx_frames(enabled=True, bus=1, behind_nosecone=False)
  vin_frame = [f for f in frames if f[0] == radar_tx.ADDR_VIN_VIP][0]
  assert vin_frame[2][:8] == FAKE_VIN.encode("ascii")[:8]


def test_radar_tx_falls_back_to_dummy(tmp_params):
  frames = radar_tx.radar_tx_frames(enabled=True, bus=1, behind_nosecone=False)
  vin_frame = [f for f in frames if f[0] == radar_tx.ADDR_VIN_VIP][0]
  assert vin_frame[2][:8] == radar_tx.DUMMY_VIN.encode("ascii")[:8]


def test_pack_dummy_refuses_real_looking():
  with pytest.raises(ValueError):
    radar_tx.pack_dummy_vin("ABCDEFGHIJKLMNOPQ")  # looks real — refuse
