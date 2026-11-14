"""Human-Like Following on a Pre-AP Model S follows the Bosch radar retrofit as it was at car start.

Runtime (FollowingToggles.read) and the panel (FollowingEditor.on / can_edit) agree for Pre-AP with the radar on and
off, AP1 Model S and AP1 Model X, with the saved value unset (registry default), an explicit Off and an explicit On.
Reading never writes Params. Both resets keep their meaning and never touch TeslaRadarEnabled.
"""
import tempfile
from types import SimpleNamespace

import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib import phase3_following as F
from openpilot.selfdrive.ui.bogpilot import phase3_following as U
from openpilot.system.bogpilot import toggle_reset as R

MARKER = F.HUMAN_FOLLOWING_ACK


class FakeParams:
  def __init__(self, **vals):
    self.d = dict(vals)
    self.puts = []

  def all_keys(self):
    return list(BOGPILOT_PARAMS)

  def get(self, k, *a, **kw):
    return self.d.get(k)

  def put(self, k, v, *a, **kw):
    self.puts.append((k, v))
    self.d[k] = v

  def put_bool(self, k, v, *a, **kw):
    self.put(k, bool(v))

  def remove(self, k):
    self.d.pop(k, None)


@pytest.fixture(autouse=True)
def files(monkeypatch):
  with tempfile.TemporaryDirectory() as d:
    monkeypatch.setenv("BOGPILOT_PARAMS_DIR", d)
    yield d


def cp(fp, long=True, radar=True):
  return SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=long, radarUnavailable=not radar)


CARS = {
  "preap_radar_on": cp("TESLA_PREAP_MODELS", radar=True),
  "preap_radar_off": cp("TESLA_PREAP_MODELS", radar=False),
  "ap1_s": cp("TESLA_AP1_MODELS"),
  "ap1_x": cp("TESLA_AP1_MODELX", long=False),
}
STATES = {
  "unset": {"HumanFollowing": "1"},                     # registry default written at boot, no marker
  "explicit_off": {"HumanFollowing": "0"},
  "explicit_on": {"HumanFollowing": "1"},
}
# (car, state) -> effective Human-Like Following
EXPECTED = {
  ("preap_radar_on", "unset"): True, ("preap_radar_on", "explicit_off"): False, ("preap_radar_on", "explicit_on"): True,
  ("preap_radar_off", "unset"): False, ("preap_radar_off", "explicit_off"): False, ("preap_radar_off", "explicit_on"): False,
  ("ap1_s", "unset"): True, ("ap1_s", "explicit_off"): False, ("ap1_s", "explicit_on"): True,
  ("ap1_x", "unset"): False, ("ap1_x", "explicit_off"): False, ("ap1_x", "explicit_on"): False,
}


def make_store(car, state):
  s = ParamStore(FakeParams(LongitudinalTune="1", **STATES[state]))
  if state != "unset":
    s.put_bool(MARKER, True)
    s._params.puts.clear()
  return s


@pytest.mark.parametrize("car,state", sorted(EXPECTED))
def test_runtime_and_panel_agree(car, state):
  s = make_store(car, state)
  CP = CARS[car]
  runtime = F.FollowingToggles.read(s, CP)
  effective = runtime.human_following and runtime.has_radar      # the planner also needs radar (phase3_following.py)
  assert effective is EXPECTED[(car, state)]
  ed = U.FollowingEditor(CP, s, lambda: True)
  if CP.openpilotLongitudinalControl:
    assert ed.on("HumanFollowing") is EXPECTED[(car, state)]
  assert s._params.puts == []                                    # looking never writes


def test_default_helper_per_platform():
  assert F.human_following_default_on(CARS["preap_radar_on"]) is True
  assert F.human_following_default_on(CARS["preap_radar_off"]) is False
  assert F.human_following_default_on(CARS["ap1_s"]) is True
  assert F.human_following_default_on(CARS["ap1_x"]) is True        # unchanged; no openpilot longitudinal anyway
  assert F.human_following_default_on(None) is True
  assert F.human_following_default_on(SimpleNamespace(openpilotLongitudinalControl=True, radarUnavailable=True)) is True


def test_preap_without_radar_row_is_shown_off_and_greyed():
  s = make_store("preap_radar_off", "unset")
  ed = U.FollowingEditor(CARS["preap_radar_off"], s, lambda: True)
  assert ed.visible("HumanFollowing")                            # visibility unchanged
  assert not ed.on("HumanFollowing") and not ed.can_edit("HumanFollowing")
  assert not ed.write("HumanFollowing", True) and s._params.puts == []
  on = U.FollowingEditor(CARS["preap_radar_on"], make_store("preap_radar_on", "unset"), lambda: True)
  assert on.can_edit("HumanFollowing") and on.write("HumanFollowing", False) and not on.on("HumanFollowing")


def test_default_is_the_car_start_snapshot_not_the_file(files):
  """The retrofit file changing mid-drive does not flip the value: only CarParams (car start) is read."""
  from pathlib import Path
  s = make_store("preap_radar_on", "unset")
  before = F.FollowingToggles.read(s, CARS["preap_radar_on"]).human_following
  (Path(files) / "TeslaRadarEnabled").write_text("0")
  s.invalidate()
  assert F.FollowingToggles.read(s, CARS["preap_radar_on"]).human_following is before is True


@pytest.mark.parametrize("reset,value,preap_on,preap_off", [(R.shipping_defaults, "1", True, False),
                                                            (R.reset_defaults, "0", False, False)])
def test_resets(reset, value, preap_on, preap_off):
  table = reset()
  assert table["HumanFollowing"] == value and table[MARKER] is None
  assert "TeslaRadarEnabled" not in table and "TeslaRadarBehindNosecone" not in table
  for car, want in (("preap_radar_on", preap_on), ("preap_radar_off", preap_off)):
    s = ParamStore(FakeParams(LongitudinalTune="1", HumanFollowing=value))
    t = F.FollowingToggles.read(s, CARS[car])
    assert (t.human_following and t.has_radar) is want
