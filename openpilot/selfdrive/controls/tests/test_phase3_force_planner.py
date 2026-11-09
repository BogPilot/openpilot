"""Real native planner/MPC proof: ForceStops works while CEM remains OFF."""
import importlib.util
import os
from pathlib import Path
import pytest

from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import planner, SM, msgs
from openpilot.selfdrive.ui.bogpilot.phase3_stopping_settings import StoppingSettingsModel, StoppingCapabilities


class EmptyKeys:
  def all_keys(self): return []


@pytest.fixture
def setup(tmp_path, monkeypatch):
  monkeypatch.setenv('BOGPILOT_PARAMS_DIR', str(tmp_path))
  store = ParamStore(params=EmptyKeys())
  p = planner(toggle=False)
  p.long_accel.store = store
  ui = StoppingSettingsModel(store, p.CP, StoppingCapabilities(force_stop_inputs=True), lambda: True)
  return p, store, ui


def test_real_force_stop_cem_off_reduces_actual_planner_output(setup):
  p, store, ui = setup
  store.put_bool("ConditionalExperimental", False)
  assert ui.change('qol', 'ForceStops', True)
  assert not store.get_bool('Phase3CEMEnabled', False)
  for _ in range(100): p.update(SM(msgs(10, 20, model_v=1)))
  assert p.long_accel.model_valid and p.long_accel.model_stopped
  assert p.long_accel.conditions is None and not p.long_accel.cem.experimental
  assert p.long_accel.cem.status == 0
  assert p.force_stop_result.forcing_stop and p.force_stop_result.target == 0
  assert p.output_a_target < 0
  assert not store.get_bool('ConditionalExperimental')
  assert not store.get_bool('Phase3CEMEnabled', False)


@pytest.mark.parametrize('bad', ['gas', 'brake', 'stale', 'disengaged', 'traffic', 'lead'])
def test_real_force_stop_release_and_source_guards(setup, bad):
  p, store, ui = setup
  ui.change('qol', 'ForceStops', True)
  for _ in range(100): p.update(SM(msgs(10, 20, model_v=1)))
  assert p.force_stop_result.forcing_stop
  sm = SM(msgs(10, 20, model_v=1, enabled=bad != 'disengaged'))
  if bad == 'gas': sm['carState'].gasPressed = True
  if bad == 'brake': sm['carState'].brakePressed = True
  if bad == 'stale': sm.valid['modelV2'] = False
  if bad == 'traffic': sm['carState'].bogpilot.trafficModeEnabled = True
  if bad == 'lead':
    sm['radarState'].leadOne.present = True
    sm['radarState'].leadOne.dRel = 10
    sm['radarState'].leadOne.vRel = 0
    sm['radarState'].leadOne.vLead = 10
  for _ in range(40 if bad == 'lead' else 1): p.update(sm)
  assert not p.force_stop_result.forcing_stop
  assert not p.long_accel.cem.experimental
  if bad == 'gas': assert p.long_stopping.force_stop.override_timer == 10


def test_real_force_stop_no_adoption_dormant_settings_preserves_stock_200_frames(setup):
  p, store, ui = setup
  store.put_bool('ForceStops', True)
  path = os.environ.get('BASELINE_LONG_PLANNER')
  if not path: pytest.skip('Set BASELINE_LONG_PLANNER to committed stock planner source')
  spec = importlib.util.spec_from_file_location('phase3_stopping_stock_planner', path)
  old_module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(old_module)
  old = old_module.LongitudinalPlanner(p.CP)
  old.curve_speed = p.curve_speed
  for tick in range(200):
    sm = SM(msgs(10 + tick/100, 20, model_v=1))
    p.update(sm)
    old.update(sm)
    assert p.output_a_target == old.output_a_target
    assert p.output_should_stop == old.output_should_stop
    assert not p.force_stop_result.forcing_stop
