from pathlib import Path
import importlib.util
import sys

P = Path(__file__).resolve().parents[1] / "phase2_settings_contract.py"
spec = importlib.util.spec_from_file_location("phase2_settings_contract", P)
c = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c
spec.loader.exec_module(c)
ROOT = Path(__file__).resolve().parents[3]

def test_source_contract():
  assert c.audit(ROOT) == []

def test_saved_values_are_never_migration_targets():
  saved = dict.fromkeys(c.CONTRACT, "0")
  saved.update(EngageVolume="37", DisengageVolume="0.000000", AdjacentLeadsUI="0", ScreenRecorder="0")
  original = saved.copy()
  assert c.missing_defaults(saved) == {}
  assert saved == original

def test_missing_only_not_falsy():
  assert "EngageVolume" not in c.missing_defaults({"EngageVolume": ""})
  assert c.missing_defaults({})["AdjacentLeadsUI"] == "1"
  assert c.missing_defaults({})["AlwaysOnLateral"] == "0"
  assert c.missing_defaults({})["NudgelessLaneChange"] == "0"
  assert c.missing_defaults({})["ScreenRecorder"] == "1"
  assert all(k not in c.missing_defaults({}) for k in ("DeveloperHUD", "EnableICIntegration", "OffroadScreensaver"))

def test_metadata_and_dormant_keys_are_not_active():
  keys = list(c.EXCLUDED) + ["NudgelessLaneChange", "OffroadScreensaver", "DeveloperHUD", "Unknown"]
  assert c.eligible(keys) == ()
  assert c.eligible(["EngageVolume", "EnableICIntegration"]) == ("EngageVolume", "EnableICIntegration")

def test_all_volumes_keep_auto_defaults():
  for key in c.VOLUME_KEYS:
    assert c.CONTRACT[key].default == "101"
  assert c.CONTRACT["AlertVolumeControl"].default == "0"

def test_consumer_removed_fails_closed(tmp_path):
  import shutil
  for name in ("bogpilot_params.py", "params_keys_bogpilot.h"):
    d = tmp_path / c.COMMON / name
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / c.COMMON / name, d)
  errors = c.audit(tmp_path)
  assert any("EngageVolume: consumer evidence missing" == e for e in errors)


def test_t968_alert_policy_is_pending_not_false_support():
  assert c.PENDING_ALERT_DEFAULTS == {"GreenLightAlert": "1", "LeadDepartingAlert": "1"}
  assert c.PENDING_ALERT_LABELS["LeadDepartingAlert"] == "Lead Departed Alert"
  assert c.eligible(c.PENDING_ALERT_DEFAULTS) == ()
  assert "GoatScream" not in c.PENDING_ALERT_DEFAULTS
