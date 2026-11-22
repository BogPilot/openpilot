"""SetSpeedLimit (0.9.7 drive_helpers.py:146-158 @568fea947) for Pre-AP with pedal: engage set = posted limit + offset."""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.structs import car
from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
from openpilot.selfdrive.car.cruise import V_CRUISE_INITIAL, V_CRUISE_MAX, V_CRUISE_MIN, V_CRUISE_UNSET, VCruiseHelper
from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import CP_AP1, FakeStore
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss

MPH = CV.MPH_TO_MS
CP_PREAP = NS(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True, pcmCruise=False,
              radarUnavailable=True, enableBsm=False)
CP_PREAP_TACC = NS(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=False, pcmCruise=True,
                   radarUnavailable=True, enableBsm=False)
CP_AP1_P = NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True, pcmCruise=True,
              radarUnavailable=False, enableBsm=True)
MOVING = NS(standstill=False, gasPressed=False, vEgo=10.0)
ButtonType = car.CarState.ButtonEvent.Type


def store(**vals):
  vals.setdefault("SpeedLimitController", "1")
  vals.setdefault("SetSpeedLimit", "1")
  return FakeStore(**vals)


def engage(cp=CP_PREAP, adopted=True, **vals):
  st = store(**vals)
  return sc.PreapEngageSetLimit(cp, store=st, toggles_fn=lambda: onroad_toggles(st, cp), adopted=adopted, auto_speed=True)


class TestEngageSetLimit(unittest.TestCase):
  def test_toggle_on_sets_limit_plus_offset(self):
    e = engage(Offset3="3")                 # 35-44 mph band
    self.assertAlmostEqual(e.kph(MOVING, 40 * MPH), (40 + 3) * MPH * 3.6, places=3)
    self.assertAlmostEqual(engage(Offset3="0").kph(MOVING, 40 * MPH), 40 * MPH * 3.6, places=3)

  def test_metric_offset_band(self):
    e = engage(IsMetric="1", Offset4="5")   # 60-79 km/h band
    self.assertAlmostEqual(e.kph(MOVING, 70 / 3.6), 75.0, places=3)

  def test_toggle_off_or_slc_off_or_unadopted_is_zero(self):
    self.assertEqual(engage(SetSpeedLimit="0").kph(MOVING, 20.0), 0.0)
    self.assertEqual(engage(SpeedLimitController="0").kph(MOVING, 20.0), 0.0)
    self.assertEqual(engage(adopted=False).kph(MOVING, 20.0), 0.0)

  def test_unknown_or_bad_limit_is_zero(self):
    e = engage()
    for v in (0.0, -5.0, float("nan"), float("inf"), float("-inf"), None, 500.0):
      self.assertEqual(e.kph(MOVING, v), 0.0, v)

  def test_stricter_than_097_standstill_and_gas(self):
    e = engage()
    self.assertEqual(e.kph(NS(standstill=True, gasPressed=False, vEgo=10.0), 20.0), 0.0)
    self.assertEqual(e.kph(NS(standstill=False, gasPressed=True, vEgo=10.0), 20.0), 0.0)
    self.assertEqual(e.kph(NS(), 20.0), 0.0)   # unreadable state fails closed

  def test_vego_stop_blocks_when_di_standstill_is_false(self):
    e = engage()
    # Pedal car at 0 mph: CS.standstill stays False because DI cruise is not engaged.
    self.assertEqual(e.kph(NS(standstill=False, gasPressed=False, vEgo=0.0), 20.0), 0.0)
    self.assertEqual(e.kph(NS(standstill=False, gasPressed=False, vEgo=0.09), 20.0), 0.0)
    self.assertEqual(e.kph(NS(standstill=False, gasPressed=False), 20.0), 0.0)  # missing vEgo
    self.assertEqual(e.kph(NS(standstill=False, gasPressed=False, vEgo=float("nan")), 20.0), 0.0)
    self.assertGreater(e.kph(NS(standstill=False, gasPressed=False, vEgo=10.0), 20.0), 0.0)
    self.assertEqual(e.kph(NS(standstill=True, gasPressed=False, vEgo=10.0), 20.0), 0.0)

  def test_real_preap_carstate_at_stop_does_not_latch(self):
    from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import Rig
    e = engage()
    stop = Rig()
    stop.frame(v_kph=0.0)
    stop.send("UI_gpsVehicleSpeed", UI_mppSpeedLimit=45, UI_mapSpeedLimitUnits=0)
    out = stop.frame(v_kph=0.0)
    self.assertLess(out.vEgo, 0.1)
    self.assertFalse(out.standstill)
    self.assertGreater(stop.cs.engage_limit_ms, 0.0)
    self.assertEqual(e.kph(out, stop.cs.engage_limit_ms), 0.0)
    move = Rig()
    move.frame(v_kph=50.0)
    move.send("UI_gpsVehicleSpeed", UI_mppSpeedLimit=45, UI_mapSpeedLimitUnits=0)
    out_m = move.frame(v_kph=50.0)
    self.assertGreater(out_m.vEgo, 0.1)
    self.assertFalse(out_m.standstill)
    self.assertGreater(e.kph(out_m, move.cs.engage_limit_ms), 0.0)

  def test_inactive_on_ap1_and_preap_without_pedal_long(self):
    self.assertFalse(engage(cp=CP_AP1_P).active)
    self.assertEqual(engage(cp=CP_AP1_P).kph(MOVING, 20.0), 0.0)
    self.assertFalse(engage(cp=CP_PREAP_TACC).active)
    self.assertTrue(engage().active)

  def test_toggle_failure_fails_closed(self):
    def boom():
      raise RuntimeError
    e = sc.PreapEngageSetLimit(CP_PREAP, store=store(), toggles_fn=boom, adopted=True, auto_speed=True)
    self.assertEqual(e.kph(MOVING, 20.0), 0.0)

  def test_key_is_configurable_and_watched(self):
    from openpilot.common.bogpilot_onroad_toggles import WATCHED_KEYS
    self.assertIn("SetSpeedLimit", sc.SLC_KEYS)
    self.assertIn("SetSpeedLimit", WATCHED_KEYS)


class TestInitializeVCruise(unittest.TestCase):
  def _h(self, cp):
    return VCruiseHelper(NS(pcmCruise=cp.pcmCruise))

  def _cs(self, v=10.0, buttons=()):
    return car.CarState(vEgo=v, buttonEvents=[car.CarState.ButtonEvent(type=b) for b in buttons])

  def test_limit_sets_engage_speed(self):
    h = self._h(CP_PREAP)
    h.initialize_v_cruise(self._cs(10.0), False, 72.4)
    self.assertEqual(h.v_cruise_kph, 72)

  def test_zero_is_stock(self):
    h = self._h(CP_PREAP)
    h.initialize_v_cruise(self._cs(10.0), False, 0.0)
    self.assertEqual(h.v_cruise_kph, V_CRUISE_INITIAL)
    h.initialize_v_cruise(self._cs(20.0), False)
    self.assertEqual(h.v_cruise_kph, 72)

  def test_clipped(self):
    h = self._h(CP_PREAP)
    h.initialize_v_cruise(self._cs(), False, 400.0)
    self.assertEqual(h.v_cruise_kph, V_CRUISE_MAX)
    h.initialize_v_cruise(self._cs(), False, 3.0)
    self.assertEqual(h.v_cruise_kph, V_CRUISE_MIN)

  def test_resume_keeps_last_priority(self):
    h = self._h(CP_PREAP)
    h.v_cruise_kph = h.v_cruise_kph_last = 90     # initialized (a previous engage)
    h.initialize_v_cruise(self._cs(10.0, (ButtonType.resumeCruise,)), False, 72.0)
    self.assertEqual(h.v_cruise_kph, 90)

  def test_pcm_cruise_ignores_limit(self):
    h = self._h(CP_AP1_P)
    before = h.v_cruise_kph
    h.initialize_v_cruise(self._cs(10.0), False, 72.0)
    self.assertEqual(h.v_cruise_kph, before)

  def test_disengage_then_reengage_uses_current_limit(self):
    h = self._h(CP_PREAP)
    h.initialize_v_cruise(self._cs(10.0), False, 72.4)
    self.assertEqual(h.v_cruise_kph, 72)
    cs = self._cs(10.0)
    cs.cruiseState.available = False
    h.update_v_cruise(cs, False, False)
    self.assertEqual(h.v_cruise_kph, V_CRUISE_UNSET)
    h.initialize_v_cruise(self._cs(10.0), False, 90.0)
    self.assertEqual(h.v_cruise_kph, 90)
    cs = self._cs(20.0)
    cs.cruiseState.available = False
    h.update_v_cruise(cs, False, False)
    h.initialize_v_cruise(self._cs(20.0), False, 0.0)
    self.assertEqual(h.v_cruise_kph, 72)

  def test_end_to_end_metric_limit_plus_offset(self):
    from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import Rig
    rig = Rig()
    rig.frame(v_kph=70.0)
    rig.send("UI_gpsVehicleSpeed", UI_mppSpeedLimit=70, UI_mapSpeedLimitUnits=1)
    out = rig.frame(v_kph=70.0)
    self.assertGreater(out.vEgo, 0.1)
    self.assertFalse(out.standstill)
    self.assertAlmostEqual(rig.cs.engage_limit_ms, 70 * CV.KPH_TO_MS, places=3)
    e = engage(IsMetric="1", Offset4="5")   # 60-79 km/h band
    self.assertAlmostEqual(e.kph(out, rig.cs.engage_limit_ms), 75.0, places=3)
    h = self._h(CP_PREAP)
    h.initialize_v_cruise(out, False, e.kph(out, rig.cs.engage_limit_ms))
    self.assertEqual(h.v_cruise_kph, 75)


class TestCardWiring(unittest.TestCase):
  SRC = (Path(__file__).resolve().parents[2] / "car" / "card.py").read_text()

  def test_only_preap_non_pcm_builds_the_reader(self):
    self.assertIn('self.CP.carFingerprint == "TESLA_PREAP_MODELS" and not self.CP.pcmCruise', self.SRC)
    self.assertIn("self.preap_engage_set_limit = None", self.SRC)

  def test_enable_edge_passes_limit(self):
    self.assertIn('self.preap_engage_set_limit.kph(self.CS_prev, getattr(self.CI.CS, "engage_limit_ms", 0.0))', self.SRC)
    self.assertIn("initialize_v_cruise(self.CS_prev, self.experimental_mode, set_limit_kph,", self.SRC)
    self.assertIn("preap_from_stop_kph=from_stop, is_metric=self.is_metric,", self.SRC)
    self.assertIn("preap_restore_kph=restore)", self.SRC)   # Pre-AP pull re-engage restore (test_preap_restore_last_set.py)


class TestSettingsRow(unittest.TestCase):
  def _qol(self, cp):
    st = FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1")
    return [r[0] for r in ss.visible_rows(st, "SLCQOL", cp)]

  def test_shown_on_preap_pedal_only(self):
    self.assertEqual(self._qol(CP_PREAP), ["SLCConfirmation", "SetSpeedLimit"])
    for cp in (CP_AP1_P, CP_AP1, CP_PREAP_TACC, None, NS(carFingerprint="TESLA_MODELX_AP1", pcmCruise=True)):
      self.assertNotIn("SetSpeedLimit", self._qol(cp), cp)

  def test_hidden_when_slc_off(self):
    st = FakeStore(SpeedLimitController="0")
    self.assertEqual(ss.visible_sub_panels(st, CP_PREAP), [])

  def test_editor_visibility_uses_cp(self):
    st = FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1")
    self.assertTrue(ss.SlcEditor(CP_PREAP, st, lambda: True).visible("SetSpeedLimit"))
    self.assertFalse(ss.SlcEditor(CP_AP1_P, st, lambda: True).visible("SetSpeedLimit"))

  def test_ap1_reason_wording(self):
    r = ss.CAR_GATED["SetSpeedLimit"]
    self.assertIn("initialize_v_cruise returned early", r)
    self.assertNotIn("bogpilot_variables ignored it", r)
    self.assertNotIn("SetSpeedLimit", ss.OMITTED)

class TestPreApTapNeverSlc(unittest.TestCase):
  """Planner side of the pre-AP engage: a tap (disengaged or steering-only) never hands the set to SLC. Only the
  pull that engages speed control (the double pull's second pull) does; that path is unchanged."""

  def _ctl(self):
    from openpilot.selfdrive.controls.tests.test_phase3_speed_control import Sm, make
    return make(cp=CP_PREAP), Sm()

  def _run(self, ctl, sm, n, **kw):
    from openpilot.selfdrive.controls.tests.test_phase3_speed_control import run
    return [run(ctl, sm, 20.0, 20.0, limit=45 * MPH, **kw) for _ in range(n)]

  def test_disengaged_tap_does_not_touch_the_set(self):
    """Disengaged, a tap never raises the planner value above the no-stalk value (unused while disengaged; a DN press
    there also withholds the SLC limit, existing SLC confirmation behavior) and leaves no latch or engage action."""
    ctl0, sm0 = self._ctl()
    base = self._run(ctl0, sm0, 45, cruise=False, long_active=False)
    for press in ({"up": True}, {"dn": True}):
      ctl, sm = self._ctl()
      out = self._run(ctl, sm, 5, cruise=False, long_active=False, **press) + self._run(ctl, sm, 40, cruise=False, long_active=False)
      self.assertTrue(all(o <= b + 1e-9 for o, b in zip(out, base, strict=True)), press)
      self.assertFalse(ctl.holdoff.sticky_vego)
      self.assertEqual(ctl.holdoff.tip_ms, 0.0)
      self.assertIsNone(ctl.holdoff.engage_kind)

  def test_steering_only_tap_never_engages_slc(self):
    for press in ({"up": True}, {"dn": True}):
      ctl, sm = self._ctl()
      self._run(ctl, sm, 2, cruise=False, long_active=False, rwd=True)   # first pull: steering only
      out = self._run(ctl, sm, 20, cruise=True, long_active=False)
      out += self._run(ctl, sm, 2, cruise=True, long_active=False, **press)
      out += self._run(ctl, sm, 60, cruise=True, long_active=False)
      self.assertTrue(all(o == 20.0 for o in out), press)                 # pass-through: never limit + offset
      self.assertFalse(ctl.holdoff.sticky_vego)
      self.assertEqual(ctl.holdoff.tip_ms, 0.0)

  def test_second_pull_still_hands_to_slc(self):
    ctl, sm = self._ctl()
    self._run(ctl, sm, 2, cruise=False, long_active=False, rwd=True)
    self._run(ctl, sm, 4, cruise=True, long_active=False)
    out = self._run(ctl, sm, 10, cruise=True, long_active=True, rwd=True)
    self.assertGreater(out[-1], 45 * MPH)                                  # limit + offset
