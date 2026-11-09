from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest

from openpilot.selfdrive.ui.bogpilot.sidebar_metrics import Reading, device_readings


def device(**kwargs):
  return SimpleNamespace(**({'maxTempC': 54.8, 'thermalStatus': 0, 'cpuUsagePercent': [10, 20, 30, 40],
                            'memoryUsagePercent': 41} | kwargs))


def test_genuine_device_readings():
  assert device_readings(device(), fresh=True) == (Reading('54°C', 'good'), Reading('25%', 'good'), Reading('41%', 'good'))


def test_fahrenheit_original_integer_conversion():
  assert device_readings(device(), fresh=True, fahrenheit=True)[0].value == '129°F'
  assert device_readings(device(maxTempC=-1), fresh=True, fahrenheit=True)[0].value == '31°F'


@pytest.mark.parametrize('fresh,state', [(False, device()), (True, None)])
def test_missing_or_stale_never_fabricates_zero(fresh, state):
  assert device_readings(state, fresh=fresh) == (Reading(), Reading(), Reading())


@pytest.mark.parametrize('value,level', [(0, 'good'), (69, 'good'), (70, 'warning'), (84, 'warning'), (85, 'danger'), (100, 'danger')])
def test_original_usage_thresholds(value, level):
  rows = device_readings(device(cpuUsagePercent=[value], memoryUsagePercent=value), fresh=True)
  assert rows[1:] == (Reading(f'{value}%', level), Reading(f'{value}%', level))


@pytest.mark.parametrize('field,bad,index', [('maxTempC', float('nan'), 0), ('maxTempC', 151, 0),
                                          ('thermalStatus', 4, 0), ('thermalStatus', True, 0),
                                          ('cpuUsagePercent', [], 1), ('cpuUsagePercent', [1, -1], 1),
                                          ('cpuUsagePercent', [101], 1), ('cpuUsagePercent', [True], 1),
                                          ('cpuUsagePercent', [float('inf')], 1), ('memoryUsagePercent', -1, 2),
                                          ('memoryUsagePercent', '50', 2), ('memoryUsagePercent', True, 2)])
def test_malformed_individual_reading_unavailable(field, bad, index):
  assert device_readings(device(**{field: bad}), fresh=True)[index] == Reading()


@pytest.mark.parametrize('severity', [1, 2])
def test_current_thermal_warning_not_softened(severity):
  assert device_readings(device(thermalStatus=SimpleNamespace(raw=severity)), fresh=True)[0].level == 'danger'


def test_capnp_like_thermal_enum():
  assert device_readings(device(thermalStatus=SimpleNamespace(raw=0)), fresh=True)[0].value == '54°C'


def test_sidebar_offroad_metrics_and_onroad_navigation(monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  sidebar = m.Sidebar.__new__(m.Sidebar)
  sidebar._offroad_temp_status, sidebar._cpu_status, sidebar._ram_status = [m.MetricData(n, '--', m.Colors.GRAY) for n in ['TEMP', 'CPU', 'RAM']]
  sidebar._temp_status, sidebar._panda_status = [m.MetricData(n, '--', m.Colors.GRAY) for n in ['TEMP', 'VEHICLE']]
  sidebar._params = SimpleNamespace(get_bool=lambda key: key in {'Fahrenheit', 'ShowCPU', 'ShowMemoryUsage', 'NumericalTemp'})  # t994 visualsTheme gating keys (compiled defaults ON)
  sidebar._update_hardware_metrics(device(), fresh=True)
  assert [r.value for r in [sidebar._offroad_temp_status, sidebar._cpu_status, sidebar._ram_status]] == ['129°F', '25%', '41%']
  calls = []
  sidebar._draw_metric = lambda rect, metric, y: calls.append((metric.label, y))
  monkeypatch.setattr(m, 'ui_state', SimpleNamespace(started=False))
  sidebar._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
  assert calls == [('TEMP', 338), ('CPU', 496), ('RAM', 654)]
  calls.clear()
  m.ui_state.started = True
  sidebar._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
  assert calls == [('TEMP', 338), ('VEHICLE', 496), ('RAM', 654)]


def test_stale_subscription_resets_readings_and_bars(monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  sidebar = m.Sidebar.__new__(m.Sidebar)
  sidebar._offroad_temp_status, sidebar._cpu_status, sidebar._ram_status = [m.MetricData(n, '42', m.Colors.GOOD) for n in ['TEMP', 'CPU', 'RAM']]
  sidebar._params = SimpleNamespace(get_bool=lambda key: False)
  sidebar._net_strength = 5
  sm = SimpleNamespace(valid={'deviceState': True}, alive={'deviceState': False}, updated={'deviceState': False})
  monkeypatch.setattr(m, 'ui_state', SimpleNamespace(sm=sm, recording_audio=False))
  sidebar._update_state()
  assert sidebar._net_strength == 0
  assert all(r.value == '--' for r in [sidebar._offroad_temp_status, sidebar._cpu_status, sidebar._ram_status])


def test_brand_asset_is_authentic_and_stock_navigation_untouched():
  from openpilot.selfdrive.ui.layouts import sidebar as m
  source = Path(m.__file__).read_text()
  assert 'gui_app.texture("bogpilot/button_home.png")' in source
  assert 'HOME_BTN.width / float(self._home_img.width)' in source
  assert 'self._flag_img if ui_state.started else self._home_img' in source
  assert 'self._on_settings_click()' in source and 'self._on_flag_click()' in source
  asset = Path(m.__file__).parents[2] / 'assets/bogpilot/button_home.png'
  # Exact 568fea old BogPilot theme asset, never a generated replacement.
  assert hashlib.sha256(asset.read_bytes()).hexdigest() == '79076f8f2abff168a0ca73099dfa19ffa45e30c8420d72d89a3fa00bfcf9f3bd'
