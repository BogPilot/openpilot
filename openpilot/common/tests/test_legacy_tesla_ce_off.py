"""Conditional Experimental Mode off on every legacy Tesla: default (one-time write), section reset and full reset."""
import pytest

from openpilot.common import bogpilot_ap1_profile as P
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS

LEGACY = ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS")
OTHER = ("TESLA_MODEL_3", "TOYOTA_RAV4", None)


class FakeParams:
  def __init__(self, **vals):
    self.vals = {k: v for k, v in vals.items() if v is not None}
    self.puts = []
    self.blocks = []

  def get(self, key):
    return self.vals.get(key)

  def put(self, key, value, block=False):
    self.vals[key] = value
    self.puts.append(key)
    self.blocks.append(block)

  def invalidate(self):
    pass


def run(p, tmp_path):
  return P.apply_legacy_tesla_ce_off_once(p, bogpilot_dir=tmp_path, refresh=False)


def test_registry_default_is_on_and_the_legacy_value_is_off():
  assert BOGPILOT_PARAMS["ConditionalExperimental"][2] == "1"
  assert P.LEGACY_TESLA_CE_OFF == {"ConditionalExperimental": "0"}
  assert P.AP1_PARAM_PROFILE["ConditionalExperimental"] == "0", "AP1 Model S profile agrees"


@pytest.mark.parametrize("car", LEGACY)
@pytest.mark.parametrize("stored", [None, "1", "1.000000"])
def test_still_default_or_unset_is_written_off_once_on_every_legacy_tesla(tmp_path, car, stored):
  p = FakeParams(CarModel=car, ConditionalExperimental=stored)
  assert run(p, tmp_path) == ["ConditionalExperimental"] and p.vals["ConditionalExperimental"] == "0"
  assert P.legacy_tesla_ce_marker_path(tmp_path).exists()
  p.vals["ConditionalExperimental"] = "1"            # the driver turns it back on afterwards
  assert run(p, tmp_path) == [] and p.vals["ConditionalExperimental"] == "1", "one time only"


@pytest.mark.parametrize("car", OTHER)
def test_other_cars_are_untouched_and_get_no_marker(tmp_path, car):
  p = FakeParams(CarModel=car, ConditionalExperimental="1")
  assert run(p, tmp_path) == [] and p.puts == [] and not P.legacy_tesla_ce_marker_path(tmp_path).exists()
  assert P.legacy_tesla_ce_off_values(p) == {}


def test_ap1_s_after_its_profile_ran_only_writes_an_unset_key(tmp_path):
  P.marker_path(tmp_path).write_text("1\n")
  p = FakeParams(CarModel="TESLA_AP1_MODELS", ConditionalExperimental="1")
  assert run(p, tmp_path) == [] and p.vals["ConditionalExperimental"] == "1"
  P.legacy_tesla_ce_marker_path(tmp_path).unlink()
  p = FakeParams(CarModel="TESLA_AP1_MODELS")
  assert run(p, tmp_path) == ["ConditionalExperimental"]


def test_full_reset_marker_clear_includes_it(tmp_path):
  P.legacy_tesla_ce_marker_path(tmp_path).write_text("1\n")
  P.clear_ap1_defaults_marker(tmp_path)
  assert not P.legacy_tesla_ce_marker_path(tmp_path).exists()


@pytest.mark.parametrize("car", LEGACY)
def test_section_reset_tables_set_it_off_on_every_legacy_tesla(car):
  from openpilot.selfdrive.ui.layouts.settings.phase3_speed_control_settings import slc_reset_profile
  prof = slc_reset_profile(FakeParams(CarModel=car))
  assert prof["ConditionalExperimental"] == "0"


def test_section_reset_tables_preap_gets_no_other_non_slc_profile_key_and_x_matches_s():
  from openpilot.common.bogpilot_ap1_profile import AP1_SLC_KEYS, LEGACY_SLC_PROFILE
  from openpilot.selfdrive.ui.layouts.settings.phase3_speed_control_settings import slc_reset_profile
  allowed = set(AP1_SLC_KEYS) | set(LEGACY_SLC_PROFILE) | {"ConditionalExperimental"}
  assert set(slc_reset_profile(FakeParams(CarModel="TESLA_PREAP_MODELS"))) <= allowed
  assert slc_reset_profile(FakeParams(CarModel="TESLA_AP1_MODELX")) == slc_reset_profile(FakeParams(CarModel="TESLA_AP1_MODELS"))


def test_ce_off_write_blocks_and_lands_before_the_marker(tmp_path):
  """Real 0.11.2 Params puts are asynchronous unless block=True; the once-only marker must come after the value."""
  marker = P.legacy_tesla_ce_marker_path(tmp_path)
  seen = []

  class Ordered(FakeParams):
    def put(self, key, value, block=False):
      seen.append((key, block, marker.exists()))
      super().put(key, value, block)

  p = Ordered(CarModel="TESLA_AP1_MODELX", ConditionalExperimental="1")
  assert run(p, tmp_path) == ["ConditionalExperimental"]
  assert seen == [("ConditionalExperimental", True, False)]
  assert marker.read_text() == "1\n" and not marker.with_name(marker.name + ".tmp").exists()


def test_store_params_passes_block_through():
  calls = []

  class Store:
    def put(self, key, value, *, block=False):
      calls.append((key, value, block))

  sp = P.StoreParams(Store())
  sp.put("ConditionalExperimental", "0", block=True)
  sp.put("ConditionalExperimental", "0")
  assert calls == [("ConditionalExperimental", "0", True), ("ConditionalExperimental", "0", False)]


def test_marker_write_is_fsynced(tmp_path, monkeypatch):
  synced = []
  real = P.os.fsync
  monkeypatch.setattr(P.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
  run(FakeParams(CarModel="TESLA_PREAP_MODELS"), tmp_path)
  assert P.legacy_tesla_ce_marker_path(tmp_path).read_text() == "1\n"
  assert len(synced) == 2, "file and directory"


def test_never_raises():
  class Broken:
    def get(self, key):
      raise RuntimeError
    def put(self, key, value):
      raise RuntimeError
    def invalidate(self):
      pass
  assert P.apply_legacy_tesla_ce_off_once(Broken(), refresh=False) == []
  assert P.legacy_tesla_ce_off_values(Broken()) == {}


def test_real_params_api_round_trip(tmp_path, monkeypatch):
  """The boot path uses the real 0.11.2 Params (typed get, no get_int). Skipped where msgq is not built."""
  try:
    from openpilot.common.params import Params
  except Exception as exc:  # noqa: BLE001
    pytest.skip(f"real Params unavailable here: {type(exc).__name__}")
  assert not hasattr(Params, "get_int")
  params = Params()
  params.put("CarModel", "TESLA_AP1_MODELX")
  params.put_bool("ConditionalExperimental", True, block=True)
  written = P.apply_legacy_tesla_ce_off_once(params, bogpilot_dir=tmp_path)
  assert written == ["ConditionalExperimental"]
  assert params.get_bool("ConditionalExperimental") is False
  assert params.get("ConditionalExperimental") in (False, b"0", "0")
