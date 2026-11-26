"""Navigation > Maps port: the Map Data source behind the existing SLC source setting changes nothing without maps.

No maps installed (or a download running, when mapd's main loop is busy and MapSpeedLimit goes stale) means the Map Data
source reads 0 and the SLC uses the next source exactly as before the port. No network, no mapd, no msgq."""
import unittest

from openpilot.selfdrive.controls.tests.test_phase3_speed_control import MPH
from openpilot.selfdrive.controls.tests.test_phase3_speed_control_osm import Ctx, limits, slc_with


class TestNoMapsFallback(unittest.TestCase):
  def test_default_priorities_without_maps_equal_no_map_context(self):
    for dash, nav in ((35 * MPH, 0.0), (0.0, 45 * MPH), (0.0, 0.0), (35 * MPH, 45 * MPH)):
      with_empty = limits(slc_with(Ctx(limit=0.0)), dash=dash, nav=nav)
      without = limits(slc_with(None), dash=dash, nav=nav)
      self.assertEqual(with_empty, without, (dash, nav))

  def test_map_data_first_without_data_falls_to_dashboard(self):
    s = slc_with(Ctx(limit=0.0), SLCPriority1="Map Data", SLCPriority2="Dashboard", SLCPriority3="Navigation")
    self.assertEqual(limits(s, dash=35 * MPH), ("Dashboard", 35 * MPH))

  def test_no_gps_position_is_no_map_limit(self):
    s = slc_with(Ctx(limit=25 * MPH, gps=False), SLCPriority1="Map Data", SLCPriority2="Dashboard")
    self.assertEqual(limits(s, dash=35 * MPH), ("Dashboard", 35 * MPH))

  def test_map_data_used_when_present(self):
    s = slc_with(Ctx(limit=25 * MPH), SLCPriority1="Map Data", SLCPriority2="Dashboard", SLCPriority3="Navigation")
    src, _tgt = limits(s, dash=0.0)
    self.assertEqual(src, "Map Data")


if __name__ == "__main__":
  unittest.main()
