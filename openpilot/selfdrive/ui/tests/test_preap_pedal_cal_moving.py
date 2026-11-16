"""Pre-AP Calibrate Pedal gate: "moving" comes from speed and gear, not carState.standstill.

On Pre-AP carState.standstill is the DI cruise STANDSTILL state, so it is False in Park with cruise off. The gate used to read it,
so Calibrate stayed greyed out whenever the car was on. These tests feed real carState messages (built, serialized and read
back the way the UI receives them) through the same calls the Vehicle Settings page makes.
"""
import math
import os
import unittest
from unittest import mock

from openpilot.cereal import log
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.preap import params as pp
from openpilot.selfdrive.ui.bogpilot import preap_pedal_cal as cal
from openpilot.selfdrive.ui.tests.test_preap_pedal_cal import MemParams, PedalCase, TestPedalCalNative, preap_cp

NOT_HEARD = cal.blocked_reason(live=False, moving=False)
MOVING = cal.blocked_reason(live=True, moving=True)


def car_state(gear="park", v_ego=0.0, standstill=False):
  """A carState as the UI reads it: built, serialized, read back. Cruise off in Park, so standstill is False."""
  ev = log.Event.new_message()
  ev.init("carState")
  ev.carState.gearShifter = gear
  ev.carState.vEgo = v_ego
  ev.carState.standstill = standstill
  with log.Event.from_bytes(ev.to_bytes()) as r:
    return r.carState


class TestCarMoving(unittest.TestCase):
  def test_park_at_rest_with_cruise_off_is_not_moving(self):
    cs = car_state("park", 0.0, standstill=False)
    self.assertFalse(cs.standstill)
    self.assertFalse(cal.car_state_moving(True, cs))

  def test_speed_blocks_even_in_park(self):
    self.assertTrue(cal.car_state_moving(True, car_state("park", 2.0)))
    self.assertTrue(cal.car_state_moving(True, car_state("park", -2.0)))
    self.assertTrue(cal.car_state_moving(True, car_state("park", cal.STOPPED_V_EGO)))
    self.assertFalse(cal.car_state_moving(True, car_state("park", cal.STOPPED_V_EGO / 2)))

  def test_any_gear_but_park_blocks_at_zero_speed(self):
    for gear in ("drive", "neutral", "reverse", "unknown"):
      with self.subTest(gear=gear):
        self.assertTrue(cal.car_state_moving(True, car_state(gear, 0.0)))
        self.assertTrue(cal.car_state_moving(True, car_state(gear, 0.0, standstill=True)))   # DI standstill does not unlock it

  def test_offroad_is_never_moving(self):
    for gear, v in (("park", 0.0), ("drive", 0.0), ("unknown", 0.0)):
      self.assertFalse(cal.car_state_moving(False, car_state(gear, v)))

  def test_builder_and_reader_enums_compare_the_same(self):
    ev = log.Event.new_message()
    ev.init("carState")
    ev.carState.gearShifter = "park"
    self.assertFalse(cal.car_state_moving(True, ev.carState))
    self.assertEqual(str(ev.carState.gearShifter), "park")
    self.assertEqual(str(car_state("park").gearShifter), "park")

  def test_missing_or_bad_speed_counts_as_moving(self):
    from opendbc.car.structs import car
    park = car.CarState.GearShifter.park
    self.assertTrue(cal.car_moving(True, None, park))
    self.assertTrue(cal.car_moving(True, math.nan, park))
    self.assertTrue(cal.car_moving(True, math.inf, park))
    self.assertFalse(cal.car_moving(True, 0.0, park))
    self.assertTrue(cal.car_state_moving(True, object()))       # no vEgo / gear at all


class TestCalibrateGate(PedalCase):
  """VehicleSettings wired exactly like the page: moving_fn = car_state_moving(started, carState)."""

  def model(self, started, cs):
    from pathlib import Path
    import tempfile
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import VehicleSettings
    tmp = tempfile.mkdtemp(prefix="vs-moving-")
    m = VehicleSettings(MemParams(), lambda: preap_cp(), lambda: not started, file_dir=Path(tmp), params_file=Path(tmp) / "DisableOpenpilotLongitudinal")
    m.moving_fn = lambda: cal.car_state_moving(started, cs)
    m.wall_fn = self.clock
    return m

  def reason(self, m):
    return cal.blocked_reason(cal.read_snapshot(m.wall()).live, m.moving())

  def test_parked_onroad_with_cruise_off_allows_calibrate(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    self.heard()
    m = self.model(True, car_state("park", 0.0, standstill=False))
    self.assertEqual(m.pedal_status(), "Needs calibration")
    self.assertTrue(m.enabled(pv.PEDAL_CALIBRATE))
    self.assertEqual(self.reason(m), "")

  def test_rolling_blocks(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    self.heard()
    m = self.model(True, car_state("park", 2.0))
    self.assertFalse(m.enabled(pv.PEDAL_CALIBRATE))
    self.assertEqual(self.reason(m), MOVING)

  def test_drive_or_neutral_at_rest_blocks(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    self.heard()
    for gear in ("drive", "neutral"):
      with self.subTest(gear=gear):
        m = self.model(True, car_state(gear, 0.0))
        self.assertFalse(m.enabled(pv.PEDAL_CALIBRATE))
        self.assertEqual(self.reason(m), MOVING)

  def test_offroad_with_a_live_pedal_still_allows(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    self.heard()
    m = self.model(False, car_state("unknown", 0.0))
    self.assertTrue(m.enabled(pv.PEDAL_CALIBRATE))

  def test_pedal_not_heard_blocks_with_the_existing_message(self):
    from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
    self.heard(False)
    m = self.model(True, car_state("park", 0.0))
    self.assertFalse(m.enabled(pv.PEDAL_CALIBRATE))
    self.assertEqual(self.reason(m), NOT_HEARD)
    self.assertIn("not being heard", NOT_HEARD)

  def test_session_stops_when_the_car_leaves_park(self):
    self.heard()
    state = {"cs": car_state("park", 0.0)}
    s = cal.PedalCalSession(monotonic=self.clock, wall=self.clock, moving=lambda: cal.car_state_moving(True, state["cs"]))
    self.assertTrue(s.begin())
    self.assertTrue(pp.get_bool(K.PEDAL_CALIB_ARMED))
    state["cs"] = car_state("drive", 0.0)
    self.clock.t += 0.1
    self.assertEqual(s.tick().phase, cal.MOVED)
    self.assertFalse(pp.get_bool(K.PEDAL_CALIB_ARMED))


@unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
class TestCalibrateGateNative(PedalCase):
  """The real Vehicle Settings page, its own moving_fn, ui_state fed a real carState."""
  setUpClass = classmethod(lambda cls: TestPedalCalNative.setUpClass.__func__(cls))

  def page(self, started, cs):
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.selfdrive.ui.bogpilot.phase2_vehicle import PEDAL_CALIBRATE, create_vehicle_settings_layout
    with mock.patch.object(ui_state, "CP", preap_cp()), mock.patch.object(ui_state, "started", started), \
         mock.patch.object(ui_state, "sm", {"carState": cs}):
      layout = create_vehicle_settings_layout(params=MemParams())
      layout.model.wall_fn = self.clock
      return layout.model.enabled(PEDAL_CALIBRATE), cal.blocked_reason(cal.read_snapshot(self.clock()).live, layout.model.moving())

  def test_page_gate(self):
    self.heard()
    self.assertEqual(self.page(True, car_state("park", 0.0, standstill=False)), (True, ""))
    self.assertEqual(self.page(True, car_state("park", 2.0)), (False, MOVING))
    self.assertEqual(self.page(True, car_state("drive", 0.0)), (False, MOVING))
    self.assertEqual(self.page(True, car_state("neutral", 0.0)), (False, MOVING))
    self.assertEqual(self.page(False, car_state("unknown", 0.0)), (True, ""))
    self.heard(False)
    self.assertEqual(self.page(True, car_state("park", 0.0)), (False, NOT_HEARD))


if __name__ == "__main__":
  unittest.main()
