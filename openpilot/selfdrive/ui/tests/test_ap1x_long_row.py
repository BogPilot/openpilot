"""AP1XOpenpilotLong on the Vehicle Controls page: no row any more. On the AP1 Model X, Disable openpilot Longitudinal Control is
the single longitudinal row, as on the Model S; the car interface no longer reads the old file."""
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


def test_key_kept_with_not_shown_text_and_help():
  assert KEY == "AP1XOpenpilotLong" and KEY in pv.TITLES and KEY in pv.DESCRIPTIONS
  assert "not shown" in pv.DESCRIPTIONS[KEY].lower() and "Disable openpilot Longitudinal Control" in pv.DESCRIPTIONS[KEY]
  entry = resolve(KEY)
  assert entry is not None and entry.default == "On" and "Disable openpilot Longitudinal Control" in entry.what
  assert "experimental" not in entry.title.lower()


@pytest.mark.parametrize("car", [cp("TESLA_AP1_MODELX"), cp("TESLA_AP1_MODELX", long=True), cp("TESLA_AP1_MODELS", long=True),
                                 cp("TESLA_PREAP_MODELS"), cp("TESLA_MODEL_Y"), cp(""), cp("MOCK"),
                                 cp("TESLA_AP1_MODELX", dashcam=True), None])
def test_hidden_on_every_car_including_the_model_x(tmp_path, car):
  m = model(car, tmp_path)
  assert m.visible(KEY) is False and m.enabled(KEY) is False
  assert m.write(KEY, True) is False and m.write(KEY, False) is False and not (tmp_path / KEY).exists()


def test_single_row_reads_only_disable_as_the_interface_does(tmp_path):
  m = model(cp("TESLA_AP1_MODELX"), tmp_path)
  assert m.read(KEY) is True                                      # legacy helper: default on, no file
  (tmp_path / KEY).write_text("0")
  assert m.read(KEY) is False
  assert m.read(pv.LONG) is False                                 # the old file does not drive the single row
  (tmp_path / pv.LONG).write_text("1")
  assert m.read(pv.LONG) is True


def test_model_s_rows_unchanged_and_the_x_sees_only_the_disable_row(tmp_path):
  s = model(cp("TESLA_AP1_MODELS", long=True), tmp_path)
  assert s.visible(pv.CLUSTER) and s.visible(pv.REGEN) and s.visible(pv.LONG) and not s.visible(KEY)
  x = model(cp("TESLA_AP1_MODELX"), tmp_path)
  for other in (pv.REGEN, pv.RADAR, pv.IBOOSTER, KEY):
    assert x.visible(other) is False
  assert x.visible(pv.LONG) is True
  assert x.visible(pv.CLUSTER) is True                            # Dash Cluster Integration, same row as the S


def test_page_note_for_model_x_points_at_the_disable_row_and_clears_once_long_is_on():
  note = menu_locks.page_note(cp("TESLA_AP1_MODELX"), "vehicle_controls")
  assert note.code == "steering_only" and "Disable openpilot Longitudinal Control" in note.detail
  assert "experimental" not in note.detail.lower()
  assert menu_locks.page_note(cp("TESLA_AP1_MODELX", long=True), "vehicle_controls") is None
  wheel = menu_locks.page_note(cp("TESLA_AP1_MODELX"), "stalk_controls")
  assert wheel is menu_locks.MODEL_X_WHEEL and "Disable openpilot Longitudinal Control" in wheel.detail
  assert menu_locks.page_note(cp("TESLA_AP1_MODELS", long=True), "vehicle_controls") is None


def test_gas_brake_lock_on_model_x_follows_the_single_row(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / KEY)
  assert menu_locks.long_lock(cp("TESLA_AP1_MODELX"), disable_toggle_on=False) is menu_locks.RESTART
  lock = menu_locks.long_lock(cp("TESLA_AP1_MODELX"), disable_toggle_on=True)
  assert lock.code == "toggle_off" and lock.unlock_toggle == pv.LONG
  (tmp_path / KEY).write_text("0")                                # old row Off: the car ignores it, so it does not lock
  assert menu_locks.long_lock(cp("TESLA_AP1_MODELX"), disable_toggle_on=False) is menu_locks.RESTART
  assert menu_locks.long_lock(cp("TESLA_AP1_MODELX", long=True)) is None
