"""Focused native gesture/CAN tests. No live car, sockets or real parameters."""
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import patch
import math
import pytest

from opendbc.car.tesla_ap1.phase3_stalk_controls import (
  AP1, Settings, Store, ExperimentalHold, StalkControls, hold_seconds, apply_experimental_toggle,
)
from openpilot.selfdrive.ui.bogpilot.phase3_stalk_controls import StalkMenu


def cp():
  return NS(carFingerprint=AP1, dashcamOnly=False, passive=False, openpilotLongitudinalControl=True)


def neutral(h, start=1., engaged=True, **overrides):
  for i in range(12):
    now = start + i*.01
    h.update(0, engaged, now, int(now*1e9), True, True, True, 1.23)
  return start + .12


@pytest.mark.parametrize('value', [1.10, 1.23, 5.00, '1.23'])
def test_valid_precise_bounds(value):
  assert hold_seconds(value) == float(value)


@pytest.mark.parametrize('value', [1.09, 5.01, -1, 0, float('nan'), float('inf'), '-inf', 'bad', None, True, 1.234])
def test_reject_bad_bounds(value):
  with pytest.raises(ValueError):
    hold_seconds(value)


@pytest.mark.parametrize('delay', [1.10, 1.23, 5.00])
@pytest.mark.parametrize('direction,engaged', [(2, True), (1, False)])
def test_exact_threshold_one_pulse(delay, direction, engaged):
  h = ExperimentalHold(direction)
  start = neutral(h, engaged=engaged)
  # First signature change aborts deliberately; neutral arms with chosen value.
  for i in range(13):
    now = start + i*.01
    h.update(0, engaged, now, int(now*1e9), True, True, True, delay)
  start += .13
  assert not h.update(direction, engaged, start, int(start*1e9), True, True, True, delay)
  for i in range(1, round(delay*100)):
    now = start + i*.01
    assert not h.update(direction, engaged, now, int(now*1e9), True, True, True, delay)
  now = start + delay
  assert h.update(direction, engaged, now, int(now*1e9), True, True, True, delay)
  for i in range(1, 501):
    now += .01
    assert not h.update(direction, engaged, now, int(now*1e9), True, True, True, delay)


@pytest.mark.parametrize('failure', ['stale', 'invalid', 'offroad', 'disabled', 'nan', 'backward', 'state'])
def test_midhold_abort_requires_neutral(failure):
  h = ExperimentalHold(2)
  start = neutral(h)
  for i in range(80):
    now = start + i*.01
    h.update(2, True, now, int(now*1e9), True, True, True, 1.23)
  frozen = int(now*1e9)
  for i in range(1, 160):
    now += .01
    t, sample, valid, allowed, enabled, engaged = now, int(now*1e9), True, True, True, True
    if failure == 'stale': sample = frozen
    if i == 1:
      if failure == 'invalid': valid = False
      if failure == 'offroad': allowed = False
      if failure == 'disabled': enabled = False
      if failure == 'nan': t = math.nan
      if failure == 'backward': sample = frozen-1
      if failure == 'state': engaged = False
    assert not h.update(2, engaged, t, sample, valid, allowed, enabled, 1.23)
  # A brief bounce shorter than one 10-Hz neutral period must not rearm.
  now += .01; h.update(0, True, now, int(now*1e9), True, True, True, 1.23)
  for i in range(150):
    now += .01
    assert not h.update(2, True, now, int(now*1e9), True, True, True, 1.23)


@pytest.mark.parametrize('direction,initial', [(2, False), (1, True)])
def test_engage_pull_and_cancel_push_never_become_experimental(direction, initial):
  h = ExperimentalHold(direction)
  start = neutral(h, engaged=initial)
  for i in range(400):
    now = start + i*.01
    assert not h.update(direction, initial if i < 20 else not initial, now, int(now*1e9), True, True, True, 1.23)


def test_fresh_release_rearms():
  h = ExperimentalHold(2)
  start = neutral(h)
  for gesture in range(2):
    pulses = 0
    for i in range(200):
      now = start + i*.01
      pulses += h.update(2, True, now, int(now*1e9), True, True, True, 1.23)
    assert pulses == 1
    start = neutral(h, start=now+.01)


def test_store_roundtrip_and_invalid_data(tmp_path):
  store = Store(tmp_path/'StalkControls.json')
  assert store.read() == Settings()
  store.write('pull_hold_s', 1.10)
  store.write('push_hold_s', 5.00)
  store.write('experimental_push', False)
  assert store.read() == replace(Settings(), pull_hold_s=1.10, push_hold_s=5., experimental_push=False)
  original = store.path.read_text()
  for bad in [1.09, 5.01, math.nan, math.inf, -1]:
    with pytest.raises(ValueError): store.write('pull_hold_s', bad)
    assert store.path.read_text() == original
  store.path.write_text('{"pull_hold_s": NaN}')
  assert not store.read().experimental_pull
  store.path.write_text('{broken')
  assert not store.read().experimental_pull and not store.read().experimental_push


def test_menu_capabilities_offroad_and_precision(tmp_path):
  car, offroad = cp(), True
  menu = StalkMenu(lambda: car, lambda: offroad, Store(tmp_path/'settings'))
  assert menu.write('pull_hold_s', 1.23)
  assert menu.step('pull_hold_s', 1)
  assert menu.store.read().pull_hold_s == 1.24
  offroad = False
  assert not menu.write('experimental_pull', False)
  offroad = True
  car.openpilotLongitudinalControl = False
  assert not menu.visible('experimental_pull')
  assert menu.visible('twist_follow')
  car.carFingerprint = 'PREAP'
  assert not menu.visible('twist_follow')
  assert not menu.write('twist_follow', False)


def test_actual_card_persistence_and_eligibility():
  data = {'ExperimentalMode': False, 'ExperimentalModeConfirmed': True}
  writes = []
  params = NS(get_bool=lambda k: data[k], put_bool=lambda k,v,block=False: (data.update({k:v}), writes.append((k,v,block))))
  car = cp()
  cs = NS(canValid=True, bogpilot=NS(ap1StalkPullToggle=True, ap1StalkFwdToggle=False))
  assert apply_experimental_toggle(params, car, cs, True) is True
  assert writes == [('ExperimentalMode', True, True)]
  for blocked in ['offroad','unconfirmed','invalid','unsupported']:
    data['ExperimentalModeConfirmed'] = blocked != 'unconfirmed'
    cs.canValid = blocked != 'invalid'
    car.openpilotLongitudinalControl = blocked != 'unsupported'
    assert apply_experimental_toggle(params, car, cs, blocked != 'offroad') is None
  assert len(writes) == 1


def test_native_can_parser_and_actual_carstate_consumer(tmp_path):
  from collections import defaultdict
  from opendbc.can import CANParser, CANPacker
  from opendbc.car import Bus
  from opendbc.car.tesla_ap1.carstate import CarState
  from opendbc.car.tesla_ap1.interface import CarInterface
  from opendbc.car import gen_empty_fingerprint
  from opendbc.car.tesla_ap1.values import CAR, AP1_CHASSIS_SIGNATURE
  from opendbc.car.tesla_ap1.values import DBC
  fingerprint = gen_empty_fingerprint()
  fingerprint[0] = dict(AP1_CHASSIS_SIGNATURE)
  fingerprint[2] = {0x399: 8, 0x2B9: 8, 0x488: 4}
  car = CarInterface.get_params(CAR.TESLA_AP1_MODELS, fingerprint, [], False, False, False)
  parser = CANParser(DBC[car.carFingerprint][Bus.chassis], [('STW_ACTN_RQ', 10)], 0)
  packer = CANPacker(DBC[car.carFingerprint][Bus.chassis])
  # Other signals are inert defaults; STW is encoded/decoded by native packer/parser.
  vl = defaultdict(lambda: defaultdict(float))
  vl_all = defaultdict(lambda: defaultdict(list))
  chassis = NS(vl=vl, vl_all=vl_all, ts_nanos={}, can_valid=True)
  cam = NS(vl=defaultdict(lambda: defaultdict(float)), vl_all=vl_all, can_valid=True)
  cs = CarState(car)
  now = 10.
  cs.stalk_controls = StalkControls(Store(tmp_path/'stalk.json'), clock=lambda: now)
  cs.stalk_controls_allowed = True
  cs.out.cruiseState.enabled = True
  pulses = []
  for i in range(240):
    now = 10 + i*.01
    value = 0 if i < 20 else 2
    packet = packer.make_can_msg('STW_ACTN_RQ', 0, {'SpdCtrlLvr_Stat': value, 'DTR_Dist_Rq': 133})
    if i % 10 == 0:  # real STW cadence: 10 Hz inside a 100-Hz car loop
      parser.update([(int(now*1e9), [packet])])
    vl['STW_ACTN_RQ'] = dict(parser.vl['STW_ACTN_RQ'])
    chassis.ts_nanos = parser.ts_nanos
    ret = cs.update({Bus.chassis: chassis, Bus.cam: cam})
    pulses.append(ret.bogpilot.ap1StalkPullToggle)
    assert ret.bogpilot.ap1StalkFollowS > 0
  assert sum(pulses) == 1
  assert pulses[20+123]
  # Twist toggle reaches the real published planner input, without changing buttons.
  cs.stalk_controls.store.write('twist_follow', False)
  now += .2
  ret = cs.update({Bus.chassis: chassis, Bus.cam: cam})
  assert ret.bogpilot.ap1StalkFollowS == 0
  # Physical cancel is still generated on the first FWD edge, independently of holds.
  vl['STW_ACTN_RQ']['SpdCtrlLvr_Stat'] = 1
  now += .01
  ret = cs.update({Bus.chassis: chassis, Bus.cam: cam})
  assert any(str(e.type) == 'cancel' and e.pressed for e in ret.buttonEvents)
  assert not ret.bogpilot.ap1StalkFwdToggle


@pytest.mark.parametrize('direction,engaged', [(2, True), (1, False)])
def test_default_normal_gesture_parity_with_existing_helpers(direction, engaged):
  from opendbc.car.tesla_ap1.stalk_pull_hold import StalkPullHold
  from opendbc.car.tesla_ap1.stalk_fwd_hold import StalkFwdHold
  old = StalkPullHold() if direction == 2 else StalkFwdHold()
  new = ExperimentalHold(direction)
  start = neutral(new, engaged=engaged)
  for i in range(400):
    now = start+i*.01
    value = direction if i < 300 else 0
    assert new.update(value, engaged, now, int(now*1e9), True, True, True, 1.23) == old.update(value, engaged, .01)


def test_store_disabled_midhold_cannot_fire_after_reenable(tmp_path):
  store = Store(tmp_path/'settings')
  model = StalkControls(store)
  car = cp()
  pulses = []
  for i in range(400):
    now = 1 + i*.01
    if i == 90: store.write('experimental_pull', False)
    if i == 110: store.write('experimental_pull', True)
    pulses.append(model.update(0 if i < 20 else 2, True, int(now*1e9), True, True, car, now)[0])
  assert not any(pulses)


def test_control_loop_gap_and_repeated_monotonic_time_abort():
  for jump in (.5, 0.0, -.01):
    h = ExperimentalHold(2)
    now = neutral(h)
    for i in range(50):
      t = now+i*.01
      h.update(2, True, t, int(t*1e9), True, True, True, 1.23)
    t += jump
    assert not h.update(2, True, t, int(max(1,t)*1e9), True, True, True, 1.23)
    for i in range(200):
      t += .01
      assert not h.update(2, True, t, int(t*1e9), True, True, True, 1.23)


def test_actual_card_state_update_uses_live_eligibility():
  # Execute the real target method, not a parallel implementation. Dependencies
  # are inert fakes; no sockets, processes, Params or vehicle are constructed.
  import ast
  from pathlib import Path
  source = (Path(__file__).resolve().parents[2]/'car'/'card.py').read_text()
  tree = ast.parse(source)
  car_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Car')
  submaster = next(n for n in ast.walk(car_class) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == 'SubMaster')
  assert 'deviceState' in ast.literal_eval(submaster.args[0])
  method = next(n for n in car_class.body if isinstance(n, ast.FunctionDef) and n.name == 'state_update')
  method.returns = None
  cs = NS(canValid=True, bogpilot=NS(ap1StalkPullToggle=True, ap1StalkFwdToggle=False))
  device = NS(started=True)

  class SM:
    valid = {'deviceState': True}
    alive = {'deviceState': True}
    def __init__(self): self.updates = 0
    def update(self, wait): self.updates += 1
    def __getitem__(self, key): return device if key == 'deviceState' else NS(enabled=False)

  data = {'ExperimentalMode': False, 'ExperimentalModeConfirmed': True}
  writes = []
  store = NS(get_bool=lambda key: data[key], put_bool=lambda key,value,block=False: (data.update({key:value}), writes.append(value)))
  parser = NS(stalk_controls_allowed=False)
  car = NS(CP=cp(), CI=NS(CS=parser, update=lambda frames: cs), RI=NS(update=lambda frames: None),
           sm=SM(), params=store, can_sock=None, ap1_model=None, experimental_mode=False,
           can_rcv_cum_timeout_counter=0, v_cruise_helper=NS(update_v_cruise=lambda *args: None,
             v_cruise_kph=50, v_cruise_cluster_kph=50), is_metric=True)
  scope = {'messaging':NS(drain_sock_raw=lambda *args,**kw:[b'fake']), 'can_capnp_to_list':lambda frames:[],
           'experimental_supported':__import__('opendbc.car.tesla_ap1.phase3_stalk_controls',fromlist=['experimental_supported']).experimental_supported,
           'apply_experimental_toggle':apply_experimental_toggle, 'REPLAY':False}
  exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])), '<actual-card-state-update>', 'exec'),scope)
  scope['state_update'](car)
  assert parser.stalk_controls_allowed and writes == [True]
  device.started = False
  scope['state_update'](car)
  assert not parser.stalk_controls_allowed and writes == [True]
  assert car.sm.updates == 2  # exactly one fresh subscription update per cycle
