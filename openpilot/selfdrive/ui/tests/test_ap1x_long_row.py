"""Vehicle Controls row for the experimental AP1 Model X openpilot long (AP1XOpenpilotLong): Model X only, default on, file-backed."""
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.bogpilot import menu_locks, phase2_vehicle as pv
from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve
from opendbc.car.tesla_ap1 import toggles

KEY = pv.X_LONG


def cp(fp, dashcam=False, long=False):
  return SimpleNamespace(carFingerprint=fp, dashcamOnly=dashcam, openpilotLongitudinalControl=long, alphaLongitudinalAvailable=False)


def model(car, tmp_path, offroad=True):
  return pv.VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: car, lambda: offroad,
                            file_dir=str(tmp_path), params_file=str(tmp_path / "unused"))


def test_row_registered_with_experimental_text_and_help():
  assert KEY == "AP1XOpenpilotLong" and KEY in pv.TITLES and KEY in pv.DESCRIPTIONS
  text = pv.DESCRIPTIONS[KEY].lower()
  assert "experimental" in text and "on by default" in text and "stock tacc" in text
  assert "next time the car starts" in text and "no reboot is needed" in text and "reboots" not in text
  assert "experimental" in pv.TITLES[KEY].lower()
  help_entry = resolve(KEY)
  assert help_entry is not None and help_entry.default == "On"


@pytest.mark.parametrize("car", [cp("TESLA_AP1_MODELS", long=True), cp("TESLA_PREAP_MODELS"), cp("TESLA_MODEL_Y"), cp(""), cp("MOCK"),
                                 cp("TESLA_AP1_MODELX", dashcam=True), None])
def test_hidden_on_every_car_but_a_detected_model_x(tmp_path, car):
  m = model(car, tmp_path)
  assert m.visible(KEY) is False and m.enabled(KEY) is False
  assert m.write(KEY, True) is False and not (tmp_path / KEY).exists()


def test_visible_on_model_x_only_offroad_editable_and_defaults_on(tmp_path):
  m = model(cp("TESLA_AP1_MODELX"), tmp_path)
  assert m.visible(KEY) is True and m.enabled(KEY) is True
  assert m.read(KEY) is True                                      # default on, no file
  assert m.write(KEY, False) is True
  assert (tmp_path / KEY).read_text() == "0" and m.read(KEY) is False
  assert toggles.ap1x_op_long("TESLA_AP1_MODELX", stored=(tmp_path / KEY).read_text()) is False   # the interface's reader agrees
  assert m.write(KEY, True) is True and m.read(KEY) is True and (tmp_path / KEY).read_text() == "1"


def test_model_x_row_does_not_appear_for_model_s_rows_and_s_rows_unchanged(tmp_path):
  s = model(cp("TESLA_AP1_MODELS", long=True), tmp_path)
  assert s.visible(pv.CLUSTER) and s.visible(pv.REGEN) and s.visible(pv.LONG) and not s.visible(KEY)
  x = model(cp("TESLA_AP1_MODELX"), tmp_path)
  for other in (pv.CLUSTER, pv.REGEN, pv.RADAR, pv.IBOOSTER):
    assert x.visible(other) is False                              # S / Pre-AP rows stay hidden on the X
  assert x.visible(pv.LONG) is True                               # the Disable row is shared with the Model S


def test_page_note_for_model_x_points_at_the_row_and_clears_once_long_is_on():
  note = menu_locks.page_note(cp("TESLA_AP1_MODELX"), "vehicle_controls")
  assert note.code == "steering_only" and "experimental" in note.detail.lower()
  assert menu_locks.page_note(cp("TESLA_AP1_MODELX", long=True), "vehicle_controls") is None
  assert menu_locks.page_note(cp("TESLA_AP1_MODELX"), "stalk_controls").code == "steering_only"   # stalk page unchanged
  assert menu_locks.page_note(cp("TESLA_AP1_MODELS", long=True), "vehicle_controls") is None


def test_gas_brake_stays_locked_on_model_x_until_long_is_on():
  assert menu_locks.long_lock(cp("TESLA_AP1_MODELX")).code == "steering_only"
  assert menu_locks.long_lock(cp("TESLA_AP1_MODELX", long=True)) is None
