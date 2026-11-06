"""Stream 6: frogpilotRadarState producer contract for stream-4 BSM flames."""
from types import SimpleNamespace
from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT.parent / "opendbc_repo"))

from openpilot.cereal import custom, log  # noqa: E402
from openpilot.common.bogpilot_store import ParamStore  # noqa: E402
from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS  # noqa: E402
from openpilot.selfdrive.controls.lib.bogpilot_radar import (  # noqa: E402
  BogPilotRadar, get_adjacent_lead, SERVICES, adjacent_side,
)
import numpy as np  # noqa: E402


class FakeTrack:
  def __init__(self, tid, d, y, v_lead=20.0):
    self.identifier = tid
    self.dRel = float(d)
    self.yRel = float(y)
    self.vRel = float(v_lead - 20.0)
    self.vLeadK = float(v_lead)
    self.aLeadK = 0.0
    self.aRel = 0.0
  def get_RadarState(self, model_prob: float = 0.0):
    return {
      "dRel": self.dRel, "yRel": self.yRel, "vRel": self.vRel,
      "vLead": self.vLeadK, "vLeadK": self.vLeadK, "aLeadK": self.aLeadK,
      "aRel": self.aRel, "status": True, "radarTrackId": self.identifier,
      "present": True, "modelProb": model_prob,
    }


class FileOnlyParams:
  def all_keys(self):
    return []
  def check_key(self, key):
    raise KeyError(key)
  def get(self, key, *a, **k):
    raise AssertionError(f"unknown get {key}")
  def put(self, key, val):
    raise AssertionError(f"unknown put {key}")


class RegisteredParams:
  def __init__(self, keys):
    self._keys = set(keys)
    self._vals = {}
  def all_keys(self):
    return list(self._keys)
  def check_key(self, key):
    if key not in self._keys:
      raise KeyError(key)
  def get(self, key, *a, **k):
    return self._vals.get(key)
  def put(self, key, val):
    if key not in self._keys:
      raise KeyError(key)
    self._vals[key] = val


def _model(lane_ys=(-5.4, -1.8, 1.8, 5.4), length=100.0):
  m = log.ModelDataV2.new_message()
  xs = np.linspace(0, length, 33).tolist()
  m.position.x = xs
  m.init("laneLines", 4)
  for i, y in enumerate(lane_ys):
    m.laneLines[i].x = xs
    m.laneLines[i].y = [y] * len(xs)
  return m


class TestRadarContract(unittest.TestCase):
  def test_services_and_schema_fields(self):
    self.assertEqual(SERVICES, ["frogpilotRadarState"])
    names = list(log.Event.schema.fieldnames)
    self.assertIn("frogpilotRadarState", names)
    msg = custom.FrogPilotRadarState.new_message()
    msg.leadLeft = {"status": True, "vLead": 40.0}
    self.assertTrue(msg.leadLeft.status)
    self.assertAlmostEqual(msg.leadLeft.vLead, 40.0)

  def test_adjacent_lead_geometry(self):
    model = _model()
    tracks = {1: FakeTrack(1, 30, 0.0), 2: FakeTrack(2, 40, 3.5), 3: FakeTrack(3, 25, 3.5), 4: FakeTrack(4, 35, -3.5)}
    left = get_adjacent_lead(tracks, model, True)
    self.assertTrue(left["status"])
    self.assertEqual(left["radarTrackId"], 3)
    self.assertIn("vLead", left)
    self.assertNotIn("present", left)

  def test_build_state_with_flame_toggle(self):
    td = tempfile.mkdtemp()
    os.environ["BOGPILOT_PARAMS_DIR"] = td
    Path(td, "BSMFlameTracks").write_text("1")
    store = ParamStore(FileOnlyParams())
    rs = log.RadarState.new_message()
    rs.leadOne.radarTrackId = -1
    rs.leadTwo.radarTrackId = -1
    RD = SimpleNamespace(tracks={4: FakeTrack(4, 35, 3.5)}, ready=True, radar_state=rs)  # yRel left-positive
    radar = BogPilotRadar(SimpleNamespace(carFingerprint="x", openpilotLongitudinalControl=True,
                                          radarUnavailable=False, enableBsm=True), store)
    radar.update(RD, {"modelV2": _model()}, now=0.0)
    self.assertTrue(radar.lead_left.get("status"))
    frs = radar.frogpilot_radar_state()
    self.assertTrue(frs.leadLeft.status)
    self.assertGreater(frs.leadLeft.vLead, 0.0)

  def test_file_only_ui_keys_never_touch_params(self):
    self.assertEqual(FILE_ONLY_UI_KEYS, frozenset({"RedesignUI", "BSMFlameTracks", "SwapSpeedGraph"}))
    td = tempfile.mkdtemp()
    os.environ["BOGPILOT_PARAMS_DIR"] = td
    params = RegisteredParams({"BlindSpotPath", "RedesignUI"})
    params.put("BlindSpotPath", "0")
    store = ParamStore(params)
    self.assertFalse(store.is_param_key("RedesignUI"))
    self.assertTrue(store.is_param_key("BlindSpotPath"))
    store.put("RedesignUI", "0")
    self.assertEqual(Path(td, "RedesignUI").read_text().strip(), "0")
    self.assertNotIn("RedesignUI", params._vals)
    store.put_bool("BlindSpotPath", True)
    # BOOL keys are stored as int 1/0 through Params
    self.assertIn(params._vals.get("BlindSpotPath"), (1, "1", True))
    self.assertTrue(store.get_bool("BlindSpotPath"))


if __name__ == "__main__":
  unittest.main()
