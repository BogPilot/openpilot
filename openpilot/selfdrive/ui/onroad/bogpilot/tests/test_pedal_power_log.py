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
  def test_torque_rule_on_after_hold(self):
    r = Rig()
    rpm = rpm_at(15)
    g = r.step(tq=-110.0, rpm=rpm, op=-1.0, n=2)                             # 0.1 s: not yet
    self.assertFalse(g.regen_flash)
    g = r.step(tq=-110.0, rpm=rpm, op=-1.0, n=5)                             # past REGEN_FLASH_ON_HOLD_S
    self.assertTrue(g.regen_flash)

  def test_torque_hysteresis_and_min_show(self):
    r = Rig()
    rpm = rpm_at(15)
    r.step(tq=-110.0, rpm=rpm, op=-1.0, n=10)
    self.assertTrue(r.step(tq=-0.85 * G3.REGEN_FULLSCALE_NM, rpm=rpm, op=-1.0, n=40).regen_flash)   # 85 %: stays on
    r.step(tq=-0.5 * G3.REGEN_FULLSCALE_NM, rpm=rpm, op=-0.5, n=1)
    g = r.step(tq=-0.5 * G3.REGEN_FULLSCALE_NM, rpm=rpm, op=-0.5, n=int(G3.REGEN_FLASH_MIN_SHOW_S / DT) + 2)
    self.assertFalse(g.regen_flash)
    r2 = Rig()
    r2.step(tq=-0.85 * G3.REGEN_FULLSCALE_NM, rpm=rpm, op=-1.0, n=40)
    self.assertFalse(r2.g.flash.on)                                          # 85 % never starts it

  def test_min_show_holds_a_short_dip(self):
    r = Rig()
    rpm = rpm_at(15)
    r.step(tq=-110.0, rpm=rpm, op=-1.0, n=8)
    self.assertTrue(r.step(tq=-40.0, rpm=rpm, op=-0.3, n=3).regen_flash)     # 0.15 s dip, still within the 1 s minimum

  def test_power_rule(self):
    rpm = rpm_at(60)
    tq = -nm_for_kw(25.0, rpm)                                               # 25 kW cap at 60 mph ~ 34 Nm ~ 0.45 m/s^2
    r = Rig()
    self.assertFalse(r.step(tq=tq, rpm=rpm, op=-0.4, n=40).regen_flash)      # request met: no flash
    r = Rig()
    self.assertFalse(r.step(tq=tq, rpm=rpm, op=-1.2, n=int(G3.LIMIT_HOLD_S / DT) - 1).regen_flash)
    self.assertTrue(r.step(tq=tq, rpm=rpm, op=-1.2, n=int(G3.REGEN_FLASH_ON_HOLD_S / DT) + 3).regen_flash)

  def test_power_rule_not_in_low_speed_fade(self):
    rpm = rpm_at(5)
    self.assertFalse(Rig().step(tq=-20.0, rpm=rpm, op=-1.5, n=60).regen_flash)

  def test_clears_at_once(self):
    rpm = rpm_at(15)
    for kw in ({"long": False}, {"tq": None}, {"pedal": 0.3}, {"brake": True}):
      r = Rig()
      r.step(tq=-110.0, rpm=rpm, op=-1.0, n=10)
      args = dict(tq=-110.0, rpm=rpm, op=-1.0)
      args.update(kw)
      self.assertFalse(r.step(**args).regen_flash, kw)
    r = Rig()
    r.step(tq=-110.0, rpm=rpm, op=-1.0, n=10)
    self.assertEqual(r.step(tq=-110.0, rpm=rpm, fresh=False), G3.EMPTY3)

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
