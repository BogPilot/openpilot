"""Developer Sidebar: metric table, tracker, inputs, placement, widget, pickers and wiring (headless, no window)."""
import importlib.util
import tempfile
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

from openpilot.selfdrive.ui.tests.test_phase2_visuals_theme import _stub_raylib_ui, FakeParams, TYPED_KEYS

_stub_raylib_ui()

from openpilot.selfdrive.ui.bogpilot import developer_sidebar_logic as L  # noqa: E402

UI = Path(__file__).resolve().parents[1]
KEYS = [*TYPED_KEYS, "DeveloperSidebar", *L.metric_keys()]


def inputs(**kw):
  return L.SidebarInputs(**kw)


class Clock:
  def __init__(self):
    self.t = 100.0

  def __call__(self):
    return self.t


class TestTable(unittest.TestCase):
  def test_numbers_and_labels_are_the_097_ones(self):
    self.assertEqual({n: m[0] for n, m in L.METRICS.items()},
                     {1: "ACCEL", 2: "MAX ACCEL", 3: "STEER DELAY", 4: "FRICTION", 5: "LAT ACCEL", 6: "STEER RATIO",
                      7: "STEER STIFF", 8: "LATERAL %", 9: "LONG %", 10: "STEER ANGLE", 11: "TORQUE %", 12: "ACT ACCEL"})
    self.assertEqual(L.METRICS[3][1], "Auto Tune: Actuator Delay")
    self.assertEqual(L.METRICS[12][1], "Longitudinal Control: Actuator Acceleration Output")

  def test_jerk_metrics_are_not_offered(self):
    for n in (13, 14, 15):
      self.assertNotIn(n, L.METRICS)

  def test_torque_metrics_hidden_only_on_a_known_angle_car(self):
    self.assertEqual(set(L.METRICS) - set(L.available_metrics(False)), {4, 5, 11})
    self.assertEqual(set(L.available_metrics(True)), set(L.METRICS))
    self.assertEqual(set(L.available_metrics(None)), set(L.METRICS))

  def test_slot_assignments(self):
    self.assertEqual(L.slot_assignments([1, 0, 99, 13, "x", None, 12, 5]), [1, 12, 5])
    self.assertEqual(L.slot_assignments([1, 4, 5, 11, 2], torque=False), [1, 2])
    self.assertEqual(L.slot_assignments([]), [])

  def test_seven_metric_keys(self):
    self.assertEqual(L.metric_keys(), tuple(f"DeveloperSidebarMetric{i}" for i in range(1, 8)))

  def test_steering_type(self):
    self.assertIsNone(L.torque_steering(None))
    self.assertTrue(L.torque_steering(SimpleNamespace(steerControlType="torque")))
    self.assertFalse(L.torque_steering(SimpleNamespace(steerControlType="angle")))
    self.assertIsNone(L.torque_steering(object()))


class TestTracker(unittest.TestCase):
  def test_acceleration_and_max(self):
    t = L.Tracker(Clock())
    v = t.update(inputs(a_ego=1.234))
    self.assertEqual((v[1], v[2]), ("1.23 m/s\u00b2", "1.23 m/s\u00b2"))
    v = t.update(inputs(a_ego=0.5))
    self.assertEqual((v[1], v[2]), ("0.50 m/s\u00b2", "1.23 m/s\u00b2"))

  def test_max_ignores_gas_pressed_frames(self):
    t = L.Tracker(Clock())
    t.update(inputs(a_ego=1.0))
    v = t.update(inputs(a_ego=3.0, gas_pressed=True))
    self.assertEqual(v[2], "1.00 m/s\u00b2")

  def test_engagement_shares_skip_reverse_and_standstill(self):
    t = L.Tracker(Clock())
    for _ in range(3):
      v = t.update(inputs(lat_active=True, long_active=False))
    self.assertEqual((v[8], v[9]), ("100.00%", "0.00%"))
    t.update(inputs(lat_active=True, standstill=True))
    v = t.update(inputs(lat_active=True, reverse=True))
    self.assertEqual(v[8], "100.00%")      # stopped and reversing frames are not counted
    v = t.update(inputs(lat_active=False, long_active=True))
    self.assertEqual((v[8], v[9]), ("75.00%", "25.00%"))

  def test_first_frame_never_divides_by_zero(self):
    v = L.Tracker(Clock()).update(inputs(standstill=True, lat_active=True))
    self.assertEqual((v[8], v[9]), ("0.00%", "0.00%"))

  def test_reset_starts_a_new_drive(self):
    t = L.Tracker(Clock())
    t.update(inputs(a_ego=2.0, lat_active=True))
    t.reset()
    v = t.update(inputs(a_ego=0.1))
    self.assertEqual((v[2], v[8]), ("0.10 m/s\u00b2", "0.00%"))

  def test_missing_sources_are_dashes_not_zeros(self):
    v = L.Tracker(Clock()).update(inputs())
    for n in (3, 4, 5, 6, 7, 11, 12):
      self.assertEqual(v[n], "-", n)

  def test_learned_values_use_five_decimals(self):
    v = L.Tracker(Clock()).update(inputs(lateral_delay=0.123456789, friction=0.1, lat_accel_factor=2.5, steer_ratio=15.0,
                                         stiffness_factor=1.0, actuator_accel=-0.456))
    self.assertEqual([v[n] for n in (3, 4, 5, 6, 7)], ["0.12346", "0.10000", "2.50000", "15.00000", "1.00000"])
    self.assertEqual(v[12], "-0.46 m/s\u00b2")

  def test_steering_angle_is_whole_degrees(self):
    v = L.Tracker(Clock()).update(inputs(steering_angle_deg=-12.9))
    self.assertEqual(v[10], "12\u00b0")

  def test_torque_hold_shows_the_maximum_for_ten_seconds(self):
    clock = Clock()
    t = L.Tracker(clock)
    v = t.update(inputs(steering_angle_deg=30, actuator_torque=0.4))
    self.assertEqual((v[10], v[11]), ("30\u00b0", "40%"))
    v = t.update(inputs(steering_angle_deg=45, actuator_torque=0.7))
    self.assertEqual((v[10], v[11]), ("45\u00b0 - (45\u00b0)", "70% - (70%)"))
    clock.t += 5
    v = t.update(inputs(steering_angle_deg=10, actuator_torque=0.1))
    self.assertEqual((v[10], v[11]), ("10\u00b0 - (45\u00b0)", "10% - (70%)"))
    clock.t += 6
    v = t.update(inputs(steering_angle_deg=10, actuator_torque=0.1))
    self.assertEqual((v[10], v[11]), ("10\u00b0", "10%"))

  def test_non_finite_input_never_reaches_the_text(self):
    v = L.Tracker(Clock()).update(inputs(a_ego=float("nan"), steering_angle_deg=float("inf"), lateral_delay=float("nan")))
    self.assertEqual((v[1], v[3], v[10]), ("-" + L.ACCEL_UNIT, "-", "0\u00b0"))


class FakeSM:
  def __init__(self, started_frame=5, **msgs):
    self.data = dict(msgs)
    self.recv_frame = {k: started_frame for k in msgs}
    self.alive = {k: True for k in msgs}
    self.valid = {k: True for k in msgs}

  def __getitem__(self, k):
    return self.data[k]


def car_state(**kw):
  return SimpleNamespace(**({"aEgo": 0.5, "gasPressed": False, "standstill": False, "gearShifter": "drive",
                            "steeringAngleDeg": 3.0} | kw))


def car_control(**kw):
  return SimpleNamespace(latActive=True, longActive=True,
                         actuators=SimpleNamespace(accel=0.2, torque=0.3), **kw)


FULL = dict(carState=car_state(), carControl=car_control(), lateralDelay=SimpleNamespace(lateralDelay=0.2),
            lateralTorqueParameters=SimpleNamespace(frictionCoefficientFiltered=0.15, latAccelFactorFiltered=2.0),
            vehicleParameters=SimpleNamespace(steerRatio=14.0, stiffnessFactor=0.9))
ANGLE = SimpleNamespace(steerControlType="angle")
TORQUE = SimpleNamespace(steerControlType="torque")


class TestInputs(unittest.TestCase):
  def test_reads_each_source_on_a_torque_car(self):
    i = L.inputs_from_messages(FakeSM(**FULL), 5, TORQUE)
    self.assertEqual((i.a_ego, i.lat_active, i.long_active, i.actuator_accel, i.actuator_torque), (0.5, True, True, 0.2, 0.3))
    self.assertEqual((i.lateral_delay, i.friction, i.lat_accel_factor, i.steer_ratio, i.stiffness_factor),
                     (0.2, 0.15, 2.0, 14.0, 0.9))

  def test_angle_car_has_no_torque_sources(self):
    i = L.inputs_from_messages(FakeSM(**FULL), 5, ANGLE)
    self.assertIsNone(i.actuator_torque)
    self.assertIsNone(i.friction)
    self.assertIsNone(i.lat_accel_factor)
    self.assertEqual(i.steer_ratio, 14.0)

  def test_unknown_car_does_not_invent_torque(self):
    i = L.inputs_from_messages(FakeSM(**FULL), 5, None)
    self.assertIsNone(i.actuator_torque)
    self.assertIsNone(i.friction)

  def test_stale_car_state_hides_everything(self):
    self.assertIsNone(L.inputs_from_messages(FakeSM(started_frame=4, **FULL), 5, TORQUE))
    sm = FakeSM(**FULL)
    sm.alive["carState"] = False
    self.assertIsNone(L.inputs_from_messages(sm, 5, TORQUE))
    self.assertIsNone(L.inputs_from_messages(FakeSM(), 5, TORQUE))

  def test_each_optional_source_degrades_on_its_own(self):
    for name, fields in (("carControl", ("lat_active", "actuator_accel")), ("lateralDelay", ("lateral_delay",)),
                         ("vehicleParameters", ("steer_ratio",)), ("lateralTorqueParameters", ("friction",))):
      msgs = dict(FULL)
      del msgs[name]
      i = L.inputs_from_messages(FakeSM(**msgs), 5, TORQUE)
      self.assertIsNotNone(i, name)
      for f in fields:
        self.assertIn(getattr(i, f), (None, False), (name, f))

  def test_reverse_gear(self):
    msgs = dict(FULL, carState=car_state(gearShifter="reverse"))
    self.assertTrue(L.inputs_from_messages(FakeSM(**msgs), 5, TORQUE).reverse)

  def test_non_finite_values_become_unavailable(self):
    msgs = dict(FULL, lateralDelay=SimpleNamespace(lateralDelay=float("nan")))
    self.assertIsNone(L.inputs_from_messages(FakeSM(**msgs), 5, TORQUE).lateral_delay)


class TestPlacement(unittest.TestCase):
  def test_takes_the_right_edge(self):
    content, side = L.split_rect(0, 0, 2160, 1080, True)
    self.assertEqual(content, (0, 0, 1860, 1080))
    self.assertEqual(side, (1860, 0, 300, 1080))

  def test_hidden_leaves_the_content_alone(self):
    self.assertEqual(L.split_rect(300, 0, 1860, 1080, False), ((300, 0, 1860, 1080), None))

  def test_narrow_screen_keeps_the_road_view(self):
    self.assertEqual(L.split_rect(0, 0, 500, 400, True), ((0, 0, 500, 400), None))

  def test_tiles_are_evenly_spaced(self):
    tops = L.layout_slots(7, 1080, 126)
    self.assertEqual(len(tops), 7)
    gap = (1080 - 7 * 126) / 8
    self.assertAlmostEqual(tops[0], gap)
    self.assertAlmostEqual(1080 - (tops[-1] + 126), gap)
    self.assertEqual(L.layout_slots(0, 1080), [])


class FakeStore:
  def __init__(self, metrics=None, level_ok=True):
    self.metrics = metrics or {}
    self.reads = 0

  def toggle_int(self, key):
    self.reads += 1
    return self.metrics.get(key, int(key[-1]))


class Gate:
  def __init__(self, on):
    self.on = on

  def get(self):
    return self.on


class TestWidget(unittest.TestCase):
  def setUp(self):
    from openpilot.selfdrive.ui.layouts import developer_sidebar as W
    self.W = W
    self.calls = []
    names = ("draw_rectangle_rec", "begin_scissor_mode", "end_scissor_mode", "draw_rectangle_rounded",
             "draw_rectangle_rounded_lines_ex", "draw_text_ex")
    saved = {n: getattr(W.rl, n) for n in names}
    saved_font, saved_measure, saved_ui = W.gui_app.font, W.measure_text_cached, W.ui_state
    W.rl.draw_rectangle_rec = lambda *a: self.calls.append(("bg",))
    W.rl.begin_scissor_mode = lambda *a: None
    W.rl.end_scissor_mode = lambda *a: None
    W.rl.draw_rectangle_rounded = lambda *a: self.calls.append(("edge",))
    W.rl.draw_rectangle_rounded_lines_ex = lambda *a: self.calls.append(("border",))
    W.rl.draw_text_ex = lambda font, text, pos, size, spacing, color: self.calls.append(("text", text, size))
    W.gui_app.font = lambda *a, **k: None
    W.measure_text_cached = lambda font, text, size: SimpleNamespace(x=len(text) * size * 0.55, y=size * 1.2)
    self.ui = SimpleNamespace(started=True, started_frame=7, sm=FakeSM(started_frame=7, **FULL), CP=TORQUE)
    W.ui_state = self.ui

    def restore():
      for n, v in saved.items():
        setattr(W.rl, n, v)
      W.gui_app.font, W.measure_text_cached, W.ui_state = saved_font, saved_measure, saved_ui
    self.addCleanup(restore)

  def widget(self, on=True, metrics=None):
    return self.W.DeveloperSidebar(store=FakeStore(metrics), gate=Gate(on))

  def draw(self, w):
    w._update_state()
    w._render(SimpleNamespace(x=1860.0, y=0.0, width=300.0, height=1080.0))

  def test_off_or_not_driving_is_not_wanted(self):
    self.assertTrue(self.widget(True).wanted())
    self.assertFalse(self.widget(False).wanted())
    self.ui.started = False
    self.assertFalse(self.widget(True).wanted())

  def test_draws_a_tile_per_chosen_metric(self):
    w = self.widget(metrics={"DeveloperSidebarMetric3": 0, "DeveloperSidebarMetric4": 0, "DeveloperSidebarMetric5": 0,
                              "DeveloperSidebarMetric6": 0, "DeveloperSidebarMetric7": 0})
    self.draw(w)
    texts = [c[1] for c in self.calls if c[0] == "text"]
    self.assertEqual(texts, ["ACCEL", "0.50 m/s\u00b2", "MAX ACCEL", "0.50 m/s\u00b2"])
    self.assertEqual(sum(c == ("border",) for c in self.calls), 2)

  def test_all_seven_default_tiles_on_a_torque_car(self):
    w = self.widget()
    self.draw(w)
    self.assertEqual([c[1] for c in self.calls if c[0] == "text"][::2],
                     ["ACCEL", "MAX ACCEL", "STEER DELAY", "FRICTION", "LAT ACCEL", "STEER RATIO", "STEER STIFF"])

  def test_angle_car_leaves_out_the_torque_tiles_and_closes_the_gap(self):
    self.ui.CP = ANGLE
    w = self.widget()
    self.draw(w)
    self.assertEqual([c[1] for c in self.calls if c[0] == "text"][::2],
                     ["ACCEL", "MAX ACCEL", "STEER DELAY", "STEER RATIO", "STEER STIFF"])

  def test_stale_data_shows_dashes(self):
    self.ui.sm = FakeSM(started_frame=1)
    w = self.widget(metrics={"DeveloperSidebarMetric2": 0, "DeveloperSidebarMetric3": 0, "DeveloperSidebarMetric4": 0,
                              "DeveloperSidebarMetric5": 0, "DeveloperSidebarMetric6": 0, "DeveloperSidebarMetric7": 0})
    self.draw(w)
    self.assertEqual([c[1] for c in self.calls if c[0] == "text"], ["ACCEL", "-"])

  def test_long_values_shrink_to_fit(self):
    w = self.widget(metrics={"DeveloperSidebarMetric1": 10})
    w._values = {10: "123\u00b0 - (123\u00b0) wide wide"}
    w._slots, w._slots_next = [10], 1e12
    w._render(SimpleNamespace(x=0.0, y=0.0, width=300.0, height=1080.0))
    sizes = [c[2] for c in self.calls if c[0] == "text"]
    self.assertLess(min(sizes), 35)
    self.assertGreaterEqual(min(sizes), 20)

  def test_a_new_drive_resets_the_tracker(self):
    w = self.widget()
    self.draw(w)
    w._tracker.max_accel = 9.0
    self.ui.started_frame = 8
    self.ui.sm = FakeSM(started_frame=8, **FULL)
    w._update_state()
    self.assertEqual(w._values[2], "0.50 m/s\u00b2")

  def test_slot_choices_are_read_through_the_store_and_cached(self):
    store = FakeStore()
    w = self.W.DeveloperSidebar(store=store, gate=Gate(True))
    w._read_slots()
    w._read_slots()
    self.assertEqual(store.reads, 7)

  def test_store_failure_draws_no_tiles(self):
    class Broken:
      def toggle_int(self, key):
        raise OSError("down")
    w = self.W.DeveloperSidebar(store=Broken(), gate=Gate(True))
    self.draw(w)
    self.assertEqual([c for c in self.calls if c[0] == "text"], [])

  def test_display_only_no_writes_anywhere(self):
    for rel in ("bogpilot/developer_sidebar_logic.py", "layouts/developer_sidebar.py"):
      src = (UI / rel).read_text()
      for needle in (".put(", "put_bool", "write_text", "open(", "os.remove", "send("):
        self.assertNotIn(needle, src, f"{rel}: {needle}")


class TestWiring(unittest.TestCase):
  def test_main_layout_gives_the_panel_its_width_only_while_driving(self):
    src = (UI / "layouts/main.py").read_text()
    self.assertIn("self._developer_sidebar = DeveloperSidebar()", src)
    body = src[src.index("developer_rect = None"):]
    self.assertIn("self._current_mode == MainState.ONROAD", body)
    self.assertIn("not ui_state.is_body", body)
    self.assertIn("self._developer_sidebar.wanted()", body)
    self.assertLess(body.index("self._layouts[self._current_mode].render(content_rect)"),
                    body.index("self._developer_sidebar.render(developer_rect)"))

  def test_reverse_camera_view_never_shows_it(self):
    src = (UI / "layouts/main.py").read_text()
    reverse = src[src.index("if self._reverse_active:"):src.index("# Render sidebar")]
    self.assertNotIn("developer", reverse)


class MetricParams(FakeParams):
  def all_keys(self):
    return [k.encode() for k in KEYS]


@unittest.skipUnless(importlib.util.find_spec("pyray") is not None, "pyray not installed")
class TestPickers(unittest.TestCase):
  """Native raylib: real button rows and the real option dialog (the window is shared with the other native tests)."""

  @classmethod
  def setUpClass(cls):
    from openpilot.selfdrive.ui.tests.test_bogpilot_developer_rows import native_window
    native_window("developer sidebar")

  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore
    self.tmp = tempfile.mkdtemp(prefix="dev_sidebar_")
    self._env = os.environ.get("BOGPILOT_PARAMS_DIR")
    os.environ["BOGPILOT_PARAMS_DIR"] = self.tmp
    self.typed = {}
    self.store = ParamStore(params=MetricParams(self.typed), cache_ttl=0)
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    self.layout = BogPilotVisualsLayout(store=self.store)
    self.pushed = []
    from openpilot.system.ui.lib import application
    self._push = application.gui_app.push_widget
    application.gui_app.push_widget = lambda w: self.pushed.append(w)
    self.addCleanup(lambda: setattr(application.gui_app, "push_widget", self._push))

  def tearDown(self):
    if self._env is None:
      os.environ.pop("BOGPILOT_PARAMS_DIR", None)
    else:
      os.environ["BOGPILOT_PARAMS_DIR"] = self._env

  def test_seven_pickers_follow_the_switch_and_show_only_while_it_is_on(self):
    self.assertEqual(tuple(self.layout._pickers), L.metric_keys())
    self.layout.refresh()
    self.assertFalse(any(p.is_visible for p in self.layout._pickers.values() if not hasattr(p, "level_gate") or p.level_gate is None))
    self.layout._toggles["DeveloperSidebar"].action_item.set_state(True)
    self.assertTrue(all(p.is_visible for p in self.layout._pickers.values() if p.level_gate is None))

  def test_picker_shows_the_stored_metric(self):
    self.assertEqual(self.layout._metric_name("DeveloperSidebarMetric3"), "Auto Tune: Actuator Delay")   # registry default
    self.typed["DeveloperSidebarMetric3"] = "10"
    self.assertEqual(self.layout._metric_name("DeveloperSidebarMetric3"), "Lateral Control: Steering Angle")
    self.typed["DeveloperSidebarMetric3"] = "0"
    self.assertEqual(self.layout._metric_name("DeveloperSidebarMetric3"), "None")
    self.typed["DeveloperSidebarMetric3"] = "14"   # an old jerk choice has no source here
    self.assertEqual(self.layout._metric_name("DeveloperSidebarMetric3"), "None")

  def test_choosing_writes_the_metric_number(self):
    from openpilot.system.ui.widgets import DialogResult
    dialog = self.layout._open_picker("DeveloperSidebarMetric2")
    self.assertEqual(self.pushed, [dialog])
    self.assertEqual(dialog.options[0], "None")
    self.assertEqual(len(dialog.options), 1 + len(L.METRICS))
    dialog.selection = "Engagement %: Longitudinal"
    dialog._callback(DialogResult.CONFIRM)
    self.assertEqual(self.typed["DeveloperSidebarMetric2"], 9)

  def test_none_writes_zero_and_cancel_writes_nothing(self):
    from openpilot.system.ui.widgets import DialogResult
    dialog = self.layout._open_picker("DeveloperSidebarMetric2")
    dialog.selection = "None"
    dialog._callback(DialogResult.CONFIRM)
    self.assertEqual(self.typed["DeveloperSidebarMetric2"], 0)
    before = dict(self.typed)
    dialog = self.layout._open_picker("DeveloperSidebarMetric2")
    dialog.selection = "Acceleration: Max"
    dialog._callback(DialogResult.CANCEL)
    self.assertEqual(self.typed, before)

  def test_angle_car_is_not_offered_the_torque_metrics(self):
    self.layout._torque_steering = lambda: False
    dialog = self.layout._open_picker("DeveloperSidebarMetric1")
    self.assertEqual(len(dialog.options), 1 + len(L.METRICS) - 3)
    self.assertNotIn("Auto Tune: Friction", dialog.options)
    self.assertNotIn("Lateral Control: Torque % Used", dialog.options)

  def test_switch_row_writes_the_key_the_sidebar_reads(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.overlay_gate import OverlayGate
    self.assertFalse(OverlayGate("DeveloperSidebar", store=self.store).get())
    self.layout._write("DeveloperSidebar", True)
    self.assertEqual(self.typed["DeveloperSidebar"], "1")
    self.assertTrue(OverlayGate("DeveloperSidebar", store=self.store).get())

  def test_pickers_have_help_and_a_level_gate(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve
    for key, picker in self.layout._pickers.items():
      self.assertEqual(picker.help_key, key)
      self.assertIsNotNone(resolve(key))
      self.assertIsNotNone(picker.level_gate)


if __name__ == "__main__":
  unittest.main()
