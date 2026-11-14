"""Human-Like Lane Changes defaults On on a Pre-AP Model S that started with the Bosch radar on, and nowhere else.

The 180-case matrix (6 platforms x 3 marker states x 5 tuning levels x BSMFlameTracks on/off) is evaluated with the
pre-change default rule (AP1 Model S only) and with the shipped rule. Only "Pre-AP radar On" may change, and exactly as
listed in INTENDED. The onroad toggle (bogpilot_onroad_toggles, not touched) and whether radard computes
leadLeft/leadRight are unchanged everywhere. Reading never writes Params.
"""
import itertools
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.common import bogpilot_toggles as BT
from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib import phase3_lanechange as L
from openpilot.selfdrive.controls.lib.bogpilot_radar import BogPilotRadar
from openpilot.selfdrive.ui.bogpilot import phase3_lanechange as UL
from openpilot.system.bogpilot import toggle_reset as R


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
    self.put(k, "1" if v else "0")

  def remove(self, k):
    self.d.pop(k, None)


def cp(fp, long=True, radar=True):
  return SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=long, radarUnavailable=not radar, enableBsm=False)


CARS = {"preap_radar_on": cp("TESLA_PREAP_MODELS"), "preap_radar_off": cp("TESLA_PREAP_MODELS", radar=False),
        "ap1_s": cp("TESLA_AP1_MODELS"), "ap1_x": cp("TESLA_AP1_MODELX", long=False),
        "ap2_unlisted": cp("TESLA_AP2_MODELS"), "other_radar_long": cp("TOYOTA_COROLLA_TSS2")}
STATES = {"marker_on": ("1", True), "unset": ("1", False), "explicit_off": ("0", True)}
LEVELS = {"unconfirmed": None, "L0": 0, "L1": 1, "L2": 2, "L3": 3}
FIELDS = ("onroad", "read_settings", "panel", "adjacent", "writes")

# The intended changes: Pre-AP radar On, unset (no marker, registry default). The panel shows On at every level; the
# lane-change runtime is On where the row's tuning level is honoured (L2, L3, unconfirmed = Developer). The onroad
# toggle already read On there, so it and the adjacent-lead computation do not change.
INTENDED = {("preap_radar_on", "unset", lvl, fl): ({"panel": (False, True), "read_settings": (False, True)}
                                                   if lvl in ("unconfirmed", "L2", "L3") else {"panel": (False, True)})
            for lvl in LEVELS for fl in (True, False)}


def _before_default_on(CP):
  """The rule before this change: the AP1 Model S only."""
  return CP is not None and str(getattr(CP, "carFingerprint", "") or "") in L.HUMAN_LANE_CHANGES_DEFAULT_ON_FPS


def _case(car, state, lvl, flames, tmp):
  BT.BOGPILOT_DIR = Path(tmp)
  if not flames:
    (Path(tmp) / "BSMFlameTracks").write_text("0")
  bit, marker = STATES[state]
  vals = {"HumanLaneChanges": bit, "LongitudinalTune": "1"}
  if LEVELS[lvl] is not None:
    vals.update(TuningLevelConfirmed="1", TuningLevel=str(LEVELS[lvl]))
  p = FakeParams(**vals)
  s = ParamStore(p)
  if marker:
    s.put_bool(L.HUMAN_LANE_CHANGES_ACK, True)
  s.invalidate()
  p.puts.clear()
  CP = CARS[car]
  t = onroad_toggles(s, CP)
  r = BogPilotRadar(CP, s)
  r.refresh_toggles(0.0)
  return {"onroad": bool(t.human_lane_changes), "read_settings": bool(L.read_settings(s, CP).human),
          "panel": bool(UL.display_bool(s, "HumanLaneChanges", CP)), "adjacent": bool(r.adjacent_enabled),
          "writes": len(p.puts)}


def _matrix(monkeypatch, before):
  out = {}
  with monkeypatch.context() as m:
    if before:
      m.setattr(L, "human_lane_changes_default_on", _before_default_on)
      m.setattr(UL, "human_lane_changes_default_on", _before_default_on)
    m.setattr(BT, "BOGPILOT_DIR", BT.BOGPILOT_DIR)
    for car, state, lvl, flames in itertools.product(CARS, STATES, LEVELS, (True, False)):
      with tempfile.TemporaryDirectory() as d:
        m.setenv("BOGPILOT_PARAMS_DIR", d)
        out[(car, state, lvl, flames)] = _case(car, state, lvl, flames, d)
  return out


def test_matrix_changes_only_preap_radar_on_as_intended(monkeypatch):
  before, after = _matrix(monkeypatch, True), _matrix(monkeypatch, False)
  assert len(before) == len(after) == 180
  changes = {}
  for k in before:
    d = {f: (before[k][f], after[k][f]) for f in FIELDS if before[k][f] != after[k][f]}
    if d:
      changes[k] = d
  outside = {k: v for k, v in changes.items() if k[0] != "preap_radar_on"}
  assert outside == {}
  assert changes == INTENDED
  assert all(r["writes"] == 0 for r in (*before.values(), *after.values()))
  # BSMFlameTracks off really turns the adjacent-lead computation off where nothing else asks for it
  assert after[("ap1_x", "unset", "L2", False)]["adjacent"] is False
  assert after[("ap1_x", "unset", "L2", True)]["adjacent"] is True


@pytest.mark.parametrize("car,want", [("preap_radar_on", True), ("preap_radar_off", False), ("ap1_s", True),
                                      ("ap1_x", False), ("ap2_unlisted", False), ("other_radar_long", False)])
def test_default_on_per_platform(car, want):
  assert L.human_lane_changes_default_on(CARS[car]) is want


def test_default_is_the_car_start_snapshot_not_the_file(monkeypatch, tmp_path):
  """Flipping the retrofit file mid-drive does not change the value: only CarParams (car start) is read."""
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  s = ParamStore(FakeParams(HumanLaneChanges="1", LongitudinalTune="1"))
  assert L.read_settings(s, CARS["preap_radar_on"]).human is True
  (tmp_path / "TeslaRadarEnabled").write_text("0")
  s.invalidate()
  assert L.read_settings(s, CARS["preap_radar_on"]).human is True


@pytest.mark.parametrize("reset,value,want", [(R.shipping_defaults, "1", True), (R.reset_defaults, "0", False)])
def test_resets(reset, value, want, monkeypatch, tmp_path):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  table = reset()
  assert table["HumanLaneChanges"] == value and table[L.HUMAN_LANE_CHANGES_ACK] is None
  assert "TeslaRadarEnabled" not in table and "TeslaRadarBehindNosecone" not in table
  s = ParamStore(FakeParams(HumanLaneChanges=value, LongitudinalTune="1"))
  assert L.read_settings(s, CARS["preap_radar_on"]).human is want
  assert L.read_settings(s, CARS["preap_radar_off"]).human is False
