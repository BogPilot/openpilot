"""DI_cruiseSet x2 scale correction (cruise_set.py: default ON x2; originally developed on the 0.9.7 line, archived and removed)."""
from types import SimpleNamespace

import pytest

from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1 import cruise_set
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.values import CAR

PACKER = CANPacker("tesla_ap1_can")


@pytest.mark.parametrize("text,expected", [
  ("", True),  # empty = default ON
  ("0", False), ("off", False), ("false", False), ("no", False), ("junk", False),
  ("1", True), ("on", True), ("true", True), ("yes", True), (b"1\n", True),
])
def test_enabled_parsing(text, expected):
  assert cruise_set.cruise_set_scale_fix_enabled(text) is expected


def test_missing_file_is_on(tmp_path, monkeypatch):
  monkeypatch.setattr(cruise_set, "_cruise_set_scale_fix_path", tmp_path / "nope")
  assert cruise_set.cruise_set_scale_fix_enabled() is True
  assert cruise_set.cruise_set_scale(False) == 1.0
  assert cruise_set.cruise_set_scale(True) == 2.0


def _speed(monkeypatch, tmp_path, file_text, op_long, cruise_state, raw, v_kph=64.0, steps=1, fingerprint=CAR.TESLA_AP1_MODELS):
  path = tmp_path / "TeslaCruiseSetScaleFix"
  if file_text is not None:
    path.write_text(file_text)
  monkeypatch.setattr(cruise_set, "_cruise_set_scale_fix_path", path)
  cp = SimpleNamespace(carFingerprint=fingerprint, openpilotLongitudinalControl=op_long)
  cs, parsers = CarState(cp), CarState.get_can_parsers(cp)
  bus, t, out = parsers[Bus.chassis].bus, 0, []
  for i in range(steps):
    t += 10_000_000
    msgs = []
    for name, vals in (("DI_state", {"DI_cruiseState": cruise_state, "DI_cruiseSet": raw * 0.5, "DI_speedUnits": 0,
                                      "DI_stateCounter": (i + 1) % 16}), ("ESP_B", {"ESP_vehicleSpeed": v_kph})):
      a, d, _ = PACKER.make_can_msg(name, bus, vals)
      msgs.append((a, d, bus))
    parsers[Bus.chassis].update([(t, msgs)])
    out.append(cs.update(parsers).cruiseState.speed)
  return out[-1]


@pytest.mark.parametrize("fingerprint", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
def test_stock_ap_is_x2_by_default_and_off_keeps_dbc(monkeypatch, tmp_path, fingerprint):
  """Openpilot long off (stock AP): raw 40 (decoded 20 mph) reads 40 mph by default; an explicit off keeps 20."""
  assert _speed(monkeypatch, tmp_path, None, False, 2, 40, fingerprint=fingerprint) == pytest.approx(40 * CV.MPH_TO_MS)
  assert _speed(monkeypatch, tmp_path, "0", False, 2, 40, fingerprint=fingerprint) == pytest.approx(20 * CV.MPH_TO_MS)


def test_read_once_in_init(monkeypatch, tmp_path):
  path = tmp_path / "TeslaCruiseSetScaleFix"
  path.write_text("0")
  monkeypatch.setattr(cruise_set, "_cruise_set_scale_fix_path", path)
  cs = CarState(SimpleNamespace(carFingerprint=CAR.TESLA_AP1_MODELS, openpilotLongitudinalControl=False))
  path.write_text("1")
  assert cs.cruise_set_scale == 1.0


@pytest.mark.parametrize("file_text", [None, "0"])
def test_op_long_set_unaffected_by_x2(monkeypatch, tmp_path, file_text):
  """Openpilot long: engaged = the engage latch (here vEgo 64 kph, no limit), not DI; not engaged = 0, never DI x2."""
  assert _speed(monkeypatch, tmp_path, file_text, True, 2, 40, steps=3) == pytest.approx(64.0 * CV.KPH_TO_MS, abs=1e-3)
  assert _speed(monkeypatch, tmp_path, file_text, True, 1, 40) == 0.0
