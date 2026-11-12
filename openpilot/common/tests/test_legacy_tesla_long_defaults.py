"""rc5 legacy Tesla long-tune defaults (the stored 0.9.7 Gas/Brake profiles and driving personalities): values and migration rule."""
import json
from pathlib import Path
import pytest
from openpilot.common import bogpilot_ap1_profile as P
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS

# initData.params of a logged 0.9.7 drive and the bench device, read-only (no secret keys)
STORED_0_9_7 = {
  "LongitudinalTune": "1", "AccelerationProfile": "2", "DecelerationProfile": "2", "HumanAcceleration": "1", "HumanFollowing": "1",
  "CustomPersonalities": "1",
  "AggressivePersonalityProfile": "1", "StandardPersonalityProfile": "1", "RelaxedPersonalityProfile": "1",
  "AggressiveFollow": "1.250000", "StandardFollow": "1.450000", "RelaxedFollow": "2.000000",
  "AggressiveJerkAcceleration": "50.000000", "AggressiveJerkDeceleration": "50.000000", "AggressiveJerkDanger": "100.000000",
  "AggressiveJerkSpeed": "50.000000", "AggressiveJerkSpeedDecrease": "50.000000",
  "StandardJerkAcceleration": "100.000000", "StandardJerkDeceleration": "100.000000", "StandardJerkDanger": "100.000000",
  "StandardJerkSpeed": "100.000000", "StandardJerkSpeedDecrease": "100.000000",
  "RelaxedJerkAcceleration": "100.000000", "RelaxedJerkDeceleration": "100.000000", "RelaxedJerkDanger": "100.000000",
  "RelaxedJerkSpeed": "100.000000", "RelaxedJerkSpeedDecrease": "100.000000",
}
ALL_KEYS = {k: v for group in P.LEGACY_TESLA_LONG_PROFILE.values() for k, v in group.items()}


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


def run(p, tmp_path):
  return P.apply_legacy_tesla_long_defaults_once(p, bogpilot_dir=tmp_path, refresh=False)


def test_profile_is_exactly_0_9_7_stored_values():
  assert set(ALL_KEYS) == set(STORED_0_9_7)
  for key, value in ALL_KEYS.items():
    assert P.values_equal(STORED_0_9_7[key], value), key


def test_profile_keys_are_registered_non_secret_and_not_in_the_never_list():
  for key in ALL_KEYS:
    assert key in BOGPILOT_PARAMS and key not in P.NEVER_PROFILE_KEYS


def test_adoption_file_names_match_the_consumers():
  from openpilot.selfdrive.controls.lib import phase3_long_accel as L, phase3_following as F
  assert set(P.LEGACY_TESLA_LONG_PROFILE) == {L.PROFILE_ACK, F.PERSONALITY_ACK, F.HUMAN_FOLLOWING_ACK}
  assert set(F.PERSONALITY_KEYS) | set(F.HUMAN_FOLLOWING_KEYS) | set(L.PROFILE_KEYS) >= set(ALL_KEYS)


def test_platforms_are_the_three_tesla_ap1_platforms_and_not_ap2():
  assert P.LEGACY_TESLA_PLATFORMS == {"TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"}
  from opendbc.car.tesla_ap1.values import CAR
  assert {str(c) for c in CAR} == P.LEGACY_TESLA_PLATFORMS      # a new platform must be decided on purpose


@pytest.mark.parametrize("model", sorted(P.LEGACY_TESLA_PLATFORMS))
def test_fresh_device_gets_the_whole_profile_once(model, tmp_path):
  p = FakeParams(CarModel=model)
  written = run(p, tmp_path)
  assert set(written) == set(ALL_KEYS)
  for key, value in ALL_KEYS.items():
    assert P.values_equal(p.vals[key], value), key
  marker = json.loads(P.legacy_tesla_long_marker_path(tmp_path).read_text())
  assert set(marker["written"]) == set(ALL_KEYS) and marker["kept"] == {} and marker["skipped_groups"] == []
  p.vals["DecelerationProfile"] = "0"          # the owner changes it afterwards: never reverted
  assert run(p, tmp_path) == [] and p.vals["DecelerationProfile"] == "0"


def test_persistent_fingerprint_is_enough_when_car_model_is_unset(tmp_path, monkeypatch):
  monkeypatch.setattr(P, "_persistent_fingerprint", lambda params: "TESLA_PREAP_MODELS")
  assert set(run(FakeParams(), tmp_path)) == set(ALL_KEYS)


@pytest.mark.parametrize("model", ["TESLA_AP2_MODELS", "TOYOTA_COROLLA_TSS2", "", None])
def test_other_platforms_and_unknown_car_get_nothing_and_retry_later(model, tmp_path):
  p = FakeParams(**({"CarModel": model} if model else {}))
  assert run(p, tmp_path) == [] and p.puts == []
  assert not P.legacy_tesla_long_marker_path(tmp_path).exists()      # unknown car: tried again next boot


def test_097_device_snapshot_is_a_no_op(tmp_path):
  p = FakeParams(CarModel="TESLA_AP1_MODELS", TuningLevel="3", TuningLevelConfirmed="1", **STORED_0_9_7)
  tmp_path.joinpath(P.MARKER_NAME).write_text("1\n")          # AP1DefaultsApplied is on the bench
  assert run(p, tmp_path) == [] and p.puts == []
  assert json.loads(P.legacy_tesla_long_marker_path(tmp_path).read_text())["written"] == {}


def test_custom_values_are_never_overwritten(tmp_path):
  p = FakeParams(CarModel="TESLA_PREAP_MODELS", AccelerationProfile="3", RelaxedFollow="1.9", AggressiveJerkAcceleration="70",
                 HumanAcceleration="0", LongitudinalTune="0", StandardFollow="1.6")
  written = run(p, tmp_path)
  for key, value in dict(AccelerationProfile="3", RelaxedFollow="1.9", AggressiveJerkAcceleration="70", HumanAcceleration="0",
                         LongitudinalTune="0", StandardFollow="1.6").items():
    assert p.vals[key] == value and key not in written
  assert p.vals["DecelerationProfile"] == "2" and p.vals["CustomPersonalities"] == "1"       # the untouched rest is filled
  kept = json.loads(P.legacy_tesla_long_marker_path(tmp_path).read_text())["kept"]
  assert kept["AccelerationProfile"] == "3" and kept["RelaxedFollow"] == "1.9" and kept["LongitudinalTune"] == "0"


def test_a_group_the_owner_adopted_is_skipped_as_a_whole(tmp_path):
  p = FakeParams(CarModel="TESLA_AP1_MODELX", Phase3LongAccelProfilesEnabled="1", DecelerationProfile="1", AccelerationProfile="2")
  written = run(p, tmp_path)
  assert p.vals["DecelerationProfile"] == "1" and "DecelerationProfile" not in written      # their Eco stays
  assert "HumanAcceleration" not in written and "LongitudinalTune" not in written
  assert p.vals["CustomPersonalities"] == "1" and p.vals["RelaxedFollow"] == "2.0"          # other groups still filled
  assert json.loads(P.legacy_tesla_long_marker_path(tmp_path).read_text())["skipped_groups"] == ["Phase3LongAccelProfilesEnabled"]


def test_adoption_file_on_disk_counts_too(tmp_path):
  tmp_path.joinpath("Phase3PersonalitiesEnabled").write_text("1")
  p = FakeParams(CarModel="TESLA_PREAP_MODELS", RelaxedFollow="1.75")
  run(p, tmp_path)
  assert p.vals["RelaxedFollow"] == "1.75" and "CustomPersonalities" not in p.vals


def test_default_equal_value_is_treated_as_unmodified_on_preap_and_x_documented_limit(tmp_path):
  p = FakeParams(CarModel="TESLA_PREAP_MODELS", DecelerationProfile="1")        # registry default (Eco)
  run(p, tmp_path)
  assert p.vals["DecelerationProfile"] == "2"


def test_ap1_s_after_its_profile_ran_keeps_a_value_chosen_back_at_the_default(tmp_path):
  # AP1DefaultsApplied already rewrote every still-default value once, so Eco (the default) now is the owner's choice
  tmp_path.joinpath(P.MARKER_NAME).write_text("1\n")
  p = FakeParams(CarModel="TESLA_AP1_MODELS", DecelerationProfile="1", RelaxedFollow="1.75")
  written = run(p, tmp_path)
  assert p.vals["DecelerationProfile"] == "1" and p.vals["RelaxedFollow"] == "1.75"
  assert "DecelerationProfile" not in written and "HumanAcceleration" in written      # unset keys are still filled


def test_works_after_the_ap1_profile_in_the_same_boot(tmp_path):
  p = FakeParams(CarModel="TESLA_AP1_MODELS")
  P.apply_ap1_defaults_once(p, bogpilot_dir=tmp_path, default_table={k: v[2] for k, v in BOGPILOT_PARAMS.items()}, refresh=False)
  run(p, tmp_path)
  for key, value in ALL_KEYS.items():
    assert P.values_equal(p.vals[key], value), key


def test_toggle_reset_clears_the_marker_so_a_shipping_reset_gets_the_profile_again(tmp_path):
  p = FakeParams(CarModel="TESLA_AP1_MODELS")
  run(p, tmp_path)
  assert P.legacy_tesla_long_marker_path(tmp_path).exists()
  P.clear_ap1_defaults_marker(tmp_path)
  assert not P.legacy_tesla_long_marker_path(tmp_path).exists()


def test_boot_hook_runs_it_and_stock_reset_suppresses_it(tmp_path):
  from openpilot.system.manager.bogpilot_startup import after_defaults, StartupResult
  p = FakeParams(CarModel="TESLA_AP1_MODELX")
  r = after_defaults(p, file_root=tmp_path)
  assert any(e.startswith("legacy-tesla-long:") and e != "legacy-tesla-long:0" for e in r.events), r.events
  assert p.vals["DecelerationProfile"] == "2"
  q = FakeParams(CarModel="TESLA_AP1_MODELX")
  d2 = tmp_path / "stock"; d2.mkdir()
  (d2 / "AP1StockReset1").write_text("1")
  r2 = after_defaults(q, file_root=d2)
  assert "ap1:suppressed-stock-reset" in r2.events and not (set(q.puts) & set(ALL_KEYS))


def test_never_raises(tmp_path):
  class Bad:
    def get(self, key):
      raise RuntimeError(key)
    def invalidate(self):
      pass
  assert P.apply_legacy_tesla_long_defaults_once(Bad(), bogpilot_dir=tmp_path) == []
