"""Vehicle Options: the Tesla Trim picker (TeslaTrim) and the read-only Detected line. Only trims consistent with what
CAN detected are listed; Auto is the default; a saved trim that contradicts CAN is kept and marked."""
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve
from opendbc.car.tesla_ap1 import trims as T


def cp(fp, long=False):
  return SimpleNamespace(carFingerprint=fp, dashcamOnly=False, openpilotLongitudinalControl=long, alphaLongitudinalAvailable=False)


def model(car, tmp_path, offroad=True, changes=None):
  m = pv.VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: car, lambda: offroad,
                         file_dir=str(tmp_path), params_file=str(tmp_path / "unused"))
  if changes is not None:
    m.on_change = changes.append
  return m


def test_registered_with_help():
  assert pv.TRIM == "TeslaTrim" and pv.TRIM_DETECTED == "TeslaTrimDetected"
  assert resolve(pv.TRIM) is not None and resolve(pv.TRIM).default == "Auto"
  assert resolve(pv.TRIM_DETECTED) is not None


@pytest.mark.parametrize("fp", ["TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"])
def test_visible_on_tesla_ap1_cars(tmp_path, fp):
  m = model(cp(fp), tmp_path)
  assert m.visible(pv.TRIM) and m.visible(pv.TRIM_DETECTED)
  assert m.enabled(pv.TRIM) and not m.enabled(pv.TRIM_DETECTED)        # Detected is read-only


@pytest.mark.parametrize("car", [cp("TESLA_MODEL_Y"), cp(""), cp("MOCK"), None])
def test_hidden_elsewhere(tmp_path, car):
  m = model(car, tmp_path)
  assert not m.visible(pv.TRIM) and not m.visible(pv.TRIM_DETECTED) and m.step_trim(1) is None
  assert not (tmp_path / pv.TRIM).exists()


def test_default_auto_and_list_follows_detection(tmp_path):
  m = model(cp("TESLA_AP1_MODELX"), tmp_path)
  assert m.trim() == "Auto" and m.trim_text() == "Auto"
  assert m.trim_keys() == ["Auto"] + [t.key for t in T.platform_trims("TESLA_AP1_MODELX")]
  T.write_detected(T.Detected("X", T.LAYOUT_DUAL, T.PERF_YES), tmp_path / pv.TRIM_DETECTED)
  assert m.trim_keys() == ["Auto", "XP90D", "XP90DL", "XP100DL"]
  assert m.detected_text() == "Model X, dual motor, Performance rear (from CAN)"


def test_step_writes_clamps_and_notifies(tmp_path):
  changes = []
  m = model(cp("TESLA_AP1_MODELS"), tmp_path, changes=changes)
  T.write_detected(T.Detected("S", T.LAYOUT_DUAL, T.PERF_NO), tmp_path / pv.TRIM_DETECTED)
  assert m.step_trim(-1) == "Auto" and changes == [] and not (tmp_path / pv.TRIM).exists()   # clamped, no write
  assert m.step_trim(1) == "S60D" and (tmp_path / pv.TRIM).read_text() == "S60D" and changes == [pv.TRIM]
  for _ in range(20):
    m.step_trim(1)
  assert m.trim() == "S100D"                                                                  # no wrap
  assert T.profile_for("TESLA_AP1_MODELS", T.read_trim((tmp_path / pv.TRIM).read_text()),
                       T.read_detected(path=tmp_path / pv.TRIM_DETECTED)).mass_kg == 2215 + 136


def test_locked_while_driving(tmp_path):
  m = model(cp("TESLA_AP1_MODELS"), tmp_path, offroad=False)
  assert m.visible(pv.TRIM) and not m.enabled(pv.TRIM) and m.step_trim(1) is None


def test_mismatch_kept_and_marked(tmp_path):
  (tmp_path / pv.TRIM).write_text("X90D")
  T.write_detected(T.Detected("X", T.LAYOUT_DUAL, T.PERF_YES), tmp_path / pv.TRIM_DETECTED)
  m = model(cp("TESLA_AP1_MODELX"), tmp_path)
  assert m.trim_mismatch() and m.trim_text() == "90D (does not match the car)"
  assert m.trim_keys()[:2] == ["Auto", "X90D"]
  assert (tmp_path / pv.TRIM).read_text() == "X90D"                     # never rewritten behind the user's back


def test_detection_for_another_chassis_is_ignored(tmp_path):
  T.write_detected(T.Detected("X", T.LAYOUT_DUAL, T.PERF_YES), tmp_path / pv.TRIM_DETECTED)
  m = model(cp("TESLA_AP1_MODELS"), tmp_path)
  assert "drive the car once" in m.detected_text()
  assert len(m.trim_keys()) == 1 + len(T.platform_trims("TESLA_AP1_MODELS"))


def test_preap_lists_only_preap_rwd_trims(tmp_path):
  m = model(cp("TESLA_PREAP_MODELS"), tmp_path)
  assert m.trim_keys() == ["Auto", "S40", "S60", "S85", "SP85", "SP85PLUS"]
