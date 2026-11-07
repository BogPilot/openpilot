"""Alert-layer contract tests.

TestPlan / TestGeometry: synthetic, headless (no pyray / cereal).
TestRealAlertManager: real selfdrived events + AlertManager (needs cereal; skipped otherwise). Not a log replay.
"""
import ast
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
  spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
  module = importlib.util.module_from_spec(spec)
  sys.modules[name] = module
  spec.loader.exec_module(module)
  return module


L = load("alert_banner_logic")
C3X = (30.0, 30.0, 2100.0, 1020.0)    # 2160x1080 minus the 30 px engage border
C4_ISH = (0.0, 0.0, 536.0, 240.0)


def A(size, status=0, t1="Text One", t2="Text Two", typ=""):
  return L.AlertIn(t1, t2, size, status, typ)


class TestPlan(unittest.TestCase):
  def test_none_and_offroad_cleanup(self):
    self.assertEqual(L.plan_alert(None, C3X, started=True, redesign=True).mode, L.MODE_NONE)
    self.assertEqual(L.plan_alert(A(L.SIZE_NONE), C3X, started=True, redesign=True).mode, L.MODE_NONE)
    for s in (L.SIZE_SMALL, L.SIZE_MID, L.SIZE_FULL):
      p = L.plan_alert(A(s, 2), C3X, started=False, redesign=True)
      self.assertEqual(p.mode, L.MODE_NONE)
      self.assertFalse(p.showing)

  def test_full_always_native_full_rect(self):
    for redesign in (False, True):
      for compact in (False, True):
        p = L.plan_alert(A(L.SIZE_FULL, L.STATUS_CRITICAL), C3X, started=True, redesign=redesign, compact=compact)
        self.assertEqual(p.mode, L.MODE_NATIVE)
        self.assertEqual(p.rect, C3X)
        self.assertTrue(p.full and p.hide_cluster and p.showing)

  def test_small_mid_banner_when_redesign(self):
    for s in (L.SIZE_SMALL, L.SIZE_MID):
      for st in (0, 1, 2):
        a = A(s, st)
        p = L.plan_alert(a, C3X, started=True, redesign=True)
        self.assertEqual(p.mode, L.MODE_BANNER)
        self.assertIs(p.alert, a)                       # text/size/status/type pass through untouched
        self.assertEqual(p.mid, s == L.SIZE_MID)
        self.assertEqual(p.use_native_fill, st != L.STATUS_NORMAL)
        self.assertFalse(p.hide_cluster)
        p2 = L.plan_alert(a, C3X, started=True, redesign=False)
        self.assertEqual(p2.mode, L.MODE_NATIVE)
        self.assertTrue(p2.hide_cluster)

  def test_compact_c4_stays_native(self):
    for s in (L.SIZE_SMALL, L.SIZE_MID):
      self.assertEqual(L.plan_alert(A(s), C4_ISH, started=True, redesign=True, compact=True).mode, L.MODE_NATIVE)
      # a tiny window that cannot fit the banner falls back to native rather than clipping
      self.assertEqual(L.plan_alert(A(s), C4_ISH, started=True, redesign=True).mode, L.MODE_NATIVE)

  def test_lkas_fault_flag(self):
    self.assertTrue(L.plan_alert(A(1, typ="steerUnavailable/permanent"), C3X, started=True, redesign=True).lkas_fault)
    self.assertTrue(L.plan_alert(A(2, t1="LKAS Fault: Restart the Car"), C3X, started=True, redesign=True).lkas_fault)
    self.assertFalse(L.plan_alert(A(2), C3X, started=True, redesign=True).lkas_fault)


class TestGeometry(unittest.TestCase):
  def test_constants_match_style(self):
    tree = ast.parse((ROOT / "style.py").read_text())
    v = {}
    for n in tree.body:
      if isinstance(n, ast.Assign):
        try:
          val = ast.literal_eval(n.value)
        except Exception:
          continue
        for t in n.targets:
          if isinstance(t, ast.Name):
            v[t.id] = val
          elif isinstance(t, ast.Tuple) and isinstance(val, tuple):
            for e, x in zip(t.elts, val):
              v[e.id] = x
    self.assertEqual(L._REC_HIT, v["REC_HIT"])
    self.assertEqual(L._ALERT_GAP, v["ALERT_GAP"])
    self.assertEqual(L._ALERT_RIGHT_MARGIN, v["ALERT_RIGHT_MARGIN"])
    self.assertEqual(L._CLUSTER_CY, v["CLUSTER_CY"])
    self.assertEqual(L._CLUSTER_D, v["CLUSTER_D"])
    self.assertEqual(L._PILL_LABEL_SPACE, v["PILL_LABEL_SPACE"])
    self.assertEqual(L._REC_CX, v["CLUSTER_LEFT"] + 75)
    self.assertEqual(L._STACK_BOTTOM, v["GRAPH_TOP"] + v["GRAPH_HEIGHT"])

  def test_wide_banner_between_stack_and_cluster(self):
    x, y, w, h = C3X
    for mid in (False, True):
      bx, by, bw, bh = L.banner_rect(x, y, w, h, mid)
      self.assertGreaterEqual(by - y, L._STACK_BOTTOM)                     # below graph / speed row
      self.assertLessEqual(by - y + bh, L._CLUSTER_CY - L._CLUSTER_D // 2 - L._PILL_LABEL_SPACE)  # above DM/pill row
      self.assertGreater(bx - x, L._REC_CX + L._REC_HIT // 2)              # right of record button
      self.assertLessEqual(bx - x + bw, w)
    self.assertEqual(L.banner_rect(x, y, w, h, False)[3], L.SMALL_H)

  def test_resize_narrow(self):
    for w, h in ((1600, 1000), (1200, 800)):
      for mid in (False, True):
        bx, by, bw, bh = L.banner_rect(0, 0, w, h, mid)
        self.assertTrue(0 <= bx and bx + bw <= w and 0 <= by and by + bh <= h)


class TestRealAlertManager(unittest.TestCase):
  """Real events.py alerts through AlertManager priority selection -> plan. Skipped without cereal/openpilot."""

  @classmethod
  def setUpClass(cls):
    try:
      from openpilot.cereal import log, car  # noqa: F401
      from openpilot.selfdrive.selfdrived.events import Events, ET, EVENTS  # noqa: F401
      from openpilot.selfdrive.selfdrived.alertmanager import AlertManager  # noqa: F401
    except Exception as e:  # pragma: no cover
      raise unittest.SkipTest(f"openpilot runtime unavailable: {e}")

  def _current(self, names, et):
    from openpilot.cereal import log
    from openpilot.selfdrive.selfdrived.events import Events
    from openpilot.selfdrive.selfdrived.alertmanager import AlertManager
    ev = Events()
    for n in names:
      ev.add(getattr(log.OnroadEvent.EventName, n))
    am = AlertManager()
    am.add_many(1, ev.create_alerts([et], [None, None, False, 0, 0]))
    am.process_alerts(1, set())
    return am.current_alert

  def _plan(self, ca):
    a = L.AlertIn(ca.alert_text_1, ca.alert_text_2, int(ca.alert_size), int(ca.alert_status), ca.alert_type)
    return a, L.plan_alert(a, C3X, started=True, redesign=True)

  def test_priority_and_semantics_preserved(self):
    from openpilot.selfdrive.selfdrived.events import ET
    from openpilot.cereal import log
    E = log.OnroadEvent.EventName
    names = [n for n in ("driverDistracted", "preDriverDistracted") if hasattr(E, n)]
    ca = self._current(names, ET.WARNING)
    a, p = self._plan(ca)
    self.assertTrue(ca.alert_text_1)
    self.assertEqual(p.alert.text1, ca.alert_text_1)
    self.assertEqual(p.alert.text2, ca.alert_text_2)
    self.assertEqual(p.alert.status, int(ca.alert_status))
    # highest-priority alert wins (driverDistracted is the critical one)
    if "driverDistracted" in names:
      self.assertEqual(int(ca.alert_status), L.STATUS_CRITICAL)
    self.assertNotEqual(p.mode, L.MODE_NONE)
    if a.size == L.SIZE_FULL:
      self.assertEqual(p.mode, L.MODE_NATIVE)

  def test_every_onroad_alert_is_shown(self):
    """No real alert is suppressed: every WARNING/PERMANENT/NO_ENTRY alert with a size yields a visible plan."""
    from openpilot.cereal import log
    from openpilot.selfdrive.selfdrived.events import EVENTS, ET, Alert
    seen = 0
    for ev, d in EVENTS.items():
      for et, alert in d.items():
        if not isinstance(alert, Alert) or et not in (ET.WARNING, ET.PERMANENT, ET.SOFT_DISABLE, ET.IMMEDIATE_DISABLE):
          continue
        a = L.AlertIn(alert.alert_text_1, alert.alert_text_2, int(alert.alert_size), int(alert.alert_status), "x")
        p = L.plan_alert(a, C3X, started=True, redesign=True)
        if alert.alert_size == log.SelfdriveState.AlertSize.none:
          self.assertEqual(p.mode, L.MODE_NONE)
        else:
          seen += 1
          self.assertTrue(p.showing)
          self.assertEqual((p.alert.text1, p.alert.text2), (alert.alert_text_1, alert.alert_text_2))
    self.assertGreater(seen, 20)


if __name__ == "__main__":
  unittest.main()
