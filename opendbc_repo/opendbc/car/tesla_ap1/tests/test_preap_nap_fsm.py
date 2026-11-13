"""NAP research cases for the Pre-AP pull FSM (NAP preap/engagement.py @ e99f4dc75, plan section 5 table) not covered elsewhere.
Covered in other files: 1 (test_preap_pedal_guard, test_preap_full_demote), 3/4 brake (test_preap_full_demote), 6 hands-on
(test_preap_nap_fsm_handson), 10/11 no pedal (test_preap_nopedal_cancel), 13 cancel-only spoofer (test_preap_nopedal_cancel).
Panda (libsafety) cases need the safety build and are not run here."""
import inspect

import pytest

from opendbc.car.tesla_ap1.preap import carstate as cs_mod
from opendbc.car.tesla_ap1.preap.cruise import CANCEL_ECHO_WINDOW_MS, SPOOF_ECHO_WINDOW_MS, is_preap_cancel_echo
from opendbc.car.tesla_ap1.preap.engagement import WINDOW_MS, Mode, PreAPEngagement
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import CANCEL, PULL, Rig, _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_engagement import full, step
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import Drive


# 2: strict `<` window (NAP engagement.py:131)
@pytest.mark.parametrize("dt,want", [(250, Mode.FULL), (WINDOW_MS - 1, Mode.FULL), (WINDOW_MS, Mode.LAT_PENDING), (WINDOW_MS + 1, Mode.LAT_PENDING)])
def test_window_boundaries(dt, want):
  e = PreAPEngagement()
  step(e, 0, pull=True)
  assert step(e, dt, pull=True, op=True).mode == want


# 4: after a brake, one pull is not enough; a double pull brings speed control back
def test_resume_after_brake_needs_a_double_pull():
  e = PreAPEngagement()
  full(e)
  step(e, 1000, op=True, brake=True)
  step(e, 1100, op=True)
  assert step(e, 2000, pull=True, op=True).mode == Mode.LAT_PENDING
  assert step(e, 3000, op=True).mode == Mode.LAT_ONLY
  step(e, 4000, pull=True, op=True)
  assert step(e, 4200, pull=True, op=True).mode == Mode.FULL


# 5: the accelerator never changes the mode (NAP passes the foot through, carcontroller.py:97-100)
def test_gas_no_state_change():
  e = PreAPEngagement()
  full(e)
  assert step(e, 1000, op=True, gas=True).mode == Mode.FULL
  e = PreAPEngagement()
  step(e, 0, pull=True)
  step(e, 1000, op=True)
  assert step(e, 1100, op=True, gas=True).mode == Mode.LAT_ONLY


# 7: leaving D ends the session; a re-pull in D starts a new one (steering only)
def test_gear_drop_then_repull():
  e = PreAPEngagement()
  full(e)
  assert step(e, 1000, op=True, gear_d=False).mode == Mode.OFF
  assert step(e, 1100, pull=True, gear_d=False).mode == Mode.OFF, "a pull out of D is ignored"
  assert step(e, 1500, pull=True).mode == Mode.LAT_PENDING


# 8: a door ends the session; a pull with a door open is ignored
def test_door_open_resets_and_pull_with_door_open_ignored():
  e = PreAPEngagement()
  full(e)
  assert step(e, 1000, op=True, door_open=True).mode == Mode.OFF
  assert step(e, 1100, pull=True, door_open=True).mode == Mode.OFF


# 9: our CANCEL echo within 600 ms of our own pull is ignored, a cancel after that is honoured (pedal mode, preap/cruise.py)
def test_cancel_echo_ignored_then_honoured():
  d = Drive(pedal=True)
  d.step(op=False)
  d.step(stalk=PULL, op=False)
  d.step()
  d.step(stalk=CANCEL)
  assert d.rig.cs.preap_fsm_mode != int(Mode.OFF), "cancel right after our pull is the echo"
  for _ in range(70):
    d.step()
  d.step(stalk=CANCEL)
  assert d.rig.cs.preap_fsm_mode == int(Mode.OFF)


def test_fail_closed_unknown_inputs():
  e = PreAPEngagement()
  assert step(e, 0, pull=True, gear_d=None).mode == Mode.OFF
  assert step(e, 100, pull=True, door_open=None).mode == Mode.OFF
  e = PreAPEngagement()
  step(e, 0, pull=True)
  assert step(e, 200, pull=True, op=True, long_allowed=None).mode == Mode.LAT_ONLY


def test_window_uses_monotonic_clock():
  assert "time.monotonic()" in inspect.getsource(cs_mod.PreApCarState.update)

# SpdCtrlLvr_Stat = 4 is an accel tip (values.py BUTTONS); a tip must not open the 600 ms cancel-echo window.
TIP = 4


def test_cancel_echo_window_follows_the_last_pull_not_a_tip():
  # tesla_preap.h:114-120: a cancel is real when more than 600 ms have passed since the last pull.
  assert is_preap_cancel_echo(now_ms=1000, last_pull_ms=0, last_cc_spoof_ms=0, cruise_enabled=True) is False
  assert is_preap_cancel_echo(now_ms=1000 + 200, last_pull_ms=1000, last_cc_spoof_ms=0, cruise_enabled=True) is True
  assert is_preap_cancel_echo(now_ms=1000 + CANCEL_ECHO_WINDOW_MS, last_pull_ms=1000, last_cc_spoof_ms=0, cruise_enabled=True) is True
  assert is_preap_cancel_echo(now_ms=1000 + CANCEL_ECHO_WINDOW_MS + 1, last_pull_ms=1000, last_cc_spoof_ms=0, cruise_enabled=True) is False
  # our own spoof frame: an echo only inside the pull window (300 ms after the frame); outside it the panda drops controls
  assert is_preap_cancel_echo(now_ms=1150 + SPOOF_ECHO_WINDOW_MS - 1, last_pull_ms=1000, last_cc_spoof_ms=1150) is True
  assert is_preap_cancel_echo(now_ms=1150 + SPOOF_ECHO_WINDOW_MS, last_pull_ms=1000, last_cc_spoof_ms=1150) is False
  assert is_preap_cancel_echo(now_ms=2000 + SPOOF_ECHO_WINDOW_MS - 1, last_pull_ms=1000, last_cc_spoof_ms=2000, cruise_enabled=True) is False


def test_cancel_shortly_after_an_up_tip_is_real():
  r = Rig()
  r.frame()
  r.frame(stalk=PULL)
  r.frame(op=True)
  r.wait(700)                                 # past the 600 ms pull-echo window
  out = r.frame(stalk=TIP, op=True)
  assert out.cruiseState.enabled
  r.wait(200)
  out = r.frame(stalk=CANCEL, op=True)
  assert not out.cruiseState.enabled          # a tip must not swallow a later cancel

