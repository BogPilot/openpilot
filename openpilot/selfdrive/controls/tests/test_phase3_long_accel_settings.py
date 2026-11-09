"""Actual raylib action callbacks -> real ParamStore -> native planner/LongControl.

Run only in native M4/AGNOS display context (Xvfb is sufficient). No on-road data.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import os
import pytest
import pyray as rl
from openpilot.common.bogpilot_store import ParamStore
from openpilot.common.params import Params
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import (
  AdvancedLongitudinalSettings, LongitudinalProfilesSettings, ConditionalExperimentalSettings,
  SettingsController, Capabilities, BY_KEY,
)
from openpilot.selfdrive.controls.lib.phase3_long_accel import PROFILE_ACK, ADVANCED_ACK, CEM_ACK
from openpilot.selfdrive.ui.onroad.bogpilot.phase3_cem_status import read_status, paint_status, HIDDEN
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import planner, SM, msgs
from openpilot.selfdrive.controls.lib.longcontrol import LongControl
from openpilot.system.ui.lib.application import gui_app


@pytest.fixture(scope='module', autouse=True)
def window():
  if os.environ.get('PHASE3_CALLBACK_ONLY'):
    # Font-resource dependency only: actual native raylib Widgets/actions and their
    # registered event callbacks remain real. No rendered-frame claim is made.
    original = gui_app.font
    gui_app.font = lambda *a, **kw: rl.Font()
    yield
    gui_app.font = original
    return
  gui_app.init_window('BogPilot isolated Gas / Brake UI tests', fps=30)
  assert rl.is_window_ready(), 'Native display server unavailable; no draw calls permitted'
  yield
  gui_app.close()


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv('BOGPILOT_PARAMS_DIR', str(tmp_path / 'prefs'))
  class BlockingSetupStore(ParamStore):
    # Only deterministic test setup defaults to blocking; configure() requests
    # block=True itself in production. All reads/writes use real native Params.
    def put(self, key, value, *, block=True): return super().put(key, value, block=block)
    def put_bool(self, key, value, *, block=True): return super().put_bool(key, value, block=block)
  s = BlockingSetupStore(params=Params(str(tmp_path / "native_params")))
  s.put_bool('TuningLevelConfirmed', True)
  s.put('TuningLevel', 3)
  return s


def metric(store, on=True):
  # IsMetric is a stock compiled BOOL key: write it through Params (ParamStore only types BogPilot registry keys).
  store._params.put_bool('IsMetric', on, block=True)
  store.invalidate()


def toggle(panel, key):
  # The REAL native Toggle mouse-release method dispatches the registered callback.
  panel.items[key].action_item.toggle._handle_mouse_release(None)


def render(panel, name=None):
  if os.environ.get("PHASE3_CALLBACK_ONLY"):
    return
  assert rl.is_window_ready(), "Native window unavailable; do not enter unsafe draw calls"
  rl.begin_drawing()
  rl.clear_background(rl.BLACK)
  panel.render(rl.Rectangle(0, 0, 2160, 1080))
  rl.end_drawing()
  if name and os.environ.get('UI_RENDER_OUT'):
    rl.take_screenshot(str(Path(os.environ['UI_RENDER_OUT']) / name))


def test_open_and_units_do_not_adopt_or_reset_saved_preferences(store):
  store.put('AccelerationProfile', 3)
  store.put('DecelerationProfile', 2)
  panel = LongitudinalProfilesSettings(store)
  panel.show_event()
  render(panel, 'profiles-not-adopted.png')
  assert not store.get_bool(PROFILE_ACK, False)
  assert store.get_int('AccelerationProfile') == 3 and store.get_int('DecelerationProfile') == 2
  assert tuple(panel.items) == ('LongitudinalTune',)
  metric(store)
  panel.show_event()
  assert not store.get_bool(PROFILE_ACK, False)
  assert store.get_int('AccelerationProfile') == 3


def test_real_profile_choice_callback_drives_native_output_and_disable_restores_baseline(store):
  store.put_bool('HumanAcceleration', False)
  store.put('AccelerationProfile', 3)
  panel = LongitudinalProfilesSettings(store)
  toggle(panel, 'LongitudinalTune')
  assert store.get_bool(PROFILE_ACK, False)
  outputs = []
  p = planner(toggle=False)
  p.long_accel.store = store
  for choice in (1, 2):
    panel.items['AccelerationProfile'].action_item.callback(choice)
    for _ in range(100): p.update(SM(msgs(10, 30)))
    outputs.append(p.output_a_target)
  assert outputs == [pytest.approx(1), pytest.approx(1.7)]
  # On/off is an actual UI callback, not merely an engine flag asserted in isolation.
  toggle(panel, 'LongitudinalTune')
  assert store.get_int('AccelerationProfile') == 2  # retained, not reset on disable
  persisted = ParamStore(params=Params(store._params.d))
  assert persisted.get_int('AccelerationProfile') == 2 and not persisted.get_bool('LongitudinalTune')
  baseline = planner(toggle=False)
  baseline.long_accel.store = ParamStore(params=Params(store._params.d))
  for _ in range(100):
    message = SM(msgs(10, 30))
    p.update(message)
    baseline.update(message)
  assert p.output_a_target == baseline.output_a_target
  render(panel, 'profiles-disabled-retained.png')


def test_actual_deceleration_choice_and_human_controls(store):
  panel = LongitudinalProfilesSettings(store)
  toggle(panel, 'LongitudinalTune')
  panel.items['DecelerationProfile'].action_item.callback(2)
  from openpilot.selfdrive.controls.lib.phase3_long_accel import Profiles
  assert Profiles.read(store).limits(10, 0, -3.5)[0] == -.875
  toggle(panel, 'HumanAcceleration')
  assert Profiles.read(store).human == store.get_bool('HumanAcceleration')
  render(panel, 'longitudinal-tuning.png')


def test_real_number_buttons_store_then_native_delay_and_actuator_cap_and_disable(store, monkeypatch):
  cp = planner().CP
  store.put('MaxDesiredAcceleration', .2)
  store.put('LongitudinalActuatorDelay', .1)
  panel = AdvancedLongitudinalSettings(store, cp=cp)
  toggle(panel, 'AdvancedLongitudinalTune')
  panel.items['MaxDesiredAcceleration'].action_item.plus._click_callback()
  panel.items['LongitudinalActuatorDelay'].action_item.plus._click_callback()
  assert store.get_float('MaxDesiredAcceleration') == .3
  assert store.get_float('LongitudinalActuatorDelay') == .11
  assert store.get_bool(ADVANCED_ACK, False)
  p = planner(toggle=False)
  p.long_accel.store = store
  import openpilot.selfdrive.controls.lib.longitudinal_planner as native
  project = native.get_accel_from_plan
  seen = []
  def capture(*a, **kw):
    seen.append(kw['action_t'])
    return project(*a, **kw)
  monkeypatch.setattr(native, 'get_accel_from_plan', capture)
  p.update(SM(msgs(10, 30)))
  assert seen == [pytest.approx(.16)]
  control = LongControl(cp)
  control.long_accel_store = store
  cs = SM(msgs(10, 30))['carState']
  assert control.update(True, cs, 2, False, [-3.5, 2]) == pytest.approx(.3)
  toggle(panel, 'AdvancedLongitudinalTune')
  assert control.update(True, cs, 2, False, [-3.5, 2]) > .3
  assert control.update(False, cs, 2, False, [-3.5, 2]) == 0
  assert store.get_float('MaxDesiredAcceleration') == .3
  toggle(panel, 'AdvancedLongitudinalTune')
  render(panel, 'advanced-longitudinal-tuning.png')


def test_numeric_clamps_metric_ranges_and_parent_tuning_visibility(store):
  panel = ConditionalExperimentalSettings(store)
  toggle(panel, 'ConditionalExperimental')
  assert 'CEModelStopTime' in panel.items and 'CEStopLights' not in panel.items
  c = panel.controller
  assert c.change('CESpeed', 999) and store.get_int('CESpeed') == 99
  metric(store)
  assert c.change('CESpeed', 999) and store.get_int('CESpeed') == 150
  assert c.value_text('CESpeed') == '150 km/h'
  assert c.change('CEModelStopTime', 999) and store.get_int('CEModelStopTime') == 9
  assert c.change('CEModelStopTime', -1) and c.value_text('CEModelStopTime') == 'Off'
  store.put('TuningLevel', 1)
  panel.show_event()
  assert 'CEStopLights' in panel.items and 'CEModelStopTime' not in panel.items
  assert 'CESignalSpeed' not in panel.items
  render(panel, 'conditional-minimal-tuning.png')


def test_all_owned_cem_nested_controls_have_real_actions_and_navigation_rows_are_hidden_without_a_producer(store):
  for key in ('CECurves', 'CELead', 'CENavigation'): store.put_bool(key, True)
  store.put('CESignalSpeed', 55)
  panel = ConditionalExperimentalSettings(store)
  toggle(panel, 'ConditionalExperimental')
  for key in ('CESpeedLead', 'CECurvesLead', 'CESlowerLead', 'CEStoppedLead', 'CESignalLaneDetection', 'ShowCEMStatus'):
    assert key in panel.items
  # No consumer-less rows: the navigation rows stay hidden (saved values retained) until a real producer exists.
  for key in ('CENavigation', 'CENavigationIntersections', 'CENavigationTurns', 'CENavigationLead'):
    assert key not in panel.items
  assert not panel.controller.enabled(BY_KEY['CENavigation'])
  before = store.raw('CENavigation')
  assert not panel.controller.change('CENavigation', False)
  assert store.raw('CENavigation') == before
  render(panel, 'conditional-experimental.png')
  # Explicitly scroll/render lower nested predicates too; no fake navigation source.
  panel.scroller.scroll_panel.set_offset(-1100)
  render(panel, 'conditional-nested.png')
  assert not Capabilities().navigation and not Capabilities().slc and not Capabilities().v9_prediction


def test_real_cem_ui_callback_to_native_e2e_status_publisher_and_hud(store):
  store.put('CESpeed', 40)
  store.put('CEModelStopTime', 0)
  store.put('CESignalSpeed', 0)
  store.put_bool('ShowCEMStatus', True)
  panel = ConditionalExperimentalSettings(store)
  toggle(panel, 'ConditionalExperimental')
  p = planner(toggle=False)
  p.long_accel.store = store
  p.update(SM(msgs(10, 20, e2e_accel=-2)))
  assert p.output_a_target <= -2 and p.long_accel.cem.status == 4
  class PM:
    plan = None
    def send(self, service, message): self.plan = message.frogpilotPlan
  pm = PM()
  p.publish_frogpilot_plan(pm)
  assert store.get_int('CEStatus') == 4
  report = SM({'frogpilotPlan': pm.plan})
  report.recv_time = {'frogpilotPlan': 99.9}
  view = read_status(store, report, 100, 90, True)
  assert view.visible and view.active and view.text == 'CEM: Speed'
  if not os.environ.get("PHASE3_CALLBACK_ONLY"):
    rl.begin_drawing()
    rl.clear_background(rl.BLACK)
    paint_status(view, rl.Rectangle(30, 470, 280, 54))
    rl.end_drawing()
    if os.environ.get('UI_RENDER_OUT'):
      rl.take_screenshot(str(Path(os.environ['UI_RENDER_OUT']) / 'cem-status-active.png'))
  assert read_status(store, report, 101, 90, True) == HIDDEN
  assert read_status(store, report, 100, 100, True) == HIDDEN
  toggle(panel, 'ShowCEMStatus')
  assert read_status(store, report, 100, 90, True) == HIDDEN
  assert p.long_accel.cem.experimental  # widget switch is display-only
  toggle(panel, 'ConditionalExperimental')
  p.update(SM(msgs(10, 20, e2e_accel=-2)))
  p.publish_frogpilot_plan(pm)
  assert store.get_int('CEStatus') == 0 and p.output_a_target > -2


def test_existing_status_key_has_no_new_schema_and_no_startup_clear_without_adoption(store):
  p = planner(toggle=False)
  p.long_accel.store = store
  store.put('CEStatus', 2)
  p.long_accel.publish_status()
  assert store.get_int('CEStatus') == 2
  from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
  assert BOGPILOT_PARAMS['CEStatus'][1] == 'INT'


def test_actual_shared_hud_proposal_import_and_badge_draw():
  if os.environ.get('PHASE3_CALLBACK_ONLY'):
    pytest.skip('Native Xvfb server segfaults before window creation; actual rendered-frame check pending')
  from openpilot.selfdrive.ui.onroad.bogpilot.bogpilot_hud import draw_cem_status
  from openpilot.selfdrive.ui.onroad.bogpilot.phase3_cem_status import StatusView
  hud = NS(bp_cem=StatusView(True, 'CEM: Lead', True, 9), bp_extra_keepouts=[])
  rl.begin_drawing()
  rl.clear_background(rl.BLACK)
  draw_cem_status(hud, rl.Rectangle(0, 0, 2160, 1080))
  rl.end_drawing()
  assert len(hud.bp_extra_keepouts) == 1
  if os.environ.get('UI_RENDER_OUT'):
    rl.take_screenshot(str(Path(os.environ['UI_RENDER_OUT']) / 'cem-actual-hud-proposal.png'))


def test_real_navigation_entry_callback_constructs_exact_factory_without_adopting(store):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import gas_accel_entries
  opened = []
  entries = gas_accel_entries(lambda widget, title: opened.append((widget, title)), store)
  assert len(entries) == 3
  entries[0].callback()
  assert opened[0][1] == 'Advanced Longitudinal Tuning'
  assert not store.get_bool(ADVANCED_ACK, False)


def test_real_nested_slower_lead_callback_drives_native_cem_and_disable(store):
  for key in ('CESpeed', 'CESpeedLead', 'CEModelStopTime', 'CESignalSpeed'): store.put(key, 0)
  store.put_bool('CELead', True)
  store.put_bool('CESlowerLead', False)
  store.put_bool('CEStoppedLead', False)
  panel = ConditionalExperimentalSettings(store)
  toggle(panel, 'ConditionalExperimental')
  toggle(panel, 'CESlowerLead')
  p = planner(toggle=False)
  p.long_accel.store = store
  for _ in range(80): p.update(SM(msgs(20, 30, lead=(15, 10))))
  assert p.long_accel.cem.status == 10
  toggle(panel, 'CESlowerLead')
  for _ in range(80): p.update(SM(msgs(20, 30, lead=(15, 10))))
  assert not p.long_accel.cem.experimental


def test_real_simple_stop_light_callback_at_historical_lower_level(store):
  store.put('TuningLevel', 1)
  for key in ('CESpeed', 'CESpeedLead', 'CESignalSpeed'): store.put(key, 0)
  store.put_bool('CEStopLights', False)
  panel = ConditionalExperimentalSettings(store)
  toggle(panel, 'ConditionalExperimental')
  assert 'CEStopLights' in panel.items and 'CEModelStopTime' not in panel.items
  toggle(panel, 'CEStopLights')
  p = planner(toggle=False)
  p.long_accel.store = store
  for _ in range(80): p.update(SM(msgs(10, 20, model_v=1)))
  assert p.long_accel.cem.status == 11
  toggle(panel, 'CEStopLights')
  for _ in range(80): p.update(SM(msgs(10, 20, model_v=1)))
  assert not p.long_accel.cem.experimental


def test_real_signal_nested_callback_uses_actual_native_lane_geometry(store):
  metric(store)
  store.put_bool('LaneChanges', True)
  store.put('LaneDetectionWidth', 3)
  store.put('MinimumLaneChangeSpeed', 0)
  for key in ('CESpeed', 'CESpeedLead', 'CEModelStopTime'): store.put(key, 0)
  store.put('CESignalSpeed', 100)
  store.put_bool('CESignalLaneDetection', False)
  panel = ConditionalExperimentalSettings(store)
  toggle(panel, 'ConditionalExperimental')
  p = planner(toggle=False)
  p.long_accel.store = store
  def message():
    sm = SM(msgs(10, 20, blinker=True))
    # Real capnp model messages with explicit synthetic geometry, not a runtime feed.
    sm['modelV2'].laneLines = [{'x': [0., 100.], 'y': [y, y]} for y in (-3., -1.8, 1.8, 5.4)]
    sm['modelV2'].roadEdges = [{'x': [0., 100.], 'y': [y, y]} for y in (-10., 10.)]
    return sm
  p.update(message())
  assert not p.long_accel.cem.experimental
  toggle(panel, 'CESignalLaneDetection')
  p.update(message())
  assert p.long_accel.cem.status == 5
  toggle(panel, 'CESignalLaneDetection')
  p.update(message())
  assert not p.long_accel.cem.experimental


def test_actual_hud_wiring_dispatches_status_painter_without_claiming_pixels(monkeypatch):
  from openpilot.selfdrive.ui.onroad.bogpilot import bogpilot_hud as native_hud
  from openpilot.selfdrive.ui.onroad.bogpilot.phase3_cem_status import StatusView
  calls = []
  monkeypatch.setattr(native_hud.CEM, 'paint_status', lambda view, rect: calls.append((view, rect)))
  hud = NS(bp_cem=StatusView(True, 'CEM: Lead', True, 9), bp_extra_keepouts=[])
  native_hud.draw_cem_status(hud, rl.Rectangle(0, 0, 2160, 1080))
  assert calls[0][0].reason == 9 and len(hud.bp_extra_keepouts) == 1


def test_explicit_units_hook_preserves_physical_saved_preferences_without_adopting(store):
  from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import convert_cem_speed_units
  store.put('CESignalSpeed', 55)
  assert convert_cem_speed_units(store, False, True)
  metric(store)
  assert store.get_int('CESignalSpeed') == 88  # old Qt integer truncation
  assert not store.get_bool(CEM_ACK, False)
  c = SettingsController('conditional', store)
  assert c.value_text('CESignalSpeed') == '88 km/h'
  assert not convert_cem_speed_units(store, True, True)
  assert store.get_int('CESignalSpeed') == 88


def test_unwritten_speed_defaults_remain_mph_based_in_metric_without_seed_writes(store):
  from openpilot.selfdrive.controls.lib.phase3_long_accel import Conditions
  metric(store)
  store.put_bool('ConditionalExperimental', True)
  store.put_bool(CEM_ACK, True)
  assert store.raw('CESignalSpeed') is None
  assert Conditions.read(store).signal == float(store.default('CESignalSpeed')) * .44704
  c = SettingsController('conditional', store)
  assert c.display_value('CESignalSpeed') == int(float(store.default('CESignalSpeed')) * 1.609344)
  assert store.raw('CESignalSpeed') is None
