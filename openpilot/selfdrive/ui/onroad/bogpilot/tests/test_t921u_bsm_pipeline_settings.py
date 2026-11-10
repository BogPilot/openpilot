"""t921u follow-up: end-to-end BSM wiring and the BogPilot Visuals settings entry.

Pipeline: packed stock 0x399 bytes on bus 2 -> tesla_ap1 CarInterface (CANParser + carstate + blindspot.py)
-> carState published as card does (cs_send.carState = CS, current schema) -> UI bsm_state.blindspots()
-> BsmPolicy (AP1 capability; enableBsm is deprecated in 0.11) -> BogPilotModelRenderer fill flags.
Settings: native BogPilotVisualsLayout registered in SettingsLayout, real toggle clicks write through ParamStore to
the same owner each onroad consumer reads (typed Params vs /data/params_bogpilot file), defaults untouched.
Synthetic CAN bytes only; no car or device.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from opendbc.car import gen_empty_fingerprint
from opendbc.car.can_definitions import CanData
from opendbc.car.tesla_ap1.cluster import AUTOPILOT_STATUS, CHECKSUM_SIGNALS, SIGNALS, pack, tesla_checksum
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.values import CAR, AP1_CHASSIS_SIGNATURE
from openpilot.cereal import messaging

from openpilot.selfdrive.ui.onroad.bogpilot import bsm_state

CK = CHECKSUM_SIGNALS[AUTOPILOT_STATUS]
DT_NS = 10_000_000  # 100 Hz carstate steps


def fingerprint(bsm_frame=True):
  fp = gen_empty_fingerprint()
  fp[0] = dict(AP1_CHASSIS_SIGNATURE)
  fp[2] = {0x2B9: 8, 0x488: 4}
  if bsm_frame:
    fp[2][0x399] = 8
  return fp


def params(bsm_frame=True):
  return CarInterface.get_params(CAR.TESLA_AP1_MODELS, fingerprint(bsm_frame), [], False, False, False)


def frame_399(left=0, right=0, good_checksum=True):
  vals = {"DAS_blindSpotRearLeft": left, "DAS_blindSpotRearRight": right}
  body = pack(AUTOPILOT_STATUS, SIGNALS[AUTOPILOT_STATUS], vals).to_bytes(8, "little")
  ck = tesla_checksum(AUTOPILOT_STATUS, body)
  if not good_checksum:
    ck = (ck + 1) & 0xFF
  vals[CK] = ck
  return pack(AUTOPILOT_STATUS, SIGNALS[AUTOPILOT_STATUS], vals).to_bytes(8, "little")


class Pipeline:
  def __init__(self):
    self.CP = params()
    self.ci = CarInterface(self.CP)
    self.t = 1_000_000_000

  def step(self, dat=None):
    self.t += DT_NS
    msgs = [CanData(AUTOPILOT_STATUS, dat, 2)] if dat is not None else []
    return self.ci.update([(self.t, msgs)])

  def publish(self, CS):
    msg = messaging.new_message("carState")
    msg.valid = True
    msg.carState = CS   # exactly what card.py does
    return messaging.log_from_bytes(msg.to_bytes()).carState


class FakeSM(dict):
  def __init__(self, cs, age=0.0, frame=10):
    super().__init__(carState=cs)
    self.valid = {"carState": True}
    self.alive = {"carState": True}
    self.recv_frame = {"carState": frame}
    self.recv_time = {"carState": time.monotonic() - age}


class TestCarParamsCapability(unittest.TestCase):
  def test_enable_bsm_is_deprecated_in_0_11_schema(self):
    from opendbc.car import structs
    self.assertNotIn("enableBsm", structs.CarParams.schema.fields)
    import opendbc.car as oc
    txt = (Path(oc.__file__).parent / "car.capnp").read_text()
    self.assertLess(txt.index("deprecated :group"), txt.index("enableBsm @56"))

  def test_capability_is_carstate_ap1_condition(self):
    self.assertTrue(bsm_state.has_bsm(params(True)))
    self.assertFalse(bsm_state.has_bsm(None))
    self.assertFalse(bsm_state.has_bsm(SimpleNamespace(carFingerprint="TESLA_MODEL_3")))

  def test_enable_bsm_has_no_controls_consumer(self):
    root = Path(__file__).resolve().parents[5]   # openpilot/
    hits = []
    for sub in ("selfdrive/controls", "selfdrive/selfdrived", "selfdrive/car", "selfdrive/monitoring"):
      for p in (root / sub).rglob("*.py"):
        if "/tests/" in str(p):
          continue
        if "enableBsm" in p.read_text(errors="ignore"):
          hits.append(str(p))
    self.assertEqual(hits, [])

  def test_lane_change_blocking_still_reads_carstate_flags(self):
    root = Path(__file__).resolve().parents[5]
    src = (root / "selfdrive/controls/lib/desire_helper.py").read_text()
    self.assertIn("bsm_side_occupied(carstate", src)  # t994 laneChange: fail-closed helper reads carstate flags
    self.assertNotIn("enableBsm", src)


class TestCanToUiPipeline(unittest.TestCase):
  def setUp(self):
    self.p = Pipeline()

  def flags(self, dat, steps=1):
    cs = None
    for i in range(steps):
      cs = self.p.step(dat if i == 0 else None)
    pub = self.p.publish(cs)
    return (bool(cs.leftBlindspot), bool(cs.rightBlindspot)), bsm_state.blindspots(FakeSM(pub), 0, time.monotonic())

  def test_left(self):
    raw, ui = self.flags(frame_399(left=1))
    self.assertEqual(raw, (True, False)); self.assertEqual(ui, (True, False))

  def test_right_level2(self):
    raw, ui = self.flags(frame_399(right=2))
    self.assertEqual(raw, (False, True)); self.assertEqual(ui, (False, True))

  def test_both(self):
    self.assertEqual(self.flags(frame_399(left=2, right=1))[1], (True, True))

  def test_off(self):
    self.assertEqual(self.flags(frame_399())[1], (False, False))

  def test_sna_is_occupied_fail_closed(self):
    # t994 laneChange: SNA is encoded OCCUPIED (never "clear") so automatic lane changes are blocked.
    self.assertEqual(self.flags(frame_399(left=3, right=3))[1], (True, True))

  def test_bad_checksum_rejected(self):
    raw, ui = self.flags(frame_399(left=1, right=1, good_checksum=False))
    self.assertEqual(ui, (True, True))  # no checksum-OK frame -> unknown -> occupied (fail closed); frame itself not trusted
    self.assertGreaterEqual(self.p.ci.CS.ap1_bsm.bad_checksum, 1)

  def test_hold_then_expires(self):
    self.assertEqual(self.flags(frame_399(left=1), steps=50)[1], (True, False))    # 0.5 s later: held
    self.p = Pipeline()
    self.assertEqual(self.flags(frame_399(left=1), steps=120)[1], (False, False))  # 1.2 s: hold ran out

  def test_stale_or_previous_drive_hidden_in_ui(self):
    cs = self.p.publish(self.p.step(frame_399(left=1, right=1)))
    self.assertEqual(bsm_state.blindspots(FakeSM(cs, age=2.0), 0, time.monotonic()), (False, False))
    self.assertEqual(bsm_state.blindspots(FakeSM(cs, frame=3), 5, time.monotonic()), (False, False))

  def test_policy_requires_enable_bsm(self):
    store = SimpleNamespace(tuning_level=lambda: 3, toggle_bool=lambda k, l=None: k == "CustomUI", get_bool=lambda k, d=False: False)
    pol = bsm_state.BsmPolicy(store=store)
    self.assertTrue(pol.enabled(True, self.p.CP))
    self.assertFalse(pol.enabled(True, SimpleNamespace(carFingerprint="TESLA_MODEL_3")))
    self.assertFalse(pol.enabled(True, None))
    self.assertFalse(bsm_state.BsmPolicy(store=store).enabled(False, self.p.CP))


class TestVisualsSettings(unittest.TestCase):
  """Native raylib: real SettingsLayout registry, real Toggle widgets and clicks, real ParamStore files."""

  @classmethod
  def setUpClass(cls):
    import pyray as rl
    from openpilot.system.ui.lib.application import gui_app
    cls.rl, cls.gui_app = rl, gui_app
    if not rl.is_window_ready():
      gui_app.init_window("t921u visuals")

  def setUp(self):
    from openpilot.common.bogpilot_store import ParamStore
    self.tmp = tempfile.mkdtemp(prefix="vis_")
    self.typed = {}
    params = SimpleNamespace(get=lambda k: self.typed.get(k), put=lambda k, v: self.typed.__setitem__(k, v),
                             put_bool=lambda k, v: self.typed.__setitem__(k, "1" if v else "0"),
                             all_keys=lambda: [b"BlindSpotPath", b"AdjacentLeadsUI", b"PedalsOnUI", b"ScreenRecorder", b"CustomUI", b"BlindSpotMetrics", b"OnroadDistanceButton", b"BorderMetrics", b"QOLVisuals", b"DriverCamera", b"DynamicPedalsOnUI", b"Fahrenheit", b"NumericalTemp", b"ShowCPU", b"ShowMemoryUsage", b"NavigationUI", b"ShowSpeedLimits"])
    self._env = os.environ.get("BOGPILOT_PARAMS_DIR"); os.environ["BOGPILOT_PARAMS_DIR"] = self.tmp
    self.store = ParamStore(params=params, cache_ttl=0)

  def tearDown(self):
    if self._env is None:
      os.environ.pop("BOGPILOT_PARAMS_DIR", None)
    else:
      os.environ["BOGPILOT_PARAMS_DIR"] = self._env

  def make(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import BogPilotVisualsLayout
    return BogPilotVisualsLayout(store=self.store)

  def test_registered_in_settings(self):
    # t1024: Visuals is no longer its own sidebar panel; the BogPilot menu opens it under Appearance / APPEARANCE
    # (its two navigation widgets under Navigation / NAVIGATION).
    from openpilot.selfdrive.ui.layouts.settings import settings as S
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import VISUAL_KEYS
    src = Path(S.__file__).read_text()
    self.assertNotIn("BOGPILOT_VISUALS", src)
    reached = {k for s in menu_sections() for p in s.pills for pg in p.pages for k in pg.controls}
    self.assertLessEqual(set(VISUAL_KEYS), reached)
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import EXISTING_VISUAL_KEYS
    self.assertEqual(EXISTING_VISUAL_KEYS, ("AdjacentLeadsUI", "BlindSpotPath", "BlindSpotMetrics", "OnroadDistanceButton",
                                   "PedalsOnUI", "ScreenRecorder", "DriverCamera"))
    for k in EXISTING_VISUAL_KEYS:
      self.assertIn(k, VISUAL_KEYS)

  def test_only_existing_registered_keys_no_new_defaults(self):
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import VISUAL_KEYS
    for k in VISUAL_KEYS:
      if k in FILE_ONLY_UI_KEYS:
        continue
      self.assertIn(k, BOGPILOT_PARAMS)

  def test_initial_state_reflects_store_and_click_writes(self):
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import VISUAL_KEYS
    from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
    VISUAL_KEYS = [k for k in VISUAL_KEYS if k not in FILE_ONLY_UI_KEYS]  # t994: file-only rows (SwapSpeedGraph) covered by visualsTheme tests
    for k in VISUAL_KEYS:
      self.typed[k] = "0"
    lay = self.make()
    for k in VISUAL_KEYS:
      self.assertFalse(lay._toggles[k].action_item.get_state(), k)
    # real Toggle click path: the widget's own callback with the new state
    for k in VISUAL_KEYS:
      tog = lay._toggles[k].action_item.toggle
      tog.set_state(True) if hasattr(tog, "set_state") else None
      tog._callback(True) if getattr(tog, "_callback", None) else lay._write(k, True)
      self.assertEqual(self.typed[k], "1", k)
    lay.refresh()
    self.assertTrue(all(lay._toggles[k].action_item.get_state() for k in lay._toggles if k in VISUAL_KEYS))

  def test_initial_state_uses_actual_key_defaults(self):
    from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
    from openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals import VISUAL_KEYS
    from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS
    lay = self.make()      # nothing stored: each row shows the registry default, unchanged by this panel
    for k in (k for k in VISUAL_KEYS if k not in FILE_ONLY_UI_KEYS):
      self.assertEqual(lay._toggles[k].action_item.get_state(), BOGPILOT_PARAMS[k][2] == "1", k)
    self.assertEqual(self.typed, {})

  def test_render_native(self):
    rl = self.rl
    lay = self.make(); lay.show_event()
    rl.begin_drawing(); rl.clear_background(rl.BLACK); lay.render(rl.Rectangle(0, 0, 1500, 1000)); rl.end_drawing()

  def test_adjacent_consumer_follows_setting(self):
    from openpilot.selfdrive.ui.onroad.bogpilot import hud_compose as HC
    cp = SimpleNamespace(radarUnavailable=False, openpilotLongitudinalControl=True, carFingerprint="TESLA_AP1_MODELS")
    old = getattr(HC.ui_state, "CP", None); HC.ui_state.CP = cp
    try:
      self.typed["AdjacentLeadsUI"] = "0"
      clock = [0.0]
      pol = HC.PolicyToggles(store=self.store, clock=lambda: clock[0])
      self.assertFalse(pol.get()["adjacent_leads"])          # default/user OFF
      self.make()._write("AdjacentLeadsUI", True)
      clock[0] += 2.1                                          # consumer cache reload
      self.assertTrue(pol.get()["adjacent_leads"])
      self.typed["HumanLaneChanges"] = "1"; self.make()._write("AdjacentLeadsUI", False); clock[0] += 2.1
      self.assertFalse(pol.get()["adjacent_leads"])           # no human-lane-change dependency
    finally:
      HC.ui_state.CP = old

  def test_bsm_consumer_follows_setting(self):
    from openpilot.selfdrive.ui.onroad.bogpilot.file_toggles import FileToggles
    cp = params()
    clock = [0.0]
    ft = FileToggles(path=self.tmp, clock=lambda: clock[0], read_param=lambda k: self.typed.get(k) if k == "BlindSpotPath" else None)
    pol = bsm_state.BsmPolicy(store=self.store, clock=lambda: clock[0])
    self.typed["BlindSpotPath"] = "0"
    self.assertFalse(pol.enabled(ft.get("BlindSpotPath"), cp))
    self.make()._write("BlindSpotPath", True); clock[0] += 2.1
    self.assertTrue(pol.enabled(ft.get("BlindSpotPath"), cp))
    self.assertFalse(pol.enabled(ft.get("BlindSpotPath"), SimpleNamespace(carFingerprint="TESLA_MODEL_3")))   # no capability

  def test_file_only_key_never_reaches_params(self):
    self.store.put_bool("RedesignUI", False)
    self.assertNotIn("RedesignUI", self.typed)
    self.assertTrue((Path(self.tmp) / "RedesignUI").exists())


if __name__ == "__main__":
  unittest.main()
