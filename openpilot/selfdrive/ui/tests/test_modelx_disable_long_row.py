"""AP1 Model X: Disable openpilot Longitudinal Control is shown (as on the Model S) and wins over AP1XOpenpilotLong, whose row is
hidden while Disable is on. The one-time Model X migration (AP1XOpenpilotLongForcedOn2) clears Disable only once, and a Disable set
on this row afterwards, or before that migration ever ran, sticks."""
from types import SimpleNamespace

import pytest

from opendbc.car.tesla_ap1 import toggles
from openpilot.common import bogpilot_ap1_profile as P
from openpilot.selfdrive.ui.bogpilot import menu_locks, onroad_policy, phase2_vehicle as pv
from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve

X, S, PREAP = "TESLA_AP1_MODELX", "TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"
LONG, X_LONG = pv.LONG, pv.X_LONG
MARKER = P.AP1X_LONG_FORCE_MARKER_NAME


def cp(fp=X, long=False, dashcam=False, alpha=False):
  return SimpleNamespace(carFingerprint=fp, dashcamOnly=dashcam, openpilotLongitudinalControl=long, alphaLongitudinalAvailable=alpha)


@pytest.fixture(autouse=True)
def pending(monkeypatch):
  store = {}
  monkeypatch.setattr(onroad_policy, "_read_all", lambda: dict(store))

  def write_all(values):
    store.clear()
    store.update(values)
    return True
  monkeypatch.setattr(onroad_policy, "_write_all", write_all)
  return store


class FileParams:
  """put_bool writes the Params file the row and the car interface read."""
  def __init__(self, path):
    self.path = path

  def put_bool(self, key, value, block=False):
    assert key == LONG
    self.path.write_text("1" if value else "0")


class FakeParams:
  def __init__(self, **vals):
    self.vals = dict(vals)

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value, block=False):
    self.vals[key] = value

  def invalidate(self):
    pass


def model(tmp_path, car=None, started=False, offroad=True):
  bp = tmp_path / "bp"
  bp.mkdir(exist_ok=True)
  return pv.VehicleSettings(FileParams(tmp_path / "params_long"), lambda: car or cp(), lambda: offroad, file_dir=str(bp),
                            params_file=str(tmp_path / "params_long"), started=lambda: started)


def migrate(tmp_path, disable_param):
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal=disable_param)
  changed = P.force_ap1x_op_long_on_once(p, bogpilot_dir=tmp_path / "bp")
  return changed, p


# ---- visibility and precedence ----
@pytest.mark.parametrize("car", [cp(X), cp(X, long=True), cp(S, long=True), cp(PREAP, long=True)])
def test_disable_row_visible_on_model_x_like_model_s(tmp_path, car):
  m = model(tmp_path, car)
  assert m.visible(LONG) is True and m.enabled(LONG) is True


@pytest.mark.parametrize("car", [cp(X, dashcam=True), cp(X, alpha=True), cp("TESLA_MODEL_Y"), cp(""), None])
def test_disable_row_hidden_for_undetected_dashcam_or_other_cars(tmp_path, car):
  m = pv.VehicleSettings(FileParams(tmp_path / "params_long"), lambda: car, lambda: True, file_dir=str(tmp_path),
                         params_file=str(tmp_path / "params_long"))
  assert m.visible(LONG) is False and m.write(LONG, True) is False and not (tmp_path / "params_long").exists()


def test_model_x_row_hidden_while_disable_is_on_and_back_when_off(tmp_path):
  m = model(tmp_path)
  assert m.visible(X_LONG) is True and m.read(LONG) is False
  assert m.write(LONG, True) is True and m.read(LONG) is True
  assert m.visible(X_LONG) is False and m.enabled(X_LONG) is False
  assert m.write(X_LONG, True) is False and m.x_long_change(True) == ("refused", None) and m.confirm_x_long_on() == ("refused", None)
  assert m.write(LONG, False) is True
  assert m.visible(X_LONG) is True and m.read(X_LONG) is True       # its own saved value is untouched


def test_model_x_row_hidden_while_disable_is_queued(tmp_path, pending):
  m = model(tmp_path, started=True, offroad=True)
  assert m.write(LONG, True) is True and pending == {LONG: True}
  assert m.read(LONG) is True and m.visible(X_LONG) is False
  assert not (tmp_path / "params_long").exists()                     # queued, written with the car off


def test_override_file_also_hides_the_model_x_row(tmp_path):
  m = model(tmp_path)
  (tmp_path / "bp" / LONG).write_text("1")                           # the file the interface reads first
  assert m.read(LONG) is True and m.visible(X_LONG) is False
  assert m.write(LONG, False) is True and (tmp_path / "bp" / LONG).read_text() == "0" and m.visible(X_LONG) is True


def test_x_description_says_disable_wins_and_s_text_unchanged(tmp_path):
  x_text = model(tmp_path).description(LONG).lower()
  assert "stock tacc" in x_text and "wins" in x_text and "next time the car starts" in x_text
  assert model(tmp_path, cp(S, long=True)).description(LONG) == pv.DESCRIPTIONS[LONG]
  assert model(tmp_path, cp(PREAP, long=True)).description(LONG) == pv.PREAP_LONG_DESCRIPTION
  assert "wins" in resolve(LONG).note and "Disable openpilot Longitudinal Control" in resolve(X_LONG).note
  for text in (pv.X_DISABLE_LONG_DESCRIPTION, resolve(LONG).note, resolve(X_LONG).note):
    assert text.isascii()


def test_locks_follow_the_winning_row():
  lock = menu_locks.long_lock(cp(X), disable_toggle_on=True)
  assert lock.code == "toggle_off" and lock.unlock_toggle == LONG
  assert menu_locks.long_lock(cp(X), disable_toggle_on=False) is menu_locks.STEERING_ONLY
  assert menu_locks.long_lock(cp(X, long=True), disable_toggle_on=False) is None
  assert menu_locks.gas_brake_pill_visible(cp(X, long=True), disable_toggle_on=True) is False
  for note in (menu_locks.MODEL_X_VEHICLE, menu_locks.MODEL_X_WHEEL):
    assert "Disable openpilot Longitudinal Control" in note.detail and note.detail.isascii()


# ---- the one-time migration and a later deliberate Disable ----
def test_migration_clears_disable_once_then_a_row_disable_sticks(tmp_path):
  bp = tmp_path / "bp"
  bp.mkdir()
  (bp / LONG).write_text("1")
  changed, p = migrate(tmp_path, "1")
  assert changed is True and (bp / LONG).read_text() == "0" and p.vals[LONG] == "0" and (bp / MARKER).exists()
  m = model(tmp_path)
  assert m.read(LONG) is False and m.write(LONG, True) is True       # the driver picks stock TACC
  for _ in range(3):
    changed, p = migrate(tmp_path, "1")
    assert changed is False and p.vals[LONG] == "1"
  assert (bp / LONG).read_text() == "1" and m.read(LONG) is True
  assert toggles.disable_openpilot_long(paths=(bp / LONG, tmp_path / "params_long")) is True   # what the car reads at start


def test_disable_set_before_the_migration_ever_ran_also_sticks(tmp_path):
  # New device: the X row shows during the first drive, before the boot-time migration has seen the car.
  m = model(tmp_path)
  assert not (tmp_path / "bp" / MARKER).exists()
  assert m.write(LONG, True) is True and (tmp_path / "bp" / MARKER).exists()
  changed, p = migrate(tmp_path, "1")
  assert changed is False and p.vals[LONG] == "1" and m.read(LONG) is True


def test_queued_disable_marks_only_when_written(tmp_path, pending):
  m = model(tmp_path, started=True)
  assert m.write(LONG, True) is True and not (tmp_path / "bp" / MARKER).exists()
  off = model(tmp_path, started=False)
  assert off.write(LONG, pending[LONG]) is True and (tmp_path / "bp" / MARKER).exists()


@pytest.mark.parametrize("car", [cp(S, long=True), cp(PREAP, long=True)])
def test_other_cars_never_write_the_model_x_marker(tmp_path, car):
  m = model(tmp_path, car)
  assert m.write(LONG, True) is True and not (tmp_path / "bp" / MARKER).exists()


def test_mark_helper_is_idempotent_and_never_raises(tmp_path):
  assert P.mark_ap1x_long_force_done(tmp_path / "new") is True
  assert P.mark_ap1x_long_force_done(tmp_path / "new") is True
  (tmp_path / "file").write_text("x")
  assert P.mark_ap1x_long_force_done(tmp_path / "file") is False     # not a directory: False, no exception
