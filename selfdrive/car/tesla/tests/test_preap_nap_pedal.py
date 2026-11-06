"""NAP-style Pre-AP pedal longitudinal unit tests (host-safe).

Covers PedalZeroTorque learn, compute_pedal_command deadband/ramps/hysteresis,
VirtualDAS feedforward, and PedalAuthority FSM. No CAN / no device.
"""
from __future__ import annotations

import math

from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.car.tesla.preap.pedal_authority import (
  PedalAuthority, PedalAuthorityState, PedalCommandAction,
)
from openpilot.selfdrive.car.tesla.preap.pedal_controller import (
  PedalZeroTorque, compute_pedal_command,
)
from openpilot.selfdrive.car.tesla.preap.pedal_feedback import PedalFeedback
from openpilot.selfdrive.car.tesla.preap.vdas_constants import (
  ACCEL_DEADBAND, PEDAL_DI_ZERO, PEDAL_HYST_GAP,
  PEDAL_RAMP_RATE_DOWN, PEDAL_RAMP_RATE_UP,
)
from openpilot.selfdrive.car.tesla.preap.virtual_das import VirtualDAS


class _FakeFeedback:
  def __init__(self, available=True, state=0, idx=0):
    self.available = available
    self.interceptor_state = state
    self.idx = idx


def test_zero_torque_learns_above_10mph_in_deadband():
  zt = PedalZeroTorque()
  assert zt.get(0.0) == PEDAL_DI_ZERO
  v = 12.0 * CV.MPH_TO_MS
  # Settle 25 @50Hz then adapt 0.1 DI/update toward observed coast DI.
  for _ in range(25 + 35):
    zt.update(-5.0, current_pedal_di=3.0, v_ego=v, control_active=True, accel_command=0.0)
  assert abs(zt.value - 3.0) < 0.5
  assert zt.get(4.0 * CV.MPH_TO_MS) == PEDAL_DI_ZERO


def test_zero_torque_ignores_large_accel_command():
  zt = PedalZeroTorque()
  v = 15.0 * CV.MPH_TO_MS
  for _ in range(40):
    zt.update(-5.0, current_pedal_di=4.0, v_ego=v, control_active=True,
              accel_command=ACCEL_DEADBAND + 0.1)
  assert zt.value == PEDAL_DI_ZERO


def test_compute_pedal_deadband_and_ramps():
  import openpilot.selfdrive.car.tesla.preap.pedal_controller as pc
  pc.current_pedal_transform = lambda: (0.0, 1.0)  # type: ignore
  pc._zero_torque = PedalZeroTorque()
  cmd, di = compute_pedal_command(0.0, v_ego=20.0, prev_pedal_di=5.0)
  assert math.isfinite(cmd) and math.isfinite(di)
  _, di_up = compute_pedal_command(2.5, v_ego=20.0, prev_pedal_di=0.0)
  assert di_up <= PEDAL_RAMP_RATE_UP + 1e-6
  _, di_dn = compute_pedal_command(-1.5, v_ego=20.0, prev_pedal_di=10.0)
  assert di_dn >= 10.0 - PEDAL_RAMP_RATE_DOWN - 1e-6


def test_compute_pedal_hysteresis_holds():
  import openpilot.selfdrive.car.tesla.preap.pedal_controller as pc
  pc.current_pedal_transform = lambda: (0.0, 1.0)  # type: ignore
  pc._zero_torque = PedalZeroTorque()
  # IRIT: hold when |target_after_ramp - prev| < PEDAL_HYST_GAP.
  # Accel ≈0.355 → target DI ≈10.5 with zero_torque=0 / max≈74 @20 m/s.
  _, di = compute_pedal_command(0.355, v_ego=20.0, prev_pedal_di=10.0)
  assert di == 10.0
  _, di2 = compute_pedal_command(0.355, v_ego=20.0, prev_pedal_di=di)
  assert di2 == di
  assert PEDAL_HYST_GAP > 0


def test_vdas_feedforward_zero_and_positive():
  vdas = VirtualDAS(dt=0.02)
  vdas.reset(measured_accel=0.0, commanded_accel=0.0, pedal_di_init=0.0)
  di = 0.0
  for _ in range(10):
    di = vdas.update(0.0, v_ego=20.0, prev_pedal_di=di, a_ego=0.0,
                     orientation_ned=[0.0, 0.0, 0.0])
  assert abs(di) < 5.0
  for _ in range(40):
    di = vdas.update(1.0, v_ego=20.0, prev_pedal_di=di, a_ego=0.5,
                     orientation_ned=[0.0, 0.0, 0.0])
  assert di > 5.0


def test_pedal_authority_acquire_enable_release():
  auth = PedalAuthority()
  fb = _FakeFeedback(available=True, state=0, idx=1)
  action = auth.update(True, fb)
  assert action == PedalCommandAction.ACQUIRE
  assert auth.state == PedalAuthorityState.ACTIVE
  assert auth.update(True, fb) == PedalCommandAction.ENABLE
  assert auth.update(False, fb) == PedalCommandAction.RELEASE
  assert auth.state == PedalAuthorityState.INACTIVE


def test_pedal_authority_reset_then_fail():
  auth = PedalAuthority()
  fb = _FakeFeedback(available=False, state=1, idx=0)
  assert auth.update(True, fb) == PedalCommandAction.RESET
  assert auth.state == PedalAuthorityState.ACQUIRING
  action = PedalCommandAction.NONE
  for _ in range(PedalAuthority.MAX_RESET_ATTEMPTS):
    action = auth.update(True, fb)
  assert action == PedalCommandAction.FAILURE
  assert auth.state == PedalAuthorityState.FAILED



def test_pedal_authority_keepalive_clears_timeout():
  """FAULT_TIMEOUT (STATE=5) keeps getting ENABLE=0 keepalives until NO_FAULT.

  Tester rlogs showed 4 RESET frames then FAILED; the pedal briefly reached
  STATE=0 after those frames, but the FSM had already latched FAILED.
  """
  auth = PedalAuthority()
  fb = _FakeFeedback(available=True, state=5, idx=0)
  assert auth.update(True, fb) == PedalCommandAction.RESET
  assert auth.state == PedalAuthorityState.ACQUIRING
  for i in range(1, 40):
    fb.idx = i % 16
    fb.interceptor_state = 5
    assert auth.update(True, fb) == PedalCommandAction.RESET
    assert auth.state == PedalAuthorityState.ACQUIRING
  fb.idx = 8
  fb.interceptor_state = 0
  assert auth.update(True, fb) == PedalCommandAction.ACQUIRE
  assert auth.state == PedalAuthorityState.ACTIVE


def test_pedal_authority_keepalive_startup_fault():
  auth = PedalAuthority()
  fb = _FakeFeedback(available=True, state=4, idx=3)
  for i in range(20):
    fb.idx = (3 + i) % 16
    assert auth.update(True, fb) == PedalCommandAction.RESET
    assert auth.state == PedalAuthorityState.ACQUIRING
  fb.interceptor_state = 0
  fb.idx = 10
  assert auth.update(True, fb) == PedalCommandAction.ACQUIRE
  assert auth.state == PedalAuthorityState.ACTIVE


def test_pedal_feedback_available_during_timeout_state():
  fb = PedalFeedback()
  now = 10_000
  msg = {"INTERCEPTOR_GAS": 0.0, "INTERCEPTOR_GAS2": 0.0, "STATE": 5, "IDX": 1}
  assert fb.update(msg, now) is True
  msg = dict(msg)
  msg["IDX"] = 2
  assert fb.update(msg, now + 20) is True
  assert fb.available is True
  assert fb.timeout is False
  assert fb.interceptor_state == 5



def test_gas_sensor_dbc_state_is_high_nibble():
  """Byte 4 is (STATE << 4) | IDX. DBC must label the high nibble STATE."""
  from pathlib import Path
  src = (Path(__file__).resolve().parents[4] / "opendbc" / "tesla_can.dbc").read_text()
  block = src.split("BO_ 1362 GAS_SENSOR", 1)[1].split("BO_", 1)[0]
  assert "SG_ STATE : 39|4@0+" in block
  assert "SG_ IDX : 35|4@0+" in block


def test_pedal_feedback_gas_pressed_threshold():
  fb = PedalFeedback()
  fb.interceptor_value = 3.0
  assert fb.gas_pressed is True
  fb.interceptor_value = 0.5
  assert fb.gas_pressed is False


def test_carcontroller_uses_vdas_not_legacy_map():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[1] / "preap" / "carcontroller.py").read_text()
  assert "PreAPLongController" in src
  assert "accel_to_pedal_command" not in src


def test_long_controller_source_has_vdas_and_authority():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[1] / "preap" / "long_controller.py").read_text()
  assert "VirtualDAS" in src
  assert "PedalAuthority" in src
  assert "get_zero_torque" in src
  assert "ENGAGE_GRACE" in src



def test_engage_grace_constants_match_nap():
  from openpilot.selfdrive.car.tesla.preap.pedal_authority import (
    ENGAGE_GRACE_FRAMES, ENGAGE_GRACE_PEDAL_RAMP_RATE_UP,
  )
  assert ENGAGE_GRACE_FRAMES == 50  # 0.5 s @ 100 Hz
  assert ENGAGE_GRACE_PEDAL_RAMP_RATE_UP == 0.9


def test_engage_grace_caps_accel_and_ramps():
  """ACQUIRE starts grace: accel_cap = progress * engage_a_max, slow pedal ramp."""
  from types import SimpleNamespace
  from openpilot.selfdrive.car.tesla.preap.long_controller import PreAPLongController
  from openpilot.selfdrive.car.tesla.preap.pedal_can import PedalCommandCounter
  from openpilot.selfdrive.car.tesla.preap.pedal_authority import (
    ENGAGE_GRACE_FRAMES, ENGAGE_GRACE_PEDAL_RAMP_RATE_UP,
  )
  from openpilot.selfdrive.car.tesla.preap.pedal_feedback import PedalFeedback

  ctrl = PreAPLongController(pedal_counter=PedalCommandCounter(), pedal_bus_fn=lambda: 0)

  fb = PedalFeedback()
  fb.available = True
  fb.interceptor_state = 0
  fb.idx = 1
  fb.torque_level = 0.0

  CS = SimpleNamespace(
    out=SimpleNamespace(vEgo=20.0, aEgo=0.0, gasPressed=False),
    real_brake_pressed=False,
    pedal=fb,
    pedal_unavailable=False,
    pedal_interceptor_value=0.0,
    pedal_first_enabled_mono_time=0,
    cruise_buttons=0,
    prev_cruise_buttons=0,
    preap_cc_cancel_needed=False,
  )
  CC = SimpleNamespace(
    enabled=True, longActive=True,
    orientationNED=[0.0, 0.0, 0.0],
    actuators=SimpleNamespace(accel=2.0),
  )

  # Frame 0 (even): ACQUIRE
  can0 = ctrl.update(CC, CS, frame=0, long_ok=True, now_nanos=1)
  assert can0
  assert ctrl.preap_long_engage_frame == 0
  assert ctrl.preap_long_handoff_slew_active is True
  di0 = ctrl.prev_pedal_di

  # Next even frame still in grace — DI change capped by ENGAGE_GRACE_PEDAL_RAMP_RATE_UP
  ctrl.update(CC, CS, frame=2, long_ok=True, now_nanos=2)
  assert ctrl.prev_pedal_di - di0 <= ENGAGE_GRACE_PEDAL_RAMP_RATE_UP + 1e-6
  assert ctrl.engage_a_max > 0.0

  # Drive through grace window
  for f in range(4, ENGAGE_GRACE_FRAMES + 40, 2):
    ctrl.update(CC, CS, frame=f, long_ok=True, now_nanos=f)
  assert (ENGAGE_GRACE_FRAMES + 38) - ctrl.preap_long_engage_frame >= ENGAGE_GRACE_FRAMES


def test_ff_default_table_works_without_json():
  """VirtualDAS FeedforwardModel uses in-tree DEFAULT_TABLE when JSON absent."""
  from openpilot.selfdrive.car.tesla.preap.ff_table_default import (
    DEFAULT_TABLE, SPEED_BP, ACCEL_BP,
  )
  from openpilot.selfdrive.car.tesla.preap.virtual_das import FeedforwardModel, FF_TABLE_PATH

  ff = FeedforwardModel(table_path="/nonexistent/vdas_ff_table.json")
  assert ff.speed_bp == list(SPEED_BP)
  assert ff.accel_bp == list(ACCEL_BP)
  assert ff.table == [list(r) for r in DEFAULT_TABLE]
  di = ff.get(1.0, 20.0, zero_torque_di=0.0)
  assert di > 0.0
  assert "vdas_ff_table" in FF_TABLE_PATH


def test_long_controller_source_has_engage_grace_ramp():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[1] / "preap" / "long_controller.py").read_text()
  assert "ENGAGE_GRACE_FRAMES" in src
  assert "ENGAGE_GRACE_PEDAL_RAMP_RATE_UP" in src
  assert "freeze_integrator" in src
  assert "accel_effort_limits" in src
  assert "preap_long_handoff_slew_active" in src


def test_preap_hud_chimes_and_regen_demand():
  from openpilot.selfdrive.car.tesla.preap.hud import (
    PreAPChimeState, RegenDemandCheck, update_preap_chimes,
  )
  chimes, prev = update_preap_chimes(lat_engaged=True, long_engaged=True, prev=PreAPChimeState())
  assert chimes.long_engage and chimes.lat_engage
  chimes, prev = update_preap_chimes(lat_engaged=True, long_engaged=False, prev=prev)
  assert chimes.long_disengage and not chimes.lat_disengage

  regen = RegenDemandCheck()
  # Below envelope floor at speed should accumulate then trip.
  tripped = False
  for _ in range(50):
    tripped = regen.update(pedal_long_active=True, brake_pressed=False, a_target=-3.0, v_ego=20.0)
  assert tripped
  # Brake clears.
  assert not regen.update(pedal_long_active=True, brake_pressed=True, a_target=-3.0, v_ego=20.0)


def test_frogpilot_pedal_hud_events_registered():
  from openpilot.selfdrive.controls.lib.events import FROGPILOT_EVENTS, FrogPilotEventName
  for name in ("pedalMaxRegen", "pedalCruiseEnabled", "pedalCruiseDisabled", "pedalUnavailable"):
    assert hasattr(FrogPilotEventName, name), name
    assert getattr(FrogPilotEventName, name) in FROGPILOT_EVENTS
  alert = FROGPILOT_EVENTS[FrogPilotEventName.pedalMaxRegen]
  from openpilot.selfdrive.controls.lib.events import ET
  assert "Regen Limit Reached" in alert[ET.WARNING].alert_text_1
  assert "Press Brake to Slow Down" in alert[ET.WARNING].alert_text_2
  unavail = FROGPILOT_EVENTS[FrogPilotEventName.pedalUnavailable]
  assert "Pedal Control Unavailable" in unavail[ET.WARNING].alert_text_1
  assert "Speed Control Disabled" in unavail[ET.WARNING].alert_text_2


def test_double_pull_first_lat_second_long():
  from cereal import car
  from openpilot.selfdrive.car.tesla.preap.engagement import (
    DoublePullEngagement, DOUBLE_PULL_WINDOW_MS,
  )
  ButtonType = car.CarState.ButtonEvent.Type

  def ev(pressed, t=ButtonType.setCruise):
    e = car.CarState.ButtonEvent.new_message()
    e.type = t
    e.pressed = pressed
    return e

  dp = DoublePullEngagement()
  # Toggle off: identity
  events = [ev(True), ev(False)]
  out = dp.filter_button_events(events, enabled=False, now_ms=1000, brake_pressed=False, cancel=False)
  assert len(out) == 2 and not dp.lat_only

  # First pull: swallow press+release, arm lat_only
  out = dp.filter_button_events([ev(True)], enabled=True, now_ms=2000, brake_pressed=False, cancel=False)
  assert out == [] and dp.lat_only and dp.pending
  out = dp.filter_button_events([ev(False)], enabled=True, now_ms=2050, brake_pressed=False, cancel=False)
  assert out == [] and dp.lat_only

  # Second pull within window: keep events (release → buttonEnable)
  out = dp.filter_button_events([ev(True)], enabled=True, now_ms=2000 + DOUBLE_PULL_WINDOW_MS - 50,
                                brake_pressed=False, cancel=False)
  assert len(out) == 1 and out[0].pressed and not dp.lat_only and dp.long_latched
  out = dp.filter_button_events([ev(False)], enabled=True, now_ms=2000 + DOUBLE_PULL_WINDOW_MS - 40,
                                brake_pressed=False, cancel=False)
  assert len(out) == 1 and not out[0].pressed and dp.long_latched

  # Brake drops long, keeps lat
  dp.filter_button_events([], enabled=True, now_ms=3000, brake_pressed=True, cancel=False)
  assert dp.lat_only and not dp.long_latched




def test_double_pull_is_file_backed_not_params_key():
  """TeslaPreApDoublePull must NOT be in frogpilot_default_params.

  July prebuilt params_pyx.so raises UnknownKeyName at manager_init for any
  new key in that list (bench crash on 2ed8ca8a2). Match Radar VIN / Upside
  Down: file-backed under /data/params_bogpilot via preap.params.
  """
  import re
  from pathlib import Path
  # Parse the defaults list from source — importing frogpilot_variables pulls
  # car_helpers/sentry and is fragile under bare PYTHONPATH.
  src = Path(__file__).parents[4] / "frogpilot/common/frogpilot_variables.py"
  # parents: tests -> tesla -> car -> selfdrive -> repo root? 
  # __file__ = .../selfdrive/car/tesla/tests/test_preap_nap_pedal.py
  # parents[0]=tests [1]=tesla [2]=car [3]=selfdrive [4]=repo root
  text = src.read_text(encoding="utf-8")
  m = re.search(r"frogpilot_default_params:.*?=\s*\[(.*?)\n\]", text, re.S)
  assert m, "frogpilot_default_params not found"
  keys = set(re.findall(r'\(\s*"([^"]+)"', m.group(1)))
  assert "TeslaPreApDoublePull" not in keys

  from openpilot.selfdrive.car.tesla.preap.params import PreApParamKeys, get_bool, DEFAULTS
  assert PreApParamKeys.DOUBLE_PULL == "TeslaPreApDoublePull"
  assert DEFAULTS[PreApParamKeys.DOUBLE_PULL] is True
  # Absent file => default ON
  assert get_bool(PreApParamKeys.DOUBLE_PULL, True) is True


def test_double_pull_off_does_not_fight_aol():
  """When TeslaPreApDoublePull is off, engagement must be a pure pass-through."""
  from cereal import car
  from openpilot.selfdrive.car.tesla.preap.engagement import DoublePullEngagement
  ButtonType = car.CarState.ButtonEvent.Type
  dp = DoublePullEngagement()
  dp.pending = True
  dp.lat_only = True
  e = car.CarState.ButtonEvent.new_message()
  e.type = ButtonType.setCruise
  e.pressed = True
  out = dp.filter_button_events([e], enabled=False, now_ms=5000, brake_pressed=False, cancel=False)
  assert out == [e]
  assert not dp.pending and not dp.lat_only
