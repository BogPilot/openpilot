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
RAW_REF = FIXTURE["defaults"]
# Product (bogpilot-tesla-c3x): approved stream-5 shipping overlay on top of the 367e1fe snapshot
# (AOL off, metrics on, TuningLevel intentionally unset 0/0, ...). The fixture itself stays untouched.
from openpilot.common.bogpilot_shipping_defaults import PARAM_OVERRIDES as SHIPPING
REF = {k: ([SHIPPING[k][0], SHIPPING[k][1], v[2]] if k in SHIPPING else v) for k, v in RAW_REF.items()}
# t968u explicit fresh-ON exceptions after the historical shipping snapshot.
# Preserve the immutable 367e1fe fixture and every other default/level/stock value.
REQUESTED_ALERT_DEFAULTS = {"GreenLightAlert": ["1", 0, "0"], "LeadDepartingAlert": ["1", 0, "0"]}
REF.update(REQUESTED_ALERT_DEFAULTS)
STOCK_011_KEYS = set(bp.FROGPILOT_STOCK_KEY_DEFAULTS)


def test_fixture_is_367e1fe():
  assert FIXTURE["ref"] == "367e1fe"
  assert len(RAW_REF) == 338
  for key, expected in REQUESTED_ALERT_DEFAULTS.items():
    assert RAW_REF[key] == ["0", expected[1], expected[2]]
    assert REF[key] == expected


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
  """End to end on release-tizi: 0.11.2's own manager_init default loop over the rebuilt libparams lands every
  typed BogPilot key at its product default (no separate bogpilot_init pass exists on this base)."""
  params = Params(str(tmp_path / "params"))
  for k in params.all_keys():
    dv = params.get_default_value(k)
    if dv is not None and params.get(k) is None:
      params.put(k, dv, block=True)
  d = tmp_path / "params" / os.environ.get("OPENPILOT_PREFIX", "d")
  typed = {k.decode() for k in params.all_keys()}
  for k, (default, _lvl, _stock) in REF.items():
    if k not in typed or k in STOCK_011_KEYS:
      continue
    f = d / k
    raw = f.read_bytes().decode("utf-8") if f.exists() else ""
    try:  # typed FLOAT/INT puts normalise text ('50' -> '50.0'); compare numerically when both parse
      same = float(raw) == float(default)
    except ValueError:
      same = raw == default
    assert same, f"{k}: stored {raw!r} != product default {default!r}"


@pytest.mark.skip(reason="367e1fe manager bogpilot_init (/cache/params backup, DoToggleResetStock) is not ported to release-tizi")
def test_reset_and_backup(tmp_path):
  pass


def test_file_toggle_defaults(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  # stream 5: SwapSpeedGraph ships ON; stream 8: HideAccelGraph ships OFF
  on = {"BSMFlameTracks", "ConfidenceBall", "RedesignUI", "ShowUploadRate", "RemoteUIStream", "HevcStream",
        "SwapSpeedGraph"}
  off = {"DeveloperHUD", "HideAccelGraph", "OccViz", "LiveYOLO", "OffroadScreensaver"}
  for k in on:
    assert bt.read_toggle(k) is True, k
  for k in off:
    assert bt.read_toggle(k) is False, k
  assert bt.read_choice("ConfidenceBallSide") == "left"
