"""AP1 Model X openpilot longitudinal: a ONE-TIME forced On (versioned marker AP1XOpenpilotLongForcedOn2) on a detected X, even
over a saved Off, and never again, so a later user Off (stock TACC) is respected. Version 2 runs again where version 1 already
ran. It also clears DisableOpenpilotLongitudinal on the X. No other car is touched."""
import pytest

from opendbc.car.tesla_ap1 import toggles
from openpilot.common import bogpilot_ap1_profile as P

X, S, PREAP = "TESLA_AP1_MODELX", "TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"


class FakeParams:
  def __init__(self, **vals):
    self.vals = {k: v for k, v in vals.items() if v is not None}

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value, block=False):
    self.vals[key] = value

  def invalidate(self):
    pass


def run(p, d):
  return P.force_ap1x_op_long_on_once(p, bogpilot_dir=d)


def test_marker_name_is_versioned():
  assert P.AP1X_LONG_FORCE_MARKER_NAME == "AP1XOpenpilotLongForcedOn2"
  assert "AP1XOpenpilotLongForcedOn1" in P.AP1X_LONG_FORCE_MARKER_HISTORY


def test_saved_off_is_forced_on_once_then_user_off_respected(tmp_path):
  (tmp_path / "AP1XOpenpilotLong").write_text("0")
  assert run(FakeParams(CarModel=X), tmp_path) is True
  assert (tmp_path / "AP1XOpenpilotLong").read_text() == "1"
  assert (tmp_path / P.AP1X_LONG_FORCE_MARKER_NAME).exists()
  assert toggles.ap1x_op_long(X, stored=(tmp_path / "AP1XOpenpilotLong").read_text()) is True
  (tmp_path / "AP1XOpenpilotLong").write_text("0")              # the user turns it off again later
  for _ in range(3):
    assert run(FakeParams(CarModel=X), tmp_path) is False       # never again
  assert (tmp_path / "AP1XOpenpilotLong").read_text() == "0"


def test_missing_file_written_on(tmp_path):
  assert run(FakeParams(CarModel=X), tmp_path) is True
  assert (tmp_path / "AP1XOpenpilotLong").read_text() == "1"


def test_already_on_only_marks(tmp_path):
  (tmp_path / "AP1XOpenpilotLong").write_text("1")
  assert run(FakeParams(CarModel=X), tmp_path) is False
  assert (tmp_path / P.AP1X_LONG_FORCE_MARKER_NAME).exists()


@pytest.mark.parametrize("car", [S, PREAP, "TESLA_MODEL_Y", None])
def test_other_cars_untouched_and_no_marker(tmp_path, car):
  (tmp_path / "AP1XOpenpilotLong").write_text("0")
  assert run(FakeParams(CarModel=car), tmp_path) is False
  assert (tmp_path / "AP1XOpenpilotLong").read_text() == "0"
  assert not (tmp_path / P.AP1X_LONG_FORCE_MARKER_NAME).exists()   # an X detected on a later start still gets it once


def test_unknown_car_waits_for_detection(tmp_path):
  (tmp_path / "AP1XOpenpilotLong").write_text("0")
  assert run(FakeParams(), tmp_path) is False and not (tmp_path / P.AP1X_LONG_FORCE_MARKER_NAME).exists()
  assert run(FakeParams(CarModel=X), tmp_path) is True and (tmp_path / "AP1XOpenpilotLong").read_text() == "1"


def test_never_raises(tmp_path):
  blocker = tmp_path / "file"
  blocker.write_text("x")
  assert run(FakeParams(CarModel=X), blocker / "sub") is False


def test_startup_hook_runs_it():
  from openpilot.system.manager import bogpilot_startup as BS
  src = open(BS.__file__).read()
  assert "force_ap1x_op_long_on_once(params, bogpilot_dir=directory)" in src and 'f"ap1x-long-on:{int(forced)}"' in src


def test_default_on_registry():
  from openpilot.common import bogpilot_toggles
  assert toggles.AP1X_OP_LONG_DEFAULT is True
  assert bogpilot_toggles.FILE_TOGGLES["AP1XOpenpilotLong"][0] is bogpilot_toggles.CAR_DEPENDENT   # car code owns the default
  for unset in ("", "garbage"):
    assert toggles.ap1x_op_long(X, stored=unset) is True
  for off in ("0", "false", "off"):
    assert toggles.ap1x_op_long(X, stored=off) is False
  for car in (S, PREAP, "TESLA_MODEL_Y", None):
    assert toggles.ap1x_op_long(car, stored="1") is False


def test_version1_marker_still_forced_by_version2(tmp_path):
  (tmp_path / "AP1XOpenpilotLongForcedOn1").write_text("1\n")     # build 7 already ran version 1
  (tmp_path / "AP1XOpenpilotLong").write_text("0")                 # then the user turned it off
  assert run(FakeParams(CarModel=X), tmp_path) is True
  assert (tmp_path / "AP1XOpenpilotLong").read_text() == "1"
  assert (tmp_path / "AP1XOpenpilotLongForcedOn2").exists()


def test_fingerprint_without_carmodel(tmp_path, monkeypatch):
  monkeypatch.setattr(P, "_persistent_fingerprint", lambda params: X)
  (tmp_path / "AP1XOpenpilotLong").write_text("0")
  assert run(FakeParams(), tmp_path) is True
  assert (tmp_path / "AP1XOpenpilotLong").read_text() == "1"


@pytest.mark.parametrize("stored", ["1", "true", "on", b"1"])
def test_disable_long_cleared_on_x(tmp_path, stored):
  (tmp_path / "AP1XOpenpilotLong").write_text("1")
  (tmp_path / "DisableOpenpilotLongitudinal").write_text("1")
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal=stored)
  assert run(p, tmp_path) is True
  assert (tmp_path / "DisableOpenpilotLongitudinal").read_text() == "0"
  assert p.vals["DisableOpenpilotLongitudinal"] == "0"
  assert toggles.disable_openpilot_long(paths=(tmp_path / "DisableOpenpilotLongitudinal",)) is False


def test_disable_long_off_or_unset_left_alone(tmp_path):
  (tmp_path / "AP1XOpenpilotLong").write_text("1")
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal="0")
  assert run(p, tmp_path) is False
  assert not (tmp_path / "DisableOpenpilotLongitudinal").exists()
  assert p.vals["DisableOpenpilotLongitudinal"] == "0"
  p2 = FakeParams(CarModel=X)
  (tmp_path / P.AP1X_LONG_FORCE_MARKER_NAME).unlink()
  assert run(p2, tmp_path) is False and "DisableOpenpilotLongitudinal" not in p2.vals


@pytest.mark.parametrize("car", [S, PREAP])
def test_disable_long_untouched_on_other_cars(tmp_path, car):
  (tmp_path / "DisableOpenpilotLongitudinal").write_text("1")
  p = FakeParams(CarModel=car, DisableOpenpilotLongitudinal="1")
  assert run(p, tmp_path) is False
  assert (tmp_path / "DisableOpenpilotLongitudinal").read_text() == "1"
  assert p.vals["DisableOpenpilotLongitudinal"] == "1"
  assert not (tmp_path / P.AP1X_LONG_FORCE_MARKER_NAME).exists()


def test_idempotent_including_disable_long(tmp_path):
  (tmp_path / "AP1XOpenpilotLong").write_text("0")
  p = FakeParams(CarModel=X, DisableOpenpilotLongitudinal="1")
  assert run(p, tmp_path) is True
  (tmp_path / "AP1XOpenpilotLong").write_text("0")                 # a deliberate Off after the migration
  p.vals["DisableOpenpilotLongitudinal"] = "1"
  for _ in range(3):
    assert run(p, tmp_path) is False
  assert (tmp_path / "AP1XOpenpilotLong").read_text() == "0" and p.vals["DisableOpenpilotLongitudinal"] == "1"


def test_interface_reads_forced_value(tmp_path, monkeypatch):
  (tmp_path / "AP1XOpenpilotLong").write_text("0")
  assert run(FakeParams(CarModel=X), tmp_path) is True
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  assert toggles.ap1x_op_long(X) is True
  assert toggles.ap1x_op_long(S) is False
