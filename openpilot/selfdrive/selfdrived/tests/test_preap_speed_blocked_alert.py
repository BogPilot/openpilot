"""Pre-AP "Speed control off" warning: with a heard but uncalibrated Comma Pedal it says to calibrate, not to retry."""
from openpilot.cereal import log
from opendbc.car.structs import car
from openpilot.selfdrive.selfdrived.events import EVENTS, ET

EventName = log.OnroadEvent.EventName


def _alert(detected, calibrated):
  CS = car.CarState.new_message()
  CS.bogpilot.preapPedalDetected = detected
  CS.bogpilot.preapPedalCalibrated = calibrated
  cb = EVENTS[EventName.preapSpeedBlocked][ET.WARNING]
  return cb(car.CarParams.new_message(), CS, None, False, 0, 0)


def test_uncalibrated_pedal_says_calibrate():
  a = _alert(True, False)
  assert a.alert_text_1 == "Speed control off"
  assert "Calibrate the pedal" in a.alert_text_2


def test_calibrated_pedal_keeps_the_retry_text():
  a = _alert(True, True)
  assert a.alert_text_1 == "Speed control off"
  assert a.alert_text_2 == "Steering only. Double pull to retry"
