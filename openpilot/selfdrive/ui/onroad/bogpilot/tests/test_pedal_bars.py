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
           level=None):
    self.t += DT
    return self.b.update(self.policy, fresh, self.t, a, v, standstill, brake, lights, pedal, op, long, self.plat,
                         brake_level=level)

  def hold(self, n=30, **k):
    out = None
    for _ in range(n):
      out = self.step(**k)
    return out


def once(**k):
  return Rig(plat=k.pop("plat", "ap1")).hold(**k)


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
    cap = RA.regen_capacity(20.0, RA.P_NOMINAL_KW)
    self.assertEqual(once(a=-0.5).decel_src, PED.DECEL_HUMAN_REGEN)                    # disengaged regen
    self.assertEqual(once(a=-0.5, op=-0.3, long=True).decel_src, PED.DECEL_OP_REGEN)
    self.assertEqual(once(a=-1.0, op=-(cap + 0.15), long=True).decel_src, PED.DECEL_OP_LIGHT)   # first 10 % above cap
    self.assertEqual(once(a=-1.0, op=-(cap + 0.6), long=True).decel_src, PED.DECEL_OP_BRAKE)
    self.assertEqual(once(a=-1.0, op=-(cap + 0.3), long=True, plat="preap").decel_src, PED.DECEL_OP_REGEN)  # AP1 only
    self.assertEqual(once(a=-1.0, op=-(cap + 0.3), long=True, plat="other").decel_src, PED.DECEL_OP_REGEN)
    for plat in ("ap1", "preap"):
      self.assertEqual(once(a=-1.0, op=-(cap + 0.3), long=True, brake=True, plat=plat).decel_src, PED.DECEL_HUMAN_BRAKE)
      self.assertEqual(once(a=-1.0, brake=True, plat=plat).decel_src, PED.DECEL_HUMAN_BRAKE)

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


class TestDecelLayout(unittest.TestCase):
  V = 20.0

  def cap(self, plat="ap1"):
    return PED.regen_scale(self.V, plat)

  def test_constants(self):
    self.assertEqual(PED.DECEL_FULL_SCALE, -interfaces.ACCEL_MIN)
    self.assertEqual((PED.REGEN_HALF, PED.OP_LIGHT_BAND), (0.5, 0.10))
    self.assertEqual((PED.HUMAN_LIGHT_MAX, PED.HUMAN_RED_MIN), (0.08, 0.12))
    self.assertFalse(hasattr(PED, "PEDAL_BAR_DECEL_SCALE_MODE"))          # scale modes replaced by the layout

  def test_regen_is_the_bottom_half_and_clamps(self):
    cap = self.cap()
    self.assertAlmostEqual(once(a=-cap / 2).decel, 0.25)
    self.assertAlmostEqual(once(a=-cap).decel, 0.5)
    self.assertEqual(once(a=-5.0).decel, 0.5)                              # (b) regen past capacity, no pedal: 50 %
    self.assertEqual(once(a=-5.0).decel_src, PED.DECEL_HUMAN_REGEN)
    self.assertAlmostEqual(once(a=-cap / 2, op=-0.3, long=True).decel, 0.25)
    self.assertAlmostEqual(once(a=-0.75, plat="preap").decel, 0.5 * 0.75 / abs(VDAS.REGEN_MAX))
    self.assertEqual(PED.regen_scale(0.0, "ap1"), RA.A_GENTLE_FLOOR)
    self.assertEqual(once(a=1.0).decel, 0.0)

  def test_driver_brake_climbs_the_top_half_and_pegs(self):
    for lvl, fill in ((0.20, 0.60), (0.5, 0.75), (0.97, 0.985), (1.0, 1.0), (7.0, 1.0)):
      b = once(a=-2.0, brake=True, level=lvl)
      self.assertAlmostEqual(b.decel, fill, msg=lvl)
      self.assertEqual(b.decel_src, PED.DECEL_HUMAN_BRAKE)

  def test_pressed_at_rest_is_light_purple_at_the_regen_part(self):   # (a)
    cap = self.cap()
    b = once(a=-cap / 2, brake=True, level=0.0)
    self.assertEqual(b.decel_src, PED.DECEL_HUMAN_LIGHT)
    self.assertAlmostEqual(b.decel, 0.25)
    b = once(a=-cap / 2, brake=True, level=0.03)
    self.assertEqual(b.decel_src, PED.DECEL_HUMAN_LIGHT)
    self.assertAlmostEqual(b.decel, 0.515)

  def test_light_purple_needs_regen_doing_most(self):
    cap = self.cap()
    self.assertEqual(once(a=-1.9 * cap, brake=True, level=0.03).decel_src, PED.DECEL_HUMAN_LIGHT)
    self.assertEqual(once(a=-2.1 * cap, brake=True, level=0.03).decel_src, PED.DECEL_HUMAN_BRAKE)

  def test_dead_band_holds_between_and_does_not_flicker(self):
    r = Rig()
    self.assertEqual(r.step(a=-1.0, brake=True, level=0.05).decel_src, PED.DECEL_HUMAN_LIGHT)   # new press: at once
    self.assertEqual(r.hold(a=-1.0, brake=True, level=0.10).decel_src, PED.DECEL_HUMAN_LIGHT)   # band holds
    self.assertEqual(r.step(a=-1.0, brake=True, level=0.13).decel_src, PED.DECEL_HUMAN_LIGHT)   # waits the hold
    self.assertEqual(r.hold(a=-1.0, brake=True, level=0.13).decel_src, PED.DECEL_HUMAN_BRAKE)
    self.assertEqual(r.hold(a=-1.0, brake=True, level=0.10).decel_src, PED.DECEL_HUMAN_BRAKE)   # band holds red
    self.assertEqual(r.hold(a=-1.0, brake=True, level=0.07).decel_src, PED.DECEL_HUMAN_LIGHT)
    r = Rig()
    self.assertEqual(r.step(a=-1.0, brake=True, level=0.10).decel_src, PED.DECEL_HUMAN_LIGHT)   # starts light in band
    for lo, hi in ((0.07, 0.13), (0.05, 0.20), (0.09, 0.11)):
      r = Rig()
      seen = [r.step(a=-1.0, brake=True, level=(lo if i % 2 else hi)).decel_src for i in range(120)]
      self.assertLessEqual(sum(1 for x, y in zip(seen, seen[1:]) if x != y), 1, (lo, hi))

  def test_stroke_without_brake_pressed_changes_nothing(self):
    # the rod lags brakePressed: a nonzero level alone never turns the bar purple or red
    cap = self.cap()
    for lvl in (0.05, 0.3, 1.0):
      b = once(a=-cap / 2, level=lvl)
      self.assertEqual((b.decel_src, round(b.decel, 6)), (PED.DECEL_HUMAN_REGEN, 0.25))
      b = once(a=-cap / 2, op=-0.5, long=True, level=lvl)
      self.assertEqual(b.decel_src, PED.DECEL_OP_REGEN)

  def test_missing_or_stale_level_falls_back_to_red_from_half(self):
    cap = self.cap()
    for lvl in (None, -1.0, float("nan"), "x"):
      b = once(a=-0.9 * cap, brake=True, level=lvl)
      self.assertEqual((b.decel_src, b.decel), (PED.DECEL_HUMAN_BRAKE, 0.5), lvl)
    self.assertAlmostEqual(once(a=-(cap + 3.5) / 2, brake=True, level=-1.0).decel, 0.75)
    self.assertEqual(once(a=-9.0, brake=True, level=-1.0).decel, 1.0)
    # Pre-AP has no level: the same fallback, whatever deprecated.brake holds
    b = once(a=-2.0, brake=True, level=0.0, plat="preap")
    self.assertEqual(b.decel_src, PED.DECEL_HUMAN_BRAKE)
    self.assertAlmostEqual(b.decel, 0.5 + 0.5 * (2.0 - 1.5) / (3.5 - 1.5))

  def test_op_light_band_then_rose_with_margin(self):
    cap = self.cap()
    edge = cap + PED.OP_LIGHT_BAND * (3.5 - cap)
    self.assertEqual(once(a=-cap, op=-(cap + 0.03), long=True).decel_src, PED.DECEL_OP_REGEN)   # inside the margin
    self.assertEqual(once(a=-cap, op=-(cap + 0.06), long=True).decel_src, PED.DECEL_OP_LIGHT)
    self.assertEqual(once(a=-cap, op=-(edge + 0.03), long=True).decel_src, PED.DECEL_OP_LIGHT)  # margin above the edge
    self.assertEqual(once(a=-cap, op=-(edge + 0.06), long=True).decel_src, PED.DECEL_OP_BRAKE)
    r = Rig()
    r.hold(a=-2.5, op=-(edge + 0.3), long=True)
    self.assertEqual(r.hold(op=-(edge - 0.03), long=True, a=-2.5).decel_src, PED.DECEL_OP_BRAKE)  # rose holds
    self.assertEqual(r.hold(op=-(edge - 0.06), long=True, a=-2.5).decel_src, PED.DECEL_OP_LIGHT)
    self.assertEqual(r.hold(op=-(cap - 0.03), long=True, a=-2.5).decel_src, PED.DECEL_OP_LIGHT)   # top band holds
    self.assertEqual(r.hold(op=-(cap - 0.06), long=True, a=-2.5).decel_src, PED.DECEL_OP_REGEN)
    seen = []
    r = Rig()
    for i in range(120):
      seen.append(r.step(a=-2.0, op=-(edge + (0.04 if i % 2 else -0.04)), long=True).decel_src)
    self.assertLessEqual(sum(1 for x, y in zip(seen, seen[1:]) if x != y), 2)
    self.assertEqual(once(a=-2.5, op=-2.5, long=True, plat="preap").decel_src, PED.DECEL_OP_REGEN)   # AP1 only

  def test_op_top_half_follows_measured_decel(self):
    cap = self.cap()
    self.assertAlmostEqual(once(a=-(cap + 3.5) / 2, op=-2.6, long=True).decel, 0.75)
    self.assertAlmostEqual(once(a=-3.5, op=-3.5, long=True).decel, 1.0)
    self.assertAlmostEqual(once(a=-cap * 0.9, op=-2.6, long=True).decel, 0.5)    # measured below capacity: half

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


if __name__ == "__main__":
  unittest.main()
