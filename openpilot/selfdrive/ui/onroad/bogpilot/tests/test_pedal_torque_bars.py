"""Torque-scaled regen and accel bars (pedals.py / pedal_gauge3.py): regen = -min(0, DI_torqueMotor) / 116 Nm, accel =
max(0, DI_torqueMotor) / 200 Nm while openpilot long is active, driver pedal unchanged, fallbacks for a missing / SNA /
stale torque. Pure Python; no window. With the power log scale these torque fills are the fallback when DI_motorRPM is
missing / SNA, so the rig passes no rpm (test_pedal_power_log.py covers the log scale)."""
import math
import unittest

from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3
from openpilot.selfdrive.ui.onroad.bogpilot import pedals as PED

ON = PED.PedalPolicy(show=True)
DT = 0.05            # the HUD rate in the replay (20 Hz)
AP1_S, PREAP = "TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"


class Rig:
  def __init__(self, fp=AP1_S):
    self.g, self.t, self.fp = PED.PedalGauge(), 0.0, fp

  def step(self, tq=None, pedal=0.0, op=0.0, long=True, fresh=True, n=1):
    out = None
    for _ in range(n):
      self.t += DT
      out = self.g.update(ON, fresh, self.t, PED.platform_of(self.fp), brake_pressed=False, brake_level=0.0, pedal_pos=pedal,
                          op_accel=op, long_active=long, motor_torque_nm=tq, motor_rpm=None, fingerprint=self.fp)
    return out


class TestConstants(unittest.TestCase):
  def test_named_full_scales(self):
    self.assertEqual(G3.REGEN_FULLSCALE_NM, 116.0)
    self.assertEqual(G3.ACCEL_FULLSCALE_NM, 200.0)
    self.assertEqual((PED.OP_ACCEL_ON, PED.OP_ACCEL_OFF), (0.10, 0.05))


class TestFormulas(unittest.TestCase):
  def test_regen_fill(self):
    self.assertAlmostEqual(G3.regen_torque_fill(-58.0), 0.5)
    self.assertAlmostEqual(G3.regen_torque_fill(-116.0), 1.0)
    self.assertEqual(G3.regen_torque_fill(-300.0), 1.0)                     # clamped
    self.assertAlmostEqual(G3.regen_torque_fill(-49.0), 49.0 / 116.0)       # 42 %, was 27 % by kW at 11 m/s
    for tq in (0.0, -0.5, -1.0, 40.0, 250.0):                               # coasting noise, drive torque
      self.assertEqual(G3.regen_torque_fill(tq), 0.0, tq)

  def test_accel_fill(self):
    self.assertAlmostEqual(G3.accel_torque_fill(91.0), 0.455)               # the 5:07 PM climb
    self.assertAlmostEqual(G3.accel_torque_fill(200.0), 1.0)
    self.assertEqual(G3.accel_torque_fill(500.0), 1.0)
    for tq in (0.0, 0.5, 1.0, -40.0, -116.0):
      self.assertEqual(G3.accel_torque_fill(tq), 0.0, tq)

  def test_missing_sna_junk_fail_closed(self):
    for bad in (None, float("nan"), float("inf"), "x", G3.MOTOR_TORQUE_SNA_NM, -5000.0):
      self.assertIsNone(G3.motor_torque_value(bad), bad)
      self.assertEqual(G3.regen_torque_fill(bad), 0.0, bad)
      self.assertEqual(G3.accel_torque_fill(bad), 0.0, bad)
    for fs in (0.0, -116.0, None, float("nan")):
      self.assertEqual(G3.regen_torque_fill(-50.0, fs), 0.0)
      self.assertEqual(G3.accel_torque_fill(50.0, fs), 0.0)

  def test_gauge_state_torque_path_and_kw_path_coexist(self):
    self.assertAlmostEqual(G3.gauge_state(0, None, 0, True, regen_nm=-58.0).regen, 0.5)
    self.assertEqual(G3.gauge_state(0, -50.0, 0, True, regen_nm=None).regen, 0.0)      # given but missing -> empty
    self.assertAlmostEqual(G3.gauge_state(0, -27.5, 0, True).regen, 0.5)               # old kW path unchanged


class TestRegenBar(unittest.TestCase):
  def test_steady_regen_is_torque_over_116(self):
    g = Rig().step(tq=-110.0, n=40)
    self.assertAlmostEqual(g.regen, 110.0 / 116.0, places=6)
    self.assertEqual(g.regen_src, G3.OP)                                    # colour: OP while long is active

  def test_same_on_preap(self):
    self.assertAlmostEqual(Rig(PREAP).step(tq=-58.0, n=40).regen, 0.5, places=6)

  def test_missing_stale_sna_empty_and_resets(self):
    r = Rig()
    r.step(tq=-100.0, n=40)
    self.assertEqual(r.step(tq=None).regen, 0.0)                            # stale -> HUD passes None
    self.assertEqual(r.step(tq=G3.MOTOR_TORQUE_SNA_NM).regen, 0.0)
    self.assertAlmostEqual(r.step(tq=-100.0).regen, 100.0 / 116.0)          # filter restarted, no stale blend
    self.assertEqual(r.step(tq=-100.0, fresh=False), G3.EMPTY3)


class TestAccelBar(unittest.TestCase):
  def test_climb_reads_torque_even_with_a_tiny_request(self):
    # 5:07 PM: request 0.03-0.07 m/s^2 (under OP_ACCEL_ON), motor 91 Nm
    g = Rig().step(tq=91.0, op=0.05, n=40)
    self.assertAlmostEqual(g.accel, 0.455, places=6)
    self.assertEqual(g.accel_src, G3.OP)                                    # OP colour anytime long is active, even below 0.10
    for op in (0.0, 0.03, 0.09):
      g = Rig().step(tq=91.0, op=op, n=40)
      self.assertEqual((round(g.accel, 6), g.accel_src), (0.455, G3.OP), op)
    g = Rig().step(tq=91.0, op=0.05, long=False, n=40)
    self.assertEqual((g.accel, g.accel_src), (0.0, G3.DRIVER))              # not long active: no OP colour
    g = Rig().step(tq=91.0, op=0.05, pedal=0.2, n=40)
    self.assertEqual((g.accel, g.accel_src), (0.2, G3.DRIVER))              # driver pedal still wins
    g = Rig().step(tq=91.0, op=0.30, n=40)
    self.assertAlmostEqual(g.accel, 0.455, places=6)
    self.assertEqual(g.accel_src, G3.OP)

  def test_request_no_longer_scales_the_fill(self):
    self.assertAlmostEqual(Rig().step(tq=50.0, op=1.9, n=40).accel, 0.25, places=6)
    self.assertEqual(Rig().step(tq=0.0, op=1.9, n=40).accel, 0.0)           # coasting, the request is not the fill

  def test_regen_torque_reads_zero_on_the_accel_bar(self):
    self.assertEqual(Rig().step(tq=-80.0, op=-0.5, n=40).accel, 0.0)

  def test_driver_pedal_unchanged_and_wins(self):
    r = Rig()
    r.step(tq=120.0, op=0.5, n=40)
    g = r.step(tq=120.0, op=0.5, pedal=0.23)
    self.assertEqual((g.accel, g.accel_src), (0.23, G3.DRIVER))
    self.assertEqual(Rig().step(tq=120.0, pedal=0.18, long=False).accel, 0.18)

  def test_not_long_active_shows_pedal_not_torque(self):
    g = Rig().step(tq=150.0, pedal=0.0, long=False, n=40)
    self.assertEqual(g.accel, 0.0)                                           # stock ACC / disengaged: torque not shown

  def test_fallback_without_valid_torque_is_the_old_request_path(self):
    for bad in (None, G3.MOTOR_TORQUE_SNA_NM):
      r = Rig()
      g = r.step(tq=bad, op=1.0, n=10)
      self.assertEqual((g.accel, g.accel_src), (0.5, G3.OP), bad)            # op / ACCEL_MAX, once past the threshold
      self.assertEqual(Rig().step(tq=bad, op=0.05, n=10).accel, 0.0, bad)    # under the threshold: empty, as before

  def test_preap_same_inputs_same_bar(self):
    self.assertAlmostEqual(Rig(PREAP).step(tq=91.0, n=40).accel, 0.455, places=6)

  def test_smoothing_follows_a_step(self):
    r = Rig()
    r.step(tq=0.0)
    g = r.step(tq=100.0)
    want = 100.0 * DT / (G3.REGEN_TAU_S + DT) / 200.0
    self.assertAlmostEqual(g.accel, want, places=6)


if __name__ == "__main__":
  unittest.main()
