"""3-bar pedal gauge state function (pedal_gauge3.py): regen kW from 0x108, per-model full scale, deadband, smoothing,
sign handling, sources and colours, fail-closed inputs and the rect geometry. Pure Python; no window."""
import math
import os
import subprocess
import sys
import unittest
from unittest import mock

from opendbc.car.tesla_ap1 import regen_aware as RA
from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3 as G3


def hexrgb(h):
  return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


class TestRegenPower(unittest.TestCase):
  def test_kw_formula(self):
    for tq, rpm in ((-100.0, 5000.0), (-250.0, 9000.0), (-0.25, 1.0), (120.0, 3000.0)):
      self.assertAlmostEqual(G3.motor_power_kw(tq, rpm), tq * rpm * math.pi / 30000.0, places=9)
    self.assertAlmostEqual(G3.motor_power_kw(-100.0, 5000.0), -52.35987755982988, places=9)

  def test_matches_regen_aware_magnitude(self):
    # the car-side estimator (regen_aware.regen_power_kw) is the same mechanical power, clamped to regen >= 0
    for tq, rpm in ((-100.0, 5000.0), (-37.5, 8123.0), (80.0, 4000.0), (40.0, -2000.0)):
      kw = G3.motor_power_kw(tq, rpm)
      self.assertAlmostEqual(max(0.0, -kw), RA.regen_power_kw(tq, rpm), places=9)

  def test_sign_handling(self):
    self.assertLess(G3.motor_power_kw(-100.0, 5000.0), 0.0)        # regen forward
    self.assertGreater(G3.motor_power_kw(100.0, 5000.0), 0.0)      # drive forward
    self.assertLess(G3.motor_power_kw(100.0, -1500.0), 0.0)        # regen in reverse (torque and speed opposite)
    self.assertGreater(G3.motor_power_kw(-100.0, -1500.0), 0.0)    # drive in reverse
    self.assertEqual(G3.regen_fill(G3.motor_power_kw(100.0, 5000.0)), 0.0)   # drive power never fills the regen bar
    self.assertGreater(G3.regen_fill(G3.motor_power_kw(100.0, -1500.0)), 0.0)

  def test_fail_closed_on_missing_or_sna(self):
    for tq, rpm in ((None, 5000), (-100, None), (float("nan"), 5000), (-100, float("inf")), ("x", 1),
                    (G3.MOTOR_TORQUE_SNA_NM, 5000), (-100, G3.MOTOR_RPM_SNA)):
      self.assertIsNone(G3.motor_power_kw(tq, rpm), (tq, rpm))
    self.assertEqual(G3.regen_fill(None), 0.0)
    self.assertEqual(G3.regen_fill(float("nan")), 0.0)
    self.assertEqual(G3.gauge_state(None, None, None, True), G3.Gauge3(regen_src=G3.OP))
    self.assertEqual(G3.MOTOR_TORQUE_SNA_NM, -4096 * 0.25)          # tesla_ap1_can.dbc VAL_ 264 DI_torqueMotor -4096 "SNA"
    self.assertEqual(G3.MOTOR_RPM_SNA, -32768)


class TestFullScaleAndDeadband(unittest.TestCase):
  def test_per_model_constants(self):
    self.assertEqual((G3.REGEN_FULLSCALE_KW_AP1_S, G3.REGEN_FULLSCALE_KW_AP1_X, G3.REGEN_FULLSCALE_KW_PREAP,
                      G3.REGEN_FULLSCALE_KW_DEFAULT), (-55.0, -55.0, -55.0, -55.0))
    self.assertEqual(G3.regen_full_scale_kw("TESLA_AP1_MODELS"), G3.REGEN_FULLSCALE_KW_AP1_S)
    self.assertEqual(G3.regen_full_scale_kw("TESLA_AP1_MODELX"), G3.REGEN_FULLSCALE_KW_AP1_X)
    self.assertEqual(G3.regen_full_scale_kw("TESLA_PREAP_MODELS"), G3.REGEN_FULLSCALE_KW_PREAP)
    self.assertEqual(G3.regen_full_scale_kw(None), G3.REGEN_FULLSCALE_KW_DEFAULT)
    self.assertEqual(G3.regen_full_scale_kw("TOYOTA_RAV4"), G3.REGEN_FULLSCALE_KW_DEFAULT)

  def test_each_model_can_be_tuned_alone(self):
    with mock.patch.dict(G3.REGEN_FULLSCALE_KW, {"TESLA_AP1_MODELX": -40.0}):
      self.assertEqual(G3.regen_full_scale_kw("TESLA_AP1_MODELX"), -40.0)
      self.assertEqual(G3.regen_full_scale_kw("TESLA_AP1_MODELS"), -55.0)
      g = G3.gauge_state(0, -20.0, 0, False, full_scale_kw=G3.regen_full_scale_kw("TESLA_AP1_MODELX"))
      self.assertAlmostEqual(g.regen, 0.5)

  def test_fill_and_clamp(self):
    self.assertAlmostEqual(G3.regen_fill(-27.5), 0.5)
    self.assertEqual(G3.regen_fill(-55.0), 1.0)
    self.assertEqual(G3.regen_fill(-90.0), 1.0)
    self.assertEqual(G3.regen_fill(10.0), 0.0)
    self.assertEqual(G3.regen_fill(-27.5, full_scale_kw=0.0), 0.0)     # a full scale that is not negative is invalid
    self.assertEqual(G3.regen_fill(-27.5, full_scale_kw=55.0), 0.0)

  def test_deadband(self):
    self.assertEqual(G3.REGEN_DEADBAND_KW, 1.0)
    self.assertEqual(G3.regen_fill(-0.5), 0.0)
    self.assertEqual(G3.regen_fill(-1.0), 0.0)
    self.assertAlmostEqual(G3.regen_fill(-1.1), 1.1 / 55.0)            # past the deadband the scale is not offset
    self.assertEqual(G3.regen_fill(-3.0, deadband_kw=5.0), 0.0)


class TestSmoothing(unittest.TestCase):
  def test_first_sample_passes_through(self):
    s = G3.RegenSmoother()
    self.assertEqual(s.update(-30.0, 10.0), -30.0)

  def test_first_order_step(self):
    s = G3.RegenSmoother(0.15)
    s.update(0.0, 0.0)
    self.assertAlmostEqual(s.update(-40.0, 0.05), -40.0 * 0.05 / 0.20)
    t, kw = 0.05, None
    while t < 0.05 + 3 * 0.15:
      t += 1 / 60
      kw = s.update(-40.0, t)
    self.assertLess(kw, -0.9 * 40.0)                                    # within 10 % after about 3 tau

  def test_missing_sample_resets(self):
    s = G3.RegenSmoother()
    s.update(-40.0, 0.0)
    self.assertIsNone(s.update(None, 0.02))
    self.assertEqual(s.update(-10.0, 0.04), -10.0)                     # no stale memory after a gap in the data

  def test_long_gap_or_time_going_back_restarts(self):
    s = G3.RegenSmoother()
    s.update(-40.0, 0.0)
    self.assertEqual(s.update(-5.0, G3.REGEN_GAP_RESET_S + 0.5), -5.0)
    self.assertEqual(s.update(-20.0, 0.1), -20.0)

  def test_proposal_constants(self):
    self.assertEqual(G3.REGEN_TAU_S, 0.15)


class TestStateAndColours(unittest.TestCase):
  def test_t4_palette(self):
    want = {(G3.BRAKE, G3.DRIVER): "#C62828", (G3.REGEN, G3.DRIVER): "#2E8BFF", (G3.ACCEL, G3.DRIVER): "#3DDC97",
            (G3.BRAKE, G3.OP): "#B5838D", (G3.REGEN, G3.OP): "#8FB3E0", (G3.ACCEL, G3.OP): "#5E8A72"}
    self.assertEqual(G3.GAUGE3_PALETTE, {k: hexrgb(v) for k, v in want.items()})
    self.assertEqual((G3.OUTLINE_RGB, G3.OUTLINE_A, G3.OUTLINE_PX), ((255, 255, 255), 255, 1.0))

  def test_disengaged_is_all_driver(self):
    g = G3.gauge_state(0.4, -27.5, 0.3, False, brake_by_op=True, accel_by_op=True)
    self.assertEqual((g.brake, g.accel), (0.4, 0.3))
    self.assertAlmostEqual(g.regen, 0.5)
    self.assertEqual((g.brake_src, g.regen_src, g.accel_src), (G3.DRIVER,) * 3)
    self.assertEqual(g.segments()[1][1], hexrgb("#2E8BFF"))

  def test_engaged_sources(self):
    g = G3.gauge_state(0.4, -27.5, 0.3, True, brake_by_op=True, accel_by_op=True)
    self.assertEqual((g.brake_src, g.regen_src, g.accel_src), (G3.OP,) * 3)
    self.assertEqual([rgb for _f, rgb in g.segments()], [hexrgb("#B5838D"), hexrgb("#8FB3E0"), hexrgb("#5E8A72")])
    g = G3.gauge_state(0.4, -27.5, 0.3, True)
    self.assertEqual((g.brake_src, g.regen_src, g.accel_src), (G3.DRIVER, G3.OP, G3.DRIVER))

  def test_brake_is_friction_only(self):
    # regen never adds to or subtracts from the brake bar, and there is no aEgo input
    for kw in (None, 0.0, -10.0, -55.0):
      self.assertEqual(G3.gauge_state(0.25, kw, 0.0, False).brake, 0.25)
    import inspect
    params = inspect.signature(G3.gauge_state).parameters
    self.assertNotIn("a_ego", params)
    self.assertNotIn("aEgo", inspect.getsource(G3.gauge_state))

  def test_missing_fracs_are_empty(self):
    for bad in (None, -1.0, float("nan"), "x"):
      g = G3.gauge_state(bad, None, bad, False)
      self.assertEqual((g.brake, g.regen, g.accel), (0.0, 0.0, 0.0))
    g = G3.gauge_state(3.0, -500.0, 2.0, False)
    self.assertEqual((g.brake, g.regen, g.accel), (1.0, 1.0, 1.0))


class TestGeometry(unittest.TestCase):
  def test_bar_rects_tile_the_footprint(self):
    rect = (99.33, 489.0, 113.33, 113.33)
    bars = G3.bar_rects(rect)
    self.assertEqual(len(bars), 3)
    self.assertAlmostEqual(bars[0][0], rect[0])
    self.assertAlmostEqual(bars[2][0] + bars[2][2], rect[0] + rect[2])
    for b in bars:
      self.assertAlmostEqual(b[2] / rect[2], G3.BAR_W / G3.FOOT_W)
      self.assertEqual((b[1], b[3]), (rect[1], rect[3]))
    self.assertAlmostEqual(bars[1][0] - (bars[0][0] + bars[0][2]), rect[2] * G3.BAR_GAP / G3.FOOT_W)
    self.assertEqual(G3.FOOT_W, 120)

  def test_fill_polygon(self):
    inner = (10.0, 20.0, 30.0, 100.0)
    self.assertEqual(G3.fill_polygon(inner, 0.0), [])
    pts = G3.fill_polygon(inner, 0.4)
    top = G3.fill_top(20.0, 100.0, 0.4)
    self.assertAlmostEqual(top, 80.0)
    self.assertAlmostEqual(min(p[1] for p in pts), top)
    for x, y in pts:
      self.assertTrue(10.0 - 1e-9 <= x <= 40.0 + 1e-9 and top - 1e-9 <= y <= 120.0 + 1e-9)
    self.assertAlmostEqual(min(p[1] for p in G3.fill_polygon(inner, 1.0)), 20.0)

  def test_outline_snaps_to_pixel_centres(self):
    pts = G3.outline_points(G3.fill_polygon((103.11, 492.78, 26.44, 105.78), 0.6))
    self.assertTrue(pts)
    for x, y in pts:
      self.assertEqual((x % 1.0, y % 1.0), (0.5, 0.5))
    self.assertEqual(min(x for x, _ in pts), 103.5)          # the left edge lands on pixel column 103
    self.assertEqual(G3.outline_points([]), [])

  def test_inner_rect_scales_inset(self):
    self.assertEqual(G3.inner_rect((0, 0, 36, 120), 1.0), (4, 4, 28, 112))
    self.assertEqual(G3.inner_rect((0, 0, 36, 120), 0.5), (2, 2, 32, 116))


class TestNoPyrayAtImport(unittest.TestCase):
  def test_state_and_adapter_import_without_pyray(self):
    code = ("import sys\n"
            "from openpilot.selfdrive.ui.onroad.bogpilot import pedal_gauge3, pedals\n"
            "bad = [m for m in ('pyray', 'raylib') if m in sys.modules]\n"
            "assert not bad, bad\n"
            "print('ok')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ), timeout=120)
    self.assertEqual(out.returncode, 0, out.stderr[-2000:])
    self.assertIn("ok", out.stdout)


if __name__ == "__main__":
  unittest.main()
