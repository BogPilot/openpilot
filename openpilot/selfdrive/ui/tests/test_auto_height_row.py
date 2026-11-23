"""Vehicle Controls: the Auto Height switch and its Park / Drive height buttons (opendbc tesla_ap1/ride_height.py)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from opendbc.car.tesla_ap1 import ride_height as rh
from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve

KEY, PARK, DRIVE = pv.AUTO_HEIGHT, pv.AUTO_HEIGHT_PARK, pv.AUTO_HEIGHT_DRIVE
ALL_LEVELS = (1, 2, 3, 4)


def cp(fp, dashcam=False, long=True):
  return SimpleNamespace(carFingerprint=fp, dashcamOnly=dashcam, openpilotLongitudinalControl=long, alphaLongitudinalAvailable=False)


def model(car, tmp_path, offroad=True, air=True):
  if air:
    (tmp_path / pv.AIR_SUSPENSION_DETECTED).write_text("1")
  return pv.VehicleSettings(SimpleNamespace(put_bool=lambda *a, **k: None), lambda: car, lambda: offroad,
                            file_dir=str(tmp_path), params_file=str(tmp_path / "unused"))


@pytest.fixture
def full_panda(monkeypatch):
  """A panda with the approval-pending rule: Park 1-4 and Drive at standstill."""
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "PANDA_PARK_LEVELS", ALL_LEVELS)
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", True)


@pytest.fixture
def park_only_panda(monkeypatch):
  """The shipped Lower on Park panda rule: Park Low / Medium only, nothing in Drive."""
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", True)
  monkeypatch.setattr(rh, "PANDA_PARK_LEVELS", (1, 2))
  monkeypatch.setattr(rh, "PANDA_DRIVE_TX_SUPPORTED", False)


def test_keys_titles_and_help():
  assert (KEY, PARK, DRIVE) == ("AutoHeight", "AutoHeightPark", "AutoHeightDrive")
  assert (KEY, PARK, DRIVE) == (rh.ENABLE_KEY, rh.HEIGHT_KEY, rh.DRIVE_HEIGHT_KEY)
  assert pv.TITLES[KEY] == "Tesla AP1: Auto Height"
  assert pv.AUTO_HEIGHT_PARK_TITLE == "Auto Height: Park" and pv.AUTO_HEIGHT_DRIVE_TITLE == "Auto Height: Drive"
  text = pv.DESCRIPTIONS[KEY].lower()
  for word in ("park", "drive", "air suspension", "engaged", "tapping a height", "next time the car starts", "stopped"):
    assert word in text, word
  assert "low (default)" in pv.AUTO_HEIGHT_PARK_DESCRIPTION.lower() and "very high" in pv.AUTO_HEIGHT_PARK_DESCRIPTION.lower()
  assert "medium (default)" in pv.AUTO_HEIGHT_DRIVE_DESCRIPTION.lower() and "very high" in pv.AUTO_HEIGHT_DRIVE_DESCRIPTION.lower()
  assert resolve(KEY).default == "Off" and "Lower on Park" in resolve(KEY).note
  assert resolve(PARK).default == "Low" and resolve(PARK).range == "Low, Medium, High, Very High, None"
  assert resolve(DRIVE).default.startswith("Medium") and resolve(DRIVE).range == "Low, Medium, High, Very High, None"
  assert "none" in resolve(KEY).what.lower() and "none" in resolve(DRIVE).note.lower()
  assert "none" in pv.AUTO_HEIGHT_PARK_DESCRIPTION.lower() and "none" in pv.AUTO_HEIGHT_DRIVE_DESCRIPTION.lower()
  for old in ("LowerOnPark", "LowerOnParkHeight", "RideHeightOnDrive"):
    assert old not in pv.TITLES and resolve(old) is None


@pytest.mark.parametrize("fp", ["TESLA_AP1_MODELS", "TESLA_AP1_MODELX"])
def test_hidden_while_the_panda_does_not_allow_it(tmp_path, monkeypatch, fp):
  monkeypatch.setattr(rh, "PANDA_TX_SUPPORTED", False)
  m = model(cp(fp), tmp_path)
  assert m.visible(KEY) is False and m.visible(PARK) is False and m.visible(DRIVE) is False and m.write(KEY, True) is False


@pytest.mark.parametrize("fp", ["TESLA_AP1_MODELS", "TESLA_AP1_MODELX"])
def test_shown_only_with_air_suspension(tmp_path, full_panda, fp):
  assert model(cp(fp), tmp_path, air=False).visible(KEY) is False
  m = model(cp(fp), tmp_path)
  assert m.visible(KEY) is True and m.enabled(KEY) is True
  assert m.write(KEY, True) is True and m.visible(PARK) is True and m.visible(DRIVE) is True
  (tmp_path / pv.AIR_SUSPENSION_DETECTED).write_text("0")
  assert m.visible(KEY) is False and m.visible(PARK) is False and m.visible(DRIVE) is False
  (tmp_path / pv.AIR_SUSPENSION_DETECTED).unlink()                    # not reported yet: hidden too
  assert m.visible(KEY) is False


@pytest.mark.parametrize("car", [cp("TESLA_PREAP_MODELS"), cp("TESLA_MODEL_Y"), cp(""), cp("TESLA_AP1_MODELS", dashcam=True),
                                 cp("TESLA_AP1_MODELX", dashcam=True), None])
def test_hidden_on_other_cars(tmp_path, full_panda, car):
  (tmp_path / KEY).write_text("1")
  m = model(car, tmp_path)
  for key in (KEY, PARK, DRIVE):
    assert m.visible(key) is False
  assert m.write(KEY, False) is False and m.next_park_height() is None and m.next_drive_height() is None
  assert (tmp_path / KEY).read_text() == "1" and not (tmp_path / PARK).exists() and not (tmp_path / DRIVE).exists()


def test_height_rows_only_while_auto_height_is_on(tmp_path, full_panda):
  m = model(cp("TESLA_AP1_MODELS"), tmp_path)
  assert m.read(KEY) is False and m.visible(PARK) is False and m.visible(DRIVE) is False
  assert m.next_park_height() is None and m.next_drive_height() is None
  assert m.write(KEY, True) is True and (tmp_path / KEY).read_text() == "1" and rh.enabled(path=tmp_path / KEY) is True
  assert m.visible(PARK) is True and m.visible(DRIVE) is True
  assert m.write(KEY, False) is True and m.visible(PARK) is False and m.visible(DRIVE) is False


def test_defaults_and_full_cycle(tmp_path, full_panda):
  m = model(cp("TESLA_AP1_MODELX"), tmp_path)
  m.write(KEY, True)
  assert (m.park_height(), m.park_height_text()) == ("low", "Low")
  assert (m.drive_height(), m.drive_height_text()) == ("medium", "Medium")
  park = [m.next_park_height() for _ in range(5)]
  assert park == ["medium", "high", "very_high", "none", "low"]
  drive = [m.next_drive_height() for _ in range(5)]
  assert drive == ["high", "very_high", "none", "low", "medium"]
  m.next_park_height(); m.next_park_height(); m.next_park_height()
  assert m.park_height_text() == "Very High" and rh.level_for(path=tmp_path / PARK) == 4
  m.next_park_height()
  assert m.park_height_text() == "None" and rh.level_for(path=tmp_path / PARK) is None
  m.next_drive_height(); m.next_drive_height(); m.next_drive_height()
  assert m.drive_height_text() == "None" and rh.drive_level_for(path=tmp_path / DRIVE) is None


def test_park_only_panda_limits_the_rows(tmp_path, park_only_panda):
  m = model(cp("TESLA_AP1_MODELS"), tmp_path)
  m.write(KEY, True)
  assert m.visible(PARK) is True and m.visible(DRIVE) is False and m.next_drive_height() is None
  assert not (tmp_path / DRIVE).exists()
  assert [m.next_park_height() for _ in range(4)] == ["medium", "none", "low", "medium"]
  # A saved height above what the panda allows is shown as is and kept until the driver presses the button.
  (tmp_path / PARK).write_text("very_high")
  assert m.park_height_text() == "Very High" and (tmp_path / PARK).read_text() == "very_high"
  assert m.next_park_height() == "low"


@pytest.mark.parametrize("saved_on, saved_height, want_on, want_height", [
  ("1", "medium", True, "medium"), ("1", "low", True, "low"), ("1", None, True, "low"),
  ("0", "medium", False, "medium"), (None, "medium", False, "medium"), (None, None, False, "low")])
def test_lower_on_park_choice_carries_over(tmp_path, full_panda, saved_on, saved_height, want_on, want_height):
  if saved_on is not None:
    (tmp_path / "LowerOnPark").write_text(saved_on)
  if saved_height is not None:
    (tmp_path / "LowerOnParkHeight").write_text(saved_height)
  before = {p.name: p.read_text() for p in tmp_path.iterdir()}
  m = model(cp("TESLA_AP1_MODELS"), tmp_path)
  want_drive = "none" if (saved_on, saved_height) != (None, None) else "medium"   # moved over: Drive starts at None
  assert m.read(KEY) is want_on and m.park_height() == want_height and m.drive_height() == want_drive
  assert m.visible(PARK) is want_on
  # Reading never writes: the old files are untouched and no new file appears.
  assert {p.name: p.read_text() for p in tmp_path.iterdir() if p.name != pv.AIR_SUSPENSION_DETECTED} == \
         {k: v for k, v in before.items() if k != pv.AIR_SUSPENSION_DETECTED}


def test_new_keys_win_and_old_files_are_never_touched(tmp_path, full_panda):
  (tmp_path / "LowerOnPark").write_text("1")
  (tmp_path / "LowerOnParkHeight").write_text("medium")
  m = model(cp("TESLA_AP1_MODELS"), tmp_path)
  assert m.write(KEY, False) is True and m.read(KEY) is False                   # the new key now decides
  assert m.write(KEY, True) is True and m.next_park_height() == "high"          # from the carried-over Medium
  assert (tmp_path / "LowerOnPark").read_text() == "1" and (tmp_path / "LowerOnParkHeight").read_text() == "medium"
  (tmp_path / KEY).write_text("0")
  assert m.read(KEY) is False


def test_edit_gate_refuses(tmp_path, full_panda):
  (tmp_path / KEY).write_text("1")
  m = model(cp("TESLA_AP1_MODELS"), tmp_path, offroad=False)
  assert m.visible(KEY) is True and m.enabled(KEY) is False and m.write(KEY, False) is False
  assert m.visible(PARK) is True and m.enabled(PARK) is False and m.next_park_height() is None
  assert m.enabled(DRIVE) is False and m.next_drive_height() is None


def test_other_rows_unchanged_for_model_x(tmp_path, full_panda):
  x = model(cp("TESLA_AP1_MODELX", long=False), tmp_path)
  for other in (pv.CLUSTER, pv.REGEN, pv.LONG, pv.RADAR, pv.IBOOSTER):
    assert x.visible(other) is False


def test_rows_sit_right_under_the_switch():
  src = Path(pv.__file__).read_text()
  i = src.index("if key == AUTO_HEIGHT:\n          ordered[AUTO_HEIGHT_PARK] = self.park_height_row")
  assert src.index("ordered[AUTO_HEIGHT_DRIVE] = self.drive_height_row") > i


def test_backup_scope_includes_the_files():
  from openpilot.system.bogpilot.settings_backup import FILE_KEYS
  assert {KEY, PARK, DRIVE, "LowerOnPark", "LowerOnParkHeight"} <= FILE_KEYS and pv.AIR_SUSPENSION_DETECTED not in FILE_KEYS
  assert "RideHeightOnDrive" not in FILE_KEYS


def test_moved_over_drive_row_reads_none_until_picked(tmp_path, full_panda):
  (tmp_path / "LowerOnPark").write_text("1")
  m = model(cp("TESLA_AP1_MODELS"), tmp_path)
  assert m.visible(DRIVE) is True and m.drive_height_text() == "None" and not (tmp_path / DRIVE).exists()
  assert m.next_drive_height() == "low" and (tmp_path / DRIVE).read_text() == "low"
  assert (tmp_path / "LowerOnPark").read_text() == "1"


def test_fresh_setup_defaults_when_turned_on(tmp_path, full_panda):
  m = model(cp("TESLA_AP1_MODELX"), tmp_path)
  assert m.read(KEY) is False                                         # master off by default
  m.write(KEY, True)
  assert (m.park_height_text(), m.drive_height_text()) == ("Low", "Medium")
