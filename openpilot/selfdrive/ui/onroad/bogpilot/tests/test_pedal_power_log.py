"""Power log scale and near-max regen flash (pedal_gauge3.py / pedals.py). Pure Python; no window."""
import math
import unittest

from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED

ON = PED.PedalPolicy(show=True)
DT = 0.05
AP1_S, PREAP = "TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"


def rpm_at(mph):
  return mph * 0.44704 / (2 * math.pi * G3.WHEEL_RADIUS_M) * 60.0 * G3.GEAR_RATIO


def nm_for_kw(kw, rpm):
  return kw * 30000.0 / (math.pi * rpm)


class Rig:
  def __init__(self, fp=AP1_S):
    self.g, self.t, self.fp = PED.PedalGauge(), 0.0, fp

  def step(self, tq=None, rpm=None, pedal=0.0, op=0.0, long=True, fresh=True, brake=False, n=1):
    out = None
    for _ in range(n):
      self.t += DT
      out = self.g.update(ON, fresh, self.t, PED.platform_of(self.fp), brake_pressed=brake, brake_level=0.0, pedal_pos=pedal,
                          op_accel=op, long_active=long, motor_torque_nm=tq, motor_rpm=rpm, fingerprint=self.fp)
    return out


class TestLogMapping(unittest.TestCase):
  def test_endpoints_and_clamp(self):
    for fs, p0 in ((G3.ACCEL_FULLSCALE_KW, G3.ACCEL_LOG_P0_KW), (G3.REGEN_PEAK_KW_DEFAULT, G3.REGEN_LOG_P0_KW)):
      self.assertEqual(G3.log_power_fill(0.0, fs, p0), 0.0)
      self.assertAlmostEqual(G3.log_power_fill(fs, fs, p0), 1.0)
      self.assertEqual(G3.log_power_fill(fs * 3, fs, p0), 1.0)

  def test_monotonic(self):
    prev = -1.0
    for i in range(0, 4001):
      f = G3.log_power_fill(i * 0.1, G3.ACCEL_FULLSCALE_KW, G3.ACCEL_LOG_P0_KW)
      self.assertGreaterEqual(f, prev)
      prev = f

  def test_table(self):
    want_drive = {5: 12, 10: 20, 25: 36, 50: 51, 100: 69, 200: 87, 300: 98}
    for kw, pct in want_drive.items():
      self.assertEqual(round(100 * G3.log_power_fill(kw, 320.0, 10.0)), pct, kw)
    want_regen = {5: 27, 10: 43, 25: 70, 50: 93}
    for kw, pct in want_regen.items():
      self.assertEqual(round(100 * G3.log_power_fill(kw, 60.0, 5.0)), pct, kw)

  def test_deadband_and_junk(self):
    for bad in (None, float("nan"), "x", -5.0, 0.5, 1.0):
      self.assertEqual(G3.log_power_fill(bad, 320.0, 10.0), 0.0, bad)
    for fs, p0 in ((0.0, 10.0), (320.0, 0.0), (-1.0, 10.0), (None, 10.0)):
      self.assertEqual(G3.log_power_fill(50.0, fs, p0), 0.0)

  def test_power_from_torque_and_rpm(self):
    self.assertAlmostEqual(G3.drive_power_kw(200.0, 3000.0), 200 * 3000 * math.pi / 30000)
    self.assertEqual(G3.drive_power_kw(-100.0, 3000.0), 0.0)
    self.assertAlmostEqual(G3.regen_power_kw(-100.0, 3000.0), 100 * 3000 * math.pi / 30000)
    self.assertAlmostEqual(G3.regen_power_kw(-100.0, -3000.0), 100 * 3000 * math.pi / 30000)   # reverse: magnitude
    for bad_rpm in (None, G3.MOTOR_RPM_SNA, float("nan")):
      self.assertIsNone(G3.drive_power_kw(100.0, bad_rpm))
      self.assertIsNone(G3.accel_power_fill(100.0, bad_rpm))
      self.assertIsNone(G3.regen_power_fill(-100.0, bad_rpm))
    self.assertIsNone(G3.regen_power_kw(G3.MOTOR_TORQUE_SNA_NM, 3000.0))

  def test_per_model_regen_peak(self):
    self.assertEqual(G3.regen_peak_kw(AP1_S), G3.REGEN_PEAK_KW_AP1_S)
    self.assertEqual(G3.regen_peak_kw("unknown"), G3.REGEN_PEAK_KW_DEFAULT)


class TestBarsOnTheLogScale(unittest.TestCase):
  def test_accel_bar_is_log_drive_power(self):
    rpm = rpm_at(30)
    tq = nm_for_kw(50.0, rpm)
    g = Rig().step(tq=tq, rpm=rpm, op=0.5, n=60)
    self.assertAlmostEqual(g.accel, G3.log_power_fill(50.0, 320.0, 10.0), places=3)
    self.assertEqual(g.accel_src, G3.OP)

  def test_accel_full_only_near_320_kw(self):
    rpm = rpm_at(70)
    self.assertLess(Rig().step(tq=200.0, rpm=rpm, n=60).accel, 0.95)        # the old 100 %: 200 Nm ~ 174 kW at 70 mph
    self.assertAlmostEqual(Rig().step(tq=nm_for_kw(320.0, rpm), rpm=rpm, n=60).accel, 1.0, places=3)

  def test_regen_bar_is_log_regen_power(self):
    rpm = rpm_at(20)
    g = Rig().step(tq=-nm_for_kw(25.0, rpm), rpm=rpm, n=60)
    self.assertAlmostEqual(g.regen, G3.log_power_fill(25.0, 60.0, 5.0), places=3)   # ~70 %, not full
    self.assertEqual(g.regen_src, G3.OP)

  def test_no_rpm_falls_back_to_torque(self):
    self.assertAlmostEqual(Rig().step(tq=-58.0, rpm=None, n=40).regen, 0.5, places=6)
    self.assertAlmostEqual(Rig().step(tq=100.0, rpm=G3.MOTOR_RPM_SNA, n=40).accel, 0.5, places=6)

  def test_colour_rules_unchanged(self):
    rpm = rpm_at(30)
    g = Rig().step(tq=60.0, rpm=rpm, op=0.05, n=40)                         # tiny request: still OP colour
    self.assertEqual(g.accel_src, G3.OP)
    g = Rig().step(tq=60.0, rpm=rpm, op=0.05, pedal=0.2, n=40)              # driver pedal wins, linear pedal position
    self.assertEqual((g.accel, g.accel_src), (0.2, G3.DRIVER))
    g = Rig().step(tq=60.0, rpm=rpm, long=False, n=40)
    self.assertEqual((g.accel, g.accel_src, g.regen_src), (0.0, G3.DRIVER, G3.DRIVER))
    g = Rig().step(tq=-60.0, rpm=rpm, long=False, n=40)                     # driver regen: log fill, driver blue, no flash
    self.assertGreater(g.regen, 0.0)
    self.assertEqual((g.regen_rgb, g.regen_flash), (G3.GAUGE3_PALETTE[(G3.REGEN, G3.DRIVER)], False))

  def test_scale_switch_off_restores_torque_bars(self):
    try:
      G3.POWER_LOG_SCALE = False
      self.assertAlmostEqual(Rig().step(tq=-58.0, rpm=rpm_at(30), n=40).regen, 0.5, places=6)
      self.assertAlmostEqual(Rig().step(tq=100.0, rpm=rpm_at(30), n=40).accel, 0.5, places=6)
    finally:
      G3.POWER_LOG_SCALE = True


class TestRegenFlash(unittest.TestCase):
  ON_STEPS = int((G3.LIMIT_FLAT_S + G3.LIMIT_HOLD_S + G3.REGEN_FLASH_ON_HOLD_S) / DT) + 4

  def test_torque_ceiling_with_a_larger_request_flashes(self):
    rpm = rpm_at(15)                                                         # low speed: regen capped by torque
    r = Rig()
    self.assertFalse(r.step(tq=-113.0, rpm=rpm, op=-1.9, n=8).regen_flash)   # not yet (hold)
    self.assertTrue(r.step(tq=-113.0, rpm=rpm, op=-1.9, n=self.ON_STEPS).regen_flash)

  def test_power_capped_at_speed_flashes(self):
    rpm = rpm_at(60)
    tq = -nm_for_kw(25.0, rpm)                                               # 25 kW cap at 60 mph ~ 34 Nm ~ 0.45 m/s^2
    self.assertFalse(Rig().step(tq=tq, rpm=rpm, op=-0.4, n=60).regen_flash)  # request met: no flash
    self.assertTrue(Rig().step(tq=tq, rpm=rpm, op=-1.2, n=self.ON_STEPS).regen_flash)

  def test_request_met_at_the_ceiling_does_not_flash_by_default(self):
    self.assertFalse(G3.REGEN_FLASH_TORQUE_RULE)
    self.assertFalse(Rig().step(tq=-113.0, rpm=rpm_at(15), op=-1.4, n=60).regen_flash)

  def test_optional_torque_rule(self):
    try:
      G3.REGEN_FLASH_TORQUE_RULE = True
      r = Rig()
      self.assertTrue(r.step(tq=-110.0, rpm=rpm_at(15), op=-1.0, n=10).regen_flash)
      self.assertTrue(r.step(tq=-0.85 * G3.REGEN_FULLSCALE_NM, rpm=rpm_at(15), op=-1.0, n=40).regen_flash)   # hysteresis
      self.assertFalse(Rig().step(tq=-0.85 * G3.REGEN_FULLSCALE_NM, rpm=rpm_at(15), op=-1.0, n=40).regen_flash)
    finally:
      G3.REGEN_FLASH_TORQUE_RULE = False

  def test_regen_still_ramping_is_lag_not_a_limit(self):
    rpm = rpm_at(30)
    r = Rig()
    out = None
    for i in range(60):                                                      # regen growing 30 Nm/s under a big request
      out = r.step(tq=-(20.0 + 1.5 * i), rpm=rpm, op=-2.5)
      self.assertFalse(out.regen_flash, i)

  def test_drag_or_grade_without_real_regen_does_not_flash(self):
    rpm = rpm_at(35)
    self.assertFalse(Rig().step(tq=-nm_for_kw(4.0, rpm), rpm=rpm, op=-1.0, n=60).regen_flash)   # 4 kW: coasting

  def test_low_speed_and_standstill_do_not_flash(self):
    self.assertFalse(Rig().step(tq=-60.0, rpm=rpm_at(5), op=-1.5, n=60).regen_flash)
    self.assertFalse(Rig().step(tq=-60.0, rpm=0.0, op=-1.5, n=60).regen_flash)
    self.assertFalse(Rig().step(tq=-60.0, rpm=None, op=-1.5, n=60).regen_flash)                # no rpm: no flash

  def test_min_show_then_off(self):
    rpm = rpm_at(15)
    r = Rig()
    r.step(tq=-113.0, rpm=rpm, op=-1.9, n=self.ON_STEPS)
    self.assertTrue(r.step(tq=-113.0, rpm=rpm, op=-1.0, n=3).regen_flash)    # request now met: held by the 1 s minimum
    self.assertFalse(r.step(tq=-113.0, rpm=rpm, op=-1.0, n=int(G3.REGEN_FLASH_MIN_SHOW_S / DT) + 2).regen_flash)

  def test_clears_at_once(self):
    rpm = rpm_at(15)
    for kw in ({"long": False}, {"tq": None}, {"pedal": 0.3}, {"brake": True}):
      r = Rig()
      r.step(tq=-113.0, rpm=rpm, op=-1.9, n=self.ON_STEPS)
      self.assertTrue(r.g.flash.on)
      args = dict(tq=-113.0, rpm=rpm, op=-1.9)
      args.update(kw)
      self.assertFalse(r.step(**args).regen_flash, kw)
    r = Rig()
    r.step(tq=-113.0, rpm=rpm, op=-1.9, n=self.ON_STEPS)
    self.assertEqual(r.step(tq=-113.0, rpm=rpm, fresh=False), G3.EMPTY3)

  def test_cadence_and_colours(self):
    g = G3.Gauge3(regen=0.8, regen_src=G3.OP, regen_flash=True)
    op_blue = G3.GAUGE3_PALETTE[(G3.REGEN, G3.OP)]
    self.assertEqual(g.regen_rgb_at(0), G3.REGEN_FLASH_RGB)
    self.assertEqual(g.regen_rgb_at(G3.REGEN_FLASH_MS - 1), G3.REGEN_FLASH_RGB)
    self.assertEqual(g.regen_rgb_at(G3.REGEN_FLASH_MS), op_blue)
    self.assertEqual(g.regen_rgb_at(2 * G3.REGEN_FLASH_MS), G3.REGEN_FLASH_RGB)
    on = sum(g.regen_rgb_at(ms) == G3.REGEN_FLASH_RGB for ms in range(0, 8 * G3.REGEN_FLASH_MS))
    self.assertEqual(on, 4 * G3.REGEN_FLASH_MS)                              # 50 % duty
    self.assertEqual(G3.REGEN_FLASH_MS, 400)
    # no flash: static colours, other bars never flash
    plain = G3.Gauge3(brake=0.2, regen=0.8, accel=0.3, brake_src=G3.OP, regen_src=G3.OP, accel_src=G3.OP)
    self.assertEqual(plain.segments_at(0), plain.segments())
    self.assertEqual(G3.Gauge3(regen=0.8, regen_src=G3.DRIVER, regen_flash=True).regen_rgb_at(0),
                     G3.GAUGE3_PALETTE[(G3.REGEN, G3.DRIVER)])
    self.assertEqual(G3.Gauge3(regen=0.0, regen_src=G3.OP, regen_flash=True).regen_rgb_at(0), op_blue)   # empty bar
    fl = G3.Gauge3(brake=0.2, regen=0.8, accel=0.3, regen_src=G3.OP, regen_flash=True)
    self.assertEqual([s[1] for s in fl.segments_at(0)][0::2], [s[1] for s in fl.segments()][0::2])

  def test_flash_flag_needs_engaged(self):
    self.assertFalse(G3.gauge_state(0, None, 0, False, regen_frac=0.9, regen_flash=True).regen_flash)
    self.assertTrue(G3.gauge_state(0, None, 0, True, regen_frac=0.9, regen_flash=True).regen_flash)


if __name__ == "__main__":
  unittest.main()
