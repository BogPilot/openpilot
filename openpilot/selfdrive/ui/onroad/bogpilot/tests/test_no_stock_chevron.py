"""Stock lead chevron is never painted, in any setting or state (headless, no graphics)."""
import itertools
import unittest
from types import SimpleNamespace

from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_hud_compose import (
  Base, Layer, FakeModel, FakeAlert, Rect, FULL, MID, SMALL,
)
from openpilot.selfdrive.ui.onroad.bogpilot.tests.test_release_adapters import ROOT, adapter_namespace


STOCK_CHEVRON_CALLS = ("stock_lead0", "stock_lead1", "stock_chevron", "stock_lead")


def _overlay_class():
  drawn = []

  class BaseRenderer:
    def __init__(self):
      self._lead_vehicles = [
        SimpleNamespace(glow=[1], chevron=[1], n=0),
        SimpleNamespace(glow=[2], chevron=[2], n=1),
      ]

    def _draw_lead_indicator(self):
      drawn.extend(v.n for v in self._lead_vehicles if v.glow and v.chevron)

  ns = adapter_namespace("bogpilot_model", {
    "ModelRenderer": BaseRenderer, "MiciModelRenderer": BaseRenderer, "toggles": None,
    "FlameTracks": lambda: None, "FlameSideInput": None, "adjacent_leads": None,
    "blindspots": None, "BsmPolicy": lambda: None, "time": None,
    "ui_state": None, "draw_polygon": None, "np": None, "rl": None,
  })
  return ns["BogPilotModelRenderer"], ns["BogPilotMiciModelRenderer"], drawn


class TestOverlayNeverPaints(unittest.TestCase):
  def _assert_silent(self, cls, drawn, defer):
    drawn.clear()
    m = cls()
    m.bp_defer_primary_lead = defer
    m._draw_lead_indicator()
    self.assertEqual(drawn, [])
    self.assertIsNone(m.bp_pending_primary)
    self.assertEqual(len(m._lead_vehicles), 2)
    m.bp_pending_primary = m._lead_vehicles[0]
    m.bp_flush_primary_lead()
    self.assertEqual(drawn, [])
    self.assertIsNone(m.bp_pending_primary)

  def test_tizi_and_mici_never_paint_or_flush(self):
    tizi, mici, drawn = _overlay_class()
    for cls in (tizi, mici):
      for defer in (False, True):
        self._assert_silent(cls, drawn, defer)


class TestSourceHasNoPaint(unittest.TestCase):
  """The stock paint call (yellow glow + red chevron) must be absent from every _draw_lead_indicator."""

  PATHS = (
    ROOT / "bogpilot_model.py",
    ROOT.parents[1] / "onroad" / "model_renderer.py",
    ROOT.parents[1] / "mici" / "onroad" / "model_renderer.py",
  )

  def test_no_triangle_fan_in_lead_indicator(self):
    for path in self.PATHS:
      src = path.read_text()
      start = src.index("def _draw_lead_indicator(")
      end = src.index("\n  def ", start + 1)
      body = src[start:end]
      self.assertNotIn("draw_triangle_fan", body, path.name)
      self.assertNotIn("218, 202, 37", body, path.name)
      self.assertNotIn("201, 34, 49", body, path.name)

  def test_flush_is_a_noop(self):
    src = (ROOT / "bogpilot_model.py").read_text()
    start = src.index("def bp_flush_primary_lead(")
    end = src.index("\n  def ", start + 1)
    body = src[start:end]
    self.assertNotIn("super()", body)
    self.assertNotIn("draw_triangle_fan", body)
    self.assertNotIn("_draw_lead_indicator", body)


class TestComposerNeverFlushes(Base):
  """Every redesign / marker / engagement / alert / width combination leaves the stock chevron unpainted."""

  def _run(self, *, redesign, hide, engaged, alert_size, longitudinal, wide, lead_kw):
    self.calls.clear()
    self.toggles["RedesignUI"] = redesign
    self.state.has_longitudinal_control = longitudinal
    self.state.sm["selfdriveState"].enabled = engaged
    self.policy = SimpleNamespace(get=lambda: {
      "hide_lead_marker": hide, "onroad_distance_button": False, "adjacent_leads": True,
    })
    self.rect = Rect(30, 30, 2100 if wide else 1200, 1020)
    alert = None if alert_size is None else SimpleNamespace(size=alert_size, text1="", text2="")
    layers = {}
    if lead_kw is not None:
      layers["lead_lockon"] = Layer(self.calls, "lead_lockon", {"lead_chevron"}, **lead_kw)
    c = self.composer(layers, alert=FakeAlert(self.calls, alert=alert), model=FakeModel(self.calls, pending=True))
    c.render(self.rect)
    for name in STOCK_CHEVRON_CALLS:
      self.assertNotIn(name, self.calls, (redesign, hide, engaged, alert_size, longitudinal, wide, lead_kw, list(self.calls)))
    self.assertFalse(hasattr(self.model, "flushed") and self.model.flushed)
    return c

  def test_matrix_never_flushes_stock_chevron(self):
    lead_cases = (None, {}, {"enabled": False}, {"draw": False}, {"raises": "draw"}, {"raises": "enabled"})
    alerts = (None, SMALL, MID, FULL)
    for redesign, hide, engaged, alert_size, longitudinal, wide, lead_kw in itertools.product(
        (True, False), (True, False), (True, False), alerts, (True, False), (True, False), lead_cases):
      c = self._run(redesign=redesign, hide=hide, engaged=engaged, alert_size=alert_size,
                    longitudinal=longitudinal, wide=wide, lead_kw=lead_kw)
      # Boxes stay available when the redesign is on, the layer is present, and it paints.
      if redesign and wide and lead_kw == {} and longitudinal and not hide:
        # Fake layer.draw returns a box whenever enabled and draw are default True, independent of long/hide;
        # the fake does not implement those gates. Only assert the stock chevron stayed off (done above)
        # and that a successful fake paint still records the lock-on layer.
        if "lead_lockon" in self.calls:
          self.assertIsNotNone(c.frame.lead_label_box)

  def test_redesign_off_is_stock_order_without_chevron(self):
    c = self._run(redesign=False, hide=False, engaged=True, alert_size=None,
                  longitudinal=True, wide=True, lead_kw={})
    self.assertEqual(list(self.calls), ["model", "hud", "alert", "stock_dm"])
    self.assertFalse(self.model.defer_seen)

  def test_redesign_on_still_paints_lock_on_box(self):
    c = self._run(redesign=True, hide=False, engaged=True, alert_size=None,
                  longitudinal=True, wide=True, lead_kw={})
    self.assertIn("lead_lockon", self.calls)
    self.assertIsNotNone(c.frame.lead_label_box)
    self.assertNotIn("stock_lead0", self.calls)


if __name__ == "__main__":
  unittest.main()
