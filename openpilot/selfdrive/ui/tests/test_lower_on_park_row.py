"""Vehicle Controls: Lower on Park switch and its Low / Medium height button (opendbc tesla_ap1/ride_height.py)."""
from types import SimpleNamespace

import pytest

from opendbc.car.tesla_ap1 import ride_height as rh
from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve

KEY, HEIGHT = pv.LOWER_ON_PARK, pv.LOWER_ON_PARK_HEIGHT


def cp(fp, dashcam=False, long=True):
  return SimpleNamespace(carFingerprint=fp, dashcamOnly=dashcam, openpilotLongitudinalControl=long, alphaLongitudinalAvailable=False)


def model(car, tmp_path, offroad=True, air=True):
  if air:
    (tmp_path / pv.AIR_SUSPENSION_DETECTED).write_text("1")
  return pv.VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: car, lambda: offroad,
                            file_dir=str(tmp_path), params_file=str(tmp_path / "unused"))


@pytest.fixture
def panda_allows(monkeypatch):
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)


def test_registered_with_text_and_help():
  assert KEY == "LowerOnPark" and HEIGHT == "LowerOnParkHeight" and KEY in pv.TITLES and KEY in pv.DESCRIPTIONS
  text = pv.DESCRIPTIONS[KEY].lower()
  assert "park" in text and "low" in text and "air suspension" in text and "next time the car starts" in text
  assert resolve(KEY) is not None and resolve(KEY).default == "Off"
  assert resolve(HEIGHT) is not None and resolve(HEIGHT).default == "Low"


@pytest.mark.parametrize("fp", ["TESLA_AP1_MODELS", "TESLA_AP1_MODELX"])
def test_hidden_while_the_panda_does_not_allow_it(tmp_path, monkeypatch, fp):
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", False)
  m = model(cp(fp), tmp_path)
  assert m.visible(KEY) is False and m.visible(HEIGHT) is False and m.write(KEY, True) is False


@pytest.mark.parametrize("fp", ["TESLA_AP1_MODELS", "TESLA_AP1_MODELX"])
def test_shown_only_with_air_suspension(tmp_path, panda_allows, fp):
  assert model(cp(fp), tmp_path, air=False).visible(KEY) is False
  m = model(cp(fp), tmp_path)
  assert m.visible(KEY) is True and m.enabled(KEY) is True
  (tmp_path / pv.AIR_SUSPENSION_DETECTED).write_text("0")
  assert m.visible(KEY) is False


@pytest.mark.parametrize("car", [cp("TESLA_PREAP_MODELS"), cp("TESLA_MODEL_Y"), cp(""), cp("TESLA_AP1_MODELS", dashcam=True),
                                 cp("TESLA_AP1_MODELX", dashcam=True), None])
def test_hidden_on_other_cars(tmp_path, panda_allows, car):
  m = model(car, tmp_path)
  assert m.visible(KEY) is False and m.write(KEY, True) is False and not (tmp_path / KEY).exists()


def test_default_off_round_trip_and_height_button(tmp_path, panda_allows):
  m = model(cp("TESLA_AP1_MODELS"), tmp_path)
  assert m.read(KEY) is False and m.visible(HEIGHT) is False          # height button only while the switch is on
  assert m.write(KEY, True) is True and (tmp_path / KEY).read_text() == "1" and m.read(KEY) is True
  assert rh.enabled(path=tmp_path / KEY) is True                      # the car's reader agrees
  assert m.visible(HEIGHT) is True and m.lop_height() == "low" and m.lop_height_text() == "Low"
  assert m.next_lop_height() == "medium" and (tmp_path / HEIGHT).read_text() == "medium" and m.lop_height_text() == "Medium"
  assert rh.level_for(path=tmp_path / HEIGHT) == rh.LEVEL_MEDIUM
  assert m.next_lop_height() == "low"
  assert m.write(KEY, False) is True and m.read(KEY) is False and m.next_lop_height() is None


def test_edit_gate_refuses(tmp_path, panda_allows):
  m = model(cp("TESLA_AP1_MODELS"), tmp_path, offroad=False)
  assert m.visible(KEY) is True and m.enabled(KEY) is False and m.write(KEY, True) is False


def test_other_rows_unchanged_for_model_x(tmp_path, panda_allows):
  x = model(cp("TESLA_AP1_MODELX", long=False), tmp_path)
  for other in (pv.CLUSTER, pv.REGEN, pv.LONG, pv.RADAR, pv.IBOOSTER):
    assert x.visible(other) is False


def test_backup_scope_includes_the_files():
  from openpilot.system.bogpilot.settings_backup import FILE_KEYS
  assert {KEY, HEIGHT} <= FILE_KEYS and pv.AIR_SUSPENSION_DETECTED not in FILE_KEYS
