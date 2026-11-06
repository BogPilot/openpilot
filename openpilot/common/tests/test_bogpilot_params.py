"""BogPilot params: defaults match the 367e1fe FrogPilot table with two BogPilot standing-rule overrides (HolidayThemes off, TuningLevel Developer).

fixtures/bogpilot_defaults_367e1fe.json is a snapshot of 367e1fe frogpilot_default_params +
misc_tuning_levels (+ params.cc flags, EXCLUDED_KEYS), taken straight from the reference git objects
by /workspace/agnos/tools/check_defaults_367e1fe.py (expression defaults evaluated with the
reference's own constants). This test never regenerates it.
"""
import json
import os
from pathlib import Path

import pytest

from openpilot.common import bogpilot_params as bp
from openpilot.common import bogpilot_toggles as bt
from openpilot.common.params import Params

FIXTURE = json.loads((Path(__file__).parent / "fixtures/bogpilot_defaults_367e1fe.json").read_text(encoding="utf-8"))
REF = FIXTURE["defaults"]
STOCK_011_KEYS = set(bp.FROGPILOT_STOCK_KEY_DEFAULTS)


def test_fixture_is_367e1fe():
  assert FIXTURE["ref"] == "367e1fe"
  assert len(REF) == 338


@pytest.mark.parametrize("key", sorted(REF))
def test_default_matches_367e1fe(key):
  default, level, stock = REF[key]
  if key in STOCK_011_KEYS:
    mine = bp.FROGPILOT_STOCK_KEY_DEFAULTS[key]
  else:
    _flags, _type, d, lvl, s = bp.BOGPILOT_PARAMS[key]
    mine = (d, lvl, s)
  assert mine == (default, level, stock), f"{key}: {mine} != 367e1fe {(default, level, stock)}"


def test_no_extra_defaults():
  rows = {k: [d, lvl, s] for k, d, lvl, s in bp.frogpilot_defaults()}
  assert rows == REF


def test_flags_match_367e1fe():
  for key, (flags, *_rest) in bp.BOGPILOT_PARAMS.items():
    if key in FIXTURE["flags"]:
      assert sorted(flags.split("|")) == FIXTURE["flags"][key], key


def test_every_367e1fe_key_is_registered():
  stock_011 = {k.decode() for k in Params().all_keys()} - set(bp.BOGPILOT_PARAMS)
  missing = sorted(k for k in FIXTURE["flags"] if k not in bp.BOGPILOT_PARAMS and k not in stock_011)
  assert not missing


def test_excluded_keys():
  assert sorted(bp.EXCLUDED_KEYS) == FIXTURE["excluded_keys"]


def test_header_in_sync():
  assert Path(bp.HEADER_PATH).read_text(encoding="utf-8") == bp.render_header()


def test_libparams_has_every_key():
  """The libparams_c.so in use must be the rebuilt one, or clearAll wipes every FrogPilot param."""
  keys = {k.decode() for k in Params().all_keys()}
  missing = sorted(set(bp.BOGPILOT_PARAMS) - keys)
  assert not missing, f"libparams_c.so lacks {len(missing)} BogPilot keys, e.g. {missing[:5]}"


def test_defaults_land_exactly(tmp_path, monkeypatch):
  """End to end: run the manager defaults pass on an empty params dir; every file holds the exact default."""
  from openpilot.system.manager import bogpilot_init
  params = Params(str(tmp_path / "params"))
  cache = Params(str(tmp_path / "cache"))
  # 0.11.2's own loop first, as manager_init does
  for k in params.all_keys():
    dv = params.get_default_value(k)
    if dv is not None and params.get(k) is None:
      params.put(k, dv, block=True)
  bogpilot_init.apply_frogpilot_defaults(params, cache)
  d = tmp_path / "params" / os.environ.get("OPENPILOT_PREFIX", "d")
  for k, (default, _lvl, _stock) in REF.items():
    f = d / k
    raw = f.read_bytes().decode("utf-8") if f.exists() else ""
    assert raw == default, f"{k}: stored {raw!r} != 367e1fe {default!r}"


def test_reset_and_backup(tmp_path):
  from openpilot.system.manager import bogpilot_init
  params = Params(str(tmp_path / "params"))
  cache = Params(str(tmp_path / "cache"))
  bogpilot_init.apply_frogpilot_defaults(params, cache)
  params.put("DeviceShutdown", "3")
  bogpilot_init.apply_frogpilot_defaults(params, cache)   # refreshes the backup
  params.remove("DeviceShutdown")
  bogpilot_init.apply_frogpilot_defaults(params, cache)   # restored from /cache/params
  assert params.get_int("DeviceShutdown") == 3
  params.put_bool("DoToggleResetStock", True)
  params.put("CarParamsPersistent", b"keep")
  bogpilot_init.apply_frogpilot_defaults(params, cache)
  assert params.get_int("DeviceShutdown") == int(REF["DeviceShutdown"][2])   # stock column
  assert params.get("CarParamsPersistent") == b"keep"               # EXCLUDED_KEYS
  assert params.get("DoToggleResetStock") is None


def test_file_toggle_defaults(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  on = {"OffroadScreensaver", "BSMFlameTracks", "ConfidenceBall", "RedesignUI", "ShowUploadRate", "RemoteUIStream", "HevcStream"}
  off = {"DeveloperHUD", "SwapSpeedGraph", "OccViz", "LiveYOLO"}
  for k in on:
    assert bt.read_toggle(k) is True, k
  for k in off:
    assert bt.read_toggle(k) is False, k
  assert bt.read_choice("ConfidenceBallSide") == "left"
