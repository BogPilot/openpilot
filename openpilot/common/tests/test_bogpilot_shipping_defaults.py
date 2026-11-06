"""Tests for BogPilot stream-5 shipping defaults + visibility."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))
# C3 frogpilot tests live at frogpilot/common/tests -> parents[2]=frogpilot; also try repo root
REPO = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else ROOT
for p in (ROOT, REPO, REPO / "openpilot", Path(__file__).resolve().parent.parent):
  if str(p) not in sys.path:
    sys.path.insert(0, str(p))


def _load_shipping():
  for mod in (
    "openpilot.common.bogpilot_shipping_defaults",
    "common.bogpilot_shipping_defaults",
    "frogpilot.common.bogpilot_shipping_defaults",
    "bogpilot_shipping_defaults",
  ):
    try:
      return importlib.import_module(mod)
    except ImportError:
      continue
  raise ImportError("bogpilot_shipping_defaults not found")


def test_border_metrics_minimal_on():
  s = _load_shipping()
  val, lvl = s.PARAM_OVERRIDES["BorderMetrics"]
  assert val == "1" and lvl == s.MINIMAL
  assert s.PARAM_OVERRIDES["BlindSpotMetrics"][0] == "1"
  assert s.PARAM_OVERRIDES["BlindSpotMetrics"][1] == s.MINIMAL


def test_developer_surfaces_off_under_developer():
  s = _load_shipping()
  for key in ("DeveloperHUD", "DeveloperWidgets", "DeveloperSidebar"):
    val, lvl = s.PARAM_OVERRIDES[key]
    assert val == "0", key
    assert lvl == s.DEVELOPER, key


def test_sidebar_cpu_gpu_ram_on_at_minimal():
  s = _load_shipping()
  for key in ("SidebarMetrics", "ShowCPU", "ShowGPU", "ShowMemoryUsage"):
    val, lvl = s.PARAM_OVERRIDES[key]
    assert val == "1", key
    assert lvl == s.MINIMAL, key


def test_nudgeless_and_aol_off():
  s = _load_shipping()
  assert s.PARAM_OVERRIDES["NudgelessLaneChange"] == ("0", s.MINIMAL)
  assert s.PARAM_OVERRIDES["AlwaysOnLateral"] == ("0", s.MINIMAL)


def test_tuning_level_unset():
  s = _load_shipping()
  assert s.PARAM_OVERRIDES["TuningLevel"] == ("0", 0)
  assert s.PARAM_OVERRIDES["TuningLevelConfirmed"] == ("0", 0)
  assert "TuningLevel" in s.AP1_PARAM_REMOVE
  assert "TuningLevelConfirmed" in s.AP1_PARAM_REMOVE


def test_model_ui_remains_advanced():
  s = _load_shipping()
  assert s.PARAM_OVERRIDES["ModelUI"][1] == s.ADVANCED


def test_apply_param_overrides_preserves_unknown_and_stock():
  s = _load_shipping()
  rows = [
    ("BorderMetrics", "0", 3, "0"),
    ("OwnerCustom", "9", 1, "9"),
    ("AlwaysOnLateral", "1", 0, "0"),
  ]
  out = s.apply_param_overrides(rows)
  m = s.default_map(out)
  lv = s.level_map(out)
  assert m["BorderMetrics"] == "1" and lv["BorderMetrics"] == 0
  assert m["OwnerCustom"] == "9" and lv["OwnerCustom"] == 1
  assert m["AlwaysOnLateral"] == "0"


def test_ap1_profile_patch_removes_tuning_lock_and_sets_shipping():
  s = _load_shipping()
  profile = {
    "AlwaysOnLateral": "1",
    "TuningLevel": "3",
    "TuningLevelConfirmed": "1",
    "BorderMetrics": "0",
  }
  out = s.patch_ap1_param_profile(profile)
  assert "TuningLevel" not in out
  assert "TuningLevelConfirmed" not in out
  assert out["AlwaysOnLateral"] == "0"
  assert out["BorderMetrics"] == "1"


def test_file_toggle_defaults():
  s = _load_shipping()
  assert s.FILE_TOGGLE_DEFAULTS["DeveloperHUD"] is False
  assert s.FILE_TOGGLE_DEFAULTS["SwapSpeedGraph"] is True
  assert s.FILE_TOGGLE_DEFAULTS["HideAccelGraph"] is False


def test_reparent_targets_include_approved_minimal_toggles():
  s = _load_shipping()
  for key in ("BorderMetrics", "SidebarMetrics", "ShowCPU", "ShowGPU", "ShowMemoryUsage", "SwapSpeedGraph", "HideAccelGraph"):
    assert key in s.REPARENT_TO_CUSTOM_UI
