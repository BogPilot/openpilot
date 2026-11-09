"""Native-only deterministic current-controller replay, not a vehicle qualification.

Run from lane worktree with primary native dependencies on PYTHONPATH.
Uses real ParamStore + current LatControlTorque + current VehicleModel.
"""
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[3]
for name, rel in [
  ('openpilot.selfdrive.controls.lib.phase3_steering_tuning', 'selfdrive/controls/lib/phase3_steering_tuning.py'),
  ('openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning', 'selfdrive/ui/bogpilot/phase3_steering_tuning.py'),
]:
  spec = importlib.util.spec_from_file_location(name, ROOT / rel)
  mod = importlib.util.module_from_spec(spec)
  sys.modules[name] = mod
  spec.loader.exec_module(mod)

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.common.bogpilot_store import ParamStore
from openpilot.selfdrive.controls.lib.phase3_steering_tuning import SteeringTuning, numeric_rows
from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import TuningEditor
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque, INTERP_SPEEDS, KP_INTERP
from opendbc.car.structs import car


# Legacy rows with no 0.11.2 consumer: omitted, never writable, never registered.
OMITTED = ('SteerKP', 'ForceTorqueController', 'NNFF', 'NNFFLite')



def _legacy_lateral_settings():
  """Legacy 0.9.7 inventory lives in git history only; skip (not fail) where that commit is not in the checkout (e.g. AGNOS VM stage)."""
  import subprocess
  import unittest
  try:
    return subprocess.check_output(['git', 'show', '04d560f3e:frogpilot/ui/qt/offroad/lateral_settings.cc'], text=True, stderr=subprocess.DEVNULL)
  except (subprocess.CalledProcessError, FileNotFoundError):
    raise unittest.SkipTest("legacy history commit 04d560f3e not available in this checkout; verified on the Mac worktree")


class MemoryParams:
  def __init__(self, values=None):
    self.data = dict(values or {})
    self.writes = []
  def all_keys(self):
    return list(BOGPILOT_PARAMS) + ['IsMetric']
  def get(self, key):
    return self.data.get(key)
  def put(self, key, value):
    self.data[key] = str(value)
    self.writes.append((key, value))
  def put_bool(self, key, value):
    self.put(key, '1' if value else '0')
  def remove(self, key):
    self.data.pop(key, None)
    self.writes.append((key, None))


def cp_for(kind='torque', brand='ford'):
  cp = car.CarParams.new_message()
  cp.brand = brand
  cp.steerControlType = kind
  cp.steerRatio = 15.
  cp.steerActuatorDelay = .1
  cp.steerLimitTimer = .8
  cp.lateralTuning.init('torque')
  cp.lateralTuning.torque.latAccelFactor = 2.
  cp.lateralTuning.torque.friction = .1
  return cp.as_reader()


class LinearInterface:
  # Deliberately simple synthetic platform, using the real current controller.
  def torque_from_lateral_accel(self):
    return lambda accel, p: accel / p.latAccelFactor
  def lateral_accel_from_torque(self):
    return lambda torque, p: torque * p.latAccelFactor


def live(auto=False):
  return NS(useParams=auto, latAccelFactorFiltered=2.2, latAccelOffsetFiltered=.02, frictionCoefficientFiltered=.12)


def replay(tuning, active=True):
  lac = LatControlTorque(tuning.cp, LinearInterface(), .01)
  tuning.update_torque(lac, live(False), True)
  cs = NS(vEgo=20., steeringAngleDeg=0., steeringPressed=False, leftBlinker=False, rightBlinker=False)
  vm = NS(calc_curvature=lambda angle, speed, roll: angle / tuning.ratio(15.) / 2.7)
  params = NS(angleOffsetDeg=0., roll=0.)
  output = []
  for _ in range(120):
    torque, _, _ = lac.update(active and tuning.lateral_allowed(cs), cs, vm, params, False, .0005, False, .3)
    assert math.isfinite(torque) and abs(torque) <= 1.
    output.append(float(torque))
  return output, lac


class TestSteeringTuning(unittest.TestCase):
  def make(self, values=None, kind='torque', brand='ford'):
    backend = MemoryParams(values)
    store = ParamStore(backend)
    cp = cp_for(kind, brand)
    editor = TuningEditor(cp, store, lambda: True)
    return cp, store, backend, editor

  def test_defaults_no_writes_identical_controller(self):
    cp, store, backend, _ = self.make()
    tuning = SteeringTuning(cp, store)
    out, lac = replay(tuning)
    baseline = LatControlTorque(cp, LinearInterface(), .01)
    cs = NS(vEgo=20., steeringAngleDeg=0., steeringPressed=False)
    vm = NS(calc_curvature=lambda *args: 0.)
    params = NS(angleOffsetDeg=0., roll=0.)
    expected = [float(baseline.update(True, cs, vm, params, False, .0005, False, .3)[0]) for _ in range(120)]
    self.assertEqual(out, expected)
    self.assertEqual(lac.pid._k_p, [INTERP_SPEEDS, KP_INTERP])
    self.assertEqual(backend.writes, [])
    self.assertEqual(tuning.values, {})

  def test_ui_param_real_controller_replay(self):
    cp, store, backend, editor = self.make()
    baseline, _ = replay(SteeringTuning(cp, store))
    self.assertTrue(editor.write('AdvancedLateralTune', True))
    self.assertTrue(editor.write('SteerLatAccel', 2.3))
    self.assertTrue(editor.write('SteerFriction', .2))
    tuned, lac = replay(SteeringTuning(cp, store))
    self.assertNotEqual(tuned, baseline)
    self.assertAlmostEqual(lac.torque_params.latAccelFactor, 2.3)
    self.assertAlmostEqual(lac.torque_params.friction, .2)
    self.assertTrue(editor.reset('SteerLatAccel'))
    self.assertTrue(editor.reset('SteerFriction'))
    restored, _ = replay(SteeringTuning(cp, store))
    self.assertEqual(restored, baseline)

  def test_ratio_range_and_real_vehicle_model(self):
    from opendbc.car.vehicle_model import VehicleModel
    cp, store, _, editor = self.make({'AdvancedLateralTune':'1'})
    cp=cp.as_builder()
    cp.wheelbase=2.7;cp.centerToFront=1.2
    cp.rotationalInertiaPerMass=1.5;cp.tireStiffnessFrontPerMass=100.;cp.tireStiffnessRearPerMass=100.
    vm = VehicleModel(cp)
    vm.update_params(1., 15.)
    before=vm.calc_curvature(.1,20.,0.)
    self.assertTrue(editor.write('SteerRatio', 18.))
    tuning=SteeringTuning(cp,store)
    vm.update_params(1.,tuning.ratio(15.))
    self.assertNotEqual(vm.calc_curvature(.1,20.,0.),before)
    self.assertFalse(editor.write('SteerRatio', 23.))

  def test_onroad_and_unknown_guard(self):
    cp, store, backend, editor = self.make({'AdvancedLateralTune':'1'})
    editor.offroad=lambda:False
    for key,val in [('SteerRatio',16.),('SteerDelay',.3),('AdvancedLateralTune',False),('ForceAutoTune',True),('QOLLateral',True)]:
      self.assertFalse(editor.write(key,val))
    self.assertFalse(editor.reset('SteerRatio'))
    editor.offroad=lambda:True
    for key in OMITTED:
      self.assertFalse(editor.write(key,True))
      self.assertFalse(editor.write(key,1.))
    self.assertEqual(backend.writes,[])

  def test_angle_curvature_no_torque_controller_override(self):
    for kind in ('angle','curvature'):
      cp,store,backend,editor=self.make({'AdvancedLateralTune':'1','SteerFriction':'.2','ForceAutoTune':'1'},kind)
      self.assertFalse(editor.write('SteerFriction',.25))
      self.assertFalse(editor.write('ForceAutoTune',True))
      tuning=SteeringTuning(cp,store)
      self.assertFalse(tuning.torque)
      self.assertNotIn('SteerFriction',tuning.values)
      tuning.update_torque(object(),live(),True)

  def test_auto_validity_and_force_off(self):
    cp,store,_,editor=self.make({'AdvancedLateralTune':'1'},brand='toyota')
    lac=LatControlTorque(cp,LinearInterface(),.01)
    tuning=SteeringTuning(cp,store)
    tuning.update_torque(lac,live(True),False)
    self.assertEqual(lac.torque_params.latAccelFactor,2.)
    tuning.update_torque(lac,live(True),True)
    self.assertAlmostEqual(lac.torque_params.latAccelFactor,2.2)
    self.assertFalse(editor.write('ForceAutoTune',True))
    self.assertTrue(editor.write('ForceAutoTuneOff',True))
    self.assertTrue(editor.write('SteerFriction',.2))
    self.assertTrue(editor.write('SteerLatAccel',2.3))
    SteeringTuning(cp,store).update_torque(lac,live(True),True)
    self.assertAlmostEqual(lac.torque_params.latAccelFactor,2.3)
    self.assertAlmostEqual(lac.torque_params.friction,.2)

  def test_force_on_does_not_ignore_validity(self):
    cp,store,_,editor=self.make({'AdvancedLateralTune':'1'})
    self.assertTrue(editor.write('ForceAutoTune',True))
    self.assertFalse(editor.write('SteerFriction',.2))
    tuning=SteeringTuning(cp,store)
    lac=LatControlTorque(cp,LinearInterface(),.01)
    tuning.update_torque(lac,live(False),False)
    self.assertEqual(lac.torque_params.latAccelFactor,2.)
    tuning.update_torque(lac,live(False),True)
    self.assertAlmostEqual(lac.torque_params.latAccelFactor,2.2)

  def test_bad_saved_values_retained_not_activated(self):
    for value in ('NaN','inf','bad','0','40'):
      cp,store,backend,_=self.make({'AdvancedLateralTune':'1','SteerRatio':value})
      self.assertEqual(SteeringTuning(cp,store).ratio(15.),15.)
      self.assertEqual(backend.data['SteerRatio'],value)
      self.assertEqual(backend.writes,[])

  def test_missing_values_not_zero_or_default_writes(self):
    cp,store,backend,_=self.make({'AdvancedLateralTune':'1'})
    self.assertEqual(SteeringTuning(cp,store).values,{})
    self.assertEqual(backend.writes,[])

  def test_tuning_level_guard(self):
    cp,store,backend,editor=self.make({'TuningLevelConfirmed':'1','TuningLevel':'0','AdvancedLateralTune':'1','SteerRatio':'18'})
    self.assertFalse(editor.write('SteerRatio',18.))
    self.assertEqual(SteeringTuning(cp,store).ratio(15.),15.)
    self.assertEqual(backend.writes,[])

  def test_next_drive_snapshot(self):
    cp,store,_,editor=self.make({'AdvancedLateralTune':'1'})
    old=SteeringTuning(cp,store)
    self.assertTrue(editor.write('SteerRatio',18.))
    self.assertEqual(old.ratio(15.),15.)
    self.assertEqual(SteeringTuning(cp,store).ratio(15.),18.)

  def test_qol_pause_signal_and_units(self):
    cp,store,_,editor=self.make()
    self.assertTrue(editor.write('QOLLateral',True))
    self.assertTrue(editor.write('PauseLateralSpeed',20))
    self.assertTrue(editor.write('PauseLateralOnSignal',True))
    t=SteeringTuning(cp,store)
    self.assertAlmostEqual(t.pause_speed,8.9408)
    self.assertFalse(t.lateral_allowed(NS(vEgo=5.,leftBlinker=True,rightBlinker=False)))
    self.assertTrue(t.lateral_allowed(NS(vEgo=5.,leftBlinker=False,rightBlinker=False)))
    self.assertTrue(t.lateral_allowed(NS(vEgo=10.,leftBlinker=True,rightBlinker=False)))
    store.put_bool('IsMetric',True)
    self.assertAlmostEqual(SteeringTuning(cp,store).pause_speed,20/3.6)
    self.assertEqual(store.get_int('PauseLateralSpeed'),20)

  def test_inactive_is_always_zero(self):
    cp,store,_,_=self.make({'AdvancedLateralTune':'1','SteerFriction':'.2'})
    out,_=replay(SteeringTuning(cp,store),False)
    self.assertEqual(out,[0.]*120)

  def test_exact_legacy_row_count_and_embedded(self):
    import subprocess,re
    s = _legacy_lateral_settings()
    vector=s.split('lateralToggles {',1)[1].split('\n  };',1)[0]
    rows=re.findall(r'\{"([^"]+)"',vector)
    self.assertEqual(len(rows),25)
    self.assertIn('PauseLateralOnSignal',s)
    self.assertEqual(set(r.key for r in numeric_rows(cp_for())),{'SteerDelay','SteerRatio','SteerFriction','SteerLatAccel'})


  def test_capability_projection_matches_current_estimator(self):
    import ast
    from openpilot.selfdrive.controls.lib.phase3_steering_tuning import NATIVE_AUTO_TUNE_BRANDS
    source=Path(sys.modules[LatControlTorque.__module__].__file__).parents[2] / 'locationd/torqued.py'
    tree=ast.parse(source.read_text())
    allowed=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ALLOWED_CARS' for t in n.targets))
    self.assertEqual(tuple(allowed),NATIVE_AUTO_TUNE_BRANDS)

  def test_default_qol_never_changes_negative_speed(self):
    cp,store,_,_=self.make()
    self.assertTrue(SteeringTuning(cp,store).lateral_allowed(NS(vEgo=-5.,leftBlinker=False,rightBlinker=False)))

  def test_manual_range_and_bool_rejection(self):
    cp,store,backend,editor=self.make({'AdvancedLateralTune':'1'})
    for key,value in [('SteerFriction',.51),('SteerLatAccel',2.51),('SteerRatio',float('nan')),('SteerRatio',True)]:
      self.assertFalse(editor.write(key,value))
    self.assertEqual(backend.writes,[])

  def test_force_on_retains_saved_ratio_without_activation(self):
    cp,store,backend,_=self.make({'AdvancedLateralTune':'1','ForceAutoTune':'1','SteerRatio':'18'})
    self.assertEqual(SteeringTuning(cp,store).ratio(15.),15.)
    self.assertEqual(backend.data['SteerRatio'],'18')



  # ---- lane t994 steerTuning additions ----
  def ap1(self):
    from opendbc.car.tesla_ap1.values import CAR
    from opendbc.car.tesla_ap1.interface import CarInterface
    return CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS)

  def test_lagd_contract_matches_row_default(self):
    import ast
    from openpilot.selfdrive.controls.lib.phase3_steering_tuning import LAG_MIN, LAG_MAX, LAG_INITIAL_OFFSET
    source = Path(sys.modules[LatControlTorque.__module__].__file__).parents[2] / 'locationd/lagd.py'
    text = source.read_text()
    consts = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(text).body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ('MIN_LAG', 'MAX_LAG')}
    self.assertEqual((LAG_MIN, LAG_MAX), (consts['MIN_LAG'], consts['MAX_LAG']))
    self.assertIn(f'self.initial_lag = CP.steerActuatorDelay + {LAG_INITIAL_OFFSET}', text)
    cp = self.ap1()
    self.assertAlmostEqual(numeric_rows(cp)[0].default, cp.steerActuatorDelay + LAG_INITIAL_OFFSET)

  def test_real_ap1_rows_are_angle_consumers_only(self):
    cp = self.ap1()
    self.assertEqual(str(cp.steerControlType), 'angle')
    store = ParamStore(MemoryParams())
    editor = TuningEditor(cp, store, lambda: True)
    self.assertEqual(tuple(editor.rows), ('SteerDelay', 'SteerRatio'))
    for key in ('SteerFriction', 'SteerLatAccel', 'ForceAutoTune', 'ForceAutoTuneOff', *OMITTED):
      self.assertFalse(editor.visible(key), key)
    self.assertTrue(editor.write('AdvancedLateralTune', True))
    for key in ('SteerFriction', 'SteerLatAccel', 'ForceAutoTune', 'ForceAutoTuneOff', *OMITTED):
      self.assertFalse(editor.write(key, True if key.startswith(('Force', 'NNFF')) else .1), key)

  def test_ap1_defaults_stock_equivalent_no_writes(self):
    cp = self.ap1()
    backend = MemoryParams()
    t = SteeringTuning(cp, ParamStore(backend))
    self.assertEqual(t.values, {})
    self.assertIsNone(t.delay_override)
    self.assertEqual(t.ratio(15.), 15.)
    self.assertEqual(t.pause_speed, 0.)
    self.assertTrue(t.lateral_allowed(NS(vEgo=0., leftBlinker=True, rightBlinker=False)))
    self.assertEqual(backend.writes, [])

  def test_ap1_delay_ui_to_store_to_override_and_reset(self):
    cp = self.ap1()
    backend = MemoryParams()
    store = ParamStore(backend)
    editor = TuningEditor(cp, store, lambda: True)
    self.assertFalse(editor.write('SteerDelay', .3))  # parent off
    self.assertTrue(editor.write('AdvancedLateralTune', True))
    self.assertAlmostEqual(editor.value('SteerDelay'), .45)
    self.assertTrue(editor.step('SteerDelay', 1))
    self.assertAlmostEqual(SteeringTuning(cp, store).delay_override, .46)
    self.assertTrue(editor.write('SteerDelay', .45))  # shown default is only an initial guess; pinning it is real
    self.assertAlmostEqual(SteeringTuning(cp, store).delay_override, .45)
    for bad in (.14, .66, float('nan'), float('inf'), True, 0):
      self.assertFalse(editor.write('SteerDelay', bad), bad)
    self.assertTrue(editor.reset('SteerDelay'))
    self.assertIsNone(SteeringTuning(cp, store).delay_override)
    # parent off again: saved value retained but never activates
    self.assertTrue(editor.write('SteerDelay', .5))
    self.assertTrue(editor.write('AdvancedLateralTune', False))
    self.assertIsNone(SteeringTuning(cp, store).delay_override)
    self.assertEqual(backend.data['SteerDelay'], '0.5')
    # bad saved values are ignored, never rewritten
    for raw in ('.01', '9', 'x', 'nan'):
      b = MemoryParams({'AdvancedLateralTune': '1', 'SteerDelay': raw})
      self.assertIsNone(SteeringTuning(cp, ParamStore(b)).delay_override)
      self.assertEqual(b.writes, [])

  def test_ap1_steer_ratio_real_vehicle_model_and_angle_controller(self):
    from opendbc.car.vehicle_model import VehicleModel
    from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle
    cp = self.ap1()
    store = ParamStore(MemoryParams())
    editor = TuningEditor(cp, store, lambda: True)
    vm = VehicleModel(cp)
    lac = LatControlAngle(cp, None, .01)
    params = NS(angleOffsetDeg=0., roll=0.)
    cs = NS(vEgo=20., steeringAngleDeg=0., steeringPressed=False, standstill=False)

    def angle():
      t = SteeringTuning(cp, store)
      vm.update_params(1., max(t.ratio(15.), .1))
      return lac.update(True, cs, vm, params, False, .001, False, .3)[1]
    stock = angle()
    self.assertTrue(editor.write('AdvancedLateralTune', True))
    self.assertTrue(editor.write('SteerRatio', 18.))
    self.assertAlmostEqual(angle(), stock * 18. / 15., places=6)
    self.assertTrue(editor.reset('SteerRatio'))
    self.assertEqual(angle(), stock)
    self.assertFalse(editor.write('SteerRatio', 7.4))   # < 0.5x
    self.assertFalse(editor.write('SteerRatio', 22.6))  # > 1.5x

  def test_no_car_known_advanced_hidden_qol_works(self):
    backend = MemoryParams()
    store = ParamStore(backend)
    editor = TuningEditor(lambda: None, store, lambda: True)
    self.assertEqual(editor.rows, {})
    for key in ('AdvancedLateralTune', 'SteerDelay', 'SteerRatio', 'ForceAutoTune'):
      self.assertFalse(editor.visible(key))
      self.assertFalse(editor.write(key, True))
    self.assertEqual(backend.writes, [])
    self.assertTrue(editor.write('QOLLateral', True))
    self.assertTrue(editor.write('PauseLateralSpeed', 15))

  def test_legacy_inventory_dispositions_complete(self):
    import subprocess, re
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import ACTIVE_CONTROLS
    s = _legacy_lateral_settings()
    rows = re.findall(r'\{"([^"]+)"', s.split('lateralToggles {', 1)[1].split('\n  };', 1)[0])
    self.assertEqual(len(rows), 25)
    shipped = {'AdvancedLateralTune', 'SteerDelay', 'SteerFriction', 'SteerLatAccel', 'SteerRatio', 'ForceAutoTune', 'ForceAutoTuneOff',
               'QOLLateral', 'PauseLateralSpeed'}
    omitted = set(OMITTED)  # no 0.11.2 consumer
    other_lanes = {'AlwaysOnLateral', 'AlwaysOnLateralMain', 'AlwaysOnLateralLKAS', 'PauseAOLOnBrake', 'LaneChanges', 'NudgelessLaneChange',
                   'LaneChangeTime', 'MinimumLaneChangeSpeed', 'LaneDetectionWidth', 'OneLaneChange', 'LateralTune', 'TurnDesires'}
    self.assertEqual(set(rows), shipped | omitted | other_lanes)
    self.assertEqual(set(ACTIVE_CONTROLS), shipped | {'PauseLateralOnSignal'})
    self.assertFalse(set(ACTIVE_CONTROLS) & (omitted | other_lanes))

  def test_aol_not_referenced_by_steering_modules(self):
    for mod in ('selfdrive/controls/lib/phase3_steering_tuning.py', 'selfdrive/ui/bogpilot/phase3_steering_tuning.py'):
      text = (ROOT / mod).read_text()
      for needle in ('AlwaysOnLateral', 'aol_', 'PauseAOLOnBrake'):
        self.assertNotIn(needle, text, mod)

  def _stub_widgets(self):
    from types import ModuleType
    class Widget:
      def __init__(self): self._visible = True
      def show_event(self): pass
    widgets = ModuleType('openpilot.system.ui.widgets'); widgets.Widget = Widget
    factory = ModuleType('openpilot.system.ui.widgets.list_view')
    def item(kind):
      def make(*args, **kwargs):
        n = NS(kind=kind, args=args, visible=lambda: True, **kwargs)
        n.set_visible = lambda fn, n=n: setattr(n, 'visible', fn)
        return n
      return make
    for key in ('toggle_item', 'text_item', 'dual_button_item', 'button_item'):
      setattr(factory, key, item(key))
    scroll = ModuleType('openpilot.system.ui.widgets.scroller_tici')
    scroll.Scroller = lambda items, **kwargs: NS(items=items)
    return {'openpilot.system.ui.widgets': widgets, 'openpilot.system.ui.widgets.list_view': factory,
            'openpilot.system.ui.widgets.scroller_tici': scroll}

  def test_widget_callbacks_to_param_to_real_controller(self):
    from unittest.mock import patch
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import make_layout
    cp, store, _, _ = self.make()
    with patch.dict(sys.modules, self._stub_widgets()):
      layout = make_layout(cp, store, lambda: True)
      rows = layout.scroller.items
      next(x for x in rows if x.kind == 'toggle_item' and x.args[0] == 'Advanced Lateral Tuning').callback(True)
      idx = next(i for i, x in enumerate(rows) if x.kind == 'text_item' and x.args[0] == 'Friction')
      rows[idx + 1].right_callback()
      self.assertAlmostEqual(store.get_float('SteerFriction'), .11)
      _, lac = replay(SteeringTuning(cp, store))
      self.assertAlmostEqual(lac.torque_params.friction, .11)
      next(x for x in rows if x.kind == 'toggle_item' and x.args[0] == 'Quality of Life').callback(True)
      idx = next(i for i, x in enumerate(rows) if x.kind == 'text_item' and x.args[0] == 'Pause Steering Below')
      for _ in range(20):
        rows[idx + 1].right_callback()
      self.assertEqual(store.get_int('PauseLateralSpeed'), 20)
      self.assertAlmostEqual(SteeringTuning(cp, store).pause_speed, 20 * .44704)

  def test_text_callables_never_raise_without_car(self):
    cp, store, _, editor = self.make()
    nocar = TuningEditor(lambda: None, store, lambda: True)
    for key in ('SteerDelay', 'SteerRatio', 'SteerFriction', 'SteerLatAccel'):
      self.assertEqual(nocar.shown(key), '')
      self.assertTrue(nocar.hint(key))
      self.assertRegex(editor.shown(key), r'^\d+\.\d\d$')
      self.assertIn('Range', editor.hint(key))

  def test_widget_visibility_follows_vehicle(self):
    from unittest.mock import patch
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import make_layout
    box = {'cp': None}
    store = ParamStore(MemoryParams())
    with patch.dict(sys.modules, self._stub_widgets()):
      rows = make_layout(lambda: box['cp'], store, lambda: True).scroller.items
      def shown():
        return {x.args[0] for x in rows if x.kind in ('toggle_item', 'text_item') and x.visible()}
      self.assertEqual(shown(), {'Quality of Life', 'Pause Steering Below', 'Turn Signal Only'})
      box['cp'] = self.ap1()
      self.assertEqual(shown(), {'Advanced Lateral Tuning', 'Actuator Delay', 'Steer Ratio', 'Quality of Life', 'Pause Steering Below', 'Turn Signal Only'})
      box['cp'] = cp_for('torque', 'ford')
      self.assertEqual(shown(), {'Advanced Lateral Tuning', 'Actuator Delay', 'Steer Ratio', 'Friction', 'Lateral Acceleration',
                                 'Force Auto-Tune On', 'Quality of Life', 'Pause Steering Below', 'Turn Signal Only'})
      box['cp'] = cp_for('torque', 'toyota')
      self.assertIn('Force Auto-Tune Off', shown())
      self.assertNotIn('Force Auto-Tune On', shown())
      offroad = {'v': False}
      editor = make_layout(lambda: box['cp'], store, lambda: offroad['v']).editor
      self.assertFalse(editor.can_edit('AdvancedLateralTune'))

  def test_loader_never_raises_and_falls_back_to_stock(self):
    from unittest.mock import patch
    import types
    from openpilot.selfdrive.controls.lib.phase3_steering_tuning import load_steering_tuning
    cp = cp_for()
    class Boom:
      def honoured(self, key): raise OSError('disk')
      def toggle_bool(self, key): raise OSError('disk')
    log = types.ModuleType('openpilot.common.swaglog')
    log.cloudlog = NS(exception=lambda *a, **k: None)
    with patch.dict(sys.modules, {'openpilot.common.swaglog': log}):
      t = load_steering_tuning(cp, Boom())
    self.assertEqual(t.values, {})
    self.assertIsNone(t.delay_override)
    self.assertEqual(t.ratio(15.), 15.)
    self.assertTrue(t.lateral_allowed(NS(vEgo=0., leftBlinker=True, rightBlinker=True)))
    self.assertFalse(t.force_on or t.force_off)


if __name__ == '__main__':
  unittest.main(verbosity=2)
