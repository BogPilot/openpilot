"""Regression: a Pre-AP car with the Comma Pedal heard but not calibrated could not engage at all.

On c31952e67 (pedal long on, pedal detected, PedalCalibDone not set): every stalk pull asked openpilot to engage
(buttonEnable) but cruiseState.available stayed False, so selfdrived answered with wrongCarMode, "openpilot Unavailable /
Enable Adaptive Cruise to Engage", and the pull FSM reset 1.5 s later (ENABLE_TIMEOUT_MS). Five pulls, zero engagements.

The fix: a heard pedal makes cruise available whether or not it is calibrated, so a pull engages STEERING ONLY. Speed control
still needs a calibrated pedal (the pull FSM's long_allowed, the CarController's pedal_long_allowed and the panda are unchanged):
a double pull or a tip with an uncalibrated pedal stays steering only, never sends pedal ENABLE=1, and raises the Speed
control off warning (preapSpeedBlocked) whose text says to calibrate the pedal.
"""
from opendbc.car.tesla_ap1.preap import calib, params
from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (  # noqa: F401  (fixture re-export)
  PULL, Rig, _drive, _params_dir,
)
from opendbc.car.tesla_ap1.values import CAR, DBC


def _uncal_rig():
  params.set_bool(params.PreApParamKeys.DOUBLE_PULL, False)
  assert not calib.is_pedal_calibrated()
  rig = Rig()
  return rig, PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], rig.CP)


def test_uncalibrated_heard_pedal_single_pull_engages_steering_only():
  rig, ctl = _uncal_rig()
  enabled, outs = _drive(rig, ctl, 0, 300, pulls={20})
  op, long_active, out = outs[-1]
  assert out.bogpilot.preapPedalDetected and not out.bogpilot.preapPedalCalibrated
  assert out.cruiseState.available, "a heard pedal must not block the steering engage"
  assert op and not long_active, "engaged, steering only"
  assert out.bogpilot.preapLatOnly
  assert enabled == 0, "the pedal is never enabled while uncalibrated"
  assert getattr(rig, "lat_frames", 0) > 50


def test_uncalibrated_double_pull_stays_steering_only_and_says_why():
  rig, ctl = _uncal_rig()
  enabled, outs = _drive(rig, ctl, 0, 300, pulls={20, 45})
  op, long_active, out = outs[-1]
  assert op and not long_active
  assert out.bogpilot.preapFsmMode == int(Mode.LAT_ONLY)
  assert out.bogpilot.preapSpeedBlocked, "the refused double pull is reported (Speed control off / calibrate)"
  assert enabled == 0


def test_uncalibrated_repeated_pulls_never_time_out_like_the_log():
  # the logged pattern: pulls ~4 s apart. Each one used to end in a 1.5 s FSM reset with no engagement.
  rig, ctl = _uncal_rig()
  enabled, outs = _drive(rig, ctl, 0, 1600, pulls={20, 450, 820, 1170})
  assert all(o[0] for o in outs[30:]), "engaged from the first pull and stays engaged (a re-pull only re-opens the window)"
  assert enabled == 0


def test_calibration_later_makes_the_next_double_pull_full():
  rig, ctl = _uncal_rig()
  _drive(rig, ctl, 0, 100, pulls={20, 45})
  calib.apply_calibration_result(calib.compute_calibration(0.8, 107.0))
  enabled, outs = _drive(rig, ctl, 0, 300, pulls={20, 45}, idx0=100)
  op, long_active, out = outs[-1]
  assert op and long_active and not out.bogpilot.preapSpeedBlocked
  assert enabled > 20


def test_pedal_not_heard_still_blocks_cruise_available():
  # unchanged on purpose: no pedal frames at all in pedal-long mode is still "cruise unavailable"
  rig = Rig()
  out = None
  for _ in range(50):
    out = rig.frame()
  assert not out.bogpilot.preapPedalDetected
  assert not out.cruiseState.available
