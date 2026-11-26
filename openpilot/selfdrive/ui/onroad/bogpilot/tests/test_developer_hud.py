"""Developer HUD: cells, thresholds, inputs, placement, gate and hook (headless, no window)."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import load

DEV = load("developer_hud_logic")
ROOT = Path(__file__).resolve().parents[1]
MPH, KPH = 2.23694, 3.6


def by_label(cells):
  return {c.label: c for c in cells}


def hud(**kw):
  return DEV.HudInputs(**kw)


class FakeSM:
  def __init__(self, started_frame=5, **msgs):
    self.data = dict(msgs)
    self.recv_frame = {k: started_frame for k in msgs}
    self.alive = {k: True for k in msgs}
    self.valid = {k: True for k in msgs}

  def __getitem__(self, k):
    return self.data[k]


class Lateral:
  def __init__(self, which, desired=12.5):
    self._which = which
    self.angleState = SimpleNamespace(steeringAngleDesiredDeg=desired)
    self.pidState = SimpleNamespace(steeringAngleDesiredDeg=desired)
    self.torqueState = SimpleNamespace()

  def which(self):
    return self._which


def messages(**over):
  m = dict(
    carState=SimpleNamespace(aEgo=0.5, vEgo=20.0, steeringAngleDeg=-3.0, steeringPressed=False),
    carControl=SimpleNamespace(latActive=True),
    radarState=SimpleNamespace(leadOne=SimpleNamespace(present=True, dRel=30.0, vRel=-2.0)),
    controlsState=SimpleNamespace(desiredCurvature=0.001, curvature=0.0008, lateralControlState=Lateral("angleState")),
    vehicleParameters=SimpleNamespace(roll=0.01),
    gpsLocationExternal=SimpleNamespace(hasFix=True, altitude=100.0),
    deviceState=SimpleNamespace(memoryUsagePercent=42),
  )
  m.update(over)
  return m


class TestCells(unittest.TestCase):
  def test_ten_cells_in_the_097_order(self):
    labels = [c.label for c in DEV.cells(hud())]
    self.assertEqual(labels, ["ACCEL", "REL DIST", "LEAD SPD", "REL SPEED", "LAT ACCEL", "REAL STEER", "DESIRED STEER",
                              "ACTUAL LAT", "ALTITUDE", "MEM %"])

  def test_formulas_imperial(self):
    i = hud(is_metric=False, a_ego=-1.234, v_ego=20.0, lead_present=True, lead_d_rel=30.0, lead_v_rel=-2.0, lat_active=True,
            desired_curvature=0.001, curvature=0.0008, roll=0.01, steering_angle_deg=-3.04, steer_angle_desired=12.55,
            gps_valid=True, altitude=100.0, memory_usage_percent=42)
    c = by_label(DEV.cells(i))
    self.assertEqual(c["ACCEL"].value, "-1.2")
    self.assertEqual(c["REL DIST"].value, str(round(30.0 * 3.28084)))
    self.assertEqual((c["REL DIST"].unit, c["LEAD SPD"].unit), ("ft", "mph"))
    self.assertEqual(c["LEAD SPD"].value, f"{(20.0 - 2.0) * MPH:.0f}")
    self.assertEqual(c["REL SPEED"].value, f"{-2.0 * MPH:.0f}")
    self.assertEqual(c["LAT ACCEL"].value, f"{0.001 * 400 - 0.01 * 9.81:.2f}")
    self.assertEqual(c["ACTUAL LAT"].value, f"{0.0008 * 400 - 0.01 * 9.81:.2f}")
    self.assertEqual(c["REAL STEER"].value, "-3.0\u00b0")
    self.assertEqual(c["DESIRED STEER"].value, "12.6\u00b0")   # nearest, as the 0.9.7 panel formatted it
    self.assertEqual(c["ALTITUDE"].value, "328")
    self.assertEqual(c["MEM %"].value, "42%")

  def test_metric_units(self):
    i = hud(is_metric=True, v_ego=20.0, lead_present=True, lead_d_rel=30.4, lead_v_rel=-2.0, gps_valid=True, altitude=100.04)
    c = by_label(DEV.cells(i))
    self.assertEqual((c["REL DIST"].value, c["REL DIST"].unit), ("30", "m"))
    self.assertEqual((c["LEAD SPD"].value, c["LEAD SPD"].unit), (f"{18 * KPH:.0f}", "km/h"))
    self.assertEqual((c["ALTITUDE"].value, c["ALTITUDE"].unit), ("100.0", "m"))

  def test_no_source_shows_a_dash_never_a_zero(self):
    c = by_label(DEV.cells(hud()))
    for label in ("REL DIST", "LEAD SPD", "REL SPEED", "LAT ACCEL", "DESIRED STEER", "ALTITUDE", "MEM %"):
      self.assertEqual(c[label].value, "-", label)

  def test_lead_colors(self):
    def dist(d):
      return by_label(DEV.cells(hud(lead_present=True, lead_d_rel=d)))["REL DIST"].color
    self.assertEqual((dist(4.9), dist(14.9), dist(15.0)), (DEV.RED, DEV.ORANGE, DEV.WHITE))

    def spd(v):
      return by_label(DEV.cells(hud(lead_present=True, lead_v_rel=v)))["LEAD SPD"].color
    self.assertEqual((spd(-4.5), spd(-1.0), spd(0.5)), (DEV.RED, DEV.ORANGE, DEV.WHITE))

  def test_steering_colors(self):
    def col(**kw):
      return by_label(DEV.cells(hud(**kw)))
    self.assertEqual(col(lat_active=True)["REAL STEER"].color, DEV.GREEN)
    self.assertEqual(col(lat_active=True, steering_pressed=True)["REAL STEER"].color, DEV.OVERRIDE_GREY)
    self.assertEqual(col()["REAL STEER"].color, DEV.WHITE)
    self.assertEqual(col(lat_active=True, steering_angle_deg=91)["REAL STEER"].color, DEV.ORANGE)
    self.assertEqual(col(lat_active=True, steering_angle_deg=-181)["REAL STEER"].color, DEV.RED)
    self.assertEqual(col(lat_active=True, steer_angle_desired=95.0)["DESIRED STEER"].color, DEV.ORANGE)

  def test_memory_warning_over_85(self):
    self.assertEqual(by_label(DEV.cells(hud(memory_usage_percent=85)))["MEM %"].color, DEV.WHITE)
    self.assertEqual(by_label(DEV.cells(hud(memory_usage_percent=86)))["MEM %"].color, DEV.ORANGE)

  def test_torque_car_shows_friction_instead_of_desired_steer(self):
    c = DEV.cells(hud(torque_control=True, friction=0.1234))
    self.assertEqual(c[6].label, "FRICTION")
    self.assertEqual(c[6].value, "0.123")

  def test_negative_zero_is_not_shown(self):
    self.assertEqual(DEV.num(-0.001, 2), "0.00")
    self.assertEqual(DEV.num(-0.04, 1), "0.0")
    self.assertEqual(DEV.num(float("nan"), 1), "-")

  def test_redesign_labels_and_unit_slot(self):
    shown = {c.label: c for c in map(DEV.display_cell, DEV.cells(hud(memory_usage_percent=40, steering_angle_deg=1.0)))}
    self.assertIn("DES STEER", shown)
    self.assertEqual((shown["MEM"].value, shown["MEM"].unit), ("40", "%"))
    self.assertEqual((shown["REAL STEER"].value, shown["REAL STEER"].unit), ("1.0", "\u00b0"))


class TestInputs(unittest.TestCase):
  def build(self, sm, cp=None, metric=False):
    return DEV.inputs_from_messages(sm, 5, metric, cp)

  def test_reads_each_source(self):
    i = self.build(FakeSM(**messages()))
    self.assertTrue(i.lat_active and i.lead_present and i.gps_valid)
    self.assertEqual((i.a_ego, i.v_ego, i.steering_angle_deg), (0.5, 20.0, -3.0))
    self.assertEqual((i.lead_d_rel, i.lead_v_rel, i.roll, i.altitude, i.memory_usage_percent), (30.0, -2.0, 0.01, 100.0, 42))
    self.assertEqual(i.steer_angle_desired, 12.5)
    self.assertFalse(i.torque_control)

  def test_stale_car_state_hides_the_panel(self):
    sm = FakeSM(**messages())
    sm.recv_frame["carState"] = 4   # before this drive started
    self.assertIsNone(self.build(sm))
    sm = FakeSM(**messages())
    sm.alive["carState"] = False
    self.assertIsNone(self.build(sm))
    sm = FakeSM(**messages())
    sm.valid["carState"] = False
    self.assertIsNone(self.build(sm))

  def test_each_optional_source_degrades_on_its_own(self):
    for name, label in (("radarState", "REL DIST"), ("gpsLocationExternal", "ALTITUDE"), ("deviceState", "MEM %"),
                        ("controlsState", "DESIRED STEER"), ("carControl", "LAT ACCEL")):
      sm = FakeSM(**messages())
      sm.alive[name] = False
      cells = by_label(DEV.cells(self.build(sm)))
      self.assertEqual(cells[label].value, "-", name)
      self.assertEqual(cells["ACCEL"].value, "0.5")

  def test_no_gps_fix_and_no_lead(self):
    m = messages(gpsLocationExternal=SimpleNamespace(hasFix=False, altitude=5.0),
                 radarState=SimpleNamespace(leadOne=SimpleNamespace(present=False, dRel=9.0, vRel=-9.0)))
    c = by_label(DEV.cells(self.build(FakeSM(**m))))
    self.assertEqual((c["ALTITUDE"].value, c["REL DIST"].value, c["LEAD SPD"].value), ("-", "-", "-"))

  def test_non_finite_values_never_reach_the_panel(self):
    m = messages(carState=SimpleNamespace(aEgo=float("nan"), vEgo=float("inf"), steeringAngleDeg=float("nan"), steeringPressed=False))
    i = self.build(FakeSM(**m))
    self.assertEqual((i.a_ego, i.v_ego, i.steering_angle_deg), (0.0, 0.0, 0.0))

  def test_lateral_state_without_a_desired_angle(self):
    m = messages(controlsState=SimpleNamespace(desiredCurvature=0.0, curvature=0.0, lateralControlState=Lateral("torqueState")))
    self.assertIsNone(self.build(FakeSM(**m)).steer_angle_desired)
    m = messages(controlsState=SimpleNamespace(desiredCurvature=0.0, curvature=0.0, lateralControlState=Lateral("pidState", 4.0)))
    self.assertEqual(self.build(FakeSM(**m)).steer_angle_desired, 4.0)

  def test_torque_car_params(self):
    cp = SimpleNamespace(steerControlType="torque", lateralTuning=SimpleNamespace(which=lambda: "torque",
                                                                                   torque=SimpleNamespace(friction=0.09)))
    i = self.build(FakeSM(**messages()), cp)
    self.assertTrue(i.torque_control)
    self.assertEqual(i.friction, 0.09)
    cp = SimpleNamespace(steerControlType="angle", lateralTuning=SimpleNamespace(which=lambda: "torque"))
    self.assertFalse(self.build(FakeSM(**messages()), cp).torque_control)


class TestPlacement(unittest.TestCase):
  def test_top_right_full_size_on_the_daily_view(self):
    x, y, w, h = DEV.panel_rect(2100, 1020, 30, 30)
    self.assertEqual((w, h), (400, 430))
    self.assertEqual(x + w, 2100 - 30)
    self.assertEqual(y, 30)

  def test_scales_down_to_fit_and_never_below_half(self):
    _, _, w, h = DEV.panel_rect(2100, 400, 30, 30)
    self.assertAlmostEqual(h / w, 430 / 400)
    self.assertLess(w, 400)
    self.assertEqual(DEV.panel_rect(2100, 100, 30, 30)[2], 200)
    self.assertEqual(DEV.panel_rect(800, 1000, 30, 30)[2], 200)

  def test_matches_the_reserved_design_size(self):
    src = (ROOT / "style.py").read_text()
    self.assertIn("HUD_W = 400", src)
    self.assertIn("HUD_H = 430", src)
    self.assertEqual((DEV.HUD_W, DEV.HUD_H), (400, 430))


class FakeStore:
  def __init__(self, on=True, level=3, fail=False):
    self.on, self.level, self.fail, self.reads = on, level, fail, 0

  def tuning_level(self):
    return self.level

  def toggle_bool(self, key, level=None):
    self.reads += 1
    if self.fail:
      raise OSError("store unreadable")
    assert key == "DeveloperHUD"
    return self.on and (level or 0) >= 3


class TestPolicy(unittest.TestCase):
  def test_off_by_default_and_gated_by_tuning_level(self):
    self.assertFalse(DEV.DeveloperHudPolicy(FakeStore(on=False)).get())
    self.assertTrue(DEV.DeveloperHudPolicy(FakeStore(on=True, level=3)).get())
    self.assertFalse(DEV.DeveloperHudPolicy(FakeStore(on=True, level=1)).get())

  def test_read_failure_is_off_and_reads_are_cached(self):
    self.assertFalse(DEV.DeveloperHudPolicy(FakeStore(fail=True)).get())
    now = [0.0]
    store = FakeStore()
    policy = DEV.DeveloperHudPolicy(store, clock=lambda: now[0])
    for _ in range(5):
      policy.get()
    self.assertEqual(store.reads, 1)
    now[0] = 2.5
    policy.get()
    self.assertEqual(store.reads, 2)

  def test_real_store_reads_the_file_toggle(self):
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
      os.environ["BOGPILOT_PARAMS_DIR"] = folder
      try:
        from openpilot.common.bogpilot_store import ParamStore
        store = ParamStore(params=SimpleNamespace(all_keys=lambda: [], get=lambda k: None, get_bool=lambda k: None))
        self.assertFalse(DEV.DeveloperHudPolicy(store).get())
        (Path(folder) / "DeveloperHUD").write_text("1\n")
        self.assertTrue(DEV.DeveloperHudPolicy(store).get())
        (Path(folder) / "DeveloperHUD").write_text("0\n")
        self.assertFalse(DEV.DeveloperHudPolicy(store).get())
      finally:
        os.environ.pop("BOGPILOT_PARAMS_DIR", None)


class TestHookAndSafety(unittest.TestCase):
  def test_display_only_no_writes_anywhere(self):
    for name in ("developer_hud_logic.py", "developer_hud.py"):
      src = (ROOT / name).read_text()
      for needle in (".put(", "put_bool", "write_text", "open(", "os.remove", "send("):
        self.assertNotIn(needle, src, f"{name}: {needle}")

  def test_hud_renderer_hooks_the_panel_and_isolates_failures(self):
    src = (ROOT / "bogpilot_hud.py").read_text()
    self.assertIn("developer_hud_logic as DEV", src)
    self.assertIn("self._bp_update_developer()", src)
    self.assertIn("self._bp_render_developer(rect,", src)
    update = src[src.index("def _bp_update_developer"):src.index("def _bp_update_features")]
    self.assertIn("except Exception", update)
    render = src[src.index("def _bp_render_developer"):src.index("def _bp_render_extras")]
    self.assertIn("except Exception", render)
    self.assertIn("bp_extra_keepouts.append", render)   # lead labels keep clear of the panel

  def test_inert_key_is_now_consumed_and_has_a_row(self):
    from openpilot.common import bogpilot_toggles as t
    self.assertIn("DeveloperHUD", t.FILE_ONLY_UI_KEYS)
    self.assertFalse(t.FILE_TOGGLES["DeveloperHUD"][0])   # default off
    self.assertIn('"DeveloperHUD"', (ROOT.parents[1] / "layouts/settings/bogpilot_visuals.py").read_text())


@unittest.skipUnless(importlib.util.find_spec("pyray") is not None, "pyray not installed")
class TestPaint(unittest.TestCase):
  def test_paint_draws_all_ten_cells_through_the_style_helpers(self):
    from openpilot.selfdrive.ui.onroad.bogpilot import developer_hud as P
    calls = []
    rl = P.rl
    saved = {n: getattr(P, n) for n in ("panel", "line", "draw_text", "text_width", "cap_height")}
    saved_rl = {n: getattr(rl, n) for n in ("rl_push_matrix", "rl_pop_matrix", "rl_translatef", "rl_scalef")}
    try:
      P.panel = lambda *a, **k: calls.append(("panel", a[0].width, a[0].height))
      P.line = lambda *a, **k: calls.append(("line",))
      P.draw_text = lambda text, x, base, size, color, weight=None: calls.append(("text", text, size)) or 10.0
      P.text_width = lambda text, size, weight=None: 10.0 * len(text)
      P.cap_height = lambda size: size * 0.7
      rl.rl_push_matrix = lambda: calls.append(("push",))
      rl.rl_pop_matrix = lambda: calls.append(("pop",))
      rl.rl_translatef = lambda *a: calls.append(("translate",) + a)
      rl.rl_scalef = lambda *a: calls.append(("scale",) + a)
      P.paint(DEV.cells(hud(memory_usage_percent=40, lead_present=True)), (1700.0, 30.0, 200.0, 215.0))
    finally:
      for n, v in saved.items():
        setattr(P, n, v)
      for n, v in saved_rl.items():
        setattr(rl, n, v)
    self.assertEqual(calls[0], ("push",))
    self.assertEqual(calls[-1], ("pop",))
    self.assertIn(("scale", 0.5, 0.5, 1), calls)
    self.assertIn(("panel", 400, 430), calls)
    labels = [c[1] for c in calls if c[0] == "text" and c[1].isupper() and c[1] not in ("MPH", "FT")]
    self.assertEqual(len([c for c in labels if c in ("ACCEL", "REL DIST", "LEAD SPD", "REL SPEED", "LAT ACCEL", "REAL STEER",
                                                      "DES STEER", "ACTUAL LAT", "ALTITUDE", "MEM")]), 10)


if __name__ == "__main__":
  unittest.main()
