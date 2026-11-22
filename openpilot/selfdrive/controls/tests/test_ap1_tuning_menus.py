"""AP1 / Pre-AP tuning menus show the real per-car starting values and the edits reach the consumers.

Real CarParams for each Tesla (opendbc get_non_essential_params), the real Advanced Longitudinal panel (raylib action callbacks ->
ParamStore -> planner / advanced_values) and the help text, so a menu can never quote a number the car code does not use.
Native AGNOS display context, like test_phase3_long_accel_settings.py.
"""
import pytest

from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.values import (CAR, AP1_LONG_ACTUATOR_DELAY, PREAP_LONG_ACTUATOR_DELAY, AP1_S_STEER_ACTUATOR_DELAY,
                                          AP1_X_STEER_ACTUATOR_DELAY, PREAP_STEER_ACTUATOR_DELAY)
from openpilot.common.bogpilot_ap1_profile import AP1_PARAM_PROFILE
from openpilot.selfdrive.controls.lib.phase3_long_accel import ADVANCED_ACK, advanced_values
from openpilot.selfdrive.controls.lib.phase3_steering_tuning import numeric_rows
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import planner, SM, msgs
from openpilot.selfdrive.controls.tests.test_phase3_long_accel_settings import window, store, press, toggle  # noqa: F401
from openpilot.selfdrive.ui.bogpilot import tesla_start_values as tsv
from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import AdvancedLongitudinalSettings, STOCK_DISPLAY

DT_MDL = 0.05
CARS = {
  "TESLA_AP1_MODELS": dict(delay=AP1_LONG_ACTUATOR_DELAY, steer_delay=AP1_S_STEER_ACTUATOR_DELAY, steer_ratio=15.0, decel="Eco+"),
  "TESLA_AP1_MODELX": dict(delay=AP1_LONG_ACTUATOR_DELAY, steer_delay=AP1_X_STEER_ACTUATOR_DELAY, steer_ratio=16.8, decel="Eco"),
  "TESLA_PREAP_MODELS": dict(delay=PREAP_LONG_ACTUATOR_DELAY, steer_delay=PREAP_STEER_ACTUATOR_DELAY, steer_ratio=15.0, decel="Eco"),
}


def cp_for(name, long=True):
  cp = CarInterface.get_non_essential_params(name)
  cp.openpilotLongitudinalControl = long
  return cp


def test_the_delays_are_the_agreed_values():
  assert (AP1_LONG_ACTUATOR_DELAY, PREAP_LONG_ACTUATOR_DELAY) == (0.35, 0.4)
  assert cp_for("TESLA_AP1_MODELS").longitudinalActuatorDelay == pytest.approx(0.35)
  assert cp_for("TESLA_AP1_MODELX").longitudinalActuatorDelay == pytest.approx(0.35)
  assert cp_for("TESLA_PREAP_MODELS").longitudinalActuatorDelay == pytest.approx(0.4)


@pytest.mark.parametrize("name", CARS)
def test_start_values_equal_what_the_car_reports(name):
  want = CARS[name]
  cp = cp_for(name)
  assert str(cp.carFingerprint) == name
  assert cp.longitudinalActuatorDelay == pytest.approx(want["delay"])
  assert cp.stopAccel == pytest.approx(tsv.STOCK_STOP_ACCEL)
  assert STOCK_DISPLAY["StopAccel"](cp, None) == pytest.approx(-2.0)
  assert STOCK_DISPLAY["StoppingDecelRate"](cp, None) == pytest.approx(tsv.STOCK_STOPPING_RATE)
  rows = {r.key: r for r in numeric_rows(cp)}
  assert rows["SteerDelay"].default == pytest.approx(round(want["steer_delay"] + 0.2, 2))
  assert rows["SteerRatio"].default == pytest.approx(want["steer_ratio"])
  assert f"{rows['SteerDelay'].default:.2f} s" in tsv.start_text("SteerDelay", cp.carFingerprint)
  assert f"{rows['SteerRatio'].default:.1f}" in tsv.start_text("SteerRatio", cp.carFingerprint)
  assert f"{cp.longitudinalActuatorDelay:.2f} s" in tsv.start_text("LongitudinalActuatorDelay", cp.carFingerprint)
  assert want["decel"] in tsv.start_text("DecelerationProfile", cp.carFingerprint)
  assert "Sport" in tsv.start_text("AccelerationProfile", cp.carFingerprint)


def test_model_s_profile_decel_is_what_the_ap1_profile_writes():
  assert tsv.PROFILE_NAMES["DecelerationProfile"][int(AP1_PARAM_PROFILE["DecelerationProfile"])] == "Eco+"
  assert tsv.PROFILE_NAMES["AccelerationProfile"][int(AP1_PARAM_PROFILE["AccelerationProfile"])] == "Sport"


def test_pre_ap_max_accel_text_names_the_pedal_limit():
  assert "2.5 m/s^2" in tsv.start_text("MaxDesiredAcceleration", "TESLA_PREAP_MODELS")
  assert "2.5" not in tsv.start_text("MaxDesiredAcceleration", "TESLA_AP1_MODELS")


def test_unknown_car_lists_all_three_and_other_keys_say_nothing():
  text = tsv.start_text("LongitudinalActuatorDelay", None)
  assert "AP1 Model S 0.35 s" in text and "AP1 Model X 0.35 s" in text and "Pre-AP Model S 0.40 s" in text
  assert tsv.start_text("CESpeed", "TESLA_AP1_MODELS") == ""
  for key in ("LongitudinalActuatorDelay", "SteerDelay", "SteerRatio", "StopAccel", "StoppingDecelRate", "MaxDesiredAcceleration",
              "AccelerationProfile", "DecelerationProfile"):
    for car in (None, *CARS):
      assert tsv.start_text(key, car).isascii()


def test_static_help_names_each_cars_value_and_matches_the_code_constants():
  assert "0.35 s" in HELP["LongitudinalActuatorDelay"].default and "0.4 s" in HELP["LongitudinalActuatorDelay"].default
  assert f"{AP1_LONG_ACTUATOR_DELAY:g} s" in HELP["LongitudinalActuatorDelay"].default
  assert f"{PREAP_LONG_ACTUATOR_DELAY:g} s" in HELP["LongitudinalActuatorDelay"].default
  assert "-2.0 m/s^2" in HELP["StopAccel"].default and "1.0 m/s^3" in HELP["StoppingDecelRate"].default
  assert "2.5 m/s^2" in HELP["MaxDesiredAcceleration"].note and "4.0 m/s^2" in HELP["MaxDesiredAcceleration"].default
  assert "Sport" in HELP["AccelerationProfile"].default
  assert "Eco+ on the AP1 Model S" in HELP["DecelerationProfile"].default and "Eco on the AP1 Model X" in HELP["DecelerationProfile"].default
  for car, want in CARS.items():
    assert f"{round(want['steer_delay'] + 0.2, 2):.2f} s" in HELP["SteerDelay"].default
    assert f"{want['steer_ratio']:.1f}" in HELP["SteerRatio"].default
  for key in ("LongitudinalActuatorDelay", "StopAccel", "StoppingDecelRate", "MaxDesiredAcceleration", "AccelerationProfile",
              "DecelerationProfile", "SteerDelay", "SteerRatio"):
    entry = HELP[key]
    assert (entry.what + entry.note + entry.default).isascii()
    assert "car's own value" not in entry.default   # no stock-generic wording for the default any more


@pytest.mark.parametrize("name", CARS)
def test_untouched_row_shows_the_real_delay_and_edits_start_from_it(store, name):
  cp = cp_for(name)
  delay = CARS[name]["delay"]
  panel = AdvancedLongitudinalSettings(store, cp=cp)
  toggle(panel, "AdvancedLongitudinalTune")                     # enabling the section writes nothing for the delay
  assert store.raw("LongitudinalActuatorDelay") in (None, "")
  c = panel.controller
  assert c.display_value("LongitudinalActuatorDelay") == pytest.approx(delay)
  assert c.value_text("LongitudinalActuatorDelay") == f"{delay:.2f} seconds"
  assert advanced_values(store, cp)[0] == pytest.approx(delay)  # untouched: the planner uses the CarParams value
  press(panel.items["LongitudinalActuatorDelay"], +1)
  assert store.get_float("LongitudinalActuatorDelay") == pytest.approx(delay + 0.01)
  assert advanced_values(store, cp)[0] == pytest.approx(delay + 0.01)
  press(panel.items["LongitudinalActuatorDelay"], -1)
  press(panel.items["LongitudinalActuatorDelay"], -1)
  assert store.get_float("LongitudinalActuatorDelay") == pytest.approx(delay - 0.01)
  assert advanced_values(store, cp)[0] == pytest.approx(delay - 0.01)


@pytest.mark.parametrize("name", CARS)
def test_section_off_keeps_the_car_delay_even_with_a_saved_value(store, name):
  cp = cp_for(name)
  store.put("LongitudinalActuatorDelay", .9)
  assert advanced_values(store, cp)[0] == pytest.approx(CARS[name]["delay"])   # Advanced Longitudinal Tuning not adopted


def test_edited_delay_reaches_the_planner_projection(store, monkeypatch):
  import openpilot.selfdrive.controls.lib.longitudinal_planner as native
  cp = cp_for("TESLA_AP1_MODELS")
  seen = []
  real = native.get_accel_from_plan
  monkeypatch.setattr(native, "get_accel_from_plan", lambda *a, **kw: (seen.append(kw["action_t"]), real(*a, **kw))[1])
  p = planner(cp=cp, toggle=False)
  p.long_accel.store = store
  p.update(SM(msgs(10, 30)))
  assert seen[-1] == pytest.approx(0.35 + DT_MDL)               # nothing edited: the real default
  panel = AdvancedLongitudinalSettings(store, cp=cp)
  toggle(panel, "AdvancedLongitudinalTune")
  for _ in range(5):
    press(panel.items["LongitudinalActuatorDelay"], +1)         # 0.35 -> 0.40
  p = planner(cp=cp, toggle=False)
  p.long_accel.store = store
  p.update(SM(msgs(10, 30)))
  assert seen[-1] == pytest.approx(0.40 + DT_MDL)


def test_standstill_tap_speed_help_states_the_code_default():
  from opendbc.car.tesla_ap1.op_long_set_speed import TAP_FROM_ZERO_DEFAULT_MPH
  from openpilot.selfdrive.ui.bogpilot.phase3_gas_brake import TAP_FROM_ZERO_DESC
  assert f"Starts at {TAP_FROM_ZERO_DEFAULT_MPH:g} mph" in TAP_FROM_ZERO_DESC
  assert TAP_FROM_ZERO_DESC.isascii()


def test_delay_help_says_it_does_not_apply_in_experimental_mode():
  note = HELP["LongitudinalActuatorDelay"].note
  assert "does not apply in Experimental mode" in note and "built-in delay" in note
  assert note.isascii()
