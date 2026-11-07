"""t956u: genuine default ON, persisted user OFF remains authoritative; no fake radar input."""
from pathlib import Path

import pytest

from openpilot.common.params import Params
from openpilot.common.bogpilot_ap1_profile import AP1_CAR_MODEL, AP1_PARAM_PROFILE, apply_ap1_defaults_once, marker_path, theme_marker_path
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS

KEY = 'AdjacentLeadsUI'


def seed_like_manager(params):
  if params.get(KEY) is None:
    params.put(KEY, params.get_default_value(KEY), block=True)


@pytest.mark.parametrize('saved,expected', [(None, True), (False, False), (True, True)])
def test_real_native_default_and_ap1_profile_preserve_saved_choice(tmp_path, saved, expected):
  p = Params(str(tmp_path / 'native-params'))
  p.put('CarModel', AP1_CAR_MODEL, block=True)
  assert p.get_default_value(KEY) is True
  if saved is not None:
    p.put_bool(KEY, saved, block=True)
  seed_like_manager(p)
  directory = tmp_path / 'bogpilot-files'
  apply_ap1_defaults_once(p, bogpilot_dir=directory, default_table={KEY: '1'}, refresh=False)
  assert marker_path(directory).exists() and theme_marker_path(directory).exists()
  assert p.get_bool(KEY) is expected


def test_subsequent_explicit_off_is_not_reenabled(tmp_path):
  p = Params(str(tmp_path / 'native-params'))
  p.put('CarModel', AP1_CAR_MODEL, block=True)
  seed_like_manager(p)
  directory = tmp_path / 'bogpilot-files'
  apply_ap1_defaults_once(p, bogpilot_dir=directory, default_table={KEY: '1'}, refresh=False)
  p.put_bool(KEY, False, block=True)
  seed_like_manager(p)
  assert apply_ap1_defaults_once(p, bogpilot_dir=directory, default_table={KEY: '1'}, refresh=False) == []
  assert not p.get_bool(KEY)


def test_profile_no_longer_overrides_registered_on_default():
  assert BOGPILOT_PARAMS[KEY][2] == '1'
  assert AP1_PARAM_PROFILE.get(KEY, '1') == '1'


def test_actual_menu_and_visual_consumer_key():
  from openpilot.selfdrive.ui.layouts.settings import bogpilot_visuals
  source = Path(bogpilot_visuals.__file__).read_text()
  assert '("AdjacentLeadsUI", tr_noop("Adjacent Lead Speed Boxes")' in source
  settings = Path(bogpilot_visuals.__file__).with_name('settings.py').read_text()
  assert 'PanelInfo(tr_noop("Visuals"), BogPilotVisualsLayout())' in settings
