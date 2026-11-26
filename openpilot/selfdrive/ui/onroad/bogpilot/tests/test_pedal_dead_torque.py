"""Dead DI_torqueMotor (flat 0.0 Nm at high motor rpm while openpilot drives): the pedal gauge must keep drawing openpilot's
accel and regen requests instead of going empty. Pure Python; no window."""
import unittest

from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED

ON = PED.PedalPolicy(show=True)
DT = 0.05
AP1_S = "TESLA_AP1_MODELS"


class Rig:
  def __init__(self):
    self.g, self.t = PED.PedalGauge(), 0.0

  def step(self, tq, rpm, op=0.0, long=True, pedal=0.0, n=1, fresh=True):
    out = None
    for _ in range(n):
      self.t += DT
      out = self.g.update(ON, fresh, self.t, "ap1", brake_pressed=False, brake_level=0.0, pedal_pos=pedal, op_accel=op,
                          long_active=long, motor_torque_nm=tq, motor_rpm=rpm, fingerprint=AP1_S)
    return out


class TestTorqueTrust(unittest.TestCase):
  def test_flat_zero_at_high_rpm_is_dead_after_hold(self):
    tt = PED.TorqueTrust()
    t, dead = 0.0, False
    for _ in range(int(PED.TORQUE_DEAD_HOLD_S / DT) - 2):
      t += DT
      dead = tt.update(0.0, 7500.0, t)
    self.assertFalse(dead)
    for _ in range(6):
      t += DT
      dead = tt.update(0.0, 7500.0, t)
    self.assertTrue(dead)

  def test_zero_at_low_rpm_is_never_dead(self):
    tt = PED.TorqueTrust()
    for i in range(400):
      self.assertFalse(tt.update(0.0, 3000.0, i * DT))

  def test_live_torque_at_high_rpm_is_never_dead(self):
    tt = PED.TorqueTrust()
    for i in range(400):
      self.assertFalse(tt.update(40.0, 8000.0, i * DT))

  def test_released_below_rpm_off(self):
    tt = PED.TorqueTrust()
    t = 0.0
    for _ in range(40):
      t += DT
      tt.update(0.0, 7500.0, t)
    self.assertTrue(tt.dead)
    t += DT
    self.assertFalse(tt.update(0.0, 4900.0, t))

  def test_released_by_sustained_live_torque_not_a_blip(self):
    tt = PED.TorqueTrust()
    t = 0.0
    for _ in range(40):
      t += DT
      tt.update(0.0, 7500.0, t)
    t += DT
    self.assertTrue(tt.update(-6.0, 7500.0, t))                      # one blip does not release
    t += DT
    self.assertTrue(tt.update(0.0, 7500.0, t))
    for _ in range(int(PED.TORQUE_ALIVE_HOLD_S / DT) + 5):
      t += DT
      tt.update(30.0, 7500.0, t)
    self.assertFalse(tt.dead)

  def test_missing_rpm_or_torque_resets(self):
    tt = PED.TorqueTrust()
    for i in range(40):
      tt.update(0.0, 7500.0, i * DT)
    self.assertTrue(tt.dead)
    self.assertFalse(tt.update(None, 7500.0, 2.1))
    self.assertFalse(tt.dead)

  def test_gap_resets(self):
    tt = PED.TorqueTrust()
    for i in range(40):
      tt.update(0.0, 7500.0, i * DT)
    self.assertTrue(tt.dead)
    self.assertFalse(tt.update(0.0, 7500.0, 60.0))


class TestGaugeWithDeadTorque(unittest.TestCase):
  def settle(self, rig, op, rpm=7500.0, seconds=1.0, long=True):
    return rig.step(0.0, rpm, op=op, long=long, n=int(seconds / DT))

  def test_op_decel_request_draws_regen_while_torque_dead(self):
    r = Rig()
    g = self.settle(r, -0.7)
    self.assertGreater(g.regen, 0.3)
    self.assertEqual(g.regen_src, G3.OP)
    self.assertEqual(g.accel, 0.0)

  def test_op_accel_request_draws_accel_while_torque_dead(self):
    r = Rig()
    g = self.settle(r, 0.7)
    self.assertGreater(g.accel, 0.2)
    self.assertEqual(g.accel_src, G3.OP)
    self.assertEqual(g.regen, 0.0)

  def test_small_request_draws_nothing(self):
    r = Rig()
    g = self.settle(r, -0.03)
    self.assertEqual((g.regen, g.accel), (0.0, 0.0))

  def test_request_fill_stops_when_openpilot_not_active(self):
    r = Rig()
    self.settle(r, -0.7)
    g = r.step(0.0, 7500.0, op=0.0, long=False, n=4)
    self.assertEqual((g.regen, g.accel), (0.0, 0.0))
    self.assertEqual(g.regen_src, G3.DRIVER)

  def test_driver_pedal_wins_over_request(self):
    r = Rig()
    self.settle(r, 0.7)
    g = r.step(0.0, 7500.0, op=0.0, long=True, pedal=0.4, n=4)
    self.assertAlmostEqual(g.accel, 0.4)
    self.assertEqual(g.accel_src, G3.DRIVER)

  def test_live_torque_still_drives_the_bars(self):
    r = Rig()
    g = r.step(-60.0, 7500.0, op=-0.7, n=40)
    self.assertGreater(g.regen, 0.3)
    g = r.step(80.0, 7500.0, op=0.5, n=40)
    self.assertGreater(g.accel, 0.2)
    self.assertEqual(g.regen, 0.0)

  def test_torque_returning_takes_over_again(self):
    r = Rig()
    self.settle(r, -0.7)
    g = r.step(-30.0, 7500.0, op=-0.7, n=int(1.0 / DT))
    self.assertFalse(r.g.trust.dead)
    self.assertGreater(g.regen, 0.0)

  def test_low_rpm_zero_torque_stays_empty_as_before(self):
    r = Rig()
    g = r.step(0.0, 3000.0, op=-0.7, n=40)
    self.assertEqual(g.regen, 0.0)

  def test_no_rpm_keeps_old_behaviour(self):
    r = Rig()
    g = r.step(0.0, None, op=-0.7, n=40)
    self.assertFalse(r.g.trust.dead)
    self.assertEqual(g.regen, 0.0)

  def test_reset_clears_dead_state(self):
    r = Rig()
    self.settle(r, -0.7)
    self.assertTrue(r.g.trust.dead)
    g = r.step(0.0, 7500.0, op=-0.7, fresh=False)
    self.assertEqual((g.regen, g.accel), (0.0, 0.0))
    self.assertFalse(r.g.trust.dead)


if __name__ == "__main__":
  unittest.main()
