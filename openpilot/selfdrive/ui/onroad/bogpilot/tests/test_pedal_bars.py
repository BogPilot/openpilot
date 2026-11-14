"""Pedal bars: heights, palette, colour source with hysteresis, the regen / brake decel layout, Static mode, RHD and the
scissor-free fill (headless)."""
import math
import unittest

from opendbc.car import interfaces
from opendbc.car.tesla_ap1 import regen_aware as RA
from opendbc.car.tesla_ap1.preap import vdas_constants as VDAS

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load

PED = load("pedals")
DYN = PED.PedalPolicy(show=True, dynamic=True)
STA = PED.PedalPolicy(show=True, static=True)
DT = 1 / 60


class Rig:
  def __init__(self, policy=DYN, plat="ap1"):
    self.b, self.t, self.policy, self.plat = PED.PedalBars(), 0.0, policy, plat

  def step(self, a=0.0, v=20.0, brake=False, pedal=0.0, op=0.0, long=False, fresh=True, standstill=False, lights=False,
           level=None, tq=None, opb=False):
    self.t += DT
    return self.b.update(self.policy, fresh, self.t, a, v, standstill, brake, lights, pedal, op, long, self.plat,
                         brake_level=level, motor_torque_nm=tq, op_brake_active=opb)

  def hold(self, n=30, **k):
    out = None
    for _ in range(n):
      out = self.step(**k)
    return out


def once(**k):
  return Rig(plat=k.pop("plat", "ap1")).hold(**k)


def tq_for(regen):
  """DI_torqueMotor (Nm) that gives this regen decel (m/s^2)."""
  return -regen * RA.MASS_KG * RA.WHEEL_RADIUS_M / RA.GEAR_RATIO


class TestAccelHeight(unittest.TestCase):
  def test_divisor_is_the_controlsd_clip(self):
    self.assertIs(PED.OP_ACCEL_FULL_SCALE, interfaces.ACCEL_MAX)
    self.assertEqual(PED.OP_ACCEL_FULL_SCALE, 2.0)
    self.assertEqual(PED.PREAP_SPEC_ACCEL_MAX, VDAS.ACCEL_MAX)     # 2.5 documented, not used as the divisor
    self.assertEqual(VDAS.ACCEL_MAX, 2.5)

  def test_op_clip_fills_the_bar_on_both_platforms(self):
    for plat in ("ap1", "preap"):
      self.assertEqual(once(op=2.0, long=True, plat=plat).accel, 1.0)
      self.assertEqual(once(op=1.0, long=True, plat=plat).accel, 0.5)

  def test_op_accel_ignored_without_long_active(self):
    self.assertEqual(once(op=2.0, long=False).accel, 0.0)

  def test_max_of_driver_and_op(self):
    self.assertEqual(once(pedal=0.4, op=0.4, long=True).accel, 0.4)
    self.assertEqual(once(pedal=0.1, op=1.4, long=True).accel, 0.7)
    self.assertEqual(PED.accel_fraction(0.3, -1.0), 0.3)

  def test_clamp_nan_missing(self):
    self.assertEqual(PED.accel_fraction(1.7, 9.0), 1.0)
    self.assertEqual(PED.accel_fraction(-0.2, -9.0), 0.0)
    self.assertEqual(PED.accel_fraction(float("nan"), None), 0.0)
    self.assertEqual(PED.accel_fraction(None, float("inf")), 0.0)
    self.assertEqual(once(a=float("nan"), pedal=float("nan")), PED.EMPTY)

  def test_stale_or_hidden_is_empty_and_resets(self):
    r = Rig()
    r.hold(brake=True, a=-2.0)
    self.assertEqual(r.step(a=-2.0, pedal=1.0, op=2.0, brake=True, fresh=False), PED.EMPTY)
    self.assertEqual(r.b.decel_src, PED.DECEL_HUMAN_REGEN)
    self.assertEqual(PED.PedalBars().update(PED.CLOSED, True, 0.0, -2.0, 20.0, False, True, False, 1.0, 2.0, True, "ap1"),
                     PED.EMPTY)


class TestPalette(unittest.TestCase):
  def test_palette_values(self):
    P = PED.PEDAL_BAR_PALETTE
    self.assertEqual(P[PED.ACCEL_HUMAN], (64, 206, 84))
    self.assertEqual(P[PED.DECEL_HUMAN_REGEN], (90, 205, 255))
    self.assertEqual(P[PED.DECEL_OP_REGEN], (122, 155, 191))
    self.assertEqual(P[PED.DECEL_HUMAN_BRAKE], (238, 48, 44))
    self.assertEqual(PED.PEDAL_BAR_OP_BRAKE_ROSE, "rose_mix")
    self.assertEqual(PED.bar_color(PED.DECEL_OP_BRAKE), (214, 110, 112))
    self.assertEqual(PED.PEDAL_BAR_OP_BRAKE_ROSES["dusty_rose"], (201, 169, 166))
    self.assertEqual(PED.FILL_A, 191)
    self.assertEqual(P[PED.DECEL_HUMAN_LIGHT], (176, 124, 255))           # #B07CFF
    self.assertEqual(P[PED.DECEL_OP_LIGHT], (154, 134, 184))              # #9A86B8
    colours = [PED.bar_color(s) for s in (PED.ACCEL_HUMAN, PED.ACCEL_OP, PED.DECEL_HUMAN_REGEN, PED.DECEL_OP_REGEN,
                                          PED.DECEL_HUMAN_BRAKE, PED.DECEL_OP_BRAKE, PED.DECEL_HUMAN_LIGHT,
                                          PED.DECEL_OP_LIGHT)]
    self.assertEqual(len(set(colours)), 8)

  def test_rose_flip_is_one_constant(self):
    try:
      PED.PEDAL_BAR_OP_BRAKE_ROSE = "dusty_rose"
      self.assertEqual(PED.bar_color(PED.DECEL_OP_BRAKE), (201, 169, 166))
    finally:
      PED.PEDAL_BAR_OP_BRAKE_ROSE = "rose_mix"


class TestSource(unittest.TestCase):
  def test_accel_sources(self):
    self.assertEqual(once(pedal=0.4).accel_src, PED.ACCEL_HUMAN)
    self.assertEqual(once(op=1.0, long=True).accel_src, PED.ACCEL_OP)
    self.assertEqual(once(op=1.0, long=True, pedal=0.1).accel_src, PED.ACCEL_HUMAN)   # driver wins
    self.assertEqual(once(op=1.0, long=False).accel_src, PED.ACCEL_HUMAN)
    self.assertEqual(once(op=-1.0, long=True).accel_src, PED.ACCEL_HUMAN)

  def test_decel_sources(self):
    cap = PED.ap1_regen_capacity(20.0)
    self.assertEqual(once(a=-0.5).decel_src, PED.DECEL_HUMAN_REGEN)                    # disengaged regen
    self.assertEqual(once(a=-0.5, op=-0.3, long=True).decel_src, PED.DECEL_OP_REGEN)
    self.assertEqual(once(a=-1.0, op=-1.3 * cap, long=True).decel_src, PED.DECEL_OP_REGEN)   # no iBooster command
    self.assertEqual(once(a=-3.0, op=-3.0 * cap, long=True).decel_src, PED.DECEL_OP_REGEN)
    self.assertEqual(once(a=-1.2 * cap, op=-1.3 * cap, long=True, opb=True).decel_src, PED.DECEL_OP_LIGHT)
    self.assertEqual(once(a=-3.0 * cap, op=-3.0 * cap, long=True, opb=True).decel_src, PED.DECEL_OP_BRAKE)
    for plat in ("preap", "other"):                                                   # AP1 only
      self.assertEqual(once(a=-1.0, op=-3.0 * cap, long=True, plat=plat).decel_src, PED.DECEL_OP_REGEN)
    for plat in ("ap1", "preap"):
      self.assertEqual(once(a=-1.0, op=-3.0 * cap, long=True, brake=True, plat=plat).decel_src, PED.DECEL_HUMAN_BRAKE)
      self.assertEqual(once(a=-1.0, brake=True, plat=plat).decel_src, PED.DECEL_HUMAN_BRAKE)   # no level: red

  def test_driver_input_shows_at_once_other_changes_wait(self):
    r = Rig()
    r.hold(op=1.0, long=True)
    self.assertEqual(r.step(op=1.0, long=True, pedal=0.3).accel_src, PED.ACCEL_HUMAN)  # immediate
    self.assertEqual(r.step(a=-1.0, brake=True).decel_src, PED.DECEL_HUMAN_BRAKE)       # immediate
    r2 = Rig()
    n_wait = 0
    while r2.step(op=1.0, long=True).accel_src != PED.ACCEL_OP:
      n_wait += 1
    self.assertAlmostEqual(n_wait * DT, PED.SOURCE_HOLD_S, delta=2 * DT)

  def test_no_flicker_on_alternating_inputs(self):
    for kw_on, kw_off, attr in (
        (dict(op=1.0, long=True), dict(op=0.0, long=True), "accel_src"),
        (dict(pedal=0.3), dict(pedal=0.0, op=1.0, long=True), "accel_src"),
        (dict(a=-1.0, brake=True), dict(a=-1.0), "decel_src"),
        (dict(a=-0.5, op=-0.3, long=True), dict(a=-0.5), "decel_src")):
      r = Rig()
      seen = []
      for i in range(120):
        seen.append(getattr(r.step(**(kw_on if i % 2 == 0 else kw_off)), attr))
      changes = sum(1 for x, y in zip(seen, seen[1:]) if x != y)
      self.assertLessEqual(changes, 1, (kw_on, kw_off, seen[:10]))

  def test_deadbands(self):
    r = Rig()
    r.hold(pedal=0.03)
    self.assertEqual(r.step(pedal=0.015, op=1.0, long=True).accel_src, PED.ACCEL_HUMAN)  # still above PEDAL_OFF
    self.assertTrue(r.b._pedal_on)
    r.step(pedal=0.005)
    self.assertFalse(r.b._pedal_on)
    r = Rig()
    r.hold(op=0.5, long=True)
    self.assertEqual(r.hold(op=0.07, long=True).accel_src, PED.ACCEL_OP)    # between OFF and ON: stays OP
    self.assertEqual(r.hold(op=0.02, long=True).accel_src, PED.ACCEL_HUMAN)


class TestDecelAp1(unittest.TestCase):
  """AP1: height = total decel on one continuous scale; colour = friction share against the UI-only regen table."""

  def a_for_share(self, share, v):
    return -PED.ap1_regen_capacity(v) / (1.0 - share)

  def test_constants_and_control_estimate_untouched(self):
    self.assertEqual((PED.AP1_BAR_REGEN_REF, PED.AP1_BAR_TOP), (2.0, 3.5))
    self.assertEqual(PED.AP1_BAR_TOP, -interfaces.ACCEL_MIN)
    self.assertEqual((PED.SHARE_VIOLET_BELOW, PED.SHARE_RED_ABOVE), (0.45, 0.55))
    self.assertEqual(len(PED.AP1_REGEN_V), len(PED.AP1_REGEN_A))
    self.assertEqual(list(PED.AP1_REGEN_V), sorted(PED.AP1_REGEN_V))
    self.assertTrue(all(0.0 < a <= RA.A_CAP_MAX for a in PED.AP1_REGEN_A))
    self.assertAlmostEqual(max(PED.AP1_REGEN_A), 1.54)                         # motor-torque regen saturates ~1.52
    # the control estimate (regen_aware, used by the planner) keeps its values
    self.assertAlmostEqual(RA.regen_capacity(20.0, RA.P_NOMINAL_KW), 30.0 * 1000 * 0.9 / (2100 * 20.0))
    self.assertEqual(RA.A_CAP_MAX, 1.6)

  def test_height_is_continuous_total_decel(self):
    for a, h in ((0.0, 0.0), (-1.0, 0.25), (-2.0, 0.5), (-2.75, 0.75), (-3.5, 1.0), (-9.0, 1.0), (1.0, 0.0)):
      self.assertAlmostEqual(once(a=a).decel, h, msg=a)
    hs = [PED.ap1_decel_height(-i / 1000) for i in range(0, 4001)]
    self.assertTrue(all(y >= x for x, y in zip(hs, hs[1:])))
    self.assertLess(max(y - x for x, y in zip(hs, hs[1:])), 0.001)               # no jump anywhere
    # a press does not change the height: same total decel, same bar
    for lvl in (0.0, 0.3, 1.0, -1.0):
      self.assertAlmostEqual(once(a=-1.0, brake=True, level=lvl).decel, 0.25)
      self.assertAlmostEqual(once(a=-1.0, brake=True, level=lvl, v=3.0).decel, 0.25)

  def test_owner_low_regen_case_reads_25_percent_violet(self):
    v, tq = 2.0, tq_for(0.8)                             # low speed, the motor gives 0.8 m/s^2 of regen
    b = once(a=-0.8, v=v, tq=tq)
    self.assertEqual((b.decel_src, round(b.decel, 3)), (PED.DECEL_HUMAN_REGEN, 0.2))   # regen alone ~20 %
    b = once(a=-1.0, v=v, tq=tq, brake=True, level=0.05)
    self.assertEqual((b.decel_src, round(b.decel, 3)), (PED.DECEL_HUMAN_LIGHT, 0.25))  # light press ~25 % violet

  def test_no_blending_live_regen_drives_the_share(self):
    self.assertAlmostEqual(PED.regen_live(tq_for(1.2)), 1.2)
    for bad in (None, float("nan"), "x", PED.MOTOR_TORQUE_SNA_NM):
      self.assertIsNone(PED.regen_live(bad))
    self.assertEqual(PED.regen_live(50.0), 0.0)                                  # driving torque: no regen
    self.assertAlmostEqual(PED.friction_share(2.0, 10.0, 1.2), 0.4)              # friction = decel - regen
    self.assertEqual(PED.friction_share(1.0, 10.0, 1.4), 0.0)                    # regen covers it: no friction
    self.assertEqual(PED.friction_share(1.0, 10.0, 0.0), 1.0)                    # motor not regenerating
    # human press, friction under the regen majority -> violet; friction majority -> red (same speed, same decel)
    self.assertEqual(once(a=-2.0, v=10.0, tq=tq_for(1.4), brake=True, level=0.2).decel_src, PED.DECEL_HUMAN_LIGHT)
    self.assertEqual(once(a=-2.0, v=10.0, tq=tq_for(0.6), brake=True, level=0.2).decel_src, PED.DECEL_HUMAN_BRAKE)
    # missing torque falls back to the measured table
    self.assertEqual(once(a=-1.2 * PED.ap1_regen_capacity(10.0), v=10.0, brake=True, level=0.2).decel_src,
                     PED.DECEL_HUMAN_LIGHT)
    # no press and no OP iBooster command: blue whatever the decel (friction is 0)
    for a in (-0.5, -2.5, -5.0):
      self.assertEqual(once(a=a, v=10.0, tq=tq_for(0.3)).decel_src, PED.DECEL_HUMAN_REGEN)

  def test_colour_follows_friction_share(self):
    for v in (5.0, 12.0, 25.0):
      self.assertEqual(once(a=self.a_for_share(0.2, v), v=v, brake=True, level=0.1).decel_src, PED.DECEL_HUMAN_LIGHT)
      self.assertEqual(once(a=self.a_for_share(0.7, v), v=v, brake=True, level=0.4).decel_src, PED.DECEL_HUMAN_BRAKE)
    self.assertEqual(once(a=0.0, v=10.0, brake=True, level=0.02).decel_src, PED.DECEL_HUMAN_LIGHT)  # no decel yet
    self.assertEqual(once(a=-0.2, v=0.0, brake=True, level=0.6, standstill=True).decel_src, PED.DECEL_HUMAN_BRAKE)
    self.assertEqual(PED.friction_share(1.0, 0.1), 1.0)                         # holding the car: friction

  def test_share_band_holds_and_does_not_flicker(self):
    v, lvl = 10.0, 0.2
    r = Rig()
    self.assertEqual(r.step(a=self.a_for_share(0.3, v), v=v, brake=True, level=lvl).decel_src, PED.DECEL_HUMAN_LIGHT)
    self.assertEqual(r.hold(a=self.a_for_share(0.5, v), v=v, brake=True, level=lvl).decel_src, PED.DECEL_HUMAN_LIGHT)
    self.assertEqual(r.step(a=self.a_for_share(0.6, v), v=v, brake=True, level=lvl).decel_src, PED.DECEL_HUMAN_LIGHT)
    self.assertEqual(r.hold(a=self.a_for_share(0.6, v), v=v, brake=True, level=lvl).decel_src, PED.DECEL_HUMAN_BRAKE)
    self.assertEqual(r.hold(a=self.a_for_share(0.5, v), v=v, brake=True, level=lvl).decel_src, PED.DECEL_HUMAN_BRAKE)
    self.assertEqual(r.hold(a=self.a_for_share(0.4, v), v=v, brake=True, level=lvl).decel_src, PED.DECEL_HUMAN_LIGHT)
    self.assertEqual(Rig().step(a=self.a_for_share(0.52, v), v=v, brake=True, level=lvl).decel_src,
                     PED.DECEL_HUMAN_BRAKE)                                     # a new press in the band: nearer side
    for lo, hi in ((0.4, 0.6), (0.3, 0.8), (0.46, 0.54)):
      r = Rig()
      seen = [r.step(a=self.a_for_share(lo if i % 2 else hi, v), v=v, brake=True, level=lvl).decel_src for i in range(120)]
      self.assertLessEqual(sum(1 for x, y in zip(seen, seen[1:]) if x != y), 1, (lo, hi))

  def test_stale_level_is_red_and_lag_without_press_is_blue(self):
    for lvl in (None, -1.0, float("nan")):
      b = once(a=-0.5, v=10.0, brake=True, level=lvl)
      self.assertEqual((b.decel_src, round(b.decel, 3)), (PED.DECEL_HUMAN_BRAKE, 0.125))
    for lvl in (0.05, 0.3, 1.0):                         # the rod lags brakePressed: a stroke alone changes nothing
      b = once(a=-1.0, v=10.0, level=lvl)
      self.assertEqual((b.decel_src, round(b.decel, 3)), (PED.DECEL_HUMAN_REGEN, 0.25))
      self.assertEqual(once(a=-1.0, op=-0.5, long=True, level=lvl).decel_src, PED.DECEL_OP_REGEN)

  def test_op_purples_only_with_an_ibooster_command(self):
    v, regen = 10.0, 1.4
    for op in (-1.5, -2.5, -3.5, -5.0):                  # past regen capacity alone never triggers it
      self.assertEqual(once(a=op, v=v, op=op, long=True, tq=tq_for(regen)).decel_src, PED.DECEL_OP_REGEN)
    self.assertEqual(once(a=-2.0, v=v, op=-2.0, long=True, tq=tq_for(regen), opb=True).decel_src, PED.DECEL_OP_LIGHT)
    self.assertEqual(once(a=-3.5, v=v, op=-3.5, long=True, tq=tq_for(regen), opb=True).decel_src, PED.DECEL_OP_BRAKE)
    self.assertEqual(once(a=-2.0, v=v, op=-2.0, long=False, tq=tq_for(regen), opb=True).decel_src, PED.DECEL_HUMAN_REGEN)
    for plat in ("preap", "other"):                      # AP1 only
      self.assertEqual(once(a=-3.5, v=v, op=-3.5, long=True, opb=True, plat=plat).decel_src, PED.DECEL_OP_REGEN)
    r = Rig()                                            # share band holds on the OP side too
    r.hold(a=-regen / 0.3, v=v, op=-3.0, long=True, tq=tq_for(regen), opb=True)
    self.assertEqual(r.hold(a=-regen / 0.5, v=v, op=-3.0, long=True, tq=tq_for(regen), opb=True).decel_src, PED.DECEL_OP_BRAKE)
    self.assertEqual(r.hold(a=-regen / 0.6, v=v, op=-3.0, long=True, tq=tq_for(regen), opb=True).decel_src, PED.DECEL_OP_LIGHT)
    self.assertAlmostEqual(once(a=-2.75, v=v, op=-3.0, long=True, opb=True).decel, 0.75)    # height = measured decel
    self.assertEqual(once(a=-2.0, v=v, op=-3.0, long=True, opb=True, brake=True).decel_src, PED.DECEL_HUMAN_BRAKE)

  def test_preap_layout_unchanged(self):
    self.assertAlmostEqual(once(a=-0.75, plat="preap").decel, 0.5 * 0.75 / abs(VDAS.REGEN_MAX))
    self.assertEqual(once(a=-5.0, plat="preap").decel, 0.5)
    b = once(a=-2.0, brake=True, level=0.0, plat="preap")
    self.assertEqual(b.decel_src, PED.DECEL_HUMAN_BRAKE)
    self.assertAlmostEqual(b.decel, 0.5 + 0.5 * (2.0 - 1.5) / (3.5 - 1.5))
    self.assertEqual(once(a=-2.5, op=-2.5, long=True, plat="preap").decel_src, PED.DECEL_OP_REGEN)
    self.assertEqual(PED.regen_scale(0.0, "ap1"), RA.A_GENTLE_FLOOR)

  def test_platform_of(self):
    self.assertEqual(PED.platform_of("TESLA_PREAP_MODELS"), "preap")
    self.assertEqual(PED.platform_of("TESLA_AP1_MODELS"), "ap1")
    self.assertEqual(PED.platform_of("TESLA_AP1_MODELX"), "ap1")
    self.assertEqual(PED.platform_of(None), "other")


class TestStatic(unittest.TestCase):
  def test_on_off_from_daily_rule(self):
    s = lambda **k: Rig(policy=STA).hold(**k)  # noqa: E731
    self.assertEqual((s().decel, s().accel), (0.0, 0.0))
    self.assertEqual(s(a=-0.3).decel, 1.0)
    self.assertEqual(s(standstill=True).decel, 1.0)
    self.assertEqual(s(lights=True).decel, 1.0)
    self.assertEqual(s(a=-0.3, brake=True).decel_src, PED.DECEL_HUMAN_BRAKE)
    self.assertEqual(s(a=0.3).accel, 1.0)
    self.assertEqual(s(pedal=0.6).accel, 0.0)          # Static follows aEgo only, as before


class TestGeometry(unittest.TestCase):
  def test_rhd_mirrors_and_keeps_order(self):
    (dl, al), (dr, ar) = PED.bar_boxes(2160, False), PED.bar_boxes(2160, True)
    self.assertEqual(dl[0], 30)
    self.assertLess(dl[0], al[0])
    self.assertLess(dr[0], ar[0])
    self.assertEqual(ar[0] + ar[2], 2160 - PED.EDGE)
    self.assertEqual(dl[1:], dr[1:])

  def test_fill_polygon_cut_flat_at_level(self):
    inner = (100.0, 200.0, 40.0, 100.0)
    r = PED.corner_radius(40.0, 100.0)
    self.assertEqual(PED.fill_polygon(inner, 0.0), [])
    for frac in (0.03, 0.25, 0.5, 0.97, 1.0):
      pts = PED.fill_polygon(inner, frac)
      top = PED.fill_top(200.0, 100.0, frac)
      self.assertAlmostEqual(min(p[1] for p in pts), top, places=6)
      self.assertTrue(all(100.0 - 1e-9 <= x <= 140.0 + 1e-9 and top - 1e-9 <= y <= 300.0 + 1e-9 for x, y in pts))
      if r <= frac * 100.0 <= 100.0 - r:
        xs = [x for x, y in pts if abs(y - top) < 1e-6]
        self.assertTrue(math.isclose(max(xs) - min(xs), 40.0))


class TestOpBrakeState(unittest.TestCase):
  """OP lavender / rose key off bogpilotCarState.ap1BrakePedalState (DI_brakePedalState): longActive AND ON AND no
  driver press. OFF / INVALID / SNA / stale (None) / junk -> OP dusty blue. Share logic, hysteresis and hold unchanged."""

  def run_bars(self, n=30, plat="ap1", state=None, a=-2.0, v=10.0, op=-2.0, long=True, brake=False, tq=None, level=0.3):
    b, t, out = PED.PedalBars(), 0.0, None
    for _ in range(n):
      t += DT
      out = b.update(DYN, True, t, a, v, False, brake, False, 0.0, op, long, plat, brake_level=level, motor_torque_nm=tq,
                     brake_pedal_state=state)
    return out

  def test_helper_gating(self):
    f = PED.op_ibooster_applied
    self.assertTrue(f(1, True, False))
    for args in ((1, False, False), (1, True, True), (0, True, False), (2, True, False), (3, True, False), (None, True, False),
                 ("x", True, False), (float("nan"), True, False), (1.5, True, False)):
      self.assertFalse(f(*args), args)

  def test_on_shows_op_purples_by_share(self):
    regen = 1.5
    self.assertEqual(self.run_bars(state=1, a=-2.0, tq=tq_for(regen)).decel_src, PED.DECEL_OP_LIGHT)   # share .25
    self.assertEqual(self.run_bars(state=1, a=-3.5, tq=tq_for(regen)).decel_src, PED.DECEL_OP_BRAKE)   # share .57

  def test_off_invalid_sna_stale_stay_blue(self):
    for st in (0, 2, 3, None):
      self.assertEqual(self.run_bars(state=st, a=-3.5, tq=tq_for(1.0)).decel_src, PED.DECEL_OP_REGEN, st)

  def test_not_long_active_is_not_op(self):
    self.assertEqual(self.run_bars(state=1, long=False, op=0.0, a=-3.5, tq=tq_for(1.0)).decel_src, PED.DECEL_HUMAN_REGEN)

  def test_driver_press_wins(self):
    out = self.run_bars(state=1, brake=True, a=-3.5, tq=tq_for(1.0))
    self.assertIn(out.decel_src, (PED.DECEL_HUMAN_LIGHT, PED.DECEL_HUMAN_BRAKE))
    self.assertEqual(out.decel_src, PED.DECEL_HUMAN_BRAKE)

  def test_state_drop_returns_to_blue_after_the_hold(self):
    b, t = PED.PedalBars(), 0.0
    def step(st, n):
      nonlocal t
      out = None
      for _ in range(n):
        t += DT
        out = b.update(DYN, True, t, -3.5, 10.0, False, False, False, 0.0, -3.5, True, "ap1", brake_level=0.3,
                       motor_torque_nm=tq_for(1.0), brake_pedal_state=st)
      return out
    self.assertEqual(step(1, 30).decel_src, PED.DECEL_OP_BRAKE)
    self.assertEqual(step(None, 5).decel_src, PED.DECEL_OP_BRAKE)                 # 0.08 s < SOURCE_HOLD_S: holds
    self.assertEqual(step(None, 30).decel_src, PED.DECEL_OP_REGEN)

  def test_preap_ignores_the_state(self):
    self.assertEqual(self.run_bars(plat="preap", state=1, a=-3.5).decel_src, PED.DECEL_OP_REGEN)


if __name__ == "__main__":
  unittest.main()
