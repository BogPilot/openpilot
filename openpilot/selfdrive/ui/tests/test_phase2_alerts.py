"""Deterministic producer/replay tests, with real current schema and source alerts.

The final test executes current Alert/AlertManager source classes with actual
capnp enums, isolated from unavailable Mac msgq binaries. No mock alert classes.
This is not a process/socket/audio-device or raylib-render test.
"""
import ast
from collections import defaultdict
from dataclasses import dataclass, replace
from enum import IntEnum
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

MODULE_PATH = Path(__file__).parents[1] / "bogpilot" / "phase2_alerts.py"
spec = importlib.util.spec_from_file_location("phase2_alerts", MODULE_PATH)
m = importlib.util.module_from_spec(spec)
# dataclasses needs an actual named module in sys.modules.
import sys
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def sample(t=0., **kw):
  base = m.AlertInput(t, True, "drive", 0., (0., 20.), (0., 0.), (0., 10.), False, 0., 0., 0.)
  return replace(base, **kw)


class FakeStore:
  def __init__(self, values=None):
    self.values = values or {}
  def get_bool(self, key, default=False):
    return self.values.get(key, default)


class TestPhase2Alerts(unittest.TestCase):
  def arm_green(self, p, t=0.):
    for i in range(30):
      self.assertEqual(p.update(sample(t + i * .05)), ())
    return t + 1.5

  def release(self, p, t):
    out = ()
    for i in range(3):
      out = p.update(sample(t+i*.05, model_x=(0., 100.), model_v=(5., 5.)))
    return out

  def arm_lead(self, p):
    for i in range(30):
      p.update(sample(i * .05, standstill=False, v_ego=5., model_x=(0., 100.),
                      lead_status=True, d_rel=10., v_rel=0., v_lead=0., lead_id=3))
    p.update(sample(1.5, lead_status=True, d_rel=10., lead_id=3))

  def test_green_transition_and_no_repeat(self):
    p = m.Phase2Alerts()
    t = self.arm_green(p)
    self.assertEqual(self.release(p, t), ("GreenLightAlert",))
    for i in range(3, 40):
      self.assertEqual(p.update(sample(t + i * .05, model_x=(0., 100.), model_v=(5., 5.))), ())

  def test_green_requires_stop_evidence(self):
    p = m.Phase2Alerts()
    for i in range(50):
      self.assertEqual(p.update(sample(i*.05, model_x=(0., 100.), model_v=(5., 5.))), ())

  def test_short_stop_hint_cannot_arm(self):
    p = m.Phase2Alerts()
    p.update(sample())
    self.assertEqual(p.update(sample(.05, model_x=(0., 100.), model_v=(5., 5.))), ())

  def test_green_once_despite_jitter(self):
    p = m.Phase2Alerts()
    t = self.arm_green(p)
    self.release(p, t)
    t = self.arm_green(p, t+.15)
    self.assertEqual(p.update(sample(t, model_x=(0., 100.), model_v=(5., 5.))), ())

  def test_single_release_frame_is_not_green(self):
    p = m.Phase2Alerts()
    t = self.arm_green(p)
    self.assertEqual(p.update(sample(t, model_x=(0., 100.), model_v=(5., 5.))), ())
    self.assertEqual(p.update(sample(t+.05)), ())

  def test_green_rearms_after_motion(self):
    p = m.Phase2Alerts()
    t = self.arm_green(p)
    self.release(p, t)
    p.update(sample(t+.15, standstill=False, v_ego=2.))
    t = self.arm_green(p, t+.2)
    self.assertEqual(self.release(p, t), ("GreenLightAlert",))

  def test_lead_thresholds_and_once(self):
    p = m.Phase2Alerts()
    self.arm_lead(p)
    self.assertEqual(p.update(sample(1.55, lead_status=True, d_rel=11., v_lead=2., lead_id=3)), ())
    self.assertEqual(p.update(sample(1.6, lead_status=True, d_rel=11.1, v_lead=1., lead_id=3)), ())
    self.assertEqual(p.update(sample(1.65, lead_status=True, d_rel=11.2, v_lead=1.1, lead_id=3)), ("LeadDepartingAlert",))
    self.assertEqual(p.update(sample(1.7, lead_status=True, d_rel=11.3, v_lead=2., lead_id=3)), ())

  def test_lead_needs_tracking_before_stop(self):
    p = m.Phase2Alerts()
    for i in range(50):
      self.assertEqual(p.update(sample(i*.05, lead_status=True, d_rel=10+i*.1, v_lead=2.)), ())

  def test_lost_lead_and_identity_jump_not_departure(self):
    for changed in (dict(lead_status=False), dict(lead_id=4, d_rel=30.), dict(d_rel=30.)):
      p = m.Phase2Alerts()
      self.arm_lead(p)
      s = sample(1.55, lead_status=True, d_rel=10., v_lead=2., lead_id=3)
      self.assertEqual(p.update(replace(s, **changed)), ())

  def test_explicit_off(self):
    p = m.Phase2Alerts()
    t = self.arm_green(p)
    self.assertEqual(p.update(sample(t, model_x=(0., 100.), model_v=(5., 5.)), green=False), ())
    p = m.Phase2Alerts()
    self.arm_lead(p)
    self.assertEqual(p.update(sample(1.55, lead_status=True, d_rel=10.8, v_lead=2., lead_id=3), lead=False), ())
    self.assertEqual(p.update(sample(1.6, lead_status=True, d_rel=11.2, v_lead=2., lead_id=3), lead=False), ())

  def test_fresh_defaults_and_saved_off(self):
    for key in m.ACTIVE_ALERT_KEYS:
      self.assertTrue(m.read_enabled(FakeStore(), key))
      self.assertFalse(m.read_enabled(FakeStore({key: False}), key))
    self.assertEqual(set(m.ACTIVE_ALERT_KEYS), {"GreenLightAlert", "LeadDepartingAlert"})

  def test_real_store_fresh_and_explicit_off(self):
    from openpilot.common.bogpilot_store import ParamStore
    class NativeParams:
      def __init__(self):
        self.data = {}
      def all_keys(self):
        return m.ACTIVE_ALERT_KEYS
      def get(self, key):
        return self.data.get(key)
      def put_bool(self, key, value):
        self.data[key] = value
    params = NativeParams()
    store = ParamStore(params=params)
    for key in m.ACTIVE_ALERT_KEYS:
      self.assertTrue(m.read_enabled(store, key))
      store.put_bool(key, False)
      self.assertFalse(m.read_enabled(store, key))
      self.assertFalse(m.read_enabled(ParamStore(params=params), key))

  def test_invalid_stale_reverse_nan_traffic_clears_evidence(self):
    for changed in (dict(valid=False), dict(model_age=.3), dict(radar_age=.3), dict(gear="reverse"),
                    dict(model_x=()), dict(model_v=(0., float("nan"))), dict(traffic_valid=False),
                    dict(model_t=(10., 0.))):
      p = m.Phase2Alerts()
      t = self.arm_green(p)
      self.assertEqual(p.update(replace(sample(t), **changed)), ())
      self.assertEqual(p.update(sample(t+.05, model_x=(0., 100.), model_v=(5., 5.))), ())
    p = m.Phase2Alerts()
    for i in range(40):
      self.assertEqual(p.update(sample(i*.05, traffic_mode=True)), ())
    self.assertEqual(p.update(sample(2., model_x=(0., 100.), model_v=(5., 5.))), ())

  def test_clock_gap_or_rewind_resets(self):
    for t in (4., 1.):
      p = m.Phase2Alerts()
      self.arm_green(p)
      self.assertEqual(p.update(sample(t, model_x=(0., 100.), model_v=(5., 5.))), ())

  def test_lead_blocks_green(self):
    p = m.Phase2Alerts()
    self.arm_green(p)
    self.assertEqual(p.update(sample(1.5, lead_status=True, d_rel=10., model_x=(0., 100.), model_v=(5., 5.))), ())

  def test_current_schema_runtime_adapter(self):
    from openpilot.cereal import log
    from opendbc.car.structs import car
    model = log.ModelDataV2.new_message()
    model.position.x = [0., 20.]
    model.velocity.x = [0., 0.]
    model.velocity.t = [0., 10.]
    radar = log.RadarState.new_message()
    radar.leadOne.present = False
    cs = car.CarState.new_message(standstill=True, gearShifter="drive", canValid=True)
    class SM(dict):
      def all_checks(self, services):
        return self.valid
    sm = SM(modelV2=model, radarState=radar)
    sm.valid = True
    sm.updated = {"modelV2": True}
    r = m.Phase2AlertRuntime(FakeStore())
    for i in range(30):
      sm.recv_time = {"modelV2": i*.05, "radarState": i*.05}
      self.assertEqual(r.update(cs, sm, i*.05), ())
    model.position.x = [0., 100.]
    model.velocity.x = [5., 5.]
    sm.recv_time = {"modelV2": 1.5, "radarState": 1.5}
    for t in (1.5, 1.55):
      sm.recv_time = {"modelV2": t, "radarState": t}
      self.assertEqual(r.update(cs, sm, t), ())
    sm.recv_time = {"modelV2": 1.6, "radarState": 1.6}
    self.assertEqual(r.update(cs, sm, 1.6), ("GreenLightAlert",))
    sm.valid = False
    self.assertEqual(r.update(cs, sm, 1.65), ())

  def test_real_alert_and_manager_source_with_real_enums(self):
    from openpilot.cereal import log
    from opendbc.car.structs import car
    # Execute unmodified production class ASTs without Mac-incompatible msgq imports.
    root = MODULE_PATH.parents[3]
    ns = dict(IntEnum=IntEnum, DT_CTRL=.01, log=log, car=car, dataclass=dataclass, defaultdict=defaultdict)
    events = ast.parse((root / "selfdrive/selfdrived/events.py").read_text())
    wanted = {"Priority", "ET", "Alert"}
    nodes = [n for n in events.body if isinstance(n, ast.ClassDef) and n.name in wanted]
    for name, val in dict(AlertStatus=log.SelfdriveState.AlertStatus, AlertSize=log.SelfdriveState.AlertSize,
                          VisualAlert=car.CarControl.HUDControl.VisualAlert, AudibleAlert=log.SelfdriveState.AudibleAlert).items():
      ns[name] = val
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "current_events_classes", "exec"), ns)
    ns["EmptyAlert"] = ns["Alert"]("", "", ns["AlertStatus"].normal, ns["AlertSize"].none,
                                   ns["Priority"].LOWEST, ns["VisualAlert"].none, ns["AudibleAlert"].none, 0.)
    amtree = ast.parse((root / "selfdrive/selfdrived/alertmanager.py").read_text())
    nodes = [n for n in amtree.body if isinstance(n, ast.ClassDef) and n.name in {"AlertEntry", "AlertManager"}]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "current_alertmanager_classes", "exec"), ns)
    api = SimpleNamespace(**ns)
    for key, text in (("GreenLightAlert", "Light turned green"), ("LeadDepartingAlert", "Lead departed")):
      alert = m.make_alert(key, api)
      self.assertEqual(alert.alert_text_1, text)
      self.assertEqual(alert.audible_alert, log.SelfdriveState.AudibleAlert.prompt)
      self.assertEqual(alert.duration, 300)
      am = ns["AlertManager"]()
      am.add_many(0, [alert])
      am.process_alerts(0, set())
      self.assertIs(am.current_alert, alert)
      safety = ns["Alert"]("Pay attention", "", ns["AlertStatus"].normal, ns["AlertSize"].small,
                            ns["Priority"].LOW, ns["VisualAlert"].none, ns["AudibleAlert"].preAlert, 3.)
      safety.alert_type = "driverDistracted1/permanent"
      safety.event_type = "permanent"
      am.add_many(1, [safety])
      am.process_alerts(1, set())
      self.assertIs(am.current_alert, safety)
      am.process_alerts(301, set())
      self.assertIs(am.current_alert, safety)
      am.process_alerts(302, set())
      self.assertIs(am.current_alert, ns["EmptyAlert"])
      # Even an equal-lowest stock notification must win, and optional must not
      # resume later. This exercises the actual integration dispatch helper.
      am = ns["AlertManager"]()
      m.add_to_alert_manager(am, 0, (key,), event_api=api)
      am.process_alerts(0, set())
      self.assertEqual(am.current_alert.alert_text_1, text)
      stock = ns["Alert"]("Reverse gear", "", ns["AlertStatus"].normal, ns["AlertSize"].small,
                           ns["Priority"].LOWEST, ns["VisualAlert"].none, ns["AudibleAlert"].none, .2)
      stock.alert_type = "reverseGear/permanent"
      stock.event_type = "permanent"
      am.add_many(1, [stock])
      m.add_to_alert_manager(am, 1, (key,), event_api=api)
      am.process_alerts(1, set())
      self.assertIs(am.current_alert, stock)
      self.assertNotIn(f"bogpilot{key}/permanent", am.alerts)
      am.process_alerts(22, set())
      self.assertIs(am.current_alert, ns["EmptyAlert"])
      m.add_to_alert_manager(am, 23, (key,), event_api=api)
      m.add_to_alert_manager(am, 24, (), eligible=False, event_api=api)
      self.assertIn(stock.alert_type, am.alerts)
      self.assertNotIn(f"bogpilot{key}/permanent", am.alerts)


if __name__ == "__main__":
  unittest.main()
