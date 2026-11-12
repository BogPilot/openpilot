"""Pre-AP / AP1 X one-shot SLC defaults, and AP1 S look-ahead profile values."""
from types import SimpleNamespace as NS

from openpilot.common.bogpilot_ap1_profile import (
  AP1_PARAM_PROFILE, LEGACY_SLC_PROFILE, apply_ap1_defaults_once, apply_legacy_slc_defaults_once,
  is_ap1, is_legacy_slc_platform, legacy_slc_marker_path, marker_path,
)
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS


class FakeParams:
  def __init__(self, **vals):
    self.vals = dict(vals)
    self.puts = []

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value):
    self.vals[key] = value
    self.puts.append(key)

  def invalidate(self):
    pass


def test_table_default_lookahead_is_five_and_higher_is_zero():
  assert BOGPILOT_PARAMS["SLCLookaheadLower"][2] == "5"
  assert BOGPILOT_PARAMS["SLCLookaheadHigher"][2] == "0"
  assert AP1_PARAM_PROFILE["SLCLookaheadLower"] == "5"
  assert AP1_PARAM_PROFILE["SLCLookaheadHigher"] == "0"


def test_legacy_slc_applies_once_for_preap_and_preserves_user_values(tmp_path):
  p = FakeParams(CarModel="TESLA_PREAP_MODELS", SLCPriority1="Navigation", SLCLookaheadLower="5")
  # Navigation is the table default, so Priority 1 is rewritten to Dashboard.
  # Look-ahead is already the table default (5), so the one-shot writes the same 5 s.
  written = apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert "SLCPriority1" in written
  assert p.vals["SLCPriority1"] == "Dashboard"
  assert p.vals["SLCLookaheadLower"] == "5"
  assert legacy_slc_marker_path(tmp_path).exists()
  # Second call is a no-op, including if we change the table later.
  p.vals["SLCPriority1"] = "Map Data"  # user change after first apply
  assert apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False) == []
  assert p.vals["SLCPriority1"] == "Map Data"


def test_legacy_slc_preserves_stored_one_second(tmp_path):
  p = FakeParams(CarModel="TESLA_AP1_MODELX", SLCLookaheadLower="1.000000")
  apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  assert p.vals["SLCLookaheadLower"] == "1.000000"


def test_legacy_slc_does_not_run_on_ap1_s(tmp_path):
  p = FakeParams(CarModel="TESLA_AP1_MODELS")
  assert is_ap1(p)
  assert not is_legacy_slc_platform(p)
  assert apply_legacy_slc_defaults_once(p, bogpilot_dir=tmp_path, refresh=False) == []
  assert not legacy_slc_marker_path(tmp_path).exists()


def test_ap1_s_profile_does_not_overwrite_stored_one_second(tmp_path):
  p = FakeParams(CarModel="TESLA_AP1_MODELS", SLCLookaheadLower="1.000000")
  apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)
  # 1 != table default 5, so the saved 1 s horizon is kept.
  assert p.vals["SLCLookaheadLower"] == "1.000000"
