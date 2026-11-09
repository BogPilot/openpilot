"""t994 INT: Lane Changes page is registered ONLY with real consumers (UI -> store -> DesireHelper), dormant until adopted."""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[4]


class Store:
  def __init__(self, **v):
    self.values = {k: str(v_) for k, v_ in v.items()}
  def raw(self, k): return self.values.get(k)
  def tuning_level(self): return 3
  def honoured(self, k, level): return True
  def get_bool(self, k, default=False): return self.values.get(k, str(int(default))) in ('1', 'true', 'True')
  def get_float(self, k, default=0.0):
    try: return float(self.values.get(k, default))
    except (TypeError, ValueError): return float(default)
  def put(self, k, v): self.values[k] = str(v)
  def put_bool(self, k, v): self.values[k] = '1' if v else '0'
  def invalidate(self, key=None): pass


def car(**kw):
  d = dict(vEgo=25.0, leftBlinker=True, rightBlinker=False, leftBlindspot=False, rightBlindspot=False,
           steeringPressed=False, steeringTorque=0.0, standstill=False)
  return NS(**(d | kw))


def _line(y):
  return NS(x=[0.0, 20.0, 80.0], y=[y, y, y])


def model():
  from openpilot.cereal import log
  return NS(laneLines=[_line(y) for y in (-5.4, -1.8, 1.8, 5.4)], roadEdges=[_line(-7.0), _line(7.0)],
            position=NS(x=[0.0, 20.0, 80.0]),
            meta=NS(laneChangeState=log.LaneChangeState.laneChangeStarting, laneChangeDirection=log.LaneChangeDirection.left))


class TestIntLaneChanges(unittest.TestCase):
  def test_registered_in_single_driving_group_with_row_keys(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import working_pages, LANE_CHANGE_CONTROLS
    from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import active_groups
    from openpilot.selfdrive.ui.bogpilot.phase3_lanechange import ROWS
    groups = [g for g in active_groups(working_pages()) if g[0] == "driving"]
    self.assertEqual(len(groups), 1)
    titles = [p.title for p in groups[0][2]]
    self.assertIn("Lane Changes", titles)
    self.assertEqual(tuple(r[0] for r in ROWS), LANE_CHANGE_CONTROLS)

  def test_saved_prefs_dormant_until_ui_adoption_then_desire_helper_consumes(self):
    from openpilot.cereal import log
    from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper
    from openpilot.selfdrive.controls.lib.phase3_lanechange import configure, read_settings, LANE_CHANGE_ACK
    LCS = log.LaneChangeState
    # Bench-like saved prefs (Nudgeless ON) must NOT activate without explicit adoption.
    store = Store(LaneChanges=1, NudgelessLaneChange=1, LaneChangeTime=0.0, OneLaneChange=1, MinimumLaneChangeSpeed=20)
    self.assertFalse(read_settings(store).nudgeless)
    self.assertIsNone(store.raw(LANE_CHANGE_ACK))
    dh = DesireHelper()
    dh.lane_change_settings = NS(read=lambda: read_settings(store))
    for _ in range(60):
      dh.update(car(), True, 0.1, model(), True)
    self.assertEqual(dh.lane_change_state, LCS.preLaneChange)  # stock: needs a nudge
    # UI write path (configure) adopts the panel; saved choice preserved, consumer goes live.
    configure(store, "NudgelessLaneChange", True)
    self.assertEqual(store.raw(LANE_CHANGE_ACK), "1")
    self.assertTrue(read_settings(store).nudgeless)
    dh = DesireHelper()
    dh.lane_change_settings = NS(read=lambda: read_settings(store))
    states = set()
    for _ in range(60):
      dh.update(car(), True, 0.1, model(), True)
      states.add(dh.lane_change_state)
    self.assertIn(LCS.laneChangeStarting, states)
    # blind spot occupied (also SNA/stale encoded True) blocks the automatic start
    dh = DesireHelper()
    dh.lane_change_settings = NS(read=lambda: read_settings(store))
    for _ in range(60):
      dh.update(car(leftBlindspot=True), True, 0.1, model(), True)
    self.assertEqual(dh.lane_change_state, LCS.preLaneChange)

  def test_reset_clears_laneChange_markers(self):
    from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import ADOPTION_MARKERS as A
    from openpilot.system.bogpilot.toggle_reset import ADOPTION_MARKERS as B
    from openpilot.system.bogpilot.settings_backup import FILE_KEYS
    lane = {"Phase3LaneChangeEnabled", "Phase3HumanLaneChangesEnabled", "Phase3TurnDesiresEnabled"}
    self.assertTrue(lane <= set(A))
    self.assertTrue(lane <= set(B))
    self.assertTrue(lane <= set(FILE_KEYS))
    self.assertEqual(len(set(A)), 15)  # 13 + t1003u Stop Accel / Stopping Rate
    self.assertEqual(set(A), set(B))

  def test_radard_and_modeld_wired_and_guarded(self):
    radard = (ROOT / "openpilot/selfdrive/controls/radard.py").read_text()
    self.assertIn("human_lane_change_track", radard)
    self.assertIn("preferred_track", radard)
    modeld = (ROOT / "openpilot/selfdrive/modeld/modeld.py").read_text()
    self.assertIn("model_valid=", modeld)


if __name__ == "__main__":
  unittest.main()
