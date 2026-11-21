"""Upper sidebar box: Temp (default) or Power, chosen by tapping it (SidebarUpperSlot file choice).

The same choice is used offroad and onroad. Power is read from sysfs microwatts, not from deviceState.powerDrawW.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.common import bogpilot_toggles as bt
from openpilot.selfdrive.ui.bogpilot import sidebar_metrics as sm
from openpilot.selfdrive.ui.bogpilot.sidebar_metrics import Reading

KEY = "SidebarUpperSlot"
ROOT = Path(__file__).resolve().parents[3]


def device(**kwargs):
  return SimpleNamespace(**({'maxTempC': 54.8, 'thermalStatus': 0, 'cpuUsagePercent': [10, 20, 30, 40],
                            'memoryUsagePercent': 41} | kwargs))


@pytest.fixture
def files(tmp_path, monkeypatch):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  return tmp_path


@pytest.fixture
def power_cache():
  cache = [None]
  yield cache
  sm.clear_power_path_cache()


def _write_power(path: Path, text) -> Path:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(text)
  return path


# --- power_reading ---

def test_power_reading_formats_microwatts(tmp_path, power_cache):
  path = _write_power(tmp_path / "power1_input", "12345678")
  assert sm.power_reading(path=str(path), scan_glob="", cache=power_cache) == Reading("12.35 W", "good")
  path.write_text("0\n")
  assert sm.power_reading(path=str(path), scan_glob="", cache=power_cache) == Reading("0.00 W", "good")


@pytest.mark.parametrize("payload", [None, "", "abc", "-1", "-1000", "12.35", "1e6"])
def test_power_reading_unreadable_is_dashes(tmp_path, power_cache, payload):
  if payload is None:
    path = tmp_path / "missing" / "power1_input"
  else:
    path = _write_power(tmp_path / "power1_input", payload)
  assert sm.power_reading(path=str(path), scan_glob="", cache=power_cache) == Reading()


def test_power_reading_directory_is_dashes(tmp_path, power_cache):
  path = tmp_path / "power1_input"
  path.mkdir()
  assert sm.power_reading(path=str(path), scan_glob="", cache=power_cache) == Reading()


def test_power_reading_injectable_read(power_cache):
  assert sm.power_reading(read=lambda p: "2500000", path="/not/used", scan_glob="", cache=power_cache) == Reading("2.50 W", "good")
  def boom(_path):
    raise OSError("missing")
  assert sm.power_reading(read=boom, path="/not/used", scan_glob="", cache=power_cache) == Reading()


def test_power_reading_prefers_primary_path(tmp_path, power_cache):
  primary = _write_power(tmp_path / "hwmon1" / "power1_input", "1000000")
  _write_power(tmp_path / "hwmon2" / "power1_input", "9000000")
  got = sm.power_reading(path=str(primary), scan_glob=str(tmp_path / "hwmon*" / "power1_input"), cache=power_cache)
  assert got == Reading("1.00 W", "good")
  assert power_cache[0] == str(primary)


def test_power_reading_scans_when_primary_missing(tmp_path, power_cache):
  _write_power(tmp_path / "hwmon2" / "power1_input", "5000000")
  _write_power(tmp_path / "hwmon3" / "power1_input", "9000000")
  missing = tmp_path / "hwmon1" / "power1_input"
  got = sm.power_reading(path=str(missing), scan_glob=str(tmp_path / "hwmon*" / "power1_input"), cache=power_cache)
  assert got == Reading("5.00 W", "good")  # first readable in sorted order
  assert power_cache[0].endswith("hwmon2/power1_input")


def test_power_reading_cached_failure_rescans_once(tmp_path, power_cache):
  first = _write_power(tmp_path / "hwmon2" / "power1_input", "5000000")
  second = _write_power(tmp_path / "hwmon3" / "power1_input", "9000000")
  missing = tmp_path / "hwmon1" / "power1_input"
  glob = str(tmp_path / "hwmon*" / "power1_input")
  assert sm.power_reading(path=str(missing), scan_glob=glob, cache=power_cache) == Reading("5.00 W", "good")
  first.write_text("nope")  # still readable, but unparsable: cached path stays, result is --
  assert sm.power_reading(path=str(missing), scan_glob=glob, cache=power_cache) == Reading()
  assert power_cache[0] == str(first)
  # Make the cached path unreadable so the next call rescans.
  first.unlink()
  first.mkdir()
  got = sm.power_reading(path=str(missing), scan_glob=glob, cache=power_cache)
  assert got == Reading("9.00 W", "good")
  assert power_cache[0] == str(second)


# --- the choice ---

def test_default_is_not_power(files):
  assert bt.FILE_CHOICES[KEY] == ("celsius", ("status", "celsius", "fahrenheit", "power"))
  assert not (files / KEY).exists()
  assert sm.read_upper_slot() is None
  assert sm.upper_slot_shown(None, True, False) == "celsius"
  assert sm.upper_slot_shown(None, True, True) == "fahrenheit"
  assert sm.upper_slot_shown(None, False, False) == "status"
  assert sm.upper_slot_shown("power", True, False) == "power"


@pytest.mark.parametrize("text,choice", [(None, None), ("", None), ("power", "power"), ("power\n", "power"),
                                         (b"power", "power"), ("POWER", None), ("celsius", "celsius"),
                                         ("status", "status"), ("fahrenheit", "fahrenheit"), ("cpu", None), (3, None)])
def test_only_an_exact_allowed_choice_is_stored(text, choice):
  assert sm.upper_slot_choice(text) == choice


def test_junk_or_unreadable_file_is_not_power(files):
  (files / KEY).write_text("garbage")
  assert sm.read_upper_slot() is None
  (files / KEY).unlink()
  (files / KEY).mkdir()
  assert sm.read_upper_slot() is None


def test_tap_cycle_order():
  assert sm.upper_cycle(False) == ("status", "celsius", "power")
  assert sm.upper_cycle(True) == ("status", "fahrenheit", "power")
  for fahrenheit, unit in ((False, "celsius"), (True, "fahrenheit")):
    other = "fahrenheit" if unit == "celsius" else "celsius"
    assert sm.cycle_upper_slot("status", fahrenheit) == unit
    assert sm.cycle_upper_slot(unit, fahrenheit) == "power"
    assert sm.cycle_upper_slot(other, fahrenheit) == "power"   # a stale other-unit choice never shows
    assert sm.cycle_upper_slot("power", fahrenheit) == "status"
    assert sm.cycle_upper_slot("junk", fahrenheit) == "status"
  assert sm.temp_writes("fahrenheit") == {"NumericalTemp": True}
  assert sm.temp_writes("status") == {"NumericalTemp": False}


def test_choice_persists_in_its_file(files):
  assert sm.write_upper_slot("power")
  assert (files / KEY).read_text().strip() == "power"
  assert sm.read_upper_slot() == "power"
  assert sm.write_upper_slot("celsius")
  assert sm.read_upper_slot() == "celsius"


# --- resets and backup ---

def test_full_resets_return_celsius_not_power():
  from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import shipping_defaults as ui_shipping
  from openpilot.system.bogpilot import toggle_reset as tr
  assert KEY in tr.FILE_CHOICE_RESET_KEYS
  for values in (tr.reset_defaults(), tr.shipping_defaults(), ui_shipping()):
    assert values[KEY] == "celsius"


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


def test_requested_reset_rewrites_a_saved_power_choice(tmp_path):
  from openpilot.system.bogpilot import toggle_reset as tr
  (tmp_path / KEY).write_text("power")
  params = _TypedParams(tr.REQUEST_KEY)
  result = tr.reset_requested(params, tmp_path, backup=lambda: True)
  assert result.status == "completed", result
  assert (tmp_path / KEY).read_text() == "celsius"
  assert KEY not in params.values                    # file-only: never a Params key


def test_backup_covers_the_choice():
  from openpilot.system.bogpilot.settings_backup import FILE_KEYS
  import json
  assert KEY in FILE_KEYS
  scope = json.loads((ROOT / "system/bogpilot/tests/fixtures/reset_backup_scope.json").read_text())
  assert KEY in scope["file_keys"]


def test_profiles_and_section_resets_never_write_it():
  for rel in ("common/bogpilot_ap1_profile.py", "system/manager/bogpilot_startup.py", "selfdrive/ui/bogpilot/step_defaults.py",
              "selfdrive/ui/bogpilot/gated_actions.py", "common/bogpilot_shipping_defaults.py"):
    assert KEY not in (ROOT / rel).read_text(), rel


# --- the sidebar itself, offroad and onroad ---

def _sidebar(m, files, choice=None, params=None, power=None):
  if choice is not None:
    (files / KEY).write_text(choice)
  s = m.Sidebar.__new__(m.Sidebar)
  s._offroad_temp_status, s._cpu_status, s._ram_status = [m.MetricData(n, '--', m.Colors.GRAY) for n in ['TEMP', 'CPU', 'RAM']]
  s._power_status = m.MetricData('POWER', '--', m.Colors.GRAY)
  s._temp_status, s._panda_status = [m.MetricData(n, '--', m.Colors.GRAY) for n in ['TEMP', 'VEHICLE']]
  on = params if params is not None else {'ShowCPU', 'ShowMemoryUsage', 'NumericalTemp', 'IsMetric'}
  sm.fahrenheit_from_metric = lambda: 'IsMetric' not in on   # the Metric Units value these fake params hold

  def put_bool(key, value):
    if value:
      on.add(key)
    else:
      on.discard(key)

  s._params = SimpleNamespace(get_bool=lambda key: key in on, put_bool=put_bool,
                              get=lambda key: "1" if key in on else None)
  if power is not None:
    s._power_read = (power if callable(power) else (lambda value=power: value))
  return s


def _draw_calls(m, s, monkeypatch, started, dev=None):
  s._update_hardware_metrics(dev or device(), fresh=True)
  calls = []
  s._draw_metric = lambda rect, metric, y: calls.append((metric.label, metric.value, metric.color, y))
  monkeypatch.setattr(m, 'ui_state', SimpleNamespace(started=started))
  s._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
  return calls


@pytest.mark.parametrize("started,middle", [(False, ("CPU", "25%", 496)), (True, ("VEHICLE", "--", 496))])
def test_sidebar_default_upper_box_is_celsius_on_both_screens(files, monkeypatch, started, middle):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  calls = _draw_calls(m, _sidebar(m, files), monkeypatch, started)
  assert calls[0][0] == "TEMP" and calls[0][1] == "54°C" and calls[0][3] == 338
  assert (calls[1][0], calls[1][1], calls[1][3]) == middle
  assert calls[2][0] == "RAM" and calls[2][3] == 654


@pytest.mark.parametrize("started", [False, True])
def test_sidebar_power_choice_shows_power_on_both_screens(files, monkeypatch, started):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, "power", power=lambda: Reading("12.35 W", "good"))
  calls = _draw_calls(m, s, monkeypatch, started)
  assert calls[0] == ("POWER", "12.35 W", m.Colors.GOOD, 338)
  assert s._slot_upper == "power"
  # last temp mode is still celsius (NumericalTemp default)
  assert s._temp_mode == "celsius"
  assert calls[2][0] == "RAM"


@pytest.mark.parametrize("started", [False, True])
def test_sidebar_power_missing_file_is_gray_dashes_on_both_screens(files, monkeypatch, started):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, "power", power=lambda: Reading())
  calls = _draw_calls(m, s, monkeypatch, started)
  assert calls[0] == ("POWER", "--", m.Colors.GRAY, 338)


@pytest.fixture(autouse=True)
def _restore_unit_reader():
  saved = sm.fahrenheit_from_metric
  yield
  sm.fahrenheit_from_metric = saved


@pytest.mark.parametrize("started", [False, True])
def test_sidebar_missing_upper_file_shows_fahrenheit_when_metric_is_off_on_both_screens(files, monkeypatch, started):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, params={"ShowCPU", "ShowMemoryUsage", "NumericalTemp"})
  calls = _draw_calls(m, s, monkeypatch, started)
  assert calls[0][0] == "TEMP" and calls[0][1] == "129°F" and calls[0][3] == 338


@pytest.mark.parametrize("started", [False, True])
def test_visuals_toggle_change_leaves_power(files, monkeypatch, started):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  params = {"ShowCPU", "ShowMemoryUsage", "NumericalTemp", "IsMetric"}
  s = _sidebar(m, files, "power", params=params, power=lambda: Reading("8.00 W", "good"))
  calls = _draw_calls(m, s, monkeypatch, started)
  assert calls[0][0] == "POWER" and s._slot_upper == "power"
  params.discard("IsMetric")   # Metric Units off: the unit becomes Fahrenheit
  calls = _draw_calls(m, s, monkeypatch, started)
  assert calls[0][0] == "TEMP" and calls[0][1] == "129°F"
  assert s._slot_upper == "fahrenheit"
  assert (files / KEY).read_text().strip() == "fahrenheit"


@pytest.mark.parametrize("started", [False, True])
def test_sidebar_tap_cycles_through_power_on_both_screens(files, monkeypatch, started):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, power=lambda: Reading("3.00 W", "good"))
  calls = _draw_calls(m, s, monkeypatch, started)
  kinds = [kind for _rect, kind in s._metric_hits]
  assert kinds[0] == "temp"
  # Metric Units on: celsius -> power -> status -> celsius. Fahrenheit never appears.
  s._cycle("temp")
  assert s._slot_upper == "power" and s._temp_mode == "celsius"
  assert (files / KEY).read_text().strip() == "power"
  calls = _draw_calls(m, s, monkeypatch, started)
  assert calls[0][0] == "POWER" and calls[0][1] == "3.00 W"
  s._cycle("temp")
  assert s._slot_upper == "status" and s._temp_mode == "status"
  assert (files / KEY).read_text().strip() == "status"
  s._cycle("temp")
  assert s._slot_upper == "celsius" and s._temp_mode == "celsius"


@pytest.mark.parametrize("started", [False, True])
def test_sidebar_tap_cycle_with_metric_off_is_fahrenheit_only(files, monkeypatch, started):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = _sidebar(m, files, params={"ShowCPU", "ShowMemoryUsage", "NumericalTemp"}, power=lambda: Reading("3.00 W", "good"))
  _draw_calls(m, s, monkeypatch, started)
  seen = [(s._slot_upper, s._temp_mode)]
  for _ in range(4):
    s._cycle("temp")
    seen.append((s._slot_upper, s._temp_mode))
  assert seen == [("fahrenheit", "fahrenheit"), ("power", "fahrenheit"), ("status", "status"),
                  ("fahrenheit", "fahrenheit"), ("power", "fahrenheit")]
  assert "celsius" not in [x for pair in seen for x in pair]


def test_draw_does_not_reread_power(files, monkeypatch):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  reads = {"n": 0}

  def read():
    reads["n"] += 1
    return Reading("1.00 W", "good")

  s = _sidebar(m, files, "power", power=read)
  _draw_calls(m, s, monkeypatch, False)
  after_update = reads["n"]
  assert after_update >= 1
  s._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
  s._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
  assert reads["n"] == after_update
