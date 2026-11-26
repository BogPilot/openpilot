"""The "Offset Set Speed by:" row (SetSpeedOffset) is hidden on every car type; its key and default stay."""
from types import SimpleNamespace as NS

import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import FakeStore
from openpilot.selfdrive.ui.bogpilot.bogpilot_defaults import DEFAULT_ROWS
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss

CARS = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS", "TESLA_MODEL_3", None)


def cp(car, pcm):
  return NS(carFingerprint=car or "", openpilotLongitudinalControl=True, pcmCruise=pcm, radarUnavailable=False,
            enableBsm=True)


@pytest.mark.parametrize("car", CARS)
@pytest.mark.parametrize("pcm", [True, False])
@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_row_is_hidden_for_every_car_type(car, pcm, level):
  vals = dict(SpeedLimitController="1", Phase3SpeedLimitEnabled="1", SetSpeedOffset="7")
  if car is not None:
    vals["CarModel"] = car
  store = FakeStore(**vals)
  store.tuning_level = lambda: level
  for panel in (None, *ss.SUB_PANELS):
    assert "SetSpeedOffset" not in [r[0] for r in ss.visible_rows(store, panel, cp(car, pcm))]
  assert "SetSpeedOffset" not in ss.BY_KEY


def test_row_is_not_built_and_the_reason_is_recorded():
  assert "SetSpeedOffset" not in [r[0] for r in ss.ROWS]
  assert "SetSpeedOffset" in ss.OMITTED and "every car type" in ss.OMITTED["SetSpeedOffset"]


def test_param_key_and_default_are_kept():
  assert BOGPILOT_PARAMS["SetSpeedOffset"][2] == "0"
  assert [r for r in DEFAULT_ROWS if r[0] == "SetSpeedOffset"] == [("SetSpeedOffset", "0", 2, "0")]
