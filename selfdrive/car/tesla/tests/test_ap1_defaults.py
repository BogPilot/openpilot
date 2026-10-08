"""One-time AP1 toggle profile (selfdrive/car/tesla/ap1_defaults.py)."""
import re
from pathlib import Path

import pytest

from cereal import car
from openpilot.common.params import Params
from openpilot.frogpilot.common.frogpilot_variables import EXCLUDED_KEYS, frogpilot_default_params
from openpilot.selfdrive.car.tesla import ap1_defaults as ap1
from openpilot.selfdrive.car.tesla.values import CAR

ROOT = Path(__file__).resolve().parents[4]
TABLE = {k: (v.decode() if isinstance(v, bytes) else v) for k, v, _, _ in frogpilot_default_params}

# The deny-list the profile was built against.
REQUIRED_DENY = {
  "GithubSshKeys", "GithubUsername", "MapboxPublicKey", "MapboxSecretKey", "AMapKey1", "AMapKey2", "WeatherToken",
  "SecOCKey", "SecOCKeys", "KonikDongleId", "DiscordUsername", "GsmApn", "FrogPilotStats",
  "FavoriteDestinations", "MapsSelected", "SearchInput", "RecordFront",
  "CarMake", "CarModel", "CarModelName", "ForceFingerprint",
  "SteerRatio", "SteerDelay", "SteerFriction", "SteerKP", "SteerLatAccel", "LongitudinalActuatorDelay", "StartAccel",
  "StopAccel", "StoppingDecelRate", "VEgoStarting", "VEgoStopping", "LiveDelay",
  "ThemesDownloaded", "ShownToggleDescriptions", "ExperimentalModeConfirmed", "UpdatedToggles", "MinimumBackupSize",
  "SshEnabled", "TetheringEnabled", "GsmRoaming", "NoUploads", "NoLogging", "DisableOnroadUploads", "UseKonikServer",
  "HigherBitrate", "DeviceManagement", "AutomaticUpdates", "IsMetric", "LastKnownTime", "Model",
}


@pytest.fixture
def env(tmp_path):
  params = Params(str(tmp_path / "params"))
  for key, value in TABLE.items():
    params.put(key, value)  # what manager.py writes on a fresh device
  bp_dir = tmp_path / "params_bogpilot"
  return params, bp_dir


def run(params, bp_dir):
  return ap1.apply_ap1_defaults_once(params, bogpilot_dir=bp_dir, default_table=TABLE, refresh=False)


def test_profile_keys_exist_in_table_and_params():
  probe = Params()
  for key in ap1.AP1_PARAM_PROFILE:
    assert key in TABLE, key
    probe.check_key(key)  # a key unknown to params.cc would crash the prebuilt params_pyx.so


def test_profile_only_lists_changes():
  for key, value in ap1.AP1_PARAM_PROFILE.items():
    assert not ap1.values_equal(value, TABLE[key]), f"{key} equals the table default"


def test_no_denied_or_private_key_in_profile():
  assert REQUIRED_DENY <= ap1.NEVER_PROFILE_KEYS
  for key in ap1.AP1_PARAM_PROFILE:
    assert key not in ap1.NEVER_PROFILE_KEYS, key
    assert key not in EXCLUDED_KEYS, key
    assert not key.endswith("Stock"), key


def test_file_toggles_are_known_bogpilot_files():
  assert set(ap1.AP1_FILE_TOGGLE_PROFILE) <= set(ap1.FILE_TOGGLE_KEYS)
  assert ap1.MARKER_NAME not in ap1.FILE_TOGGLE_KEYS
  assert ap1.AP1_FILE_TOGGLE_PROFILE == {"DeveloperHUD": "1"}


def test_standing_preferences():
  # Increase Stopped Distance stays 0: not in the profile, and the table default is 0.
  assert "IncreasedStoppedDistance" not in ap1.AP1_PARAM_PROFILE
  assert TABLE["IncreasedStoppedDistance"] == "0"
  # Lead metrics off because the Developer HUD shows lead data; the lead marker is left as-is.
  assert ap1.AP1_PARAM_PROFILE["LeadInfo"] == "0"
  assert "HideLeadMarker" not in ap1.AP1_PARAM_PROFILE
  # Developer tuning level, confirmed so the first-open popup does not drop it to Minimal.
  assert ap1.AP1_PARAM_PROFILE["TuningLevel"] == "3"
  assert ap1.AP1_PARAM_PROFILE["TuningLevelConfirmed"] == "1"


def test_ap1_car_model_name_matches_platform():
  assert ap1.AP1_CAR_MODEL == str(CAR.TESLA_AP1_MODELS)


@pytest.mark.parametrize("car_model", [None, "TESLA_AP2_MODELS", "TESLA_MODELS_RAVEN", "TOYOTA_RAV4"])
def test_only_fires_for_ap1(env, car_model):
  params, bp_dir = env
  if car_model is not None:
    params.put("CarModel", car_model)
  assert run(params, bp_dir) == []
  assert not ap1.marker_path(bp_dir).exists()
  assert not (bp_dir / "DeveloperHUD").exists()
  for key in ap1.AP1_PARAM_PROFILE:
    assert params.get(key, encoding="utf-8") == TABLE[key]


def test_applies_on_fresh_ap1(env):
  params, bp_dir = env
  params.put("CarModel", ap1.AP1_CAR_MODEL)
  written = run(params, bp_dir)
  assert set(written) == set(ap1.AP1_PARAM_PROFILE) | set(ap1.AP1_FILE_TOGGLE_PROFILE)
  for key, value in ap1.AP1_PARAM_PROFILE.items():
    assert params.get(key, encoding="utf-8") == value
  assert (bp_dir / "DeveloperHUD").read_text() == "1"
  assert ap1.marker_path(bp_dir).exists()
  assert params.get("CarModel", encoding="utf-8") == ap1.AP1_CAR_MODEL
  assert params.get_int("IncreasedStoppedDistance") == 0


def test_applies_from_persistent_fingerprint(env):
  params, bp_dir = env
  cp = car.CarParams.new_message(carFingerprint=ap1.AP1_CAR_MODEL)
  params.put("CarParamsPersistent", cp.to_bytes())
  assert run(params, bp_dir)
  assert params.get("TuningLevel", encoding="utf-8") == "3"


def test_never_overwrites_owner_changes(env):
  params, bp_dir = env
  params.put("CarModel", ap1.AP1_CAR_MODEL)
  params.put("RelaxedFollow", "1.5")
  params.put("CustomColors", "frog")
  params.put("DisengageVolume", "80")
  bp_dir.mkdir(parents=True)
  (bp_dir / "DeveloperHUD").write_text("0")
  written = run(params, bp_dir)
  assert "RelaxedFollow" not in written and "CustomColors" not in written and "DeveloperHUD" not in written
  assert params.get("RelaxedFollow", encoding="utf-8") == "1.5"
  assert params.get("CustomColors", encoding="utf-8") == "frog"
  assert params.get("DisengageVolume", encoding="utf-8") == "80"
  assert (bp_dir / "DeveloperHUD").read_text() == "0"
  # untouched keys still got the profile
  assert params.get("LeadInfo", encoding="utf-8") == "0"


def test_numeric_default_formats_count_as_default(env):
  params, bp_dir = env
  params.put("CarModel", ap1.AP1_CAR_MODEL)
  params.put("Offset2", "5.000000")  # UI float format of the table default "5"
  run(params, bp_dir)
  assert params.get("Offset2", encoding="utf-8") == ap1.AP1_PARAM_PROFILE["Offset2"]


def test_confirmed_tuning_level_is_respected(env):
  params, bp_dir = env
  params.put("CarModel", ap1.AP1_CAR_MODEL)
  params.put("TuningLevelConfirmed", "1")  # owner already picked Minimal (TuningLevel 0 == table default)
  written = run(params, bp_dir)
  assert "TuningLevel" not in written and "TuningLevelConfirmed" not in written
  assert params.get_int("TuningLevel") == 0


def test_runs_once(env):
  params, bp_dir = env
  params.put("CarModel", ap1.AP1_CAR_MODEL)
  assert run(params, bp_dir)
  params.put("LeadInfo", TABLE["LeadInfo"])  # owner turns it back on
  (bp_dir / "DeveloperHUD").unlink()
  assert run(params, bp_dir) == []
  assert params.get("LeadInfo", encoding="utf-8") == TABLE["LeadInfo"]
  assert not (bp_dir / "DeveloperHUD").exists()


def test_reset_clears_marker_and_reapplies(env):
  params, bp_dir = env
  params.put("CarModel", ap1.AP1_CAR_MODEL)
  assert run(params, bp_dir)
  for key, value in TABLE.items():  # DoToggleReset puts the table defaults back
    if key not in EXCLUDED_KEYS and key != "CarModel":
      params.put(key, value)
  assert run(params, bp_dir) == []
  ap1.clear_ap1_defaults_marker(bp_dir)
  assert not ap1.marker_path(bp_dir).exists()
  assert run(params, bp_dir)
  assert params.get("LeadInfo", encoding="utf-8") == "0"


def test_hook_never_raises():
  class Broken:
    def get(self, *a, **k):
      raise RuntimeError("boom")
  assert ap1.apply_ap1_defaults_once(Broken(), bogpilot_dir=Path("/nonexistent/x"), default_table=TABLE, refresh=False) == []


def test_manager_wiring():
  src = (ROOT / "system/manager/manager.py").read_text()
  loop_end = src.index('params.remove("DoToggleResetStock")')
  hook = src.index("apply_ap1_defaults_once(params)")
  assert loop_end < hook < src.index("frogpilot_boot_functions(build_metadata")
  block = src[loop_end:hook]
  assert re.search(r"if reset_toggles:\s*\n\s*clear_ap1_defaults_marker\(\)", block)
  assert "reset_toggles_stock" not in block  # a reset to stock leaves the marker alone


def test_frogpilot_process_wiring():
  src = (ROOT / "frogpilot/frogpilot_process.py").read_text()
  block = src[src.index('if params_memory.get_bool("FrogPilotTogglesUpdated")'):]
  block = block[:block.index("frogpilot_variables.update(")]
  assert re.search(r"if not started:\s*\n\s*apply_ap1_defaults_once\(params, refresh=False\)", block)
