"""AP1 Model X planner side of single-pull Speed Limit Control: the SLC consumer and the AP1 stalk set authority run on the X
exactly when openpilot longitudinal is on, as on the Model S, and never with stock TACC."""
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.controls.lib.phase3_speed_control import SLC_PLATFORMS, Ap1SpeedControl, slc_supported

X, S = "TESLA_AP1_MODELX", "TESLA_AP1_MODELS"


def _cp(fp, long):
  return SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=long, pcmCruise=True, radarUnavailable=False,
                         enableBsm=False)


@pytest.mark.parametrize("fp", [X, S])
def test_slc_runs_with_openpilot_long(fp):
  assert fp in SLC_PLATFORMS
  assert slc_supported(_cp(fp, True)) is True
  ctl = Ap1SpeedControl(_cp(fp, True), toggles_fn=lambda: None, adopted=True)
  assert ctl.ap1 is True and ctl._ap1_op_long is True and ctl._cluster_lifted is True


@pytest.mark.parametrize("fp", [X, S])
def test_slc_off_without_openpilot_long(fp):
  assert slc_supported(_cp(fp, False)) is False
  ctl = Ap1SpeedControl(_cp(fp, False), toggles_fn=lambda: None, adopted=True)
  assert ctl.ap1 is False and ctl._ap1_op_long is False
