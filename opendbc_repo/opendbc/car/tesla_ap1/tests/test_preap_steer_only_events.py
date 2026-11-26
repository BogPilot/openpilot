"""Pre-AP pull FSM event names from Ap1Events: steering-only banner, speed blocked (pedal), stock cruise not armed (no pedal)."""
from types import SimpleNamespace

from opendbc.car.tesla_ap1.ap1_events import PREAP_CC_NOT_ARMED, PREAP_SPEED_BLOCKED, PREAP_STEER_ONLY, Ap1Events


def _bp(**kw):
  base = dict(ap1DriverYield=False, ap1HandsOnLevel=0, ap1EacInhibited=False, preapLatOnly=False, preapSpeedBlocked=False,
              preapPedalDetected=True, preapPedalNotResponding=False, preapPedalUnavailable=False)
  base.update(kw)
  return SimpleNamespace(**base)


def _names(enabled=True, **kw):
  return Ap1Events().update([], enabled, enabled, _bp(**kw))


def test_steering_only_banner_only_while_engaged_steering_only():
  assert PREAP_STEER_ONLY in _names(preapLatOnly=True)
  assert PREAP_STEER_ONLY not in _names(preapLatOnly=False)
  assert PREAP_STEER_ONLY not in _names(enabled=False, preapLatOnly=True)


def test_speed_blocked_pedal_vs_cruise_not_armed_no_pedal():
  n = _names(preapLatOnly=True, preapSpeedBlocked=True, preapPedalDetected=True)
  assert PREAP_SPEED_BLOCKED in n and PREAP_STEER_ONLY not in n
  n = _names(preapLatOnly=True, preapSpeedBlocked=True, preapPedalDetected=False)
  assert PREAP_CC_NOT_ARMED in n and PREAP_SPEED_BLOCKED not in n
