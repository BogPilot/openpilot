"""Shared BogPilot param store, the common AP1 profile and the onroad toggle formulas (367e1fe)."""
from types import SimpleNamespace

import pytest

from openpilot.common import bogpilot_store
from openpilot.common.bogpilot_store import ParamStore
from openpilot.common.bogpilot_onroad_toggles import onroad_toggles, toggles_signature


class FileOnlyParams:
  """A Params that knows no FrogPilot key (an old libparams_c.so): everything lands in the file store."""
  def check_key(self, key):
    raise KeyError(key)

  def get(self, key, *a, **k):
    return None


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "params_bogpilot"))
  return ParamStore(FileOnlyParams())


def test_defaults_and_roundtrip(store):
  assert store.get("SLCPriority1") == "Navigation"
  assert store.get_bool("SpeedLimitController") is True
  store.put("Offset1", 7)
  assert store.get_int("Offset1") == 7
  store.put_bool("SpeedLimitController", False)
  assert store.get_bool("SpeedLimitController") is False
  store.remove("Offset1")
  assert store.get_int("Offset1") == 5


def test_float_text_and_level_gate(store):
  store.put("EngageVolume", "0.000000")  # the AP1 profile writes this
  assert store.get_int("EngageVolume") == 0
  store.put("CustomPersonalities", True)
  assert store.tuning_level() == 3       # unconfirmed level counts as 3 (367e1fe)
  store.put("TuningLevelConfirmed", "1")
  store.put("TuningLevel", 0)
  assert store.toggle_bool("CustomPersonalities") is False  # level 2 key above level 0 reads its default
  assert store.toggle_bool("SpeedLimitController") is True


def test_cache_ttl_and_invalidate(store):
  cached = ParamStore(FileOnlyParams(), cache_ttl=60)
  assert cached.get_int("Offset2") == store.get_int("Offset2")
  bogpilot_store.write_text("Offset2", "9")
  assert cached.get_int("Offset2") != 9
  cached.invalidate()
  assert cached.get_int("Offset2") == 9


def test_common_ap1_profile_wraps_a_bare_params(store, tmp_path):
  from openpilot.common import bogpilot_ap1_profile as prof

  class BareParams(FileOnlyParams):
    pass

  bogpilot_store.write_text("CarModel", prof.AP1_CAR_MODEL)
  written = prof.apply_ap1_defaults_once(BareParams(), bogpilot_dir=tmp_path / "markers")
  assert written, "profile should apply to an AP1 device through the file store"
  assert store.get_int("EngageVolume") == 0 and store.get_int("DisengageVolume") == 0
  assert store.get_bool("AlertVolumeControl") is True
  assert prof.apply_ap1_defaults_once(BareParams(), bogpilot_dir=tmp_path / "markers") == []


def test_ui_store_is_the_shared_store():
  from openpilot.selfdrive.ui.bogpilot import store as ui_store
  assert issubclass(ui_store.ParamStore, ParamStore)
  from openpilot.selfdrive.ui.bogpilot import ap1_profile
  from openpilot.common import bogpilot_ap1_profile
  assert ap1_profile.AP1_PARAM_PROFILE is bogpilot_ap1_profile.AP1_PARAM_PROFILE


def _cp(long=True, radar=True, fingerprint="TESLA_AP1_MODELS", bsm=True):
  return SimpleNamespace(openpilotLongitudinalControl=long, radarUnavailable=not radar, carFingerprint=fingerprint, enableBsm=bsm)


def test_onroad_toggles_formulas(store):
  t = onroad_toggles(store, _cp())
  # DeveloperUI defaults off, so AdjacentLeadsUI alone does not track adjacent leads (367e1fe)
  assert t.adjacent_lead_tracking is False
  assert t.human_lane_changes is True
  assert t.speed_limit_controller and t.show_speed_limits
  assert t.slc_fallback_previous_speed_limit and not t.slc_fallback_set_speed
  assert t.speed_limit_offset1 == pytest.approx(5 * 0.44704)
  assert t.speed_limit_priority1 == "Navigation" and not t.speed_limit_priority_highest

  store.put_bool("DeveloperUI", True)
  assert onroad_toggles(store, _cp()).adjacent_lead_tracking is True
  assert onroad_toggles(store, _cp(radar=False)).adjacent_lead_tracking is False

  store.put_bool("IsMetric", True)
  assert onroad_toggles(store, _cp()).speed_limit_offset1 == pytest.approx(5 / 3.6)

  no_long = onroad_toggles(store, _cp(long=False))
  assert not no_long.speed_limit_controller and no_long.speed_limit_offset1 == 0
  assert not no_long.human_lane_changes and not no_long.custom_personalities


def test_custom_personalities(store):
  assert onroad_toggles(store, _cp()).aggressive_follow == pytest.approx(1.25)
  store.put_bool("CustomPersonalities", True)
  store.put("AggressiveFollow", 9.0)
  t = onroad_toggles(store, _cp())
  assert t.custom_personalities and t.aggressive_follow == pytest.approx(3.0)  # clipped to MAX_T_FOLLOW


def test_signature_changes(store):
  before = toggles_signature(store)
  store.put("Offset3", 12)
  assert toggles_signature(store) != before
