"""BogPilot params: defaults match the 367e1fe BogPilot table with two BogPilot standing-rule overrides (HolidayThemes off, TuningLevel Developer).

fixtures/bogpilot_defaults_367e1fe.json is a snapshot of 367e1fe bogpilot_default_params +
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
# Product (bogpilot-tesla-c3x): approved shipping overlay on top of the 367e1fe snapshot
# (AOL off, metrics on, TuningLevel intentionally unset 0/0, ...). The fixture itself stays untouched.
from openpilot.common.bogpilot_shipping_defaults import PARAM_OVERRIDES as SHIPPING
REF = {k: ([SHIPPING[k][0], SHIPPING[k][1], v[2]] if k in SHIPPING else v) for k, v in RAW_REF.items()}
# explicit fresh-ON exceptions after the historical shipping snapshot.
# Preserve the immutable 367e1fe fixture and every other default/level/stock value.
REQUESTED_ALERT_DEFAULTS = {"GreenLightAlert": ["1", 0, "0"], "LeadDepartingAlert": ["1", 0, "0"],
                            "LoudBlindspotAlert": ["1", 0, "0"], "SpeedLimitChangedAlert": ["1", 0, "0"]}
REF.update(REQUESTED_ALERT_DEFAULTS)
# two default-ON rows move from Developer (3) to Minimal (0); default and stock value unchanged.
REQUESTED_MINIMAL_LEVELS = {"AdjacentLeadsUI": ["1", 0, "0"], "NumericalTemp": ["1", 0, "0"]}
REF.update(REQUESTED_MINIMAL_LEVELS)
# BogPilot-added key with no 367e1fe row: the cruise engage / disengage chimes, fresh install ON, Minimal level.
BOGPILOT_ADDED_KEYS = {"CruiseEngageDisengageChimes": ["1", 0, "1"]}
REF.update(BOGPILOT_ADDED_KEYS)
# AP1 standstill tap-from-0 speed, stored in m/s (UI whole mph 5-30 or km/h 8-48, default 15 mph = 6.7056 m/s).
# New in 0.11; not in the 367e1fe snapshot. Replaced AP1TapFromZeroMph (whole mph, default "15").
REQUESTED_AP1_TAP_FROM_ZERO = {"AP1TapFromZeroMs": ["6.7056", 1, "6.7056"]}
REF.update(REQUESTED_AP1_TAP_FROM_ZERO)
# Lead-aware accel cap for the legacy Teslas (NAP-style Adaptive Accel Limits): new in this branch, OFF by default, Standard level.
REQUESTED_ADAPTIVE_ACCEL_LEAD = {"AdaptiveAccelLead": ["0", 2, "0"]}
REF.update(REQUESTED_ADAPTIVE_ACCEL_LEAD)
# mapd v2 (map curve speed preview for CSC, live speed limits during downloads): both new, OFF by default.
REQUESTED_MAPD_V2 = {"CSCMapCurvature": ["0", 2, "0"], "MapdV2": ["0", 0, "0"]}
REF.update(REQUESTED_MAPD_V2)
# Smooth Curve Braking for the AP1 curve brake: new in this branch, OFF by default, Standard level.
REQUESTED_CSC_TESLA_SMOOTHING = {"CSCTeslaSmoothing": ["0", 2, "0"]}
REF.update(REQUESTED_CSC_TESLA_SMOOTHING)
# SLC look-ahead horizon: 5 s default, 0 = off. Fixture stays at the 367e1fe "0".
REQUESTED_SLC_LOOKAHEAD = {"SLCLookaheadLower": ["5", 2, "0"]}
REF.update(REQUESTED_SLC_LOOKAHEAD)
# FPS Display registers OFF (the 367e1fe snapshot had it on); level and stock value unchanged.
REQUESTED_FPS_OFF = {"FPSCounter": ["0", 3, "0"]}
REF.update(REQUESTED_FPS_OFF)
# Camera View registers Auto (the 367e1fe snapshot had Wide, 3); level and stock value unchanged.
REQUESTED_CAMERA_AUTO = {"CameraView": ["0", 2, "0"]}
REF.update(REQUESTED_CAMERA_AUTO)
# Pedals on Screen registers on (the 367e1fe snapshot had it off); level and stock value unchanged.
REQUESTED_PEDALS_ON = {"PedalsOnUI": ["1", 1, "0"]}
REF.update(REQUESTED_PEDALS_ON)
# Driver Camera When In Reverse registers on, stock value on too (the 367e1fe snapshot had both off); level unchanged.
REQUESTED_DRIVER_CAMERA_ON = {"DriverCamera": ["1", 1, "1"]}
REF.update(REQUESTED_DRIVER_CAMERA_ON)
# Automatically Update Maps registers Weekly (the 367e1fe snapshot had Monthly, 2); level and stock value unchanged.
REQUESTED_MAPS_WEEKLY = {"PreferredSchedule": ["1", 0, "0"]}
REF.update(REQUESTED_MAPS_WEEKLY)
# Speed Limit Offsets register the BogPilot values 4/5/5/5/7/8/10 mph (slc-offset-defaults; the 367e1fe snapshot had
# 5/5/5/5/10/10/10). Only Offset1, Offset5 and Offset6 differ; level and stock value unchanged.
REQUESTED_SLC_OFFSETS = {"Offset1": ["4", 0, "0"], "Offset5": ["7", 0, "0"], "Offset6": ["8", 0, "0"]}
REF.update(REQUESTED_SLC_OFFSETS)
STOCK_011_KEYS = set(bp.BOGPILOT_STOCK_KEY_DEFAULTS)
# Screen Timeout (Onroad) registers 10 s, the stock value (the 367e1fe snapshot had the 0.9.7 value 30).
REQUESTED_SCREEN_TIMEOUT_ONROAD = {"ScreenTimeoutOnroad": ["10", 2, "10"]}
REF.update(REQUESTED_SCREEN_TIMEOUT_ONROAD)


def test_fixture_is_367e1fe():
  assert FIXTURE["ref"] == "367e1fe"
  assert len(RAW_REF) == 338
  for key, expected in REQUESTED_ALERT_DEFAULTS.items():
    assert RAW_REF[key] == ["0", expected[1], expected[2]]
    assert REF[key] == expected
  for key, expected in REQUESTED_MINIMAL_LEVELS.items():
    assert RAW_REF[key] == ["1", 3, "0"]   # the immutable snapshot keeps the 367e1fe level
    assert REF[key] == expected
  assert RAW_REF["FPSCounter"] == ["1", 3, "0"]
  assert REF["FPSCounter"] == ["0", 3, "0"]
  assert RAW_REF["SLCLookaheadLower"] == ["0", 2, "0"]
  assert REF["SLCLookaheadLower"] == ["5", 2, "0"]
  assert RAW_REF["CameraView"] == ["3", 2, "0"]
  assert REF["CameraView"] == ["0", 2, "0"]
  assert RAW_REF["PedalsOnUI"] == ["0", 1, "0"]
  assert REF["PedalsOnUI"] == ["1", 1, "0"]
  assert RAW_REF["DriverCamera"] == ["0", 1, "0"]
  assert REF["DriverCamera"] == ["1", 1, "1"]
  for key, expected in REQUESTED_SCREEN_TIMEOUT_ONROAD.items():
    assert RAW_REF[key] == ["30", 2, "10"]  # 0.9.7 / 367e1fe snapshot stays 30
    assert REF[key] == expected


@pytest.mark.parametrize("key", sorted(REF))
def test_default_matches_367e1fe(key):
  default, level, stock = REF[key]
  if key in STOCK_011_KEYS:
    mine = bp.BOGPILOT_STOCK_KEY_DEFAULTS[key]
  else:
    _flags, _type, d, lvl, s = bp.BOGPILOT_PARAMS[key]
    mine = (d, lvl, s)
  assert mine == (default, level, stock), f"{key}: {mine} != 367e1fe {(default, level, stock)}"


def test_no_extra_defaults():
  rows = {k: [d, lvl, s] for k, d, lvl, s in bp.bogpilot_defaults()}
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
  """The libparams_c.so in use must be the rebuilt one, or clearAll wipes every BogPilot param."""
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
  # ShowAccelGraph / LowerSpeedLimitsBox ship OFF; SwapSpeedGraph remains a legacy file default ON.
  # telemetryAudit: cloud-only orphans (upload rate / remote stream / HEVC stream) ship OFF (no menus, no uploader).
  on = {"BSMFlameTracks", "ConfidenceBall", "RedesignUI", "SwapSpeedGraph"}
  off = {"DeveloperHUD", "HideAccelGraph", "ShowAccelGraph", "LowerSpeedLimitsBox", "OccViz", "LiveYOLO", "OffroadScreensaver",
         "ShowUploadRate", "RemoteUIStream", "HevcStream"}
  for k in on:
    assert bt.read_toggle(k) is True, k
  for k in off:
    assert bt.read_toggle(k) is False, k
  assert bt.read_choice("ConfidenceBallSide") == "left"


def test_driving_personality_button_and_profiles_default_on():
  """On the road no personality button was drawn because OnroadDistanceButton defaulted to 0
  (QOLVisuals, the parent CustomUI and the three personality profiles were already on)."""
  from openpilot.common.bogpilot_store import registry_default, registry_level
  from openpilot.common.bogpilot_shipping_defaults import PARAM_OVERRIDES
  from openpilot.selfdrive.ui.bogpilot.bogpilot_defaults import DEFAULT_ROWS
  for key in ("OnroadDistanceButton", "QOLVisuals", "CustomUI", "AggressivePersonalityProfile",
              "StandardPersonalityProfile", "RelaxedPersonalityProfile"):
    assert registry_default(key) == "1", key
  assert PARAM_OVERRIDES["OnroadDistanceButton"] == ("1", 0)
  assert {r[0]: r[1] for r in DEFAULT_ROWS}["OnroadDistanceButton"] == "1"
  assert registry_level("OnroadDistanceButton") == 0   # honoured at every tuning level, a fresh install included
