"""Gas / Brake: the Curve Speed Control (CurveSpeedController) and Map Curve Speed (CSCMapCurvature) on/off rows, side by
side outside Longitudinal Tuning, and both on by default (with mapd v2) on the AP1 Model S and X. Pure data, no renderer."""
from types import SimpleNamespace

import pytest

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib import ap1_curve_speed as A
from openpilot.selfdrive.controls.lib import phase3_long_accel as L
from openpilot.selfdrive.ui.layouts.settings import phase3_long_accel_settings as LS

from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import ap1_cp
from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake as GB
from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve


class Store:
  def __init__(self, honoured=True):
    self.vals, self._honoured, self.writes = {GB.CSC_KEY: True, GB.MAP_CURVE_KEY: True}, honoured, []

  def honoured(self, key, level=None):
    return self._honoured(key) if callable(self._honoured) else self._honoured

  def get_bool(self, key, default=False):
    return bool(self.vals.get(key, default))

  def put_bool(self, key, value, block=False):
    self.writes.append((key, value, block))
    self.vals[key] = bool(value)

  def invalidate(self):
    pass


def test_row_shows_on_the_csc_cars_and_greyed_without_car_params():
  s = Store()
  assert GB.csc_visible(s, None)
  assert GB.csc_visible(s, GB.LiveCP(lambda: None))            # no CarParams yet: shown (greyed by its enabled gate)
  assert GB.csc_visible(s, GB.LiveCP(lambda: ap1_cp()))
  assert not GB.csc_visible(s, GB.LiveCP(lambda: ap1_cp(long=False)))
  assert not GB.csc_visible(Store(honoured=False), None)        # Tuning Level hides it


def test_write_is_blocking_and_gated():
  s = Store()
  assert not GB.set_csc(s, False, can_edit=lambda: False, long_on=lambda: True) and s.writes == []
  assert not GB.set_csc(s, False, can_edit=lambda: True, long_on=lambda: False) and s.writes == []
  assert GB.set_csc(s, False, can_edit=lambda: True, long_on=lambda: True)
  assert s.writes == [(GB.CSC_KEY, False, True)] and s.get_bool(GB.CSC_KEY) is False
  assert GB.set_csc(s, False, can_edit=lambda: True, long_on=lambda: True, key=GB.MAP_CURVE_KEY)
  assert s.writes[-1] == (GB.MAP_CURVE_KEY, False, True) and s.get_bool(GB.MAP_CURVE_KEY) is False
  assert not GB.set_csc(s, True, can_edit=lambda: True, long_on=lambda: True, key="LongitudinalTune")   # curve rows only
  assert s.writes[-1] == (GB.MAP_CURVE_KEY, False, True)


def test_row_is_a_page_control_with_plain_help():
  assert GB.CSC_KEY in GB.CONTROLS
  h = resolve(GB.CSC_KEY)
  assert h is not None and h.title == GB.CSC_TITLE == "Curve Speed Control"
  for text in (GB.CSC_DESC, h.what, h.when, h.note, h.default):
    assert "\u2014" not in text and "\u2013" not in text
  assert h.default == "On"


def test_root_entries_unchanged_by_the_row():
  s = SimpleNamespace(honoured=lambda k, level=None: True)
  assert [k for k, *_ in GB.root_entries(s, None)][:3] == ["advanced", "personalities", "profiles"]


# --- Map Curve Speed next to Curve Speed Control, out of Longitudinal Tuning ---

def test_map_curve_speed_sits_right_below_curve_speed_control():
  assert [k for k, *_ in GB.CURVE_ROWS] == [GB.CSC_KEY, GB.MAP_CURVE_KEY]
  assert GB.MAP_CURVE_TITLE == "Map Curve Speed" and resolve(GB.MAP_CURVE_KEY).title == GB.MAP_CURVE_TITLE
  assert "\u2014" not in GB.MAP_CURVE_DESC and "\u2013" not in GB.MAP_CURVE_DESC and "<" not in GB.MAP_CURVE_DESC
  assert GB.CONTROLS.index(GB.MAP_CURVE_KEY) == GB.CONTROLS.index(GB.CSC_KEY) + 1
  for fp in (S, X):
    assert [k for k, *_ in GB.curve_rows(Store(), car(fp))] == [GB.CSC_KEY, GB.MAP_CURVE_KEY]
  assert GB.curve_rows(Store(), car(S, long=False)) == []
  # each row follows its own Tuning Level: Map Curve Speed (level 2) hides alone, Curve Speed Control stays
  assert [k for k, *_ in GB.curve_rows(Store(honoured=lambda k: k != GB.MAP_CURVE_KEY), car(S))] == [GB.CSC_KEY]


def test_map_curve_speed_left_the_longitudinal_tuning_group():
  assert GB.MAP_CURVE_KEY not in LS.GROUPS["profiles"][3] and GB.MAP_CURVE_KEY not in LS.BY_KEY
  assert GB.MAP_CURVE_KEY not in L.PROFILE_KEYS          # its write never adopts the profiles group
  assert GB.MAP_CURVE_KEY not in LS.HISTORICAL_DESCRIPTIONS


S, X = "TESLA_AP1_MODELS", "TESLA_AP1_MODELX"


def car(fp, long=True):
  return SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=long, pcmCruise=not long)


class FreshParams:
  """A device with nothing saved: every read falls back to the registered default."""
  KEYS = ("CurveSpeedController", "CSCMapCurvature", "MapdV2")

  def all_keys(self):
    return [k.encode() for k in self.KEYS]

  def get(self, key, *a, **kw):
    return None


@pytest.mark.parametrize("fp", [S, X])
def test_curve_rows_and_mapd_v2_on_by_default_on_ap1_s_and_x(fp):
  for key in FreshParams.KEYS:
    assert BOGPILOT_PARAMS[key][2] == "1"
  store = ParamStore(FreshParams())
  cp = ap1_cp()
  cp.carFingerprint = fp
  c = A.Ap1CurveSpeed(cp, DT_MDL, store)
  assert c._toggle_on() and c._map_on()                  # Curve Speed Control on, Map Curve Speed on with mapd v2 on
  assert c.planner is not None


def test_ap1_profile_never_writes_the_curve_keys():
  """Defaults only: the AP1 profile does not set them, so a saved choice is kept and nothing is forced on."""
  from openpilot.common import bogpilot_ap1_profile as P
  profile_keys = {k for group in P.LEGACY_TESLA_LONG_PROFILE.values() for k in group}
  assert not (profile_keys & set(FreshParams.KEYS))
