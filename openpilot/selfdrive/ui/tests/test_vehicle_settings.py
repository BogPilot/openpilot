"""Vehicle panel model: fresh/missing/stored params, UI->store->consumer, gates. No device/process access."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.common.params import Params
from openpilot.selfdrive.ui.bogpilot import vehicle_settings as vs
from opendbc.car.tesla_ap1 import regen_brake, toggles


@pytest.fixture
def params(tmp_path, monkeypatch):
  p = Params()
  for k in (vs.DISABLE_LONG_KEY,):
    p.remove(k)
  yield p
  for k in (vs.DISABLE_LONG_KEY,):
    p.remove(k)


def test_key_registered_with_expected_defaults(params):
  for k in (vs.DISABLE_LONG_KEY,):
    params.check_key(k)
  assert params.get_bool(vs.DISABLE_LONG_KEY) is False


def test_disable_long_ui_to_interface_consumer(params, tmp_path):
  assert vs.disable_long_effective(tmp_path, Path(params.get_param_path(vs.DISABLE_LONG_KEY))) is False
  vs.set_disable_long(params, True, tmp_path)
  assert params.get_bool(vs.DISABLE_LONG_KEY) and vs.disable_long_effective(tmp_path, Path(params.get_param_path(vs.DISABLE_LONG_KEY)))
  vs.set_disable_long(params, False, tmp_path)
  assert vs.disable_long_effective(tmp_path, Path(params.get_param_path(vs.DISABLE_LONG_KEY))) is False


def test_disable_long_stale_file_cannot_override(params, tmp_path):
  (tmp_path / vs.DISABLE_LONG_KEY).write_text("1")
  vs.set_disable_long(params, False, tmp_path)
  assert (tmp_path / vs.DISABLE_LONG_KEY).read_text() == "0"
  assert vs.disable_long_effective(tmp_path, Path(params.get_param_path(vs.DISABLE_LONG_KEY))) is False


def test_disable_long_visibility():
  assert not vs.disable_long_visible(None)
  assert vs.disable_long_visible(SimpleNamespace(openpilotLongitudinalControl=True, alphaLongitudinalAvailable=False))
  assert not vs.disable_long_visible(SimpleNamespace(openpilotLongitudinalControl=True, alphaLongitudinalAvailable=True))


@pytest.mark.parametrize("key,mod,attr", [("EnableICIntegration", toggles, "_ic_integration_path"),
                                          ("RegenComfortBrake", regen_brake, "_regen_comfort_path")])
def test_ap1_rows_ui_to_consumer(tmp_path, monkeypatch, key, mod, attr):
  monkeypatch.setattr(mod, attr, tmp_path / key)
  read, write = vs.ap1_rows()[key]
  assert read(vs.AP1_FINGERPRINT) is True            # missing file = AP1 default on
  write(False)
  assert (tmp_path / key).read_text() == "0" and read(vs.AP1_FINGERPRINT) is False
  write(True)
  assert read(vs.AP1_FINGERPRINT) is True
  assert read("TOYOTA_RAV4") is False                 # non-AP1 inert


def test_vehicle_info_from_carparams():
  CP = SimpleNamespace(carFingerprint=vs.AP1_FINGERPRINT, openpilotLongitudinalControl=True, radarUnavailable=False, autoResumeSng=False)
  assert vs.vehicle_info(CP) == {"Detected": vs.AP1_FINGERPRINT, "openpilot Longitudinal Support": "Yes",
                                 "Radar Support": "Yes", "Stop-and-Go Support": "No"}
  assert vs.vehicle_info(None) == {"Detected": "No connected vehicle"}


def test_panel_offers_only_active_rows():
  import pathlib
  src = pathlib.Path(vs.__file__).read_text()
  for dormant in ("TeslaEarly", "TeslaLongControl", "TeslaStalkFollow", "PedalCanBus", "TeslaRadarEnabled"):
    assert dormant not in src.split('"""', 2)[2]
  assert set(vs.ap1_rows()) == {"EnableICIntegration", "RegenComfortBrake"}


def test_unknown_vehicle_is_not_reported_as_detected_support():
  assert vs.vehicle_info(None) == {"Detected": "No connected vehicle"}
  assert vs.vehicle_info(SimpleNamespace(carFingerprint="")) == {"Detected": "No connected vehicle"}


def test_actual_settings_menu_preserves_visuals_and_replaces_cloud():
  source = Path(__file__).parents[1] / "layouts/settings/settings.py"
  text = source.read_text()
  assert 'PanelType.BOGPILOT: PanelInfo(tr_noop("BogPilot"), BogPilotLayout())' in text
  # t1024: Visuals moved into the BogPilot panel (Theme and Appearance / APPEARANCE); it is not a sidebar panel any more.
  assert "BogPilotVisualsLayout" not in text and "BOGPILOT_VISUALS" not in text
  from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
  assert any(pg.key == "appearance" for s in menu_sections() for p in s.pills for pg in p.pages)
  assert "FirehoseLayout" not in text


def test_network_page_does_not_modify_routes_on_refresh():
  source = Path(__file__).parents[3] / "system/ui/widgets/network.py"
  text = source.read_text()
  assert "prime_state" not in text
  assert "set_ipv4_forward" not in text
