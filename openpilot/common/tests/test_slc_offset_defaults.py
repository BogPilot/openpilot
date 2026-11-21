"""Speed Limit Controller offsets (Offset1-7) ship with the BogPilot values, 4/5/5/5/7/8/10 mph, everywhere a default is
declared, and the Speed Limit Offsets menu (shared by the 3X and the comma 4, which mounts the same panel) and the
planner read the same value. A value the user saved is never touched, and the one-time profiles still move a device that
only holds the old stock default (5/5/5/5/10/10/10)."""
import re
from pathlib import Path

import pytest

from openpilot.common import bogpilot_params as P
from openpilot.common.bogpilot_ap1_profile import (
  AP1_CAR_MODEL, AP1_SPEED_OFFSETS_MPH, MPH_TO_KPH, OLD_STOCK_OFFSETS_MPH, apply_ap1_defaults_once,
  apply_legacy_slc_defaults_once, legacy_slc_marker_path, marker_path,
)
from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import CP_AP1, FakeStore, toggles
from openpilot.selfdrive.ui.bogpilot.bogpilot_defaults import DEFAULT_ROWS
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss

ROOT = Path(P.__file__).resolve().parents[1]
KEYS = tuple(f"Offset{i}" for i in range(1, 8))
BOGPILOT = ["4", "5", "5", "5", "7", "8", "10"]
STOCK = ["5", "5", "5", "5", "10", "10", "10"]
MPH = 0.44704


def editor(**vals):
  store = FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1", **vals)
  return ss.SlcEditor(CP_AP1, store, lambda: True), store


class DictParams:
  def __init__(self, **vals):
    self.vals = {k: str(v) for k, v in vals.items()}

  def get(self, k): return self.vals.get(k)
  def put(self, k, v, block=False): self.vals[k] = str(v)
  def invalidate(self): pass


def test_every_declared_default_is_the_bogpilot_value():
  assert [P.BOGPILOT_PARAMS[k][2] for k in KEYS] == BOGPILOT
  assert [r[1] for k in KEYS for r in DEFAULT_ROWS if r[0] == k] == BOGPILOT
  assert [str(v) for v in AP1_SPEED_OFFSETS_MPH.values()] == BOGPILOT      # the AP1 profile table is the same numbers
  header = (ROOT / "common/params_keys_bogpilot.h").read_text()
  assert header == P.render_header()
  assert [re.search(r'\{"%s", \{PERSISTENT, INT, "(\d+)"\}\}' % k, header).group(1) for k in KEYS] == BOGPILOT
  specs = (ROOT / "selfdrive/ui/bogpilot/phase3_system_settings_feature_specs.py").read_text()
  assert [re.search(r'"%s": \{\n\s+"declared_default": "(\d+)"' % k, specs).group(1) for k in KEYS] == BOGPILOT
  assert OLD_STOCK_OFFSETS_MPH == dict(zip(KEYS, map(int, STOCK)))


def test_menu_shows_the_bogpilot_defaults_on_a_fresh_device():
  for car in (None, AP1_CAR_MODEL, "TESLA_PREAP_MODELS", "TESLA_AP1_MODELX"):
    ed, _ = editor(**({"CarModel": car} if car else {}))
    assert [ed.offset(k) for k in KEYS] == [int(v) for v in BOGPILOT], car
    assert [ed.default(k) for k in KEYS] == [int(v) for v in BOGPILOT], car
    assert [ed.default_text(k) for k in KEYS] == [f"+{v} mph" for v in BOGPILOT], car
    assert all(ed.at_default(k) for k in KEYS), car


def test_planner_reads_the_same_defaults_as_the_menu():
  t = toggles()                                                    # nothing saved
  assert [getattr(t, f"speed_limit_offset{i}") for i in range(1, 8)] == pytest.approx([int(v) * MPH for v in BOGPILOT])
  for limit, want in ((20, 4), (30, 5), (40, 5), (50, 5), (60, 7), (70, 8), (80, 10)):
    assert sc.offset_for(limit * MPH, t) == pytest.approx(want * MPH), limit
  ed, _ = editor()
  assert ed.offset("Offset5") * MPH == pytest.approx(sc.offset_for(60 * MPH, t))


def test_saved_values_are_kept_by_menu_and_planner():
  saved = dict(zip(KEYS, ["5", "5", "5", "5", "10", "10", "10"]))   # a user who saved the stock numbers keeps them
  ed, _ = editor(**saved)
  assert [ed.offset(k) for k in KEYS] == [int(v) for v in STOCK]
  assert [getattr(toggles(**saved), f"speed_limit_offset{i}") for i in range(1, 8)] == pytest.approx(
    [int(v) * MPH for v in STOCK])
  ed2, _ = editor(Offset1="0", Offset7="-3")                       # 0 and negative saved values are real values
  assert (ed2.offset("Offset1"), ed2.offset("Offset7"), ed2.offset("Offset4")) == (0, -3, 5)


def test_reading_never_writes():
  ed, store = editor()
  [ed.offset(k) for k in KEYS]
  [ed.default_text(k) for k in KEYS]
  assert not store.puts


@pytest.mark.parametrize("metric", [False, True])
@pytest.mark.parametrize("car", ["TESLA_PREAP_MODELS", "TESLA_AP1_MODELX"])
def test_legacy_profile_still_moves_an_old_stock_default_but_not_a_custom_value(tmp_path, car, metric):
  stock = [round(int(v) * MPH_TO_KPH) if metric else int(v) for v in STOCK]
  p = DictParams(CarModel=car, IsMetric="1" if metric else "0", **{k: str(s) for k, s in zip(KEYS, stock)})
  p.vals["Offset2"] = "6"                                          # the user picked 6
  apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  want = [round(m * MPH_TO_KPH) if metric else m for m in AP1_SPEED_OFFSETS_MPH.values()]
  got = [round(float(p.get(k))) for k in KEYS]
  assert got[1] == 6 and [g for i, g in enumerate(got) if i != 1] == [w for i, w in enumerate(want) if i != 1]
  assert legacy_slc_marker_path(tmp_path).exists()


def test_unsaved_offsets_are_written_by_the_profile_on_every_car(tmp_path):
  for car in ("TESLA_PREAP_MODELS", "TESLA_AP1_MODELX"):
    p = DictParams(CarModel=car)
    apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path / car, refresh=False)
    assert [float(p.get(k)) for k in KEYS] == [float(v) for v in BOGPILOT]


def test_ap1_s_profile_still_moves_an_old_stock_default_but_not_a_custom_value(tmp_path):
  p = DictParams(CarModel=AP1_CAR_MODEL, Offset1="5", Offset2="9", Offset5="10")
  apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert marker_path(tmp_path).exists()
  assert float(p.get("Offset1")) == 4 and float(p.get("Offset5")) == 7 and p.get("Offset2") == "9"
