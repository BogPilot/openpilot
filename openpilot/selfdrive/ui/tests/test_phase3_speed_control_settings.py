"""Pure tests for the phase 3 SLC settings rows (no pyray)."""
import os
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace as NS

from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.ui.layouts.settings import phase3_speed_control_settings as ss
from openpilot.selfdrive.controls.lib import phase3_speed_control as sc
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import CP_AP1, FakeStore, Sm, run, DT, MPH


class TestRows(unittest.TestCase):
  def test_keys_registered(self):
    for k in ss.ACTIVE_KEYS + tuple(ss.OMITTED):
      if k not in ("SLCPriority", "SetWeatherKey"):
        self.assertIn(k, BOGPILOT_PARAMS, k)
    self.assertFalse(set(ss.ACTIVE_KEYS) & set(ss.OMITTED))

  def test_visibility_nesting(self):
    on = FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1")
    self.assertEqual([r[0] for r in ss.visible_rows(on)],
                     ["SpeedLimitController", "SLCFallback", "SLCOverride",
                      "SLCPriority1", "SLCPriority2", "SLCPriority3", "SLCLookaheadLower"])
    self.assertEqual([r[0] for r in ss.visible_rows(on, "SLCOffsets")], [f"Offset{i}" for i in range(1, 8)])
    self.assertEqual([r[0] for r in ss.visible_rows(on, "SLCQOL")], ["SLCConfirmation"])
    on2 = FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1", SLCConfirmation="1")
    self.assertEqual([r[0] for r in ss.visible_rows(on2, "SLCQOL")],
                     ["SLCConfirmation", "SLCConfirmationLower", "SLCConfirmationHigher"])
    off = FakeStore(SpeedLimitController="0")
    self.assertEqual([r[0] for r in ss.visible_rows(off)], ["SpeedLimitController"])
    self.assertEqual(ss.visible_sub_panels(off), [])
    self.assertEqual(ss.visible_sub_panels(on), ["SLCOffsets", "SLCQOL", "SLCVisuals"])

  def test_units_and_ranges(self):
    self.assertEqual(ss.offset_title("Offset2", False), "Speed Offset (25–34 mph)")
    self.assertEqual(ss.offset_title("Offset7", True), "Speed Offset (120–140 km/h)")
    self.assertEqual(ss.clamp_offset(400, False), 99)
    self.assertEqual(ss.clamp_offset(-400, True), -150)

  @mock.patch.object(sc, "ACTIVATION_POLICY", "adoption")
  def test_unadopted_default_on_reads_off(self):
    """Registry default SpeedLimitController="1" but the planner is dormant until adopted: the panel must say OFF."""
    fresh = FakeStore()
    self.assertEqual([r[0] for r in ss.visible_rows(fresh)], ["SpeedLimitController"])
    self.assertEqual(ss.visible_sub_panels(fresh), [])
    self.assertFalse(ss.SlcEditor(CP_AP1, fresh, lambda: True).on("SpeedLimitController"))

  def test_experimental_fallback_hidden_without_planner_consumer(self):
    labels = [o[1] for o in ss.choice_options(FakeStore(), "SLCFallback")]
    if not ss.experimental_fallback_available(FakeStore()):
      self.assertEqual(labels, ["Set Speed", "Previous Limit"])
    else:
      self.assertEqual(labels, ["Set Speed", "Experimental Mode", "Previous Limit"])
    self.assertEqual([o[0] for o in ss.choice_options(FakeStore(), "SLCOverride")], [0, 1, 2])

  def test_no_writes_or_key_collection(self):
    from pathlib import Path
    src = Path(ss.__file__).read_text()
    self.assertNotIn(".put(", src)
    self.assertNotIn("InputDialog", src)


class TestEditor(unittest.TestCase):
  """UI write -> store -> Ap1SpeedControl consumer (the same FakeStore object, real onroad_toggles path)."""

  def editor(self, store=None, offroad=True, cp=CP_AP1):
    store = FakeStore() if store is None else store
    flag = [offroad]
    return ss.SlcEditor(cp, store, lambda: flag[0]), store, flag

  def consumer(self, store):
    t = [0.0]
    def clock():
      t[0] += 2.0
      return t[0]
    return sc.Ap1SpeedControl(CP_AP1, store=store, clock=clock)

  @mock.patch.object(sc, "ACTIVATION_POLICY", "adoption")
  def test_toggle_on_reaches_consumer(self):
    ed, store, _ = self.editor()
    ctl, sm = self.consumer(store), Sm()
    self.assertEqual(run(ctl, sm, 30.0, 20.0, limit=45 * MPH), 30.0)         # fresh install: stock
    self.assertTrue(ed.write("SpeedLimitController", True))
    self.assertTrue(ed.on("SpeedLimitController"))
    out = run(ctl, sm, 30.0, 20.0, limit=45 * MPH, rwd=True)
    self.assertAlmostEqual(out, 50 * MPH, places=4)                           # 45 + default Offset4 5 mph
    self.assertTrue(ed.write("Offset4", 9))
    self.assertAlmostEqual(run(ctl, sm, 30.0, 20.0, limit=45 * MPH), 54 * MPH, places=4)
    self.assertTrue(ed.step_offset("Offset4", -2))
    self.assertAlmostEqual(run(ctl, sm, 30.0, 20.0, limit=45 * MPH), 52 * MPH, places=4)
    self.assertTrue(ed.write("SpeedLimitController", False))
    self.assertEqual(run(ctl, sm, 30.0, 20.0, limit=45 * MPH), 30.0)

  def test_choice_and_confirmation_reach_consumer(self):
    ed, store, _ = self.editor()
    self.assertTrue(ed.write("SpeedLimitController", True))
    self.assertTrue(ed.write("SLCFallback", 0))
    self.assertEqual(ed.choice("SLCFallback"), 0)
    ctl, sm = self.consumer(store), Sm()
    run(ctl, sm, 25.0, 20.0, limit=0.0, enabled=True)
    self.assertAlmostEqual(ctl.slc.target, 25.0)                              # Fallback = Set Speed
    self.assertTrue(ed.write("SLCConfirmation", True))
    self.assertTrue(ed.write("SLCConfirmationHigher", True))
    self.assertTrue(ed.write("SLCFallback", 2))                               # Previous Limit: no set-speed substitute target
    store.vals.pop("PreviousSpeedLimit", None)                                # fresh drive (0.9.7 previous-limit quirk, see wiring test)
    ctl2, sm2 = self.consumer(store), Sm()
    run(ctl2, sm2, 30.0, 20.0, limit=45 * MPH, cruise=False)
    self.assertEqual(ctl2.slc.target, 0.0)                                    # waits for confirmation
    self.assertAlmostEqual(ctl2.slc.unconfirmed_speed_limit, 45 * MPH)

  def test_experimental_choice_follows_planner_consumer(self):
    ed, store, _ = self.editor()
    ed.write("SpeedLimitController", True)
    ok = ss.experimental_fallback_available(store)
    self.assertEqual(ed.write("SLCFallback", ss.FALLBACK_EXPERIMENTAL), ok)
    if ok:
      ctl, sm = self.consumer(store), Sm()
      run(ctl, sm, 25.0, 20.0, limit=0.0)
      self.assertTrue(ctl.resolve_experimental(False))
      run(ctl, sm, 25.0, 20.0, limit=30 * MPH)
      self.assertTrue(ctl.resolve_experimental(True))                         # default "or": honor the user's toggle

  @mock.patch.object(sc, "ACTIVATION_POLICY", "adoption")
  def test_guards(self):
    ed, store, flag = self.editor()
    self.assertFalse(ed.write("SLCFallback", 0))                              # hidden until SLC on
    self.assertFalse(ed.write("Offset1", 3))
    self.assertEqual(store.puts, [])
    self.assertTrue(ed.write("SpeedLimitController", True))
    n = len(store.puts)
    for key, bad in (("SpeedLimitController", 1), ("SLCFallback", True), ("SLCFallback", 7), ("SLCFallback", 1.0),
                     ("SLCOverride", -1), ("Offset1", 100), ("Offset1", -100), ("Offset1", float("nan")), ("Offset1", True),
                     ("Offset1", "3"), ("ShowSLCOffset", 1), ("SpeedLimitSources", True), ("CustomCruise", 5)):
      if key == "SLCFallback" and bad == 7:
        pass
      self.assertFalse(ed.write(key, bad), (key, bad))
    # SLCFallback=1 is only valid when the planner consumer exists; everything above must have been refused
    self.assertEqual(len(store.puts), n)
    flag[0] = False                                                           # onroad
    self.assertFalse(ed.write("Offset1", 3))
    self.assertFalse(ed.write("SpeedLimitController", False))
    self.assertEqual(len(store.puts), n)
    flag[0] = True
    store.put("IsMetric", True)
    self.assertFalse(ed.write("Offset1", 151))
    self.assertTrue(ed.write("Offset1", 150))
    self.assertEqual(ed.offset("Offset1"), 150)

  def test_not_available_without_legacy_tesla_longitudinal(self):
    for cp in (None, NS(carFingerprint="TESLA_MODEL_3", openpilotLongitudinalControl=True),
               NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=False)):
      ed, store, _ = self.editor(cp=cp)
      self.assertFalse(ed.visible("SpeedLimitController"))
      self.assertFalse(ed.write("SpeedLimitController", True))
      self.assertEqual(store.puts, [])

  def test_available_on_preap_and_ap1_x(self):
    for fp in ("TESLA_PREAP_MODELS", "TESLA_AP1_MODELX", "TESLA_AP1_MODELS"):
      ed, store, _ = self.editor(cp=NS(carFingerprint=fp, openpilotLongitudinalControl=True))
      self.assertTrue(ed.available(), fp)
      self.assertTrue(ed.visible("SpeedLimitController"), fp)

  def test_stored_garbage_is_clamped_not_rewritten(self):
    ed, store, _ = self.editor(FakeStore(Offset2="9999", SLCFallback="42", SLCLookaheadLower="99"))
    self.assertEqual(ed.offset("Offset2"), 99)
    self.assertEqual(ed.choice("SLCFallback"), 0)
    self.assertEqual(ed.seconds("SLCLookaheadLower"), 15)
    self.assertEqual(store.puts, [])

  @unittest.skipUnless(os.getenv("RAYLIB_BACKEND") == "headless", "requires authorized native headless render")
  def test_native_layout_render_and_toggle_callback_writes(self):
    """Real raylib widgets (no fakes): render, tap-callback -> store -> consumer, nested rows appear, render again."""
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    gui_app.init_window("SLC native layout")
    store = FakeStore()
    layout = ss.make_layout(CP_AP1, store, lambda: True)
    rect = rl.Rectangle(500, 0, 1660, 1080)

    def render():
      rl.begin_drawing()
      try:
        layout.render(rect)
      finally:
        rl.end_drawing()
    layout.show_event()
    render()
    self.assertEqual(list(layout.toggles), ["SpeedLimitController"])            # nothing nested while OFF
    layout.toggles["SpeedLimitController"].action_item.toggle._callback(True)   # what the Toggle widget calls on a tap
    self.assertEqual((store.vals["SpeedLimitController"], store.vals[sc.SLC_ACK]), ("1", "1"))
    render()
    self.assertIn("SLCFallback", layout.choices)                                # nested rows appear after adoption
    ctl, sm = self.consumer(store), Sm()
    self.assertAlmostEqual(run(ctl, sm, 30.0, 20.0, limit=45 * MPH, rwd=True), 50 * MPH, places=4)
    sub = ss.make_layout(CP_AP1, store, lambda: True, section="SLCOffsets")
    sub.show_event()
    rl.begin_drawing()
    try:
      sub.render(rect)
    finally:
      rl.end_drawing()
    layout.hide_event()


class TestDefaultOnPanel(unittest.TestCase):
  """SLC default ON (0.9.7) - the panel shows the real state from the first launch."""

  def test_fresh_panel_reads_on(self):
    fresh = FakeStore()
    self.assertTrue(ss.SlcEditor(CP_AP1, fresh, lambda: True).on("SpeedLimitController"))
    self.assertIn("SLCOffsets", ss.visible_sub_panels(fresh))

  def test_user_off_is_respected(self):
    off = FakeStore(SpeedLimitController="0")
    self.assertFalse(ss.SlcEditor(CP_AP1, off, lambda: True).on("SpeedLimitController"))
    self.assertEqual(ss.visible_sub_panels(off), [])



class TestPriorityAndLookaheadRows(unittest.TestCase):
  def editor(self, store=None, cp=CP_AP1):
    store = FakeStore() if store is None else store
    return ss.SlcEditor(cp, store, lambda: True), store

  def test_stale_no_mapd_reason_is_gone(self):
    text = Path(ss.__file__).read_text()
    self.assertNotIn("no mapd", text)
    self.assertNotIn("no mapd / NextMapSpeedLimit", text)
    self.assertIn("SLCLookaheadLower", ss.ACTIVE_KEYS)
    self.assertNotIn("SLCLookaheadLower", ss.OMITTED)
    self.assertIn("SLCPriority1", ss.ACTIVE_KEYS)

  def test_help_text_is_mph(self):
    desc = ss.BY_KEY["SLCLookaheadLower"][3]
    self.assertIn("mph", desc)
    self.assertIn("2.0 mph/s", desc)
    self.assertIn("65 mph", desc)
    self.assertIn("480 feet", desc)
    self.assertIn("5 seconds", desc)
    self.assertNotIn("m/s", desc)
    self.assertNotIn("km/h", desc)

  def test_highest_hides_priority_2_and_3(self):
    on = FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1", SLCPriority1="Highest")
    self.assertEqual([r[0] for r in ss.visible_rows(on)],
                     ["SpeedLimitController", "SLCFallback", "SLCOverride", "SLCPriority1", "SLCLookaheadLower"])
    on2 = FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1", SLCPriority1="Lowest")
    self.assertNotIn("SLCPriority2", [r[0] for r in ss.visible_rows(on2)])

  def test_write_priority_and_horizon_reaches_consumer(self):
    ed, store = self.editor()
    self.assertTrue(ed.write("SpeedLimitController", True))
    self.assertTrue(ed.write("SLCPriority1", "Map Data"))
    self.assertEqual(ed.priority("SLCPriority1"), "Map Data")
    self.assertTrue(ed.write("SLCLookaheadLower", 7))
    self.assertEqual(ed.seconds("SLCLookaheadLower"), 7)
    self.assertFalse(ed.write("SLCLookaheadLower", 16))
    self.assertFalse(ed.write("SLCLookaheadLower", -1))
    self.assertFalse(ed.write("SLCPriority1", "Off"))
    self.assertEqual(store.vals["SLCLookaheadLower"], "7")
    from openpilot.common.bogpilot_onroad_toggles import onroad_toggles
    t = onroad_toggles(store, CP_AP1)
    self.assertEqual(t.speed_limit_priority1, "Map Data")
    self.assertEqual(t.map_speed_lookahead_lower, 7)

  def test_horizon_zero_is_off_and_stored_one_is_kept(self):
    ed, store = self.editor(FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1",
                                      SLCLookaheadLower="1.000000"))
    self.assertEqual(ed.seconds("SLCLookaheadLower"), 1)
    self.assertTrue(ed.write("SLCLookaheadLower", 0))
    self.assertEqual(ed.seconds("SLCLookaheadLower"), 0)
    self.assertEqual(store.vals["SLCLookaheadLower"], "0")

  def test_unset_horizon_defaults_to_five(self):
    ed, store = self.editor(FakeStore(SpeedLimitController="1", Phase3SpeedLimitEnabled="1"))
    self.assertEqual(ed.seconds("SLCLookaheadLower"), 5)
    self.assertEqual(store.puts, [])



if __name__ == "__main__":
  unittest.main()
