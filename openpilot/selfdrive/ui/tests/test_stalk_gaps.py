"""Native tests for stalk port gaps 2, 3 and 5. No car, sockets or install."""
from types import SimpleNamespace as NS

from opendbc.car.tesla_ap1.phase3_stalk_controls import (
  AP1, apply_experimental_toggle, cem_is_on, cem_stalk_override, experimental_hold_unconfirmed,
  twist_follow_on,
)
from opendbc.car.tesla_ap1.stalk_follow import parse_stalk_raw
from openpilot.selfdrive.controls.lib.phase3_following import Ap1PersonalitySync
from openpilot.selfdrive.controls.lib.phase3_long_accel import CEM_ACK, ConditionalMode, LongAccelPort
from openpilot.selfdrive.selfdrived.events import EVENTS, ET
from openpilot.cereal import log

EventName = log.OnroadEvent.EventName


def cp():
  return NS(carFingerprint=AP1, dashcamOnly=False, passive=False, openpilotLongitudinalControl=True)


def cs(pull=True, fwd=False, can_valid=True, twist=True):
  return NS(
    canValid=can_valid,
    bogpilot=NS(ap1StalkPullToggle=pull, ap1StalkFwdToggle=fwd),
    stalk_controls=NS(settings=NS(twist_follow=twist)),
  )


class Params:
  def __init__(self, **data):
    self.data = dict(data)
    self.puts = []

  def get_bool(self, key, block=False):
    return bool(self.data.get(key, False))

  def get(self, key, block=False, return_default=False):
    return self.data.get(key)

  def put(self, key, value, block=False):
    self.data[key] = value
    self.puts.append((key, value, block))

  def put_bool(self, key, value, block=False):
    self.data[key] = bool(value)
    self.puts.append((key, bool(value), block))


def test_cem_override_formula_matches_097():
  assert cem_stalk_override(0) == 2
  assert cem_stalk_override(2) == 0
  assert cem_stalk_override(1) == 0
  assert cem_stalk_override(3) == 1
  assert cem_stalk_override(13) == 1
  assert cem_stalk_override(None) == 2
  assert cem_stalk_override("4") == 1


def test_cem_is_on_requires_toggle_and_adoption():
  assert not cem_is_on(Params())
  assert not cem_is_on(Params(ConditionalExperimental=True))
  assert not cem_is_on(Params(Phase3CEMEnabled=True))
  assert cem_is_on(Params(ConditionalExperimental=True, Phase3CEMEnabled=True))


def test_hold_with_cem_on_flips_cestatus_not_experimental_mode():
  p = Params(ExperimentalMode=False, ExperimentalModeConfirmed=True,
             ConditionalExperimental=True, Phase3CEMEnabled=True, CEStatus=0)
  assert apply_experimental_toggle(p, cp(), cs(), True) is None
  assert p.data["ExperimentalMode"] is False
  assert p.data["CEStatus"] == 2
  assert p.puts == [("CEStatus", 2, True)]
  assert apply_experimental_toggle(p, cp(), cs(), True) is None
  assert p.data["CEStatus"] == 0
  p.data["CEStatus"] = 4
  assert apply_experimental_toggle(p, cp(), cs(), True) is None
  assert p.data["CEStatus"] == 1
  assert p.data["ExperimentalMode"] is False


def test_hold_with_cem_off_still_toggles_experimental_mode():
  p = Params(ExperimentalMode=False, ExperimentalModeConfirmed=True,
             ConditionalExperimental=True, Phase3CEMEnabled=False)
  assert apply_experimental_toggle(p, cp(), cs(), True) is True
  assert p.data["ExperimentalMode"] is True
  assert all(k != "CEStatus" for k, *_ in p.puts)


def test_unconfirmed_hold_is_rejected_and_flagged():
  p = Params(ExperimentalMode=False, ExperimentalModeConfirmed=False)
  car, state = cp(), cs()
  assert apply_experimental_toggle(p, car, state, True) is None
  assert p.puts == []
  assert experimental_hold_unconfirmed(p, car, state, True)
  assert not experimental_hold_unconfirmed(Params(ExperimentalModeConfirmed=True), car, state, True)
  assert not experimental_hold_unconfirmed(p, car, state, False)
  assert not experimental_hold_unconfirmed(p, car, cs(pull=False, fwd=False), True)
  assert not experimental_hold_unconfirmed(p, car, cs(can_valid=False), True)
  car.openpilotLongitudinalControl = False
  assert not experimental_hold_unconfirmed(p, car, state, True)


def test_unconfirmed_alert_is_brief_and_names_settings():
  assert EventName.experimentalModeUnconfirmed in EVENTS
  alert = EVENTS[EventName.experimentalModeUnconfirmed][ET.PERMANENT]
  text = (alert.alert_text_1 + " " + alert.alert_text_2).lower()
  assert "experimental mode" in text and "settings" in text
  assert alert.duration >= 1.0
  assert alert.audible_alert == log.SelfdriveState.AudibleAlert.none


def test_publish_status_keeps_manual_cem_override():
  store = Params(**{CEM_ACK: True})
  port = LongAccelPort.__new__(LongAccelPort)
  port.store = store
  port.cem = ConditionalMode()
  port._published_status = None
  port.cem.status, port.cem.experimental = 1, False
  port.publish_status()
  assert store.data["CEStatus"] == 1
  port.cem.status, port.cem.experimental = 2, True
  port.publish_status()
  assert store.data["CEStatus"] == 2
  port.cem.status, port.cem.experimental = 4, False
  port.publish_status()
  assert store.data["CEStatus"] == 0


def test_twist_follow_off_does_not_write_personality():
  assert twist_follow_on(cs(twist=True))
  assert not twist_follow_on(cs(twist=False))
  assert twist_follow_on(NS())  # missing store: default on

  class Recorder(Params):
    def put(self, key, value, block=False):
      self.data[key] = value
      self.puts.append((key, value))

  decision = parse_stalk_raw(66, None)  # detent 3, aggressive
  off_params = Recorder(LongitudinalPersonality=1)
  # card skips Ap1PersonalitySync.update when twist following is off
  if twist_follow_on(cs(twist=False)):
    raise AssertionError("twist_follow off must skip the personality write")
  assert off_params.puts == []
  assert off_params.data["LongitudinalPersonality"] == 1

  on_params = Recorder(LongitudinalPersonality=1)
  assert Ap1PersonalitySync(on_params).update(decision) is False
  assert on_params.puts == [("LongitudinalPersonality", 0)]
