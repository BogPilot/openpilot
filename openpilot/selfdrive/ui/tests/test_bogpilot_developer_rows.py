"""Developer overlays: the sidebar slot contents (tap to cycle), the Visuals rows and their write rules (headless)."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openpilot.selfdrive.ui.tests.test_phase2_visuals_theme import _stub_raylib_ui, FakeParams, TYPED_KEYS

_stub_raylib_ui()

from openpilot.selfdrive.ui.bogpilot import sidebar_metrics as SM  # noqa: E402

KEYS = [*TYPED_KEYS, "FPSCounter", "DeveloperSidebar", "ShowGPU", "ShowStorageLeft", "ShowStorageUsed", "ShowIP", "Sidebar"]   # all registered Params keys in the real build


class RowParams(FakeParams):
  def all_keys(self):
    return [k.encode() for k in KEYS]

  def check_key(self, k):
    if k not in KEYS:
      raise KeyError(k)


def device(**kw):
  return SimpleNamespace(**({'maxTempC': 50, 'thermalStatus': 0, 'cpuUsagePercent': [10, 30], 'memoryUsagePercent': 41,
                            'gpuUsagePercent': 73, 'freeSpacePercent': 60} | kw))


def flags(**on):
  base = {k: False for k in (*SM.CHIP_KEYS, *SM.MEMORY_KEYS)}
  return base | on


class TestSlots(unittest.TestCase):
  def test_defaults_keep_cpu_and_memory(self):
    self.assertEqual(SM.slot_choices(flags(ShowCPU=True, ShowMemoryUsage=True)), ("cpu", "memory"))
    # Nothing stored (or an older build saved a slot as off): the defaults show, so there is always a box to tap.
    self.assertEqual(SM.slot_choices(flags()), ("cpu", "memory"))

  def test_first_enabled_wins_in_each_slot(self):
    self.assertEqual(SM.slot_choices(flags(ShowCPU=True, ShowGPU=True))[0], "cpu")
    self.assertEqual(SM.slot_choices(flags(ShowGPU=True))[0], "gpu")
    self.assertEqual(SM.slot_choices(flags(ShowMemoryUsage=True, ShowStorageLeft=True))[1], "memory")
    self.assertEqual(SM.slot_choices(flags(ShowStorageLeft=True, ShowStorageUsed=True))[1], "storage_left")
    self.assertEqual(SM.slot_choices(flags(ShowStorageUsed=True))[1], "storage_used")

  def test_gpu_counts_only_when_explicitly_stored(self):
    # ShowGPU registers ON next to ShowCPU: turning CPU off must not make GPU appear by itself.
    stored = {"ShowGPU": None}
    f = SM.slot_flags(lambda k: k == "ShowGPU", lambda k: stored.get(k))
    self.assertFalse(f["ShowGPU"])
    stored["ShowGPU"] = "1"
    self.assertTrue(SM.slot_flags(lambda k: False, lambda k: stored.get(k))["ShowGPU"])
    stored["ShowGPU"] = True
    self.assertTrue(SM.slot_flags(lambda k: False, lambda k: stored.get(k))["ShowGPU"])
    stored["ShowGPU"] = "0"
    self.assertFalse(SM.slot_flags(lambda k: True, lambda k: stored.get(k))["ShowGPU"])

  def test_each_cycle_visits_every_content_once_and_wraps(self):
    seen = []
    chip = "cpu"
    for _ in range(3):
      chip = SM.slot_choices({**flags(), **SM.cycle_chip(chip)})[0]
      seen.append(chip)
    self.assertEqual(seen, ["gpu", "cpu", "gpu"])
    seen, memory = [], "memory"
    for _ in range(4):
      memory = SM.slot_choices({**flags(), **SM.cycle_memory(memory)})[1]
      seen.append(memory)
    self.assertEqual(seen, ["storage_left", "storage_used", "memory", "storage_left"])
    seen, mode = [], "status"
    for _ in range(4):
      writes = SM.cycle_temp(mode, fahrenheit=False)
      self.assertEqual(sorted(writes), ["NumericalTemp"])
      mode = SM.temp_mode(writes["NumericalTemp"], False)
      seen.append(mode)
    self.assertEqual(seen, ["celsius", "status", "celsius", "status"])

  def test_a_cycle_has_no_off_step_and_writes_exactly_one_content_per_slot(self):
    for current in SM.CHIP_CYCLE:
      writes = SM.cycle_chip(current)
      self.assertEqual(sorted(writes), sorted(SM.CHIP_KEYS))
      self.assertEqual(sum(writes.values()), 1)
    for current in SM.MEMORY_CYCLE:
      writes = SM.cycle_memory(current)
      self.assertEqual(sorted(writes), sorted(SM.MEMORY_KEYS))
      self.assertEqual(sum(writes.values()), 1)

  def test_unknown_current_content_starts_the_cycle_at_its_first_step(self):
    self.assertEqual(SM.cycle_chip("bogus"), SM.chip_writes("cpu"))
    self.assertEqual(SM.cycle_memory(None), SM.memory_writes("memory"))

  def test_temp_mode_reads_the_saved_flags(self):
    self.assertEqual(SM.temp_mode(False, False), "status")
    self.assertEqual(SM.temp_mode(False, True), "status")
    self.assertEqual(SM.temp_mode(True, False), "celsius")
    self.assertEqual(SM.temp_mode(True, True), "fahrenheit")


class TestReadings(unittest.TestCase):
  def test_gpu_and_cpu_chip(self):
    gpu = lambda v: (lambda: v)   # noqa: E731
    self.assertEqual(SM.chip_reading(device(), "gpu", fresh=True, gpu_percent=gpu(73.0)), SM.Reading("73%", "warning"))
    self.assertEqual(SM.chip_reading(device(), "cpu", fresh=True), SM.Reading("20%", "good"))
    self.assertEqual(SM.chip_reading(device(), "gpu", fresh=True, gpu_percent=gpu(90.0)).level, "danger")

  def test_gpu_parsing_from_the_kgsl_counters(self):
    self.assertEqual(SM.GPU_BUSY_PATH, "/sys/class/kgsl/kgsl-3d0/gpubusy")
    self.assertEqual(SM.parse_gpu_busy("73 100\n"), 73.0)
    self.assertEqual(SM.parse_gpu_busy(b"1 4"), 25.0)
    self.assertEqual(SM.parse_gpu_busy("0 5000"), 0.0)   # a real idle zero is a number
    self.assertEqual(SM.parse_gpu_busy("9 4"), 100.0)    # clamped
    for bad in ("", "0 0", "5", "a b", "1 2 3", "-1 4", "1 -4", None, 5, "nan inf"):
      self.assertIsNone(SM.parse_gpu_busy(bad), bad)

  def test_gpu_reading_from_a_file_and_unavailable_is_a_dash(self):
    with tempfile.TemporaryDirectory() as d:
      f = Path(d) / "gpubusy"
      f.write_text("730 1000\n")
      self.assertEqual(SM.read_gpu_percent(str(f)), 73.0)
      self.assertEqual(SM.chip_reading(device(), "gpu", fresh=True, gpu_percent=lambda: SM.read_gpu_percent(str(f))),
                       SM.Reading("73%", "warning"))
      f.write_text("garbage")
      self.assertIsNone(SM.read_gpu_percent(str(f)))
      self.assertIsNone(SM.read_gpu_percent(str(Path(d) / "missing")))
      self.assertIsNone(SM.read_gpu_percent(d))   # a directory is unreadable
    self.assertEqual(SM.chip_reading(device(), "gpu", fresh=True, gpu_percent=lambda: None), SM.Reading())

  def test_unavailable_is_never_zero(self):
    self.assertEqual(SM.chip_reading(device(), "gpu", fresh=False), SM.Reading())
    self.assertEqual(SM.chip_reading(None, "gpu", fresh=True), SM.Reading())
    for bad in (-1, 101, True, "5", float("nan")):
      self.assertEqual(SM.chip_reading(device(), "gpu", fresh=True, gpu_percent=lambda: bad), SM.Reading())
    self.assertEqual(SM.chip_reading(device(cpuUsagePercent=[]), "cpu", fresh=True), SM.Reading())

  def test_storage_values_and_colors(self):
    usage = (123.9, 77.2)
    self.assertEqual(SM.storage_reading(device(), "storage_left", usage, fresh=True), SM.Reading("123 GB", "good"))
    self.assertEqual(SM.storage_reading(device(), "storage_used", usage, fresh=True), SM.Reading("77 GB", "good"))
    for percent, level in ((60, "good"), (25, "good"), (24, "warning"), (10, "warning"), (9, "danger"), (0, "danger")):
      self.assertEqual(SM.storage_reading(device(freeSpacePercent=percent), "storage_left", usage, fresh=True).level, level)

  def test_storage_unavailable(self):
    self.assertEqual(SM.storage_reading(device(), "storage_left", None, fresh=True), SM.Reading())
    self.assertEqual(SM.storage_reading(device(), "storage_left", (1, 1), fresh=False), SM.Reading())
    self.assertEqual(SM.storage_reading(device(freeSpacePercent=-5), "storage_left", (1, 1), fresh=True), SM.Reading())
    self.assertEqual(SM.storage_reading(device(), "storage_left", (float("nan"), 1), fresh=True), SM.Reading())

  def test_data_usage_reads_statvfs(self):
    free, used = SM.data_usage_gb("/")
    self.assertGreater(free, 0)
    self.assertGreater(used, 0)
    self.assertIsNone(SM.data_usage_gb("/definitely/not/a/path"))


def make_sidebar(params, monkeypatch_started=False):
  from openpilot.selfdrive.ui.layouts import sidebar as m
  s = m.Sidebar.__new__(m.Sidebar)
  s._offroad_temp_status, s._cpu_status, s._ram_status = [m.MetricData(n, '--', m.Colors.GRAY) for n in ['TEMP', 'CPU', 'RAM']]
  s._temp_status, s._panda_status = [m.MetricData(n, '--', m.Colors.GRAY) for n in ['TEMP', 'VEHICLE']]
  s._params = SimpleNamespace(get_bool=lambda key: key in params, get=lambda key: params.get(key))
  return m, s


class TestSidebar(unittest.TestCase):
  def setUp(self):
    # The onroad middle box saves its choice as a file (SidebarVehicleSlot). Point the file store at a temp dir so a tap
    # here never leaves a choice behind for later tests, the same way TestRows isolates its params.
    from openpilot.common import bogpilot_toggles as bt
    saved = bt.BOGPILOT_DIR
    bt.BOGPILOT_DIR = Path(tempfile.mkdtemp(prefix="sidebar_slots_"))
    self.addCleanup(setattr, bt, "BOGPILOT_DIR", saved)
    # A real GPU reading for the layout tests (the sysfs counters do not exist off the device).
    self.addCleanup(setattr, SM, "read_gpu_percent", SM.read_gpu_percent)
    SM.read_gpu_percent = lambda *a: 73.0

  def draw(self, on, started=False, dev=None):
    m, s = make_sidebar(on)
    calls = []
    saved = m.ui_state, m.data_usage_gb
    m.data_usage_gb = lambda: (200.0, 50.0)
    try:
      s._update_hardware_metrics(dev or device(), fresh=True)
      s._draw_metric = lambda rect, metric, y: calls.append((metric.label, metric.value, y))
      m.ui_state = SimpleNamespace(started=started)
      s._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
    finally:
      m.ui_state, m.data_usage_gb = saved
    return calls

  def test_default_slots_unchanged(self):
    self.assertEqual(self.draw({"ShowCPU": True, "ShowMemoryUsage": True, "NumericalTemp": True, "IsMetric": True}),
                     [("TEMP", "50\u00b0C", 338), ("CPU", "20%", 496), ("RAM", "41%", 654)])

  def test_gpu_replaces_cpu(self):
    calls = self.draw({"ShowGPU": True, "ShowMemoryUsage": True, "NumericalTemp": True})
    self.assertEqual(calls[1], ("GPU", "73%", 496))

  def test_storage_replaces_memory_offroad_and_onroad(self):
    calls = self.draw({"ShowCPU": True, "ShowStorageLeft": True, "NumericalTemp": True})
    self.assertEqual(calls[2], ("LEFT", "200 GB", 654))
    calls = self.draw({"ShowCPU": True, "ShowStorageUsed": True}, started=True)
    self.assertEqual(calls[1][0], "VEHICLE")
    self.assertEqual(calls[2], ("USED", "50 GB", 654))

  def test_a_slot_saved_as_off_shows_its_default_instead_of_vanishing(self):
    calls = self.draw({"NumericalTemp": True})
    self.assertEqual([c[0] for c in calls], ["TEMP", "CPU", "RAM"])

  def test_temperature_follows_the_saved_mode_onroad_and_offroad(self):
    # The unit is the Metric Units toggle: Celsius when on, Fahrenheit when off. The old Fahrenheit param is ignored.
    self.assertEqual(self.draw({"NumericalTemp": True, "IsMetric": True})[0][1], "50\u00b0C")
    self.assertEqual(self.draw({"NumericalTemp": True})[0][1], "122\u00b0F")
    self.assertEqual(self.draw({"NumericalTemp": True, "IsMetric": True, "Fahrenheit": True})[0][1], "50\u00b0C")
    self.assertEqual(self.draw({"NumericalTemp": True, "Fahrenheit": True}, started=True)[0][1], "122\u00b0F")
    self.assertEqual(self.draw({"NumericalTemp": True, "IsMetric": True}, started=True)[0][1], "50\u00b0C")
    # status mode draws the GOOD / HIGH box (not yet updated in this bare sidebar, so still dashes), never the number
    self.assertEqual(self.draw({}, started=True)[0][:2], ("TEMP", "--"))
    self.assertEqual(self.draw({})[0][:2], ("TEMP", "--"))

  # ---- taps inside the boxes
  def tapper(self, on, started=False):
    """A sidebar with recording params: returns (module, sidebar, writes, tap) where tap(x, y) hits the real handler."""
    m, s = make_sidebar(on)
    writes = {}
    self.addCleanup(setattr, SM, "fahrenheit_from_metric", SM.fahrenheit_from_metric)
    SM.fahrenheit_from_metric = lambda: "IsMetric" not in on   # the same Metric Units value the fake params hold

    def put_bool(key, value):
      writes[key] = value
      (on.__setitem__(key, "1") if value else on.pop(key, None))
    s._params = SimpleNamespace(get_bool=lambda key: key in on, get=lambda key: on.get(key), put_bool=put_bool)
    s._on_settings_click = s._on_flag_click = s._open_settings_callback = None
    s._recording_audio = False
    s._mic_indicator_rect = m.rl.Rectangle(0, 0, 0, 0)
    saved = m.ui_state, m.data_usage_gb, m.rl.check_collision_point_rec
    m.data_usage_gb = lambda: (200.0, 50.0)
    m.rl.check_collision_point_rec = lambda p, r: r.x <= p.x <= r.x + r.width and r.y <= p.y <= r.y + r.height
    m.ui_state = SimpleNamespace(started=started)
    s._update_hardware_metrics(device(), fresh=True)
    s._draw_metric = lambda rect, metric, y: None
    s._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
    self.addCleanup(lambda: (setattr(m, "ui_state", saved[0]), setattr(m, "data_usage_gb", saved[1]),
                             setattr(m.rl, "check_collision_point_rec", saved[2])))

    def tap(x, y):
      s._handle_mouse_release(SimpleNamespace(x=x, y=y))
      s._draw_metrics(m.rl.Rectangle(0, 0, 300, 1080))
    return m, s, writes, tap

  def test_tap_in_the_chip_box_cycles_cpu_and_gpu_and_saves_it(self):
    m, s, writes, tap = self.tapper({"ShowCPU": "1", "ShowMemoryUsage": "1", "NumericalTemp": "1"})
    tap(100, 496 + 60)
    self.assertEqual(writes, {"ShowCPU": False, "ShowGPU": True})
    self.assertEqual(s._slot_chip, "gpu")
    tap(100, 496 + 60)
    self.assertEqual((writes["ShowCPU"], writes["ShowGPU"], s._slot_chip), (True, False, "cpu"))

  def test_tap_in_the_memory_box_cycles_ram_and_storage(self):
    m, s, writes, tap = self.tapper({"ShowCPU": "1", "ShowMemoryUsage": "1", "NumericalTemp": "1"})
    tap(100, 654 + 60)
    self.assertEqual(s._slot_memory, "storage_left")
    tap(100, 654 + 60)
    self.assertEqual(s._slot_memory, "storage_used")
    tap(100, 654 + 60)
    self.assertEqual(s._slot_memory, "memory")
    self.assertEqual(writes, {"ShowMemoryUsage": True, "ShowStorageLeft": False, "ShowStorageUsed": False})

  def test_tap_in_the_temperature_box_cycles_status_one_unit_power(self):
    # Metric Units off: status -> Fahrenheit -> power -> status. Celsius never shows.
    # Metric Units on:  status -> Celsius -> power -> status. Fahrenheit never shows.
    for metric, unit in ((False, "fahrenheit"), (True, "celsius")):
      on = {"ShowCPU": "1", "ShowMemoryUsage": "1"}   # numerical temperature unset in this fake = off
      if metric:
        on["IsMetric"] = "1"
      m, s, writes, tap = self.tapper(on)
      seen = [(s._temp_mode, s._slot_upper)]
      for _ in range(4):
        tap(100, 338 + 60)
        seen.append((s._temp_mode, s._slot_upper))
      self.assertEqual(seen, [("status", "status"), (unit, unit), (unit, "power"), ("status", "status"), (unit, unit)])
      self.assertNotIn("Fahrenheit", writes)   # the old param is never written by the tap

  def test_the_cycle_starts_from_what_is_stored_not_from_zero(self):
    m, s, writes, tap = self.tapper({"ShowGPU": "1", "ShowMemoryUsage": "1", "NumericalTemp": "1"})
    self.assertEqual((s._slot_chip, s._temp_mode), ("gpu", "fahrenheit"))
    tap(100, 496 + 60)
    self.assertEqual(s._slot_chip, "cpu")
    tap(100, 338 + 60)
    self.assertEqual(s._slot_upper, "power")
    self.assertEqual(s._temp_mode, "fahrenheit")

  def test_onroad_the_vehicle_box_flips_to_cpu_and_the_others_cycle(self):
    from openpilot.common import bogpilot_toggles as bt
    m, s, writes, tap = self.tapper({"ShowCPU": "1", "ShowMemoryUsage": "1", "NumericalTemp": "1"}, started=True)
    tap(100, 496 + 60)
    self.assertEqual(writes, {})   # no Params write: the choice is the SidebarVehicleSlot file
    self.assertEqual(s._slot_vehicle, "cpu")
    self.assertEqual((bt.BOGPILOT_DIR / "SidebarVehicleSlot").read_text().strip(), "cpu")
    tap(100, 654 + 60)
    self.assertEqual(s._slot_memory, "storage_left")
    tap(100, 338 + 60)
    self.assertEqual(s._slot_upper, "power")   # Metric Units off: already Fahrenheit, so the next step is power

  def test_a_tap_outside_the_boxes_or_on_a_button_changes_nothing(self):
    m, s, writes, tap = self.tapper({"ShowCPU": "1", "ShowMemoryUsage": "1", "NumericalTemp": "1"})
    for x, y in ((100, 100), (100, 480), (10, 560), (290, 560), (100, 800), (150, 900)):
      tap(x, y)
    self.assertEqual(writes, {})

  def test_an_unwritable_preference_never_raises(self):
    m, s, writes, tap = self.tapper({"ShowCPU": "1", "ShowMemoryUsage": "1"})

    def boom(key, value):
      raise RuntimeError("read-only")
    s._params.put_bool = boom
    tap(100, 496 + 60)
    self.assertEqual(s._slot_chip, "cpu")

  def test_gpu_box_is_a_dash_when_the_counters_are_unavailable(self):
    SM.read_gpu_percent = lambda *a: None
    calls = self.draw({"ShowGPU": True, "ShowMemoryUsage": True, "NumericalTemp": True})
    self.assertEqual(calls[1], ("GPU", "--", 496))

  def test_stale_device_state_shows_dashes(self):
    m, s = make_sidebar({"ShowGPU": True, "ShowStorageLeft": True})
    s._update_hardware_metrics(None, fresh=False)
    self.assertEqual({k: v.value for k, v in s._extra_status.items()}, {"gpu": "--", "storage_left": "--", "storage_used": "--"})


def native_window(title: str) -> None:
  """Open the shared headless window the way the other native tests do (2160 x 1080), unless one is already open. A stub
  environment without raylib has nothing to open: the layout then runs on the stand-in widgets."""
  try:
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
  except ImportError:
    return
  if rl.is_window_ready():
    return
  if not gui_app.big_ui():
    gui_app._width, gui_app._height = 2160, 1080
    gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
  gui_app.init_window(title)


class TestRows(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    native_window("developer rows")

  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore
    self.tmp = tempfile.mkdtemp(prefix="dev_rows_")
    self._env = os.environ.get("BOGPILOT_PARAMS_DIR")
    os.environ["BOGPILOT_PARAMS_DIR"] = self.tmp
    self.typed = {}
    self.params = RowParams(self.typed)
    self.store = ParamStore(params=self.params, cache_ttl=0)
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    self.layout = BogPilotVisualsLayout(store=self.store)

  def tearDown(self):
    if self._env is None:
      os.environ.pop("BOGPILOT_PARAMS_DIR", None)
    else:
      os.environ["BOGPILOT_PARAMS_DIR"] = self._env

  def states_of(self, key):
    return self.layout._toggles[key].action_item.get_state()

  def test_developer_rows_exist(self):
    from openpilot.selfdrive.ui.layouts.settings import bogpilot_visuals as bv
    self.assertEqual(bv.DEVELOPER_KEYS, ("ShowAccelGraph", "DeveloperHUD", "FPSCounter", "DeveloperSidebar", "ShowIP"))
    for key in bv.DEVELOPER_KEYS:
      self.assertIn(key, bv.APPEARANCE_KEYS)
      self.assertIn(key, self.layout._toggles)

  def test_sidebar_content_rows_are_gone_because_the_boxes_cycle_them(self):
    from openpilot.selfdrive.ui.layouts.settings import bogpilot_visuals as bv
    for key in ("ShowCPU", "ShowGPU", "ShowMemoryUsage", "ShowStorageLeft", "ShowStorageUsed", "NumericalTemp", "Fahrenheit"):
      self.assertNotIn(key, bv.VISUAL_KEYS)
      self.assertNotIn(key, self.layout._toggles)

  def test_developer_hud_row_writes_the_file_the_hud_reads(self):
    self.layout._write("DeveloperHUD", True)
    self.assertEqual((Path(self.tmp) / "DeveloperHUD").read_text().strip(), "1")
    self.assertNotIn("DeveloperHUD", self.typed)
    from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load
    self.assertTrue(load("developer_hud_logic").DeveloperHudPolicy(self.store).get())
    self.layout._write("DeveloperHUD", False)
    self.assertFalse(load("developer_hud_logic").DeveloperHudPolicy(self.store).get())

  def test_fps_row_shows_only_a_stored_on_value(self):
    # FPSCounter registers OFF and the counter needs it stored: a fresh install shows the row off.
    self.assertEqual(self.states_of("FPSCounter"), False)
    self.typed["FPSCounter"] = "1"
    self.layout.refresh()
    self.assertEqual(self.states_of("FPSCounter"), True)
    self.layout._write("FPSCounter", False)
    self.assertEqual(self.typed["FPSCounter"], "0")
    self.layout.refresh()
    self.assertEqual(self.states_of("FPSCounter"), False)

  def test_fps_row_writes_what_the_overlay_reads(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.overlay_gate import read_overlay
    self.layout._write("FPSCounter", True)
    self.assertTrue(read_overlay(self.store, "FPSCounter", stored_only=True))
    self.layout._write("FPSCounter", False)
    self.assertFalse(read_overlay(self.store, "FPSCounter", stored_only=True))

  def test_ip_row_writes_what_the_sidebar_reads(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.overlay_gate import OverlayGate
    self.assertFalse(OverlayGate("ShowIP", store=self.store).get())   # off on a fresh install
    self.layout._write("ShowIP", True)
    self.assertEqual(self.typed["ShowIP"], "1")
    self.assertTrue(OverlayGate("ShowIP", store=self.store).get())


if __name__ == "__main__":
  unittest.main()
