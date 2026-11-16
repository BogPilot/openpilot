"""Pre-AP radar donor VIN, host side: the 0x560 stream, the manual Read Radar VIN runner and the ported F190 reader.

VINs here are synthetic: each contains I, O and Q, which no real VIN may contain.
Reader tests ported from NAP opendbc/car/tesla/preap/tests/test_radar_donor_vin.py:18-121 @ opendbc 5dbe36d37
(openpilot naponsp-alpha-prebuilt 7eb09d2a7); its Commissioner (automatic start) tests are not ported with it.
"""
import io
import logging
import pathlib
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.can_definitions import CanData
from opendbc.car.carlog import carlog
from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys
from opendbc.car.tesla_ap1.preap.radar_donor import RadarDonorStream, create_radar_vin_msg, normalize_radar_donor_vin
from opendbc.car.tesla_ap1.preap.radar_donor_vin import (
  FLOW_CONTROL,
  RADAR_UDS_BUS,
  RADAR_UDS_RX,
  RADAR_UDS_TX,
  RadarDonorVinFailure,
  RadarDonorVinReader,
  RadarDonorVinState,
  radar_alert_vin_validity,
)
from opendbc.car.tesla_ap1.preap.radar_vin_read import STATUS_ENGAGED, STATUS_RADAR_OFF, STATUS_SAVED, RadarVinReadRunner

VIN = "TESTQQQ4OIQ000001"
GEAR = structs.CarState.GearShifter
PREAP_DIR = pathlib.Path(params.__file__).parent


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  yield tmp_path


# ---- 0x560 stream ----

def test_normalize_radar_donor_vin():
  assert normalize_radar_donor_vin("testqqq4oiq000001") == VIN
  assert normalize_radar_donor_vin("TEST-QQQ4OIQ 000001") == VIN
  assert normalize_radar_donor_vin(VIN.encode()) == VIN
  assert normalize_radar_donor_vin("TESTQQQ4OIQ00000") == ""
  assert normalize_radar_donor_vin(None) == ""
  assert normalize_radar_donor_vin("TÉSTQQQ4OIQ000001") == ""


def test_create_radar_vin_msg_layout():
  r0, r1, r2 = (create_radar_vin_msg(i, VIN, True, 1, 3) for i in range(3))
  assert all((m.address, m.src, len(m.dat)) == (0x560, 0, 8) for m in (r0, r1, r2))
  assert r0.dat == bytes((0, 1, 1 | (1 << 1) | (3 << 3), 0, 0)) + VIN[0:3].encode()
  assert r1.dat == b"\x01" + VIN[3:10].encode()
  assert r2.dat == b"\x02" + VIN[10:17].encode()
  assert create_radar_vin_msg(1, "", True, 0, 0).dat == b"\x01" + b" " * 7
  with pytest.raises(ValueError):
    create_radar_vin_msg(3, VIN, True, 0, 0)


def _run(stream, frames, enabled=False, gear=GEAR.park):
  out = []
  for f in range(frames):
    out += stream.update(f, enabled, gear)
  return out


def test_stream_only_with_flag_256_disengaged_not_in_drive():
  assert _run(RadarDonorStream(False, VIN, 1), 100) == []
  s = RadarDonorStream(True, "", 0)
  sent = _run(s, 60)
  assert [m.dat[0] for m in sent] == [0, 1, 2, 0, 1, 2]        # 10 Hz at 100 Hz, records cycle
  assert _run(RadarDonorStream(True, "", 0), 100, enabled=True) == []
  assert _run(RadarDonorStream(True, "", 0), 100, gear=GEAR.drive) == []
  assert len(_run(RadarDonorStream(True, "", 0), 30, gear=GEAR.reverse)) == 3


def test_stream_position_is_donor_type_and_blank_vin_is_spaces():
  for want in (0, 1, 2):
    s = RadarDonorStream(True, "", want)
    r0, r1, r2 = _run(s, 30)
    assert (r0.dat[2] >> 1) & 3 == want and (r0.dat[2] >> 3) & 7 == 0 and r0.dat[2] & 1 == 1
    assert r0.dat[5:] == b"   " and r1.dat[1:] == b" " * 7 and r2.dat[1:] == b" " * 7
    assert not s.donor_active
  for bad in (3, -1, 7, None, True):
    assert RadarDonorStream(True, "", bad).position == 0, bad


@pytest.mark.parametrize("text, want", (("0", 0), ("1", 1), ("2", 2), ("3", 0), ("-1", 0), ("x", 0), ("1.5", 0), ("inf", 0), ("nan", 0), ("", 0),
                                        (None, 0)))
def test_radar_donor_type_param(tmp_path, text, want):
  if text is not None:
    (tmp_path / PreApParamKeys.RADAR_DONOR_TYPE).write_text(text)
  assert params.radar_donor_type() == want
  assert params.DEFAULTS[PreApParamKeys.RADAR_DONOR_TYPE] == 0


def test_carcontroller_streams_from_safety_param(tmp_path):
  from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
  from opendbc.car.tesla_ap1.values import CAR, DBC
  (tmp_path / PreApParamKeys.RADAR_DONOR_VIN).write_text(VIN)

  def make(param):
    CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True,
                         safetyConfigs=[SimpleNamespace(safetyParam=param)])
    return PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], CP)

  # No donor type set: position 0 (NAP default) even with the nosecone flag 128 (480 used to send 1).
  for param, want_on in ((480, True), (32 | 64 | 256, True), (32 | 64 | 128, False), (32 | 64, False)):
    ctl = make(param)
    assert ctl.radar_donor.radar_emulation is want_on, param
    assert ctl.radar_donor.position == 0, param
    assert ctl.radar_donor.donor_active is want_on, param
  # The donor type picks the position, with or without flag 128; radar off always sends nothing (position 0).
  for text, want in (("1", 1), ("2", 2), ("0", 0), ("5", 0)):
    (tmp_path / PreApParamKeys.RADAR_DONOR_TYPE).write_text(text)
    for param in (480, 32 | 64 | 256):
      ctl = make(param)
      assert ctl.radar_donor.position == want, (text, param)
      r0 = _run(ctl.radar_donor, 30)[0]
      assert (r0.dat[2] >> 1) & 3 == want, (text, param)
    assert make(32 | 64 | 128).radar_donor.position == 0, text


# ---- Read Radar VIN runner (button path only) ----

def _rx(payload: bytes) -> CanData:
  return CanData(RADAR_UDS_RX, (bytes([len(payload)]) + payload).ljust(8, b"\x00"), RADAR_UDS_BUS)


def _first_frame(payload: bytes) -> CanData:
  return CanData(RADAR_UDS_RX, (bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[:6]).ljust(8, b"\x00"), RADAR_UDS_BUS)


def _consecutive(seq: int, data: bytes) -> CanData:
  return CanData(RADAR_UDS_RX, bytes([0x20 | seq]) + data.ljust(7, b"\x00"), RADAR_UDS_BUS)


REPLIES = {b"\x3e\x00": b"\x7e\x00", b"\x10\x01": b"\x50\x01", b"\x10\x03": b"\x50\x03"}


def _fake_radar(sent):
  """Answer the last request like a radar would; F190 gets the synthetic VIN as a multi-frame reply."""
  out = []
  for m in sent:
    assert (m.address, m.src) == (RADAR_UDS_TX, RADAR_UDS_BUS)
    n = m.dat[0]
    if n > 7:
      continue
    req = m.dat[1:1 + n]
    if req in REPLIES:
      out.append(_rx(REPLIES[req]))
    elif req == b"\x22\xf1\x90":
      payload = b"\x62\xf1\x90" + VIN.encode()
      out.append({"first_frame": payload})
  return out


def _drive_runner(runner, engaged_at=None, steps=400):
  now, pending, all_sent = 0.0, [], []
  for i in range(steps):
    rx = []
    for p in pending:
      if isinstance(p, dict):                       # CanData is a NamedTuple, so mark the F190 reply with a dict
        rx.append(_first_frame(p["first_frame"]))
        rest = p["first_frame"][6:]
        pending_cf = [_consecutive(1, rest[:7]), _consecutive(2, rest[7:])]
      else:
        rx.append(p)
    sent = runner.update(rx, now, engaged=(engaged_at is not None and i >= engaged_at))
    if any(s.dat == FLOW_CONTROL for s in sent):
      sent = [s for s in sent if s.dat != FLOW_CONTROL]
      pending = pending_cf
    else:
      pending = _fake_radar(sent)
    all_sent += sent
    now += 0.01
    if not params.get_bool(PreApParamKeys.RADAR_READ_VIN) and runner.reader is None:
      break
  return all_sent


def test_runner_never_starts_without_the_button():
  runner = RadarVinReadRunner(True)
  fault = CanData(0x501, bytes([0, 0, 0, 0, 0x10, 0, 0, 0]), RADAR_UDS_BUS)   # NAP's auto-start trigger: ignored
  for i in range(500):
    assert runner.update([fault], i * 0.01, engaged=False) == []
  assert runner.reader is None
  assert params.get_str(PreApParamKeys.RADAR_DONOR_VIN) == ""


def test_button_read_stores_vin_only_in_donor_param(tmp_path):
  params.set_bool(PreApParamKeys.RADAR_READ_VIN, True)
  runner = RadarVinReadRunner(True)
  sent = _drive_runner(runner)
  assert sent and all((s.address, s.src) == (RADAR_UDS_TX, RADAR_UDS_BUS) for s in sent)
  assert params.get_str(PreApParamKeys.RADAR_DONOR_VIN) == VIN
  assert params.get_str(PreApParamKeys.RADAR_VIN_READ_STATUS) == STATUS_SAVED
  assert not params.get_bool(PreApParamKeys.RADAR_READ_VIN)
  holders = [p.name for p in tmp_path.iterdir() if VIN in p.read_text(errors="ignore")]
  assert holders == [PreApParamKeys.RADAR_DONOR_VIN]


def test_button_refused_while_engaged():
  params.set_bool(PreApParamKeys.RADAR_READ_VIN, True)
  runner = RadarVinReadRunner(True)
  assert runner.update([], 0.0, engaged=True) == []
  assert runner.reader is None
  assert params.get_str(PreApParamKeys.RADAR_VIN_READ_STATUS) == STATUS_ENGAGED
  assert not params.get_bool(PreApParamKeys.RADAR_READ_VIN)


def test_engaging_mid_read_stops_at_once():
  params.set_bool(PreApParamKeys.RADAR_READ_VIN, True)
  runner = RadarVinReadRunner(True)
  sent_before = runner.update([], 0.0, engaged=False)
  assert sent_before
  assert runner.update([_rx(b"\x7e\x00")], 0.01, engaged=True) == []
  assert runner.reader is None
  assert runner.update([], 0.02, engaged=False) == []
  assert params.get_str(PreApParamKeys.RADAR_DONOR_VIN) == ""


def test_button_refused_without_radar_flag():
  params.set_bool(PreApParamKeys.RADAR_READ_VIN, True)
  runner = RadarVinReadRunner(False)
  assert runner.update([], 0.0, engaged=False) == []
  assert params.get_str(PreApParamKeys.RADAR_VIN_READ_STATUS) == STATUS_RADAR_OFF


def test_vin_never_in_logs_or_status():
  stream = io.StringIO()
  handler = logging.StreamHandler(stream)
  root = logging.getLogger()
  carlog.addHandler(handler)
  root.addHandler(handler)
  old_level = root.level
  root.setLevel(logging.DEBUG)
  out = io.StringIO()
  try:
    with redirect_stdout(out):
      params.set_bool(PreApParamKeys.RADAR_READ_VIN, True)
      _drive_runner(RadarVinReadRunner(True))
      RadarDonorStream(True, VIN, 1)
  finally:
    carlog.removeHandler(handler)
    root.removeHandler(handler)
    root.setLevel(old_level)
  assert params.get_str(PreApParamKeys.RADAR_DONOR_VIN) == VIN
  assert VIN not in stream.getvalue() and VIN not in out.getvalue()
  assert VIN not in params.get_str(PreApParamKeys.RADAR_VIN_READ_STATUS)


def test_no_vin_logging_calls_in_sources():
  for name in ("radar_donor.py", "radar_donor_vin.py", "radar_vin_read.py"):
    text = (PREAP_DIR / name).read_text()
    for bad in ("carlog", "cloudlog", "print(", "logging."):
      assert bad not in text.split('"""', 2)[-1], (name, bad)


# ---- ported NAP reader tests (synthetic VIN) ----

def _drive_to_read(reader: RadarDonorVinReader, now: float) -> float:
  replies = {
    RadarDonorVinState.TESTER_PRESENT: b"\x7e\x00",
    RadarDonorVinState.DEFAULT_SESSION: b"\x50\x01",
    RadarDonorVinState.EXTENDED_SESSION: b"\x50\x03",
    RadarDonorVinState.READINESS: b"\x7e\x00",
  }
  while reader.state in replies:
    assert reader.update([], now).can_sends
    now += 0.01
    assert reader.update([_rx(replies[reader.state])], now).failure is None
    now += 0.01
  assert reader.state == RadarDonorVinState.READ_F190
  return now


def test_radar_alert_vin_validity_bit():
  assert radar_alert_vin_validity(bytes(8)) is False
  assert radar_alert_vin_validity(bytes([0, 0, 0, 0, 0x10, 0, 0, 0])) is True
  assert radar_alert_vin_validity(b"\x00") is False


def test_reader_completes_on_multiframe_f190():
  reader = RadarDonorVinReader()
  reader.start(0.0)
  now = _drive_to_read(reader, 0.0)
  out = reader.update([], now)
  assert out.can_sends[0].address == RADAR_UDS_TX and out.can_sends[0].dat[:4] == b"\x03\x22\xf1\x90"
  payload = b"\x62\xf1\x90" + VIN.encode()
  now += 0.01
  assert reader.update([_first_frame(payload)], now).can_sends == (CanData(RADAR_UDS_TX, FLOW_CONTROL, RADAR_UDS_BUS),)
  now += 0.01
  rest = payload[6:]
  out = reader.update([_consecutive(1, rest[:7]), _consecutive(2, rest[7:])], now)
  assert out.vin == VIN and out.state == RadarDonorVinState.CLEANUP
  now += 0.01
  out = reader.update([], now)
  assert out.can_sends[0].dat[:3] == b"\x02\x3e\x80" and out.can_sends[1].dat[:3] == b"\x02\x10\x01"
  for _ in range(2):
    now += 0.01
    out = reader.update([_rx(b"\x50\x01")], now)
    now += 0.01
    if out.state != RadarDonorVinState.COMPLETE:
      out = reader.update([], now)
  assert out.state == RadarDonorVinState.COMPLETE and out.vin == VIN and out.failure is None


def test_reader_rejects_short_vin_and_cleans_up():
  reader = RadarDonorVinReader()
  reader.start(0.0)
  now = _drive_to_read(reader, 0.0)
  reader.update([], now)
  out = reader.update([_rx(b"\x62\xf1\x90ABC")], now + 0.01)
  assert out.failure == RadarDonorVinFailure.INVALID_VIN and out.state == RadarDonorVinState.CLEANUP and out.vin is None


def test_reader_times_out_waiting_for_f190():
  reader = RadarDonorVinReader()
  reader.start(0.0)
  now = _drive_to_read(reader, 0.0)
  reader.update([], now)
  out = reader.update([], now + RadarDonorVinReader.RESPONSE_TIMEOUT)
  assert out.failure == RadarDonorVinFailure.TIMEOUT and out.state == RadarDonorVinState.CLEANUP


def test_reader_does_not_start_from_idle():
  out = RadarDonorVinReader().update([], 1.0)
  assert out.state == RadarDonorVinState.IDLE and out.can_sends == ()


def test_reader_only_sends_allow_listed_frames():
  allowed = {bytes(x) for x in (
    [0x02, 0x3E, 0, 0, 0, 0, 0, 0], [0x02, 0x10, 0x01, 0, 0, 0, 0, 0], [0x02, 0x10, 0x03, 0, 0, 0, 0, 0],
    [0x03, 0x22, 0xF1, 0x90, 0, 0, 0, 0], [0x30, 0, 0, 0, 0, 0, 0, 0], [0x02, 0x3E, 0x80, 0, 0, 0, 0, 0])}
  params.set_bool(PreApParamKeys.RADAR_READ_VIN, True)
  sent = _drive_runner(RadarVinReadRunner(True))
  assert sent and {s.dat for s in sent} <= allowed
