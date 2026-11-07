"""CSC MAX slot display contract: CurveSpeedController + ShowCSCStatus gate and the plannerd frogpilotPlan report."""
import time
import unittest
from types import SimpleNamespace

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import adapter_namespace, load

L = load("cluster_layout")


class Store:
  def __init__(self, **vals):
    self.vals = vals
    self.reads = 0

  def toggle_bool(self, key):
    self.reads += 1
    if key not in self.vals:
      raise KeyError(key)
    return self.vals[key]


def hud_env():
  return adapter_namespace("bogpilot_hud", {
    "HudRenderer": object, "MiciHudRenderer": object, "COLORS": SimpleNamespace(ENGAGED=1, DISENGAGED=0),
    "UIStatus": SimpleNamespace(ENGAGED=1), "ui_state": SimpleNamespace(is_metric=False, status=1),
    "R": SimpleNamespace(SpeedRowInputs=lambda **kw: kw), "toggles": SimpleNamespace(get=lambda k: True),
    "L": L, "time": time, "AccelGraph": None, "messaging": None, "SERVICE_LIST": {},
  })


def plan(**kw):
  base = {"cscTraining": False, "cscControllingSpeed": True, "cscSpeed": 12.0, "roadCurvature": 0.02,
          "slcOverriddenSpeed": 0.0, "slcSpeedLimit": 0.0, "slcSpeedLimitOffset": 0.0, "speedLimitChanged": False}
  base.update(kw)
  return SimpleNamespace(**base)


class TestCscStatusToggle(unittest.TestCase):
  def test_both_toggles_required(self):
    env = hud_env()
    for csc, show, want in ((True, True, True), (False, True, False), (True, False, False), (False, False, False)):
      t = env["CscStatusToggle"](Store(CurveSpeedController=csc, ShowCSCStatus=show), clock=lambda: 0.0)
      self.assertEqual(t.get(), want)

  def test_read_failure_hides(self):
    env = hud_env()
    self.assertFalse(env["CscStatusToggle"](Store(), clock=lambda: 0.0).get())

  def test_cached_between_reads(self):
    env = hud_env()
    now = [0.0]
    store = Store(CurveSpeedController=True, ShowCSCStatus=True)
    t = env["CscStatusToggle"](store, clock=lambda: now[0], ttl=2.0)
    self.assertTrue(t.get())
    store.vals["ShowCSCStatus"] = False
    now[0] = 1.0
    self.assertTrue(t.get())          # still cached
    now[0] = 2.5
    self.assertFalse(t.get())         # picked up within the ttl

  def test_slot_follows_toggle(self):
    env = hud_env()
    hud = SimpleNamespace(is_cruise_set=True, set_speed=65.0, bp_csc=L.csc_status_from_plan(plan()))
    env["csc_status_toggle"] = env["CscStatusToggle"](Store(CurveSpeedController=True, ShowCSCStatus=True), clock=lambda: 0.0)
    slot = env["csc_slot"](hud)
    self.assertTrue(slot.active)
    self.assertEqual((slot.speed, slot.from_speed), (str(round(12.0 * 2.23694)), 65))
    env["csc_status_toggle"] = env["CscStatusToggle"](Store(CurveSpeedController=True, ShowCSCStatus=False), clock=lambda: 0.0)
    self.assertEqual(env["csc_slot"](hud), L.CscSlot())
    hud.bp_csc = L.INVALID_CSC        # planner report missing / stale / invalid: blank even with the toggle on
    env["csc_status_toggle"] = env["CscStatusToggle"](Store(CurveSpeedController=True, ShowCSCStatus=True), clock=lambda: 0.0)
    self.assertEqual(env["csc_slot"](hud), L.CscSlot())


class TestProducerRoundTrip(unittest.TestCase):
  """Real msgq pub/sub of plannerd's frogpilotPlan into the UI reader (requires cereal + msgq)."""

  def test_fresh_valid_then_stale(self):
    import openpilot.cereal.messaging as messaging
    from opendbc.car.tesla_ap1.interface import CarInterface
    from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
    from openpilot.selfdrive.controls.tests.test_ap1_curve_speed_planner import SM, ToggleStore, msgs, road
    from openpilot.selfdrive.controls.lib.ap1_curve_speed import Ap1CurveSpeed

    cp = CarInterface.get_non_essential_params("TESLA_AP1_MODELS")
    cp.openpilotLongitudinalControl = True
    p = LongitudinalPlanner(cp)
    p.curve_speed = Ap1CurveSpeed(cp, 0.05, ToggleStore(True))
    pm = messaging.PubMaster(['frogpilotPlan'])
    sm = messaging.SubMaster(['frogpilotPlan'])
    drive_start = time.monotonic()
    time.sleep(0.2)
    status = L.INVALID_CSC
    for i in range(40):
      p.update(SM(msgs(20.0, 30.0, 240.0 + i, road(300.0, 0.02, 150.0))))
      p.publish_frogpilot_plan(pm)
      time.sleep(0.05)
      sm.update(0)
      status = L.read_csc_status(sm, time.monotonic(), drive_start)
    self.assertTrue(status.valid and status.controlling)
    self.assertAlmostEqual(status.road_curvature, 0.02, places=5)
    self.assertAlmostEqual(status.csc_speed, p.curve_speed.target, places=4)
    self.assertFalse(L.read_csc_status(sm, time.monotonic(), time.monotonic()).valid)      # message from before this drive
    time.sleep(0.6)
    sm.update(0)
    self.assertFalse(L.read_csc_status(sm, time.monotonic(), drive_start).valid)           # stale > 0.5 s
    # Toggle off: plannerd keeps publishing but valid = False, so the slot stays blank.
    p.curve_speed = Ap1CurveSpeed(cp, 0.05, ToggleStore(False))
    for _ in range(10):
      p.update(SM(msgs(20.0, 30.0, 280.0, road(300.0, 0.02, 150.0))))
      p.publish_frogpilot_plan(pm)
      time.sleep(0.05)
      sm.update(0)
    self.assertFalse(L.read_csc_status(sm, time.monotonic(), drive_start).valid)


if __name__ == "__main__":
  unittest.main()
