"""Pre-AP "Cruise didn't arm": openpilot enabled but the panda not armed -> a plain alert in 0.3 s, not controlsMismatch after 2 s."""
from types import SimpleNamespace

from opendbc.car.structs import car
from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import Alert, EVENTS, ET
from openpilot.selfdrive.selfdrived.preap_arm import NOT_ARMED_FRAMES, NOT_ARMED_SECONDS, PreapArmWatch

EventName = log.OnroadEvent.EventName
SafetyModel = car.CarParams.SafetyModel
IGNORED = (SafetyModel.silent, SafetyModel.noOutput)


def panda(allowed, model=SafetyModel.tesla):
  return SimpleNamespace(controlsAllowed=allowed, safetyModel=model)


def run(watch, frames, enabled=True, states=(), **kw):
  hit = False
  for _ in range(frames):
    hit = watch.update(enabled, list(states), IGNORED, **kw)
  return hit


def cp(name="TESLA_PREAP_MODELS"):
  return SimpleNamespace(carFingerprint=name)


def test_raised_after_0_3_seconds_not_before_and_well_before_the_2_second_mismatch():
  w = PreapArmWatch(cp())
  assert NOT_ARMED_SECONDS == 0.3 and NOT_ARMED_FRAMES == 30
  assert not run(w, NOT_ARMED_FRAMES - 1, states=[panda(False)])
  assert w.update(True, [panda(False)], IGNORED)
  assert NOT_ARMED_FRAMES < 200                      # selfdrived's controlsMismatch needs 200 frames (2 s)


def test_armed_panda_never_raises_and_a_late_arm_resets_the_count():
  w = PreapArmWatch(cp())
  assert not run(w, 500, states=[panda(True)])
  run(w, NOT_ARMED_FRAMES - 1, states=[panda(False)])
  assert not w.update(True, [panda(True)], IGNORED)    # the pull arrived just in time
  assert not run(w, NOT_ARMED_FRAMES - 1, states=[panda(False)])


def test_not_enabled_never_raises():
  w = PreapArmWatch(cp())
  assert not run(w, 500, enabled=False, states=[panda(False)])


def test_silent_pandas_are_ignored_like_the_mismatch_check():
  w = PreapArmWatch(cp())
  assert not run(w, 500, states=[panda(False, SafetyModel.silent), panda(False, SafetyModel.noOutput)])


def test_other_cars_keep_the_generic_two_second_behaviour():
  for name in ("TESLA_AP1_MODELS", "HONDA_CIVIC", ""):
    assert not run(PreapArmWatch(cp(name)), 500, states=[panda(False)]), name


def test_a_deliberately_unarmed_panda_never_raises():
  """The steer-through-brake latch keeps openpilot engaged with controls_allowed false on purpose (when that lane is merged it passes this)."""
  w = PreapArmWatch(cp())
  assert not run(w, 500, states=[panda(False)], dropped_on_purpose=True)
  assert w.count == 0


def test_alert_wording_is_plain_and_disengages():
  types = EVENTS[EventName.preapNotArmed]
  assert set(types) == {ET.USER_DISABLE}
  a = types[ET.USER_DISABLE]
  assert isinstance(a, Alert)
  assert (a.alert_text_1, a.alert_text_2) == ("Cruise didn't arm", "Pull the stalk again")
  for bad in ("panda", "controls", "mismatch", "safety", "allowed"):
    assert bad not in (a.alert_text_1 + a.alert_text_2).lower()
