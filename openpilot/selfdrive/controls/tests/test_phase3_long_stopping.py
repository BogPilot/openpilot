"""Native Mac, dependency-free unit and deterministic helper replay tests."""
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

MODULE = Path(__file__).resolve().parents[1] / "lib" / "phase3_long_stopping.py"
if not MODULE.exists():
  MODULE = Path(__file__).with_name("phase3_long_stopping.py")
spec = importlib.util.spec_from_file_location("phase3_long_stopping", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class Store:
  def __init__(self, values=None, defaults=None, hidden=()):
    self.values, self.defaults = values or {}, defaults or {}
    self.hidden = hidden
  def tuning_level(self): return 3
  def honoured(self, key, level): return key not in self.hidden
  def get(self, key): return self.values.get(key, self.default(key))
  def default(self, key): return self.defaults.get(key, "0")
  def get_bool(self, key, default=False): return m._bool(self.values.get(key, self.defaults.get(key, default)))


def cp(**kw):
  return NS(**dict(dict(openpilotLongitudinalControl=True, stopAccel=-2.0,
                       carName="tesla", pcmCruise=True), **kw))


class StoppingTests(unittest.TestCase):
  def test_inventory_unique(self):
    self.assertEqual(len(m.OWNED_KEYS), len(set(m.OWNED_KEYS)))
    self.assertNotIn("HumanFollowing", m.OWNED_KEYS)
    self.assertEqual(len(m.WEATHER_KEYS), 22)
  def test_native_defaults_no_new_start_state(self):
    tune = m.read_runtime_stopping(Store(), cp())
    self.assertEqual(tune, m.StoppingTune(None, None, -2, 1, None))
  def test_stored_children_do_not_bypass_parent(self):
    tune = m.read_runtime_stopping(Store({"StopAccel": "-4", "StoppingDecelRate": ".02"}), cp())
    self.assertEqual(tune.stop_accel, -2)
    self.assertEqual(tune.stopping_decel_rate, 1)
  def test_historical_bounds(self):
    store = Store({"AdvancedLongitudinalTune": "1", "StartAccel": "9", "VEgoStarting": "-2",
                   "StopAccel": "-9", "StoppingDecelRate": "2", "VEgoStopping": "8"})
    self.assertEqual(m.read_stopping_tune(store, cp()), m.StoppingTune(4, .01, -4, 1, 1))
  def test_level_falls_back_cp_not_registered_tune(self):
    store = Store({"AdvancedLongitudinalTune": "1", "StopAccel": "-4"}, hidden={"StopAccel"})
    self.assertEqual(m.read_runtime_stopping(store, cp()).stop_accel, -2)
  def test_invalid_tuning_falls_back(self):
    for v in ("nan", "inf", "-inf", "bad"):
      s = Store({"AdvancedLongitudinalTune": "1", "StopAccel": v, "StoppingDecelRate": v})
      t = m.read_runtime_stopping(s, cp())
      self.assertEqual((t.stop_accel, t.stopping_decel_rate), (-2, 1))
  def test_no_longitudinal_control_no_custom_tune(self):
    store = Store({"AdvancedLongitudinalTune": "1", "StopAccel": "-4", "ForceStops": "1", "QOLLongitudinal": "1"})
    self.assertEqual(m.read_runtime_stopping(store, cp(openpilotLongitudinalControl=False)).stop_accel, -2)
    self.assertFalse(m.read_options(store, cp(openpilotLongitudinalControl=False), is_metric=True).force_stops)
  def test_disable_longitudinal(self):
    store = Store({"DisableOpenpilotLongitudinal": "1", "AdvancedLongitudinalTune": "1", "StopAccel": "-4"})
    self.assertEqual(m.read_runtime_stopping(store, cp()).stop_accel, -2)
  def test_native_stop_replay_equivalent_1000_frames(self):
    tune = m.native_stopping_tune(cp())
    expected = actual = .5
    for _ in range(1000):
      if expected > -2:
        expected = min(expected, 0.0) - .01
      expected = max(-3, min(2, expected))
      actual = m.stopping_accel(actual, tune, .01, (-3, 2))
      self.assertEqual(actual, expected)
  def test_custom_stop_rate_and_hardware_clamp(self):
    tune = m.StoppingTune(None, None, -4, .3, None)
    self.assertAlmostEqual(m.stopping_accel(.5, tune, .01, (-3, 2)), -.003)
    self.assertEqual(m.stopping_accel(-3, tune, .01, (-3, 2)), -3)
  def test_distance_units_saved_values_unchanged(self):
    s = Store({"QOLLongitudinal": "1", "IncreasedStoppedDistance": "3"})
    before = s.values.copy()
    self.assertEqual(m.read_options(s, cp(), is_metric=True).stopped_distance, 3)
    self.assertAlmostEqual(m.read_options(s, cp(), is_metric=False).stopped_distance, .9144)
    self.assertEqual(s.values, before)
  def test_default_distance_always_feet(self):
    s = Store(defaults={"IncreasedStoppedDistance": "10"})
    self.assertAlmostEqual(m.read_options(s, cp(), is_metric=True).stopped_distance, 3.048)
  def test_human_parent_gate(self):
    s = Store({"HumanAcceleration": "1"})
    self.assertFalse(m.read_options(s, cp(), is_metric=True).human_acceleration)
    s.values["LongitudinalTune"] = "1"
    self.assertTrue(m.read_options(s, cp(), is_metric=True).human_acceleration)
  def test_human_accel_exact_golden(self):
    for cruise, ego, expected in ((0, 0, 0), (12.5, 0, 1), (25, 0, 2), (25, 25, 0), (25, 24, .5), (25, 22, 1.25)):
      self.assertAlmostEqual(m.human_accel_limit(2, cruise, ego, True), expected)
    self.assertEqual(m.human_accel_limit(2, 25, 25, False), 2)
    self.assertEqual(m.human_accel_limit(-1, 25, 25, True), -1)
  def test_map_gear_subtoggles_and_reverse_toyota_only(self):
    s = Store({k: "1" for k in ("QOLLongitudinal", "MapGears", "MapAcceleration", "MapDeceleration", "ReverseCruise")})
    self.assertTrue(m.read_options(s, cp(), is_metric=True).map_acceleration)
    self.assertFalse(m.read_options(s, cp(), is_metric=True).reverse_cruise)
    self.assertTrue(m.read_options(s, cp(carName="toyota"), is_metric=True).reverse_cruise)
    self.assertFalse(m.read_options(s, cp(carName="toyota", pcmCruise=False), is_metric=True).reverse_cruise)
  def test_weather_boundary_categories(self):
    values = {"IncreaseFollowing" + suffix: str(i + 1) for i, (suffix, _) in enumerate(m.WEATHER_RANGES)}
    store = Store(values)
    option = m.LongStoppingOptions(weather_presets=True)
    for i, (_, ranges) in enumerate(m.WEATHER_RANGES):
      for lo, hi in ranges:
        for wid in (lo, hi):
          self.assertEqual(m.weather_offsets(store, option, wid, is_metric=True, valid=True).following_seconds, i + 1)
    for wid in (0, 299, 322, 505, 599, 623, 763, 800, 801):
      self.assertEqual(m.weather_offsets(store, option, wid, is_metric=True, valid=True), m.WeatherOffsets())
  def test_weather_units_and_navigation_not_toggle(self):
    store = Store({"IncreasedStoppedDistanceRain": "3", "ReduceAccelerationRain": "25", "ReduceLateralAccelerationRain": "10"})
    offsets = m.weather_offsets(store, m.LongStoppingOptions(weather_presets=True), 500, is_metric=False, valid=True)
    self.assertEqual(offsets, m.WeatherOffsets(0, .9144000000000001, .25, .1))
  def test_weather_missing_disabled_invalid(self):
    for option, valid in ((False, True), (True, False)):
      self.assertEqual(m.weather_offsets(Store(), m.LongStoppingOptions(weather_presets=option), 500, is_metric=True, valid=valid), m.WeatherOffsets())
  def test_traffic_mode_disables_stopped_offsets(self):
    opts, weather = m.LongStoppingOptions(stopped_distance=2), m.WeatherOffsets(stopped_metres=1)
    self.assertEqual(m.stopped_distance(opts, weather), 3)
    self.assertEqual(m.stopped_distance(opts, weather, traffic_mode=True), 0)
  def test_lead_offset_after_matching_no_track_mutation(self):
    lead = {"present": True, "dRel": 20., "radarTrackId": 3}
    out = m.offset_lead(lead, 3)
    self.assertEqual(out["dRel"], 17)
    self.assertEqual(lead["dRel"], 20)
    self.assertEqual(out["radarTrackId"], 3)
    self.assertEqual(m.offset_lead({"present": False}, 3), {"present": False})


class ForceStopTests(unittest.TestCase):
  def setUp(self):
    self.c = m.ForceStopController()
    self.inputs = dict(enabled=True, option=True, stop_light_detected=True, model_stopped=True,
                       gas_pressed=False, accel_pressed=False, standstill=False,
                       model_length=60., v_ego=10., v_cruise=15., planner_time=10.)
  def step(self, **kw): return self.c.update(**dict(self.inputs, **kw))
  def test_full_second_required_then_floor_division(self):
    for _ in range(19):
      self.assertEqual(self.step().target, 15)
    self.assertEqual(self.step().target, 5)
    self.assertTrue(self.c.forcing_stop)
  def test_each_predicate_required(self):
    for key in ("enabled", "option", "stop_light_detected", "model_stopped"):
      self.c = m.ForceStopController()
      for _ in range(25):
        self.assertEqual(self.step(**{key: False}).target, 15)
  def test_driver_gas_and_accel_override_ten_seconds(self):
    for key in ("gas_pressed", "accel_pressed"):
      self.c = m.ForceStopController()
      for _ in range(20): self.step()
      self.assertEqual(self.step(**{key: True}).target, 15)
      self.assertEqual(self.c.override_timer, 10)
      for _ in range(200): self.assertEqual(self.step().target, 15)
      # A fresh one-second confirmation is required after the holdoff.
      self.assertEqual(self.step().target, 15)
      for _ in range(21): result = self.step()
      self.assertLess(result.target, 15)
  def test_disengagement_and_option_off_clear_forcing(self):
    for key in ("enabled", "option"):
      for _ in range(21): self.step()
      self.assertEqual(self.step(**{key: False}).target, 15)
      self.assertFalse(self.c.forcing_stop)
      self.assertEqual(self.c.confirmation_time, 0)
  def test_nonnegative_distance_no_target_raise(self):
    for _ in range(160): result = self.step()
    self.assertEqual(result.tracked_model_length, 0)
    self.assertEqual(result.target, 0)
  def test_invalid_model_fails_open_to_stock_target(self):
    for _ in range(21): self.step()
    for kw in ({"planner_time": 0}, {"model_length": math.nan}, {"dt": 0}):
      self.assertEqual(self.step(**kw).target, 15)
      self.assertFalse(self.c.forcing_stop)
  def test_synthetic_replay_1000_frames_with_overrides(self):
    trace = []
    for tick in range(1000):
      result = self.step(enabled=tick < 700, gas_pressed=50 <= tick < 60)
      self.assertGreaterEqual(result.target, 0)
      self.assertLessEqual(result.target, 15)
      if tick >= 700 or 50 <= tick < 60:
        self.assertEqual(result.target, 15)
      trace.append((result.target, result.forcing_stop))
    self.assertTrue(any(force for _, force in trace))
    self.assertFalse(any(force for _, force in trace[700:]))


if __name__ == "__main__":
  unittest.main(verbosity=2)
