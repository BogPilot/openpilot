"""The UI catalog's SLC look-ahead default text matches the registry and what the panel shows (5 s)."""
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.controls.lib.phase3_speed_control import LOOKAHEAD_HORIZON_DEFAULT
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import CP_AP1, FakeStore
from openpilot.selfdrive.ui.bogpilot.bogpilot_defaults import DEFAULT_ROWS
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss


def test_catalog_lookahead_default_matches_registry_and_panel():
  row = [r for r in DEFAULT_ROWS if r[0] == "SLCLookaheadLower"]
  assert row == [("SLCLookaheadLower", "5", 2, "0")]
  assert BOGPILOT_PARAMS["SLCLookaheadLower"][2] == row[0][1]
  ed = ss.SlcEditor(CP_AP1, FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1"), lambda: True)
  assert ed.default("SLCLookaheadLower") == int(row[0][1]) == LOOKAHEAD_HORIZON_DEFAULT == 5
  assert ed.seconds("SLCLookaheadLower") == 5
  assert ed.default_text("SLCLookaheadLower") == "5 seconds"
