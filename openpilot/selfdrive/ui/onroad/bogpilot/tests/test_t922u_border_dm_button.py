"""t922u/t924u: BSM half border, BSM fill to the bottom, DM moved beside the personality button, LKAS-fault border.

Current-schema messages; the composer methods are the production ones (HudComposer instance without peer layers).
"""
import time
import unittest
from types import SimpleNamespace

import numpy as np
import pyray as rl

from openpilot.cereal import log, messaging
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.onroad.bogpilot import hud_compose as HC
from openpilot.selfdrive.ui.onroad.bogpilot import redesign as R
from openpilot.selfdrive.ui.onroad.bogpilot import alert_banner_logic as L
from openpilot.selfdrive.ui.onroad.bogpilot.style import CLUSTER_GAP, LKAS_FAULT_FLASH_MS
from openpilot.selfdrive.ui.onroad.bogpilot.bogpilot_model import extend_to_bottom

AP1 = SimpleNamespace(carFingerprint="TESLA_AP1_MODELS", radarUnavailable=False, openpilotLongitudinalControl=True)
CRIT = int(log.SelfdriveState.AlertStatus.critical)


class SM(dict):
  def __init__(self, left=False, right=False, age=0.0, frame=10, personality=1):
    cs = messaging.new_message("carState").carState
    cs.leftBlindspot, cs.rightBlindspot = left, right
    ss = messaging.new_message("selfdriveState").selfdriveState
    ss.personality = personality
    super().__init__(carState=cs, selfdriveState=ss)
    self.valid = {k: True for k in self}; self.alive = dict(self.valid)
    self.recv_frame = {k: frame for k in self}; self.recv_time = {k: time.monotonic() - age for k in self}


class Store:
  def __init__(self, **v): self.v = {"BorderMetrics": True, "BlindSpotMetrics": True, **v}
  def tuning_level(self): return 3
  def toggle_bool(self, k, level=None): return bool(self.v.get(k, False))
  def get_bool(self, k, default=False): return bool(self.v.get(k, default))


def composer(lkas=False, store=None):
  c = HC.HudComposer.__new__(HC.HudComposer)
  c.alert = SimpleNamespace(hud_state=lambda: SimpleNamespace(lkas_fault=lkas))
  c.disabled = set(); c.clock = lambda: 0.0; c._bsm_store = store or Store()
  c.frame = SimpleNamespace(full_alert=False, alert=None, rhd=False, personality_rect=None, traffic_mode=False, dm_shift=0.0)
  return c


class Base(unittest.TestCase):
  def setUp(self):
    self._saved = (ui_state.sm, ui_state.started_frame, getattr(ui_state, "CP", None))
    ui_state.started_frame = 0; ui_state.CP = AP1

  def tearDown(self):
    ui_state.sm, ui_state.started_frame, ui_state.CP = self._saved


class TestBsmBorder(Base):
  def sides(self, c=None, **sm):
    ui_state.sm = SM(**sm)
    return (c or composer()).bsm_border()

  def test_left_right_both_off(self):
    self.assertEqual(self.sides(left=True), (True, False))
    self.assertEqual(self.sides(right=True), (False, True))
    self.assertEqual(self.sides(left=True, right=True), (True, True))
    self.assertIsNone(self.sides())

  def test_stale_and_previous_drive_normal(self):
    self.assertIsNone(self.sides(left=True, age=2.0))
    ui_state.started_frame = 20
    self.assertIsNone(self.sides(left=True, frame=10))

  def test_rhd_keeps_physical_sides(self):
    c = composer(); c.frame.rhd = True
    self.assertEqual(self.sides(c, left=True), (True, False))

  def test_lkas_fault_full_and_critical_alert_keep_border(self):
    self.assertIsNone(self.sides(composer(lkas=True), left=True))
    c = composer(); c.frame.full_alert = True
    self.assertIsNone(self.sides(c, left=True))
    c = composer(); c.frame.alert = SimpleNamespace(status=CRIT, size=1)
    self.assertIsNone(self.sides(c, left=True))

  def test_gates(self):
    self.assertIsNone(self.sides(composer(store=Store(BlindSpotMetrics=False)), left=True))
    self.assertIsNone(self.sides(composer(store=Store(BorderMetrics=False)), left=True))
    self.assertEqual(self.sides(composer(store=Store(BorderMetrics=False, DebugMode=True)), left=True), (True, False))
    ui_state.CP = SimpleNamespace(carFingerprint="TESLA_MODEL_3")
    self.assertIsNone(self.sides(left=True))

  def test_daily_colour(self):
    self.assertEqual(HC.HudComposer.BSM_BORDER_RGBA, (0xC9, 0x22, 0x31, 0xF1))


class TestLkasFaultBorder(Base):
  def test_cadence_and_palette_daily(self):
    self.assertEqual(LKAS_FAULT_FLASH_MS, 200)
    col = lambda ms: (lambda c: (c.r, c.g, c.b))(R.lkas_fault_border_color(ms))   # noqa: E731
    red, orange = (0xE0, 0x1B, 0x24), (0xFF, 0x8C, 0x00)
    for ms, want in ((0, red), (199, red), (200, orange), (399, orange), (400, red), (1000, orange), (-5, red)):
      self.assertEqual(col(ms), want, ms)
    frames = [col(i * 50) for i in range(16)]         # 20 Hz UI: four frames per 200 ms phase, 50 % duty
    self.assertEqual(frames.count(red), 8)

  def test_all_steer_unavailable_forms_and_text(self):
    from openpilot.selfdrive.selfdrived.events import EVENTS, ET
    forms = [et for et in EVENTS[log.OnroadEvent.EventName.steerUnavailable]]
    self.assertTrue(forms)
    for et in forms:
      self.assertTrue(L.is_lkas_fault(L.AlertIn("x", "y", 1, 1, f"steerUnavailable/{et}")), et)
    self.assertTrue(L.is_lkas_fault(L.AlertIn("TAKE CONTROL", "LKAS Fault: Restart the Car", 2, 2, "")))
    self.assertFalse(L.is_lkas_fault(L.AlertIn("TAKE CONTROL IMMEDIATELY", "System Unresponsive", 3, 2, "")))  # stale
    self.assertFalse(L.is_lkas_fault(L.AlertIn("Steering Temporarily Unavailable", "", 2, 1, "steerTempUnavailable/warning")))

  def test_override_follows_plan(self):
    c = composer(lkas=True); c.frame = SimpleNamespace()
    self.assertIsNotNone(c.border_override(0))
    c = composer(lkas=False); c.frame = SimpleNamespace()
    self.assertIsNone(c.border_override(0))
    c = composer(lkas=True); c.frame = None
    self.assertIsNone(c.border_override(0))


class TestFillToBottom(unittest.TestCase):
  def test_extends_both_edges_to_bottom_along_their_direction(self):
    left = np.array([[900, 800], [950, 700], [980, 640], [1000, 600]], np.float32)
    right = np.array([[700, 800], [800, 700], [860, 640], [900, 600]], np.float32)
    poly = np.vstack((left, right[::-1]))
    out = extend_to_bottom(poly, 1050.0)
    self.assertEqual(len(out), len(poly) + 2)
    self.assertAlmostEqual(float(out[0, 1]), 1050.0, 3); self.assertAlmostEqual(float(out[-1, 1]), 1050.0, 3)
    # on the line through the nearest and 3rd point
    self.assertAlmostEqual(float(out[0, 0]), 900 + (900 - 1000) / (800 - 600) * 250, 3)
    np.testing.assert_array_equal(out[1:-1], poly)

  def test_no_change_when_already_at_bottom_or_degenerate(self):
    poly = np.array([[0, 1060], [1, 900], [2, 900], [3, 1060]], np.float32)
    np.testing.assert_array_equal(extend_to_bottom(poly, 1050.0), poly)
    self.assertEqual(len(extend_to_bottom(np.zeros((3, 2), np.float32), 1050.0)), 3)


class TestDmAndButton(Base):
  def frame(self, rhd=False, button=True, full=False, traffic=False):
    return SimpleNamespace(rect=rl.Rectangle(0, 0, 2160, 1080), scale=1.0, layout=SimpleNamespace(keepouts=lambda: []),
                           wide=True, onroad_distance_button=button, traffic_mode=traffic, full_alert=full, rhd=rhd, alert=None)

  def layout(self, **kw):
    c = composer(); f = self.frame(**kw); c._keepouts(f, True); c.frame = f
    return c, f

  def test_lhd_button_in_stock_corner_dm_beside(self):
    c, f = self.layout()
    off = HC.UI_BORDER + HC.DM_BTN // 2
    pill, dm = f.personality_rect, f.stock_dm_rect
    self.assertAlmostEqual(pill.x + pill.width / 2, off); self.assertAlmostEqual(pill.y + pill.height / 2, 1080 - off)
    self.assertAlmostEqual(dm.x, pill.x + pill.width + CLUSTER_GAP + HC.LABEL_CLEAR_MARGIN)
    self.assertEqual((dm.width, dm.height), (HC.DM_BTN, HC.DM_BTN))   # stock size
    self.assertFalse(rl.check_collision_recs(pill, dm))
    from openpilot.selfdrive.ui.onroad.bogpilot.lead_labels import clear
    self.assertTrue(clear((pill.x, pill.y - 40, pill.width, pill.height + 40), f.rect, f.label_keepouts))   # pill paints
    r = c.dm_rect(f.rect, f)      # what the unmodified stock renderer receives
    self.assertAlmostEqual(r.x + off, dm.x + HC.DM_BTN / 2)          # stock: position_x = rect.x + offset

  def test_rhd_mirrored(self):
    c, f = self.layout(rhd=True)
    off = HC.UI_BORDER + HC.DM_BTN // 2
    pill, dm = f.personality_rect, f.stock_dm_rect
    self.assertAlmostEqual(pill.x + pill.width / 2, 2160 - off)
    self.assertAlmostEqual(dm.x + dm.width, pill.x - CLUSTER_GAP - HC.LABEL_CLEAR_MARGIN)
    r = c.dm_rect(f.rect, f)
    self.assertAlmostEqual(r.x + r.width - off, dm.x + HC.DM_BTN / 2)  # stock: rect.x + width - offset

  def test_no_button_stock_position(self):
    c, f = self.layout(button=False)
    self.assertIsNone(f.personality_rect); self.assertEqual(f.dm_shift, 0.0)
    self.assertIs(c.dm_rect(f.rect, f), f.rect)
    c, f = self.layout(full=True)
    self.assertEqual(f.dm_shift, 0.0)

  def test_click_cycles_like_stalk_and_is_consumed(self):
    c, f = self.layout()
    ui_state.sm = SM(personality=1)
    pill = f.personality_rect; centre = SimpleNamespace(x=pill.x + pill.width / 2, y=pill.y + pill.height / 2)
    writes = []
    self.assertTrue(c.handle_press(centre, write=lambda k, v: writes.append((k, v))))
    self.assertEqual(writes, [("LongitudinalPersonality", 0)])     # standard -> aggressive (stock: personality - 1)
    ui_state.sm = SM(personality=0); writes.clear()
    c.handle_press(centre, write=lambda k, v: writes.append((k, v)))
    self.assertEqual(writes, [("LongitudinalPersonality", 2)])
    dm = f.stock_dm_rect
    self.assertFalse(c.handle_press(SimpleNamespace(x=dm.x + 96, y=dm.y + 96), write=lambda k, v: writes.append(k)))

  def test_traffic_mode_tap_consumed_without_write(self):
    c, f = self.layout(traffic=True)
    ui_state.sm = SM()
    pill = f.personality_rect; writes = []
    self.assertTrue(c.handle_press(SimpleNamespace(x=pill.x + 75, y=pill.y + 75), write=lambda k, v: writes.append(k)))
    self.assertEqual(writes, [])


if __name__ == "__main__":
  unittest.main()
