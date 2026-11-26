"""AP1 Model X: Disable openpilot Longitudinal Control is the single longitudinal row (as on the Model S), and the car reads only
it; the AP1XOpenpilotLong row is always hidden and the car no longer reads that file. A row change removes the old file. A saved
AP1XOpenpilotLong Off from the old row is carried over to Disable on at start, after the one-time step (AP1XOpenpilotLongForcedOn2),
which still runs once. A Disable set on the row always sticks."""
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
    self.vals = {k: v for k, v in vals.items() if v is not None}

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value, block=False):
    self.vals[key] = value

  def invalidate(self):
    pass


def bp(tmp_path):
  d = tmp_path / "bp"
  d.mkdir(exist_ok=True)
  return d


def model(tmp_path, car=None, started=False):
  return pv.VehicleSettings(FileParams(tmp_path / "params_long"), lambda: car or cp(), lambda: True, file_dir=str(bp(tmp_path)),
                            params_file=str(tmp_path / "params_long"), started=lambda: started)


def interface_long(tmp_path):
  """What tesla_ap1/interface.py decides at car start for a detected X: only Disable, as on the Model S."""
  d = bp(tmp_path)
  return not toggles.disable_openpilot_long(paths=(d / LONG, tmp_path / "params_long"))


def force(tmp_path, p):
  return P.force_ap1x_op_long_on_once(p, bogpilot_dir=bp(tmp_path))


def merge(tmp_path, p):
  return P.merge_ap1x_long_into_disable(p, bogpilot_dir=bp(tmp_path))


# ---- the single row ----
@pytest.mark.parametrize("car", [cp(X), cp(X, long=True), cp(S, long=True), cp(PREAP, long=True)])
def test_disable_row_visible_like_model_s_and_model_x_row_never(tmp_path, car):
  m = model(tmp_path, car)
  assert m.visible(LONG) is True and m.enabled(LONG) is True
  assert m.visible(X_LONG) is False and m.enabled(X_LONG) is False


@pytest.mark.parametrize("car", [cp(X, dashcam=True), cp(X, alpha=True), cp("TESLA_MODEL_Y"), cp(""), None])
def test_disable_row_hidden_for_undetected_dashcam_or_other_cars(tmp_path, car):
  m = pv.VehicleSettings(FileParams(tmp_path / "params_long"), lambda: car, lambda: True, file_dir=str(tmp_path),
                         params_file=str(tmp_path / "params_long"))
  assert m.visible(LONG) is False and m.write(LONG, True) is False and not (tmp_path / "params_long").exists()


@pytest.mark.parametrize("x_saved", [None, "0", "1"])
def test_turning_disable_off_gives_openpilot_long_back_whatever_was_saved(tmp_path, x_saved):
  m = model(tmp_path)
  if x_saved is not None:
    (bp(tmp_path) / X_LONG).write_text(x_saved)
  assert m.write(LONG, False) is True
  assert not (bp(tmp_path) / X_LONG).exists() and (tmp_path / "params_long").read_text() == "0"
  assert m.read(LONG) is False and interface_long(tmp_path) is True


@pytest.mark.parametrize("x_saved", [None, "0", "1"])
def test_turning_disable_on_keeps_long_off(tmp_path, x_saved):
  m = model(tmp_path)
  if x_saved is not None:
    (bp(tmp_path) / X_LONG).write_text(x_saved)
  assert m.write(LONG, True) is True
  assert (tmp_path / "params_long").read_text() == "1" and not (bp(tmp_path) / X_LONG).exists()
  assert m.read(LONG) is True and interface_long(tmp_path) is False


@pytest.mark.parametrize("disable,x_saved,shown", [(None, None, False), ("0", "1", False), ("0", "0", False), ("1", "1", True),
                                                   ("1", "0", True), (None, "off", False), (None, "garbage", False)])
def test_row_always_shows_what_the_car_will_do(tmp_path, disable, x_saved, shown):
  if disable is not None:
    (tmp_path / "params_long").write_text(disable)
  if x_saved is not None:
    (bp(tmp_path) / X_LONG).write_text(x_saved)
  assert model(tmp_path).read(LONG) is shown and interface_long(tmp_path) is (not shown)


def test_override_file_is_kept_in_step(tmp_path):
  m = model(tmp_path)
  (bp(tmp_path) / LONG).write_text("1")                               # the file the interface reads first
  assert m.read(LONG) is True
  assert m.write(LONG, False) is True and (bp(tmp_path) / LONG).read_text() == "0" and interface_long(tmp_path) is True


def test_queued_while_driving_nothing_written_until_the_car_is_off(tmp_path, pending):
  (bp(tmp_path) / X_LONG).write_text("0")
  m = model(tmp_path, started=True)
  assert m.write(LONG, False) is True and pending == {LONG: False}
  assert m.read(LONG) is False and (bp(tmp_path) / X_LONG).read_text() == "0" and not (bp(tmp_path) / MARKER).exists()
  off = model(tmp_path)
  assert off.write(LONG, pending[LONG]) is True and pending == {}
  assert not (bp(tmp_path) / X_LONG).exists() and interface_long(tmp_path) is True and (bp(tmp_path) / MARKER).exists()


@pytest.mark.parametrize("car", [cp(S, long=True), cp(PREAP, long=True)])
def test_other_cars_never_touch_the_model_x_file_or_marker(tmp_path, car):
  m = model(tmp_path, car)
  (bp(tmp_path) / X_LONG).write_text("0")
  for state in (True, False):
    assert m.write(LONG, state) is True
  assert (bp(tmp_path) / X_LONG).read_text() == "0" and not (bp(tmp_path) / MARKER).exists()


def test_texts_name_the_single_row(tmp_path):
  x_text = model(tmp_path).description(LONG).lower()
  assert "stock tacc" in x_text and "off (the default)" in x_text and "next time the car starts" in x_text
  assert model(tmp_path, cp(S, long=True)).description(LONG) == pv.DESCRIPTIONS[LONG]
  assert model(tmp_path, cp(PREAP, long=True)).description(LONG) == pv.PREAP_LONG_DESCRIPTION
  assert "only longitudinal setting" in resolve(LONG).note
  for text in (pv.X_DISABLE_LONG_DESCRIPTION, resolve(LONG).note, resolve(X_LONG).what, resolve(X_LONG).note,
               menu_locks.MODEL_X_VEHICLE.detail, menu_locks.MODEL_X_WHEEL.detail, menu_locks.STEERING_ONLY.detail):
    assert text.isascii() and "experimental" not in text.lower() and "\u2014" not in text


# ---- existing devices: the one-time forced On, then the carry-over ----
def test_saved_off_and_disable_off_resolves_to_disable_on(tmp_path):
  # AP1XOpenpilotLong=0, Disable=0 after the forced On already ran: a deliberate stock TACC choice on the old row. It stays stock.
  d = bp(tmp_path)
  (d / MARKER).write_text("1\n")
  (d / X_LONG).write_text("0")
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal="0")
  assert merge(tmp_path, p) is True
  assert p.vals[LONG] == "1" and not (d / X_LONG).exists()
  assert merge(tmp_path, p) is False                                   # idempotent
  (tmp_path / "params_long").write_text(p.vals[LONG])
  assert interface_long(tmp_path) is False and model(tmp_path).read(LONG) is True
  assert model(tmp_path).write(LONG, False) is True and interface_long(tmp_path) is True   # one tap gives long back


def test_override_file_carried_over_too(tmp_path):
  d = bp(tmp_path)
  (d / MARKER).write_text("1\n")
  (d / X_LONG).write_text("off")
  (d / LONG).write_text("0")
  p = FakeParams(CarModel=X)
  assert merge(tmp_path, p) is True and (d / LONG).read_text() == "1" and p.vals[LONG] == "1"


def test_device_that_never_ran_the_forced_on_gets_it_first(tmp_path):
  # Old build with the row Off and no v2 marker: the one-time step wins once (openpilot long on), the carry-over has nothing to do.
  d = bp(tmp_path)
  (d / X_LONG).write_text("0")
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal="1")
  assert merge(tmp_path, p) is False and (d / X_LONG).read_text() == "0"   # waits for the marker
  assert force(tmp_path, p) is True and merge(tmp_path, p) is False
  assert not (d / X_LONG).exists() and p.vals[LONG] == "0" and (d / MARKER).exists()
  for _ in range(3):
    assert force(tmp_path, p) is False                                 # the forced On still runs only once


@pytest.mark.parametrize("stored", [None, "1", "true", "", "garbage"])
def test_nothing_to_carry_over(tmp_path, stored):
  d = bp(tmp_path)
  (d / MARKER).write_text("1\n")
  if stored is not None:
    (d / X_LONG).write_text(stored)
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal="0")
  assert merge(tmp_path, p) is False and p.vals[LONG] == "0"


@pytest.mark.parametrize("car", [S, PREAP, "TESLA_MODEL_Y", None])
def test_carry_over_never_runs_on_other_cars(tmp_path, car):
  d = bp(tmp_path)
  (d / MARKER).write_text("1\n")
  (d / X_LONG).write_text("0")
  p = FakeParams(CarModel=car, DisableOpenpilotLongitudinal="0")
  assert merge(tmp_path, p) is False and (d / X_LONG).read_text() == "0" and p.vals.get(LONG) == "0"


def test_a_later_deliberate_disable_sticks(tmp_path):
  d = bp(tmp_path)
  (d / LONG).write_text("1")
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal="1")
  assert force(tmp_path, p) is True and p.vals[LONG] == "0" and (d / LONG).read_text() == "0"   # the one-time clear
  (tmp_path / "params_long").write_text("0")
  assert model(tmp_path).write(LONG, True) is True                     # the driver picks stock TACC
  p.vals[LONG] = (tmp_path / "params_long").read_text()
  for _ in range(3):
    assert force(tmp_path, p) is False and merge(tmp_path, p) is False
  assert p.vals[LONG] == "1" and (d / LONG).read_text() == "1" and interface_long(tmp_path) is False


def test_disable_set_before_the_forced_on_ever_ran_also_sticks(tmp_path):
  # New device: the row shows during the first drive, before the boot-time forced On has seen the car.
  m = model(tmp_path)
  assert m.write(LONG, True) is True and (bp(tmp_path) / MARKER).exists()
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal="1")
  assert force(tmp_path, p) is False and merge(tmp_path, p) is False and p.vals[LONG] == "1"


def test_startup_runs_the_carry_over_after_the_forced_on():
  from openpilot.system.manager import bogpilot_startup as BS
  src = open(BS.__file__).read()
  i = src.index("force_ap1x_op_long_on_once(params, bogpilot_dir=directory)")
  j = src.index("merge_ap1x_long_into_disable(params, bogpilot_dir=directory)")
  assert i < j and 'f"ap1x-long-merge:{int(merged)}"' in src


def test_mark_helper_is_idempotent_and_never_raises(tmp_path):
  assert P.mark_ap1x_long_force_done(tmp_path / "new") is True
  assert P.mark_ap1x_long_force_done(tmp_path / "new") is True
  (tmp_path / "file").write_text("x")
  assert P.mark_ap1x_long_force_done(tmp_path / "file") is False


def test_carry_over_never_raises(tmp_path):
  (tmp_path / "file").write_text("x")
  assert P.merge_ap1x_long_into_disable(FakeParams(CarModel=X), bogpilot_dir=tmp_path / "file") is False


# ---- locks ----
def test_locks_follow_the_single_row(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / X_LONG)
  lock = menu_locks.long_lock(cp(X), disable_toggle_on=True)
  assert lock.code == "toggle_off" and lock.unlock_toggle == LONG
  assert menu_locks.long_lock(cp(X), disable_toggle_on=False) is menu_locks.RESTART
  assert menu_locks.long_lock(cp(X, long=True), disable_toggle_on=False) is None
  assert menu_locks.gas_brake_pill_visible(cp(X, long=True), disable_toggle_on=True) is False
