"""Onroad sidebar middle box: Vehicle Online (default) or CPU, chosen by tapping it (SidebarVehicleSlot file choice)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.common import bogpilot_toggles as bt
from openpilot.selfdrive.ui.bogpilot import sidebar_metrics as sm
from openpilot.selfdrive.ui.bogpilot.sidebar_metrics import Reading, chip_reading, device_readings

KEY = "SidebarVehicleSlot"
ROOT = Path(__file__).resolve().parents[3]


def device(**kwargs):
  return SimpleNamespace(**({'maxTempC': 54.8, 'thermalStatus': 0, 'cpuUsagePercent': [10, 20, 30, 40],
                            'memoryUsagePercent': 41} | kwargs))


@pytest.fixture
def files(tmp_path, monkeypatch):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  return tmp_path


# --- the choice ---

def test_default_is_vehicle_status(files):
  assert bt.FILE_CHOICES[KEY] == ("vehicle", ("vehicle", "cpu"))
  assert not (files / KEY).exists()
  assert sm.read_vehicle_slot() == "vehicle"


@pytest.mark.parametrize("text,choice", [(None, "vehicle"), ("", "vehicle"), ("vehicle", "vehicle"), ("cpu", "cpu"),
                                         ("cpu\n", "cpu"), (b"cpu", "cpu"), ("CPU", "vehicle"), ("gpu", "vehicle"),
                                         ("1", "vehicle"), (3, "vehicle")])
def test_only_an_exact_cpu_choice_shows_cpu(text, choice):
  assert sm.vehicle_slot_choice(text) == choice


def test_junk_or_unreadable_file_is_vehicle(files):
  (files / KEY).write_text("garbage")
  assert sm.read_vehicle_slot() == "vehicle"
  (files / KEY).unlink()
  (files / KEY).mkdir()                   # unreadable as a file
  assert sm.read_vehicle_slot() == "vehicle"


def test_tap_cycles_vehicle_cpu_vehicle():
  assert sm.cycle_vehicle_slot("vehicle") == "cpu"
  assert sm.cycle_vehicle_slot("cpu") == "vehicle"
  assert sm.cycle_vehicle_slot("junk") == "vehicle"


def test_choice_persists_in_its_file(files):
  assert sm.write_vehicle_slot("cpu")
  assert (files / KEY).read_text().strip() == "cpu"
  assert sm.read_vehicle_slot() == "cpu"
  assert sm.write_vehicle_slot("vehicle")
  assert sm.read_vehicle_slot() == "vehicle"


def test_no_panda_always_takes_the_box_back():
  assert sm.vehicle_slot_shown("cpu", panda_seen=True) == "cpu"
  assert sm.vehicle_slot_shown("cpu", panda_seen=False) == "vehicle"
  assert sm.vehicle_slot_shown("vehicle", panda_seen=True) == "vehicle"
  assert sm.vehicle_slot_shown("vehicle", panda_seen=False) == "vehicle"


# --- CPU value: the existing source, aggregation and thresholds ---

def test_cpu_is_the_mean_per_core_load():
  assert device_readings(device(cpuUsagePercent=[10, 20, 30, 41]), fresh=True)[1] == Reading('25%', 'good')
  assert chip_reading(device(cpuUsagePercent=[10, 20, 30, 41]), "cpu", fresh=True) == Reading('25%', 'good')


@pytest.mark.parametrize('value,level', [(0, 'good'), (69, 'good'), (70, 'warning'), (84, 'warning'), (85, 'danger'),
                                         (100, 'danger')])
def test_cpu_thresholds(value, level):
  assert device_readings(device(cpuUsagePercent=[value]), fresh=True)[1] == Reading(f'{value}%', level)


def test_cpu_stale_is_unknown_not_zero():
  assert device_readings(device(), fresh=False)[1] == Reading()


# --- resets and backup ---

def test_full_resets_return_vehicle():
  from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import shipping_defaults as ui_shipping
  from openpilot.system.bogpilot import toggle_reset as tr
  assert KEY in tr.FILE_CHOICE_RESET_KEYS
  for values in (tr.reset_defaults(), tr.shipping_defaults(), ui_shipping()):
    assert values[KEY] == "vehicle"


class _TypedParams:
  def __init__(self, request_key):
    self.values = {request_key: True}

  def all_keys(self):
    return list(self.values)

  def get_bool(self, k):
    return bool(self.values.get(k))

  def get(self, k):
    return self.values.get(k)

  def cpp2python(self, k, b):
    return b.decode()

  def put(self, k, v, block=False):
    self.values[k] = v

  def remove(self, k):
    self.values.pop(k, None)


def test_requested_reset_rewrites_a_saved_cpu_choice(tmp_path):
  from openpilot.system.bogpilot import toggle_reset as tr
  (tmp_path / KEY).write_text("cpu")
  params = _TypedParams(tr.REQUEST_KEY)
  result = tr.reset_requested(params, tmp_path, backup=lambda: True)
  assert result.status == "completed", result
  assert (tmp_path / KEY).read_text() == "vehicle"
  assert KEY not in params.values                    # file-only: never a Params key


def test_backup_covers_the_choice():
  from openpilot.system.bogpilot.settings_backup import FILE_KEYS
  import json
  assert KEY in FILE_KEYS
  scope = json.loads((ROOT / "system/bogpilot/tests/fixtures/reset_backup_scope.json").read_text())
  assert KEY in scope["file_keys"]


def test_profiles_and_section_resets_never_write_it():
  # The AP1 profile and the F6 legacy SLC fill only fill keys still at their default, and the sidebar has no menu rows
  # (its contents are saved by tapping), so no section reset owns it. None of them may write a CPU choice.
  for rel in ("common/bogpilot_ap1_profile.py", "system/manager/bogpilot_startup.py", "selfdrive/ui/bogpilot/step_defaults.py",
              "selfdrive/ui/bogpilot/gated_actions.py", "common/bogpilot_shipping_defaults.py"):
    assert KEY not in (ROOT / rel).read_text(), rel


# --- the sidebar itself ---

def _sidebar(m, files, choice=None, panda_seen=None):
  if choice is not None:
    (files / KEY).write_text(choice)
  s = m.Sidebar.__new__(m.Sidebar)
  s._offroad_temp_status, s._cpu_status, s._ram_status = [m.MetricData(n, '--', m.Colors.GRAY) for n in ['TEMP', 'CPU', 'RAM']]
  s._temp_status, s._panda_status = [m.MetricData(n, '--', m.Colors.GRAY) for n in ['TEMP', 'VEHICLE']]
  s._params = SimpleNamespace(get_bool=lambda key: key in {'ShowCPU', 'ShowMemoryUsage', 'NumericalTemp'},
                              put_bool=lambda key, value: None)
  if panda_seen is not None:
    s._panda_seen = panda_seen
  return s


def _onroad_calls(m, s, monkeypatch, cpu=(10, 20, 30, 40)):
  s._update_hardware_metrics(device(cpuUsagePercent=list(cpu)), fresh=True)
  calls = []
  s._draw_metric = lambda rect, metric, y: calls.append((metric.label, metric.value, y))
  monkeypatch.setattr(m, 'ui_state', SimpleNamespace(started=True))
  s._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
  return calls


def test_sidebar_default_onroad_is_unchanged(files, monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  calls = _onroad_calls(m, _sidebar(m, files), monkeypatch)
  assert [(c[0], c[2]) for c in calls] == [('TEMP', 338), ('VEHICLE', 496), ('RAM', 654)]


def test_sidebar_cpu_choice_shows_cpu_with_ram(files, monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, "cpu")
  calls = _onroad_calls(m, s, monkeypatch, cpu=(80, 90))
  assert calls == [('TEMP', '54°C', 338), ('CPU', '85%', 496), ('RAM', '41%', 654)]
  assert s._cpu_status.color == m.Colors.DANGER
  calls = _onroad_calls(m, s, monkeypatch, cpu=(70, 71))
  assert calls[1] == ('CPU', '70%', 496) and s._cpu_status.color == m.Colors.WARNING
  calls = _onroad_calls(m, s, monkeypatch, cpu=(5, 6))
  assert calls[1] == ('CPU', '5%', 496) and s._cpu_status.color == m.Colors.GOOD


def test_sidebar_no_panda_overrides_cpu(files, monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  calls = _onroad_calls(m, _sidebar(m, files, "cpu", panda_seen=False), monkeypatch)
  assert calls[1][0] == 'VEHICLE'


def test_sidebar_offroad_unchanged_by_choice(files, monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, "cpu")
  s._update_hardware_metrics(device(), fresh=True)
  calls = []
  s._draw_metric = lambda rect, metric, y: calls.append((metric.label, y))
  monkeypatch.setattr(m, 'ui_state', SimpleNamespace(started=False))
  s._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
  assert calls == [('TEMP', 338), ('CPU', 496), ('RAM', 654)]


def test_sidebar_tap_on_middle_box_cycles_and_saves(files, monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files)
  _onroad_calls(m, s, monkeypatch)
  kinds = [kind for _rect, kind in s._metric_hits]
  assert kinds == ["temp", "vehicle", "memory"]
  s._cycle("vehicle")
  assert (files / KEY).read_text().strip() == "cpu" and s._slot_vehicle == "cpu"
  s._cycle("vehicle")
  assert (files / KEY).read_text().strip() == "vehicle" and s._slot_vehicle == "vehicle"


def test_sidebar_tap_during_no_panda_is_ignored_and_not_saved(files, monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, "cpu", panda_seen=False)
  calls = _onroad_calls(m, s, monkeypatch)
  assert calls[1][0] == 'VEHICLE' and s._slot_vehicle == "cpu"
  writes = []
  monkeypatch.setattr(m, 'write_vehicle_slot', lambda choice: writes.append(choice) or True)
  s._recording_audio = False
  box = next(rect for rect, kind in s._metric_hits if kind == "vehicle")
  tap = m.rl.Vector2(box.x + box.width / 2, box.y + box.height / 2)
  for _ in range(3):
    s._handle_mouse_release(tap)                  # the real tap path
    s._cycle("vehicle")
  assert writes == [] and s._slot_vehicle == "cpu"
  assert (files / KEY).read_text().strip() == "cpu"
  # the panda is back: the chosen CPU returns, and taps flip it again
  s._panda_seen = True
  assert _onroad_calls(m, s, monkeypatch)[1][0] == 'CPU'
  s._handle_mouse_release(tap)
  assert writes == ["vehicle"] and s._slot_vehicle == "vehicle"


def test_sidebar_tap_flips_at_any_time_the_panda_is_seen(files, monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, panda_seen=True)
  _onroad_calls(m, s, monkeypatch)
  for expect in ("cpu", "vehicle", "cpu"):
    s._cycle("vehicle")
    assert s._slot_vehicle == expect and (files / KEY).read_text().strip() == expect
