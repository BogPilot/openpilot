"""Vehicle Controls: Tesla AP1 lead side check row (opendbc tesla_ap1/lead_side_check.py), default off."""
from types import SimpleNamespace

import pytest

from opendbc.car.tesla_ap1 import lead_side_check as lsc
from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve

KEY = pv.SIDE_CHECK


def cp(fp, dashcam=False, long=True):
  return SimpleNamespace(carFingerprint=fp, dashcamOnly=dashcam, openpilotLongitudinalControl=long, alphaLongitudinalAvailable=False)


def model(car, tmp_path, offroad=True):
  return pv.VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: car, lambda: offroad,
                            file_dir=str(tmp_path), params_file=str(tmp_path / "unused"))


def test_registered_with_text_and_help():
  assert KEY == lsc.SIDE_CHECK_KEY == "AP1LeadSideCheck" and KEY in pv.TITLES and KEY in pv.DESCRIPTIONS
  text = pv.DESCRIPTIONS[KEY].lower()
  assert "34 mph" in text and "off by default" in text and "next time the car starts" in text
  assert resolve(KEY) is not None and resolve(KEY).default == "Off"


@pytest.mark.parametrize("car,shown", [(cp("TESLA_AP1_MODELS"), True), (cp("TESLA_AP1_MODELS", long=False), False),
                                       (cp("TESLA_AP1_MODELX"), True), (cp("TESLA_AP1_MODELX", long=False), False),
                                       (cp("TESLA_PREAP_MODELS"), False), (cp("TESLA_AP1_MODELS", dashcam=True), False),
                                       (cp("TESLA_MODEL_3"), False), (None, False)])
def test_visibility(tmp_path, car, shown):
  assert model(car, tmp_path).visible(KEY) is shown


def test_default_off_and_write(tmp_path):
  m = model(cp("TESLA_AP1_MODELS"), tmp_path)
  assert m.read(KEY) is False
  assert m.write(KEY, True) is True and (tmp_path / KEY).read_text() == "1" and m.read(KEY) is True
  assert lsc.side_check_enabled(path=tmp_path / KEY) is True
  assert m.write(KEY, False) is True and m.read(KEY) is False


def test_hidden_row_refuses_write(tmp_path):
  m = model(cp("TESLA_PREAP_MODELS"), tmp_path)
  assert m.write(KEY, True) is False and not (tmp_path / KEY).exists()


def test_backed_up():
  from openpilot.system.bogpilot import settings_backup
  assert KEY in settings_backup.FILE_KEYS
