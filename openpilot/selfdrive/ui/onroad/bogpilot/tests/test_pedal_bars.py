"""3X pedal gauge adapter (pedals.py): gate (one mode), per-bar inputs, driver wins, colour-source hysteresis, Pre-AP
binary and iBooster brake bar, regen smoothing, fail closed, and the column footprint (headless)."""
import inspect
import unittest

from opendbc.car import interfaces
from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED

ON = PED.PedalPolicy(show=True)
DT = 1 / 60
AP1_S = "TESLA_AP1_MODELS"
PREAP = "TESLA_PREAP_MODELS"


class Rig:
  def __init__(self, fp=AP1_S):
    self.g, self.t, self.fp = PED.PedalGauge(), 0.0, fp

  def step(self, brake=False, level=0.0, pedal=0.0, op=0.0, long=False, tq=None, rpm=None, bps=None, fresh=True, policy=ON):
    self.t += DT
    return self.g.update(policy, fresh, self.t, PED.platform_of(self.fp), brake_pressed=brake, brake_level=level,
                         pedal_pos=pedal, op_accel=op, long_active=long, motor_torque_nm=tq, motor_rpm=rpm,
                         brake_pedal_state=bps, fingerprint=self.fp)

  def hold(self, n=None, **kw):
    out = None
    for _ in range(n or int(PED.SOURCE_HOLD_S / DT) + 3):
      out = self.step(**kw)
    return out


class TestGate(unittest.TestCase):
  class S:
    def __init__(self, **v):
      self.v = v

    def tuning_level(self):
      return 3

    def toggle_bool(self, k, level=None):
      return self.v.get(k, False)

  def test_one_mode_gate(self):
    on = dict(CustomUI=True, PedalsOnUI=True)
    self.assertEqual(PED.policy_from_store(self.S(**on), True), ON)
    self.assertEqual(PED.policy_from_store(self.S(**on), False), PED.CLOSED)            # needs openpilot longitudinal
    self.assertFalse(PED.policy_from_store(self.S(PedalsOnUI=True), True).show)         # needs CustomUI
    self.assertFalse(PED.policy_from_store(self.S(CustomUI=True), True).show)           # needs Pedals on Screen
    # the old Dynamic / Static values are not read: no combination hides or changes the gauge
    for dyn in (True, False):
      for sta in (True, False):
        self.assertEqual(PED.policy_from_store(self.S(**on, DynamicPedalsOnUI=dyn, StaticPedalsOnUI=sta), True), ON)
    self.assertEqual([f for f in PED.PedalPolicy.__dataclass_fields__], ["show"])

  def test_no_static_or_aego_inputs(self):
    params = inspect.signature(PED.PedalGauge.update).parameters
    for gone in ("a_ego", "v_ego", "standstill", "brake_lights", "static"):
      self.assertNotIn(gone, params)
    src = inspect.getsource(PED)
    for gone in ("StaticPedalsOnUI\")", "daily_opacity", "DECEL_FULL_SCALE", "blend"):
      self.assertNotIn(gone, src)

  def test_hidden_or_stale_is_empty_and_resets(self):
    r = Rig()
    r.hold(long=True, op=1.0)
    self.assertEqual(r.step(policy=PED.CLOSED), G3.EMPTY3)
    self.assertEqual(r.g.accel_src, G3.DRIVER)
    self.assertEqual(r.step(fresh=False, tq=-100, rpm=5000), G3.EMPTY3)


class TestBars(unittest.TestCase):
  def test_driver_brake_regen(self):
    g = Rig().step(brake=True, level=0.6, tq=-100.0, rpm=5000.0)
    self.assertEqual((g.brake, g.brake_src, g.regen_src), (0.6, G3.DRIVER, G3.DRIVER))
    self.assertAlmostEqual(g.regen, 100.0 / G3.REGEN_FULLSCALE_NM)

  def test_engaged_op_brake_and_regen_colours(self):
    r = Rig()
    g = r.hold(long=True, level=0.4, bps=1, tq=-80.0, rpm=6000.0)
    self.assertEqual((g.brake, g.brake_src, g.regen_src), (0.4, G3.OP, G3.OP))
    self.assertEqual(g.brake_rgb, G3.GAUGE3_PALETTE[(G3.BRAKE, G3.OP)])
    g = r.step(long=True, brake=True, level=0.7, bps=1, tq=-80.0, rpm=6000.0)    # a driver press shows at once
    self.assertEqual((g.brake, g.brake_src), (0.7, G3.DRIVER))

  def test_op_brake_colour_needs_ap1_and_state_on(self):
    for fp, bps in ((PREAP, 1), (AP1_S, 0), (AP1_S, None), (AP1_S, 3), (AP1_S, "x")):
      g = Rig(fp).hold(long=True, level=0.4, bps=bps)
      self.assertEqual(g.brake_src, G3.DRIVER, (fp, bps))
    self.assertEqual(Rig().hold(long=False, level=0.4, bps=1).brake_src, G3.DRIVER)   # not while disengaged

  def test_accel_driver_wins(self):
    r = Rig()
    g = r.hold(long=True, op=interfaces.ACCEL_MAX)
    self.assertEqual((g.accel, g.accel_src), (1.0, G3.OP))
    g = r.step(long=True, op=interfaces.ACCEL_MAX, pedal=0.3)                     # pedal wins at once
    self.assertEqual((g.accel, g.accel_src), (0.3, G3.DRIVER))
    self.assertEqual(g.accel_rgb, G3.GAUGE3_PALETTE[(G3.ACCEL, G3.DRIVER)])

  def test_op_accel_scale_and_hysteresis(self):
    r = Rig()
    g = r.step(long=True, op=interfaces.ACCEL_MAX / 2)
    self.assertEqual((g.accel, g.accel_src), (0.0, G3.DRIVER))                    # waits SOURCE_HOLD_S before op colour
    g = r.hold(long=True, op=interfaces.ACCEL_MAX / 2)
    self.assertEqual(g.accel_src, G3.OP)
    self.assertAlmostEqual(g.accel, 0.5)
    self.assertEqual(PED.OP_ACCEL_FULL_SCALE, interfaces.ACCEL_MAX)
    self.assertEqual(Rig().hold(long=False, op=2.0).accel, 0.0)                   # op accel ignored while disengaged

  def test_pedal_sna_is_empty(self):
    self.assertEqual(Rig().step(pedal=-1.0).accel, 0.0)
    self.assertEqual(Rig().step(pedal=float("nan")).accel, 0.0)

  def test_preap_binary_and_ibooster_left_bar(self):
    r = Rig(PREAP)
    self.assertEqual(r.step(brake=True, level=1.0).brake, 1.0)          # binary: the car state publishes 1.0 / 0.0
    self.assertEqual(r.step(brake=False, level=0.0).brake, 0.0)
    self.assertEqual(r.step(brake=True, level=0.5).brake, 0.5)          # iBooster swap: proportional level
    self.assertEqual(r.step(brake=True, level=-1.0).brake, 0.0)         # iBooster missing / stale / fault: fail closed

  def test_regen_on_every_platform_and_fail_closed(self):
    for fp in (AP1_S, "TESLA_AP1_MODELX", PREAP):
      self.assertGreater(Rig(fp).step(tq=-60.0, rpm=4000.0).regen, 0.0, fp)
    for tq, rpm in ((None, None), (None, 4000.0), (G3.MOTOR_TORQUE_SNA_NM, 4000.0)):
      self.assertEqual(Rig().step(tq=tq, rpm=rpm).regen, 0.0, (tq, rpm))
    self.assertGreater(Rig().step(tq=-60.0, rpm=None).regen, 0.0)       # the torque bar does not need the RPM
    self.assertEqual(Rig().step(tq=60.0, rpm=4000.0).regen, 0.0)        # drive torque

  def test_regen_is_smoothed_and_reset_by_missing(self):
    r = Rig()
    r.step(tq=0.0, rpm=5000.0)
    g = r.step(tq=-100.0, rpm=5000.0)
    want = 100.0 * DT / (G3.REGEN_TAU_S + DT)
    self.assertAlmostEqual(g.regen, want / G3.REGEN_FULLSCALE_NM, places=6)
    r.step(tq=None, rpm=None)
    self.assertAlmostEqual(r.step(tq=-100.0, rpm=5000.0).regen, 100.0 / G3.REGEN_FULLSCALE_NM)

  def test_regen_torque_scale_is_the_same_on_every_platform(self):
    # the torque bar has one full scale (REGEN_FULLSCALE_NM); the per-model kW table no longer scales it
    for fp in (AP1_S, "TESLA_AP1_MODELX", PREAP):
      self.assertAlmostEqual(Rig(fp).step(tq=-58.0, rpm=5000.0).regen, 0.5, msg=fp)


class TestFootprint(unittest.TestCase):
  def test_option_a_on_3x(self):
    content, s = (30.0, 30.0, 2100.0, 1020.0), min(1.0, 2100 / 2160, 1020 / 1080)
    ww = content[2] / s
    rect = type("R", (), {"x": content[0], "y": content[1]})()
    x, y, w, h = PED.screen_rect(rect, s, ww, False)
    self.assertAlmostEqual(x, 99.333, places=2)
    self.assertAlmostEqual(y, 489.0, places=2)
    self.assertAlmostEqual(x + w, 212.667, places=2)
    self.assertAlmostEqual(y + h, 602.333, places=2)
    self.assertAlmostEqual(x + w / 2, content[0] + PED.COLUMN_CX, places=6)     # on the record / personality column
    xr, yr, wr, hr = PED.screen_rect(rect, s, ww, True)
    self.assertAlmostEqual(content[0] + content[2] - (xr + wr / 2), PED.COLUMN_CX, places=4)
    self.assertEqual((yr, wr, hr), (y, w, h))

  def test_widget_space_y_and_size_unchanged(self):
    for rhd in (False, True):
      _x, y, w, h = PED.pedal_rect(2160, rhd)
      self.assertEqual((y, w, h), (486, 120, 120))
    self.assertEqual(PED.pedal_rect(2160, False), (66.0, 486, 120, 120))


if __name__ == "__main__":
  unittest.main()
