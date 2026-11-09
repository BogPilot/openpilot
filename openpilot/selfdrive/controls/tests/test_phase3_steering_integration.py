"""Steering Tuning shared-file integration: UI -> ParamStore -> real lagd / real controlsd.

Needs PROPOSED_shared.patch (controlsd.py, lagd.py, layouts/settings/bogpilot.py) applied; skipped when it is
not, unless BOGPILOT_REQUIRE_STEER_PATCH=1 (INT sets this after applying). Native tests also need the aarch64/Linux
msgq build (AGNOS VM); BOGPILOT_REQUIRE_STEER_NATIVE=1 turns a missing native stack into a failure, not a skip.
"""
import os
import time
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[3]
CONTROLSD = (ROOT / 'selfdrive/controls/controlsd.py').read_text()
LAGD = (ROOT / 'selfdrive/locationd/lagd.py').read_text()
NAV = (ROOT / 'selfdrive/ui/layouts/settings/bogpilot.py').read_text()
PATCHED = 'load_steering_tuning' in CONTROLSD and 'delay_override' in LAGD and 'phase3_steering_tuning' in NAV
REQUIRE_PATCH = os.getenv('BOGPILOT_REQUIRE_STEER_PATCH') == '1'
REQUIRE_NATIVE = os.getenv('BOGPILOT_REQUIRE_STEER_NATIVE') == '1'


def need_patch(test):
  return unittest.skipUnless(PATCHED or REQUIRE_PATCH, 'PROPOSED_shared.patch not applied')(test)


class MemoryParams:
  def __init__(self, values=None):
    self.data = dict(values or {})
  def all_keys(self):
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    return list(BOGPILOT_PARAMS) + ['IsMetric']
  def get(self, key):
    return self.data.get(key)
  def put(self, key, value):
    self.data[key] = str(value)
  def put_bool(self, key, value):
    self.put(key, '1' if value else '0')
  def remove(self, key):
    self.data.pop(key, None)


def ap1_cp():
  from opendbc.car.tesla_ap1.values import CAR
  from opendbc.car.tesla_ap1.interface import CarInterface
  return CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS)


def sync_store():
  """Real compiled Params, but blocking writes: Params.put defaults to block=False (async), which a test cannot race."""
  from openpilot.common.bogpilot_store import ParamStore
  from openpilot.common.params import Params

  class SyncParams(Params):
    def put(self, key, dat, block=True):
      super().put(key, dat, block=True)
    def put_bool(self, key, val, block=True):
      super().put_bool(key, val, block=True)
  return ParamStore(SyncParams())


def must_write(case, editor, key, value):
  ok = editor.write(key, value)
  store = editor.store
  case.assertTrue(ok, f"write({key}, {value}) refused: offroad={editor.offroad()} honoured={store.honoured(key)} visible={editor.visible(key)} "
                      f"can_edit={editor.can_edit(key)} adv={store.toggle_bool('AdvancedLateralTune')} adv_raw={store.raw('AdvancedLateralTune')!r} "
                      f"level={store.tuning_level()} rows={list(editor.rows)}")


class TestSharedPatchStatic(unittest.TestCase):
  @need_patch
  def test_hooks_present_once_and_stock_lines_retained(self):
    self.assertEqual(CONTROLSD.count('load_steering_tuning(self.CP)'), 1)
    self.assertIn('self.steering_tuning.ratio(lp.steerRatio)', CONTROLSD)
    self.assertIn('self.steering_tuning.update_torque(self.LaC, torque_params', CONTROLSD)
    self.assertIn('CC.latActive and self.steering_tuning.lateral_allowed(CS)', CONTROLSD)
    self.assertEqual(LAGD.count('delay_override'), 5)
    self.assertIn('self.initial_lag = CP.steerActuatorDelay + 0.2', LAGD)

  @need_patch
  def test_no_aol_in_runtime_hooks(self):
    for text in (CONTROLSD, LAGD):
      self.assertNotIn('AlwaysOnLateral', text)
      self.assertNotIn('aol_', text)

  @need_patch
  def test_navigation_registers_one_driving_page_with_consumer_backed_controls(self):
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location('phase2_navigation_contract', ROOT / 'selfdrive/ui/layouts/settings/phase2_navigation.py')
    nav = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = nav
    spec.loader.exec_module(nav)
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import ACTIVE_CONTROLS, PAGE_KEY, PAGE_TITLE
    groups = nav.active_groups({'driving': [nav.Page(PAGE_KEY, PAGE_TITLE, lambda: None, ACTIVE_CONTROLS)]})
    self.assertEqual([(g[0], g[1], [p.key for p in g[2]]) for g in groups], [('driving', 'Driving Controls', ['steering_tuning'])])
    for omitted in ('SteerKP', 'ForceTorqueController', 'NNFF', 'NNFFLite', 'TurnDesires', 'AlwaysOnLateral'):
      self.assertNotIn(omitted, ACTIVE_CONTROLS)
    # INT t994: one combined "driving" tuple (steering page registered via aliased names)
    self.assertIn('"driving": (', NAV)
    self.assertIn('Page(STEER_KEY, STEER_TITLE, create_steering_tuning_layout, STEER_CONTROLS)', NAV)
    self.assertEqual(NAV.count('"driving":'), 1)  # one combined tuple


def native_ready():
  try:
    import openpilot.cereal.messaging  # noqa: F401
    import openpilot.selfdrive.locationd.lagd  # noqa: F401
    import openpilot.selfdrive.controls.controlsd  # noqa: F401
    return True
  except Exception:
    return False


NATIVE = native_ready()


@unittest.skipUnless(NATIVE or REQUIRE_NATIVE, 'native msgq stack unavailable (run in AGNOS VM)')
class TestSharedPatchNative(unittest.TestCase):
  def editor(self, store, offroad=True):
    from openpilot.selfdrive.ui.bogpilot.phase3_steering_tuning import TuningEditor
    return TuningEditor(ap1_cp(), store, lambda: offroad)

  @need_patch
  def test_lagd_publishes_ui_delay_and_leaves_estimates_alone(self):
    from openpilot.common.bogpilot_store import ParamStore
    from openpilot.selfdrive.controls.lib.phase3_steering_tuning import load_steering_tuning
    from openpilot.selfdrive.locationd.lagd import LateralLagEstimator, MAX_LAG, MIN_LAG
    cp = ap1_cp()
    store = ParamStore(MemoryParams())
    editor = self.editor(store)

    def publish():
      est = LateralLagEstimator(cp, .05)
      est.delay_override = load_steering_tuning(cp, store).delay_override
      return est.get_msg(True).lateralDelay
    stock = publish()
    self.assertAlmostEqual(stock.lateralDelay, cp.steerActuatorDelay + .2)
    self.assertEqual((MIN_LAG, MAX_LAG), (.15, .65))
    must_write(self, editor, 'AdvancedLateralTune', True)
    must_write(self, editor, 'SteerDelay', .55)
    tuned = publish()
    self.assertAlmostEqual(tuned.lateralDelay, .55, places=6)
    self.assertEqual(tuned.lateralDelayEstimate, stock.lateralDelayEstimate)
    self.assertEqual(tuned.status, stock.status)
    est = LateralLagEstimator(cp, .05)
    est.delay_override = 9.
    self.assertAlmostEqual(est.get_msg(True).lateralDelay.lateralDelay, MAX_LAG, places=6)  # capnp float32
    est.delay_override = .01
    self.assertAlmostEqual(est.get_msg(True).lateralDelay.lateralDelay, MIN_LAG, places=6)
    self.assertTrue(editor.reset('SteerDelay'))
    self.assertAlmostEqual(publish().lateralDelay, stock.lateralDelay)

  @need_patch
  def test_controlsd_real_init_ui_to_ratio_and_pause(self):
    import tempfile
    os.environ['BOGPILOT_PARAMS_DIR'] = tempfile.mkdtemp(prefix='steer-bogpilot-')
    os.environ.setdefault('PARAMS_ROOT', tempfile.mkdtemp(prefix='steer-params-'))
    from openpilot.common.params import Params
    from openpilot.common.bogpilot_store import ParamStore
    import openpilot.cereal.messaging as messaging
    from openpilot.selfdrive.controls.controlsd import Controls
    cp = ap1_cp()
    Params().put('CarParams', cp.as_builder().to_bytes() if hasattr(cp, 'as_builder') else cp.to_bytes())
    from opendbc.car.structs import car

    def run(speed, left_blinker=False):
      c = Controls()
      cs = car.CarState.new_message()
      cs.vEgo, cs.steeringAngleDeg, cs.leftBlinker = speed, 0., left_blinker
      cs.vCruise = 100.
      model = messaging.new_message('modelV2').modelV2
      model.action.desiredCurvature = .002
      sm = {'carState': cs.as_reader(), 'vehicleParameters': NS(stiffnessFactor=1., steerRatio=15., angleOffsetDeg=0., roll=0.),
            'lateralTorqueParameters': None, 'longitudinalPlan': NS(aTarget=0., shouldStop=False, hasLead=False),
            'modelV2': model.as_reader(), 'selfdriveState': NS(active=True, enabled=True), 'onroadEvents': [],
            'lateralDelay': NS(lateralDelay=.3)}
      class SM(dict):
        valid = {'lateralManeuverPlan': False}
        def all_checks(self, *a, **k):
          return True
      c.sm = SM(sm)
      CC, _ = c.state_control()
      return c, CC

    # Defaults: stock-equivalent, tuning object inert.
    c, CC = run(20.)
    stock_angle = CC.actuators.steeringAngleDeg
    self.assertEqual(c.steering_tuning.values, {})
    self.assertTrue(CC.latActive)
    self.assertNotEqual(stock_angle, 0.)

    store = sync_store()
    editor = self.editor(store)
    must_write(self, editor, 'AdvancedLateralTune', True)
    must_write(self, editor, 'SteerRatio', 18.)
    _, CC = run(20.)
    self.assertAlmostEqual(CC.actuators.steeringAngleDeg, stock_angle * 18. / 15., places=4)
    self.assertTrue(editor.reset('SteerRatio'))
    must_write(self, editor, 'AdvancedLateralTune', False)

    must_write(self, editor, 'QOLLateral', True)
    must_write(self, editor, 'PauseLateralSpeed', 20)  # mph: 8.94 m/s
    _, below = run(5.)
    _, above = run(12.)
    self.assertFalse(below.latActive)
    self.assertTrue(above.latActive)
    must_write(self, editor, 'PauseLateralOnSignal', True)
    self.assertTrue(run(5., False)[1].latActive)       # no signal: keeps steering
    self.assertFalse(run(5., True)[1].latActive)       # signal below pause speed: paused
    self.assertTrue(run(12., True)[1].latActive)       # above pause speed: never paused
    must_write(self, editor, 'PauseLateralSpeed', 0)
    self.assertTrue(run(5., True)[1].latActive)        # 0 = off


if __name__ == '__main__':
  unittest.main(verbosity=2)
