"""AP1 Model X openpilot longitudinal: a ONE-TIME forced On (versioned marker AP1XOpenpilotLongForcedOn1) on a detected X, even
over a saved Off, and never again, so a later user Off (stock TACC) is respected. No other car is touched."""
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
  assert P.AP1X_LONG_FORCE_MARKER_NAME == "AP1XOpenpilotLongForcedOn1"


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
