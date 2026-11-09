"""Actual native LongControl/RadarD + real ParamStore file-backend integration.

Only message-stream/Params IO is supplied by the harness; control/PID/schema/
RadarD/lead selection and the settings model are the real imported implementations.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from opendbc.car.structs import car
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib.longcontrol import LongControl, LongCtrlState
from openpilot.selfdrive.controls.lib.phase3_long_stopping import LongStoppingRuntime, ModelStopInputs
from openpilot.selfdrive.ui.bogpilot.phase3_stopping_settings import StoppingSettingsModel, StoppingCapabilities
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController

try:
  from openpilot.selfdrive.controls.radard import RadarD
  from openpilot.cereal import log
  RADAR_IMPORT_ERROR = ""
except ImportError as exc:
  RadarD = None
  RADAR_IMPORT_ERROR = str(exc)


class UnknownCompiledKeys:
  def all_keys(self): return []


def make_cp():
  cp = car.CarParams.new_message()
  cp.openpilotLongitudinalControl = True
  cp.stopAccel = -2
  cp.brand = "tesla"
  cp.carFingerprint = "TESLA_AP1_MODELS"
  cp.longitudinalTuning.kiBP = [0.0]
  cp.longitudinalTuning.kiV = [0.2]
  return cp


class NativeConsumerTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.old_dir = os.environ.get("BOGPILOT_PARAMS_DIR")
    os.environ["BOGPILOT_PARAMS_DIR"] = self.tmp.name
    self.store = ParamStore(params=UnknownCompiledKeys())
    self.cp = make_cp()
    self.cap = StoppingCapabilities(stopped_distance=True)
    self.ui = StoppingSettingsModel(self.store, self.cp, self.cap, can_edit=lambda: True)
    # Stop Acceleration / Stopping Rate live in the single Advanced panel's controller.
    self.adv = SettingsController("advanced", self.store, cp=self.cp)
  def tearDown(self):
    if self.old_dir is None: os.environ.pop("BOGPILOT_PARAMS_DIR", None)
    else: os.environ["BOGPILOT_PARAMS_DIR"] = self.old_dir
    self.tmp.cleanup()
  def baseline(self):
    baseline_path = os.environ.get("BASELINE_LONGCONTROL")
    if baseline_path:
      source = Path(baseline_path).read_text()
    else:
      source = subprocess.check_output(["git", "show", "feae029245e281e37667457a74387671458d716f:openpilot/selfdrive/controls/lib/longcontrol.py"], text=True)
    namespace = {"__name__": "phase3_native_stock_longcontrol"}
    exec(compile(source, "native_stock_longcontrol.py", "exec"), namespace)
    return namespace["LongControl"](self.cp)
  def test_actual_off_baseline_5000_frame_lifecycle(self):
    # Non-default dormant child values must have no effect with parent OFF.
    self.store.put("StopAccel", -4)
    self.store.put("StoppingDecelRate", .001)
    self.store.put_bool("AdvancedLongitudinalTune", True)
    # No adoption marker: saved dormant parent/children must still be inert.
    original, actual = self.baseline(), LongControl(self.cp, stopping_store=self.store)
    cs = car.CarState.new_message()
    for tick in range(5000):
      cs.vEgo = (tick % 100) / 10
      cs.aEgo = ((tick % 11) - 5) / 10
      cs.brakePressed = tick % 23 < 3
      cs.gasPressed = tick % 19 < 2
      cs.cruiseState.standstill = tick % 29 < 5
      active, stop = tick % 1000 >= 50, tick % 150 < 75
      target = ((tick % 17) - 8) / 5
      expected = original.update(active, cs, target, stop, (-3., 2.))
      got = actual.update(active, cs, target, stop, (-3., 2.))
      self.assertEqual(got, expected, tick)
      self.assertEqual(actual.long_control_state, original.long_control_state, tick)
      self.assertEqual(actual.pid.i, original.pid.i, tick)
  def test_actual_settings_file_to_stopping_output(self):
    self.assertTrue(self.adv.change("AdvancedLongitudinalTune", True))
    self.assertTrue(self.adv.change("StoppingDecelRate", .3))
    self.assertTrue(self.adv.change("StopAccel", -1.5))
    controller = LongControl(self.cp, stopping_store=self.store)
    cs = car.CarState.new_message()
    result = controller.update(True, cs, 0, True, (-3., 2.))
    self.assertEqual(controller.long_control_state, LongCtrlState.stopping)
    self.assertAlmostEqual(result, -.003)
    self.assertEqual((Path(self.tmp.name)/"StoppingDecelRate").read_text(), "0.3")
    # Turning the UI parent OFF immediately restores stock stopping ramp.
    self.adv.change("AdvancedLongitudinalTune", False)
    result = controller.update(True, cs, 0, True, (-3., 2.))
    self.assertAlmostEqual(result, -.013)
  def test_physical_brake_and_standstill_release_guards_preserved(self):
    self.adv.change("AdvancedLongitudinalTune", True)
    controller = LongControl(self.cp, stopping_store=self.store)
    cs = car.CarState.new_message()
    controller.update(True, cs, 0, True, (-3., 2.))
    for brake, standstill in ((True, False), (False, True), (True, True)):
      cs.brakePressed, cs.cruiseState.standstill = brake, standstill
      controller.update(True, cs, 1, False, (-3., 2.))
      self.assertEqual(controller.long_control_state, LongCtrlState.stopping)
    cs.brakePressed = cs.cruiseState.standstill = False
    controller.update(True, cs, 1, False, (-3., 2.))
    self.assertEqual(controller.long_control_state, LongCtrlState.pid)
    self.assertEqual(controller.update(False, cs, 1, False, (-3., 2.)), 0)
    self.assertEqual(controller.long_control_state, LongCtrlState.off)
  def test_actual_actuator_limits_retained(self):
    self.adv.change("AdvancedLongitudinalTune", True)
    self.adv.change("StopAccel", -4)
    controller = LongControl(self.cp, stopping_store=self.store)
    cs = car.CarState.new_message()
    for _ in range(1000):
      result = controller.update(True, cs, 0, True, (-.7, 1.))
      self.assertGreaterEqual(result, -.7)
    self.assertEqual(result, -.7)
  def test_human_settings_delegate_once_to_lane4_adoption(self):
    ui = StoppingSettingsModel(self.store, self.cp, StoppingCapabilities(human_acceleration=True), lambda: True)
    self.assertTrue(ui.change("longitudinal", "LongitudinalTune", True))
    self.assertTrue(ui.change("longitudinal", "HumanAcceleration", True))
    from openpilot.selfdrive.controls.lib.phase3_long_accel import Profiles
    self.assertTrue(Profiles.read(self.store).human)
    self.assertTrue(self.store.get_bool("Phase3LongAccelProfilesEnabled", False))
  def test_no_dummy_or_unavailable_rows(self):
    keys = {r.key for page in ("root", "advanced", "qol", "weather", "Rain") for r in self.ui.rows(page)}
    for key in ("StartAccel", "VEgoStarting", "VEgoStopping", "ForceStops", "MapGears", "ReverseCruise", "SetWeatherKey"):
      self.assertNotIn(key, keys)
    empty = StoppingSettingsModel(self.store, self.cp, StoppingCapabilities(), lambda: True)
    self.assertEqual(empty.rows(), [])
  def test_offroad_edit_guard_and_stale_callbacks(self):
    self.adv.can_edit = lambda: False
    self.assertFalse(self.adv.change("AdvancedLongitudinalTune", True))
    self.adv.can_edit = lambda: True
    self.assertFalse(self.adv.change("StopAccel", -3))
    self.adv.change("AdvancedLongitudinalTune", True)
    self.assertTrue(self.adv.nudge("StopAccel", -1))  # t1003u: row registered
  def test_manual_weather_ui_to_effective_distance_no_network(self):
    self.store.put_bool("IsMetric", True)
    self.ui.change("qol", "IncreasedStoppedDistance", value=2)
    self.ui.change("qol", "WeatherPresets", True)
    self.assertTrue(self.ui.change("weather", "BogPilotManualWeather", "rain"))
    self.assertTrue(self.ui.change("Rain", "IncreasedStoppedDistanceRain", value=1))
    runtime = LongStoppingRuntime(self.store, self.cp)
    opts, weather = runtime.snapshot()
    self.assertEqual((opts.stopped_distance, weather.stopped_metres), (2, 1))
    self.assertFalse(self.ui.change("Rain", "ReduceAccelerationRain", value=10))
    self.ui.change("weather", "BogPilotManualWeather", "clear")
    self.assertEqual(runtime.snapshot()[1].stopped_metres, 0)
    self.assertNotIn("WeatherToken", [p.name for p in Path(self.tmp.name).iterdir()])
  def test_force_settings_to_real_backend_interface_with_explicit_test_inputs(self):
    self.ui = StoppingSettingsModel(self.store, self.cp, StoppingCapabilities(force_stop_inputs=True), lambda: True)
    self.assertTrue(self.ui.change("qol", "ForceStops", True))
    runtime = LongStoppingRuntime(self.store, self.cp)
    kwargs = dict(longitudinal_active=True, gas_pressed=False, accel_pressed=False, standstill=False, v_ego=10.)
    for _ in range(25):
      self.assertEqual(runtime.arbitrate_force_stop(12., model_stop=None, **kwargs).target, 12.)
    inputs = ModelStopInputs(True, True, 60., 10., True)
    for _ in range(20): result = runtime.arbitrate_force_stop(12., model_stop=inputs, **kwargs)
    self.assertEqual(result.target, 5.)
    self.assertEqual(runtime.arbitrate_force_stop(3., model_stop=inputs, **kwargs).target, 3.)
    kwargs["gas_pressed"] = True
    self.assertEqual(runtime.arbitrate_force_stop(12., model_stop=inputs, **kwargs).target, 12.)


@unittest.skipIf(RadarD is None, "native RadarD unavailable: " + RADAR_IMPORT_ERROR)
class NativeRadarConsumerTests(unittest.TestCase):
  setUp = NativeConsumerTests.setUp
  tearDown = NativeConsumerTests.tearDown
  def baseline_radar(self):
    source = Path(os.environ["BASELINE_RADARD"]).read_text() if "BASELINE_RADARD" in os.environ else subprocess.check_output(
      ["git", "show", "feae029245e281e37667457a74387671458d716f:openpilot/selfdrive/controls/radard.py"], text=True)
    namespace = {"__name__": "phase3_native_stock_radard"}
    exec(compile(source, "native_stock_radard.py", "exec"), namespace)
    return namespace["RadarD"]()
  def stream(self):
    class Stream(dict):
      seen = {"modelV2": True}
      recv_frame = {"carState": 1}
      logMonoTime = {"modelV2": 123}
      def all_checks(self, services=None): return True
    model = log.ModelDataV2.new_message()
    model.velocity.x = [10.]
    leads = model.init("leadsV3", 2)
    for lead in leads:
      lead.prob = 1.
      for field, value in (("x", 50.), ("y", 0.), ("v", 10.), ("a", 0.),
                           ("xStd", 1.), ("yStd", 1.), ("vStd", 1.), ("aStd", 1.)):
        setattr(lead, field, [value])
    cs = car.CarState.new_message()
    cs.vEgo = 10
    radar = car.RadarData.new_message()
    points = radar.init("points", 1)
    points[0].trackId, points[0].dRel, points[0].yRel, points[0].vRel = 1, 50., 0., 0.
    return Stream(modelV2=model, carState=cs), radar
  def test_actual_radar_selected_offset_exactly_once_200_frames(self):
    self.store.put_bool("IsMetric", True)
    self.ui.change("qol", "IncreasedStoppedDistance", value=2)
    runtime = LongStoppingRuntime(self.store, self.cp)
    plain, tuned = self.baseline_radar(), RadarD(stopping_runtime=runtime)
    sm, rr = self.stream()
    for frame in range(200):
      sm.recv_frame["carState"] = frame
      plain.update(sm, rr)
      tuned.update(sm, rr, traffic_mode=False)
      self.assertTrue(tuned.radar_state.leadOne.present)
      self.assertAlmostEqual(plain.radar_state.leadOne.dRel - tuned.radar_state.leadOne.dRel, 2.)
      self.assertEqual(tuned.tracks[1].dRel, plain.tracks[1].dRel)
      self.assertEqual(tuned.radar_state_valid, plain.radar_state_valid)
  def test_actual_radar_off_baseline_and_traffic_weather(self):
    runtime = LongStoppingRuntime(self.store, self.cp)
    plain, tuned = self.baseline_radar(), RadarD(stopping_runtime=runtime)
    sm, rr = self.stream()
    plain.update(sm, rr)
    tuned.update(sm, rr, traffic_mode=False)
    self.assertEqual(plain.radar_state.to_dict(), tuned.radar_state.to_dict())
    self.store.put_bool("IsMetric", True)
    self.ui.change("qol", "IncreasedStoppedDistance", value=2)
    self.ui.change("qol", "WeatherPresets", True)
    self.ui.change("weather", "BogPilotManualWeather", "rain")
    self.ui.change("Rain", "IncreasedStoppedDistanceRain", value=1)
    for mode, expected in ((False, 3.), (True, 0.), (None, 0.)):
      plain.update(sm, rr)
      tuned.update(sm, rr, traffic_mode=mode)
      self.assertAlmostEqual(plain.radar_state.leadOne.dRel - tuned.radar_state.leadOne.dRel, expected)


if __name__ == "__main__": unittest.main(verbosity=2)
