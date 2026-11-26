"""AP1 Model X with openpilot longitudinal: engage from 0 mph as on the Model S (AP1StandstillEngage, panda standstill bit 16).
The Model X with Disable openpilot Longitudinal Control on (stock TACC) is unchanged: no standstill bit
and no standby DAS_control."""
from collections import deque
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.actuator_plan import AP1_STANDBY_ACCEL_MAX, AP1_STANDBY_ACCEL_MIN
from opendbc.car.tesla_ap1.carstate import CarState
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.safety_flags import flags_for_candidate
from opendbc.car.tesla_ap1.tests.ap1_harness import make_controller, record_requests
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.values import CAR

X = CAR.TESLA_AP1_MODELX
S = CAR.TESLA_AP1_MODELS
MOBILEYE = {0x399: 8, 0x2B9: 8, 0x488: 4}
AP1_FLAG, LONG_FLAG, STANDSTILL_FLAG = 8, 1, 16
X_LONG_STANDSTILL = AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG
GearShifter = structs.CarState.GearShifter


@pytest.fixture(autouse=True)
def _files(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "_ap1_standstill_path", tmp_path / "AP1StandstillEngage")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (tmp_path / "Disable1", tmp_path / "Disable2"))
  return tmp_path


def _x():
  return CarInterface.get_params(X, {0: dict(TINKLA_AP1_MODELX), 2: dict(MOBILEYE)}, [], False, False, False)


# Car start: toggle, interface and safety param

def test_toggle_covers_the_x_and_the_s(_files):
  assert toggles.ap1_standstill_engage(X) is True and toggles.ap1_standstill_engage(S) is True   # no file: on
  for text in ("0", "false", "off", " off \n"):
    assert toggles.ap1_standstill_engage(X, stored=text) is False
    assert toggles.ap1_standstill_engage(S, stored=text) is False
  for fp in (CAR.TESLA_PREAP_MODELS, "TESLA_MODEL_Y", "", None):
    assert toggles.ap1_standstill_engage(fp) is False and toggles.ap1_standstill_engage(fp, stored="1") is False


def test_x_with_openpilot_long_gets_the_standstill_bit_by_default():
  cp = _x()
  assert cp.openpilotLongitudinalControl is True
  assert cp.safetyConfigs[0].safetyParam == X_LONG_STANDSTILL      # same 25 as the Model S
  assert cp.minEnableSpeed == -1.0


def test_x_standstill_off_keeps_long_without_the_bit(_files):
  (_files / "AP1StandstillEngage").write_text("0")
  cp = _x()
  assert cp.openpilotLongitudinalControl is True and cp.safetyConfigs[0].safetyParam == AP1_FLAG | LONG_FLAG


def test_x_stock_tacc_unchanged(_files):
  (_files / "AP1StandstillEngage").write_text("1")
  (_files / "Disable1").write_text("1")                              # Disable openpilot Longitudinal Control on
  cp = _x()
  assert cp.openpilotLongitudinalControl is False and cp.safetyConfigs[0].safetyParam == AP1_FLAG


def test_x_retired_file_off_is_ignored_by_the_car(_files):
  # The old AP1XOpenpilotLong Off is carried over to Disable at start; the car itself reads only Disable, as on the Model S.
  (_files / "AP1StandstillEngage").write_text("1")
  (_files / "AP1XOpenpilotLong").write_text("0")
  cp = _x()
  assert cp.openpilotLongitudinalControl is True and cp.safetyConfigs[0].safetyParam == AP1_FLAG | LONG_FLAG | STANDSTILL_FLAG


def test_flags_helper_standstill_only_with_x_long():
  assert flags_for_candidate(X, standstill=True) == (AP1_FLAG,)                       # lateral only: never the bit
  assert flags_for_candidate(X, standstill=True, x_long=True) == (X_LONG_STANDSTILL,)
  assert flags_for_candidate(X, x_long=True) == (AP1_FLAG | LONG_FLAG,)
  assert flags_for_candidate(S, standstill=True) == flags_for_candidate(X, standstill=True, x_long=True)


# Controller: standby DAS_control while disengaged in Drive

def _cs(stock_ap=False, gear=GearShifter.drive):
  return SimpleNamespace(
    out=SimpleNamespace(steeringAngleDeg=0.0, vEgo=0.0, vEgoRaw=0.0, gasPressed=False, standstill=True, gearShifter=gear),
    steer_warning="EAC_ERROR_IDLE", hands_on_level=0, eac_fault=False, eac_status="EAC_AVAILABLE",
    acc_state=2, das_control_counters=deque([1]), msg_stw_actn_req={}, cluster_stock={},
    stock_steer_counters=[3], stock_ap_active=stock_ap,
  )


def _standby_frames(controller, **cs):
  CC = structs.CarControl()
  CC.enabled = False
  reqs = record_requests(controller)
  controller.update(CC, _cs(**cs), 10_000_000)
  return [vals for name, vals, _bus in reqs if name == "DAS_control"]


def test_x_long_controller_sends_the_model_s_standby_frame():
  x = make_controller(long=True, fingerprint=X, safety_param=X_LONG_STANDSTILL)
  s = make_controller(long=True, fingerprint=S, safety_param=X_LONG_STANDSTILL)
  assert x.ap1_standstill is True and s.ap1_standstill is True
  fx, fs = _standby_frames(x), _standby_frames(s)
  assert fx and fx == fs
  assert fx[0]["DAS_setSpeed"] == 0 and fx[0]["DAS_accState"] == 4
  assert fx[0]["DAS_accelMin"] == pytest.approx(AP1_STANDBY_ACCEL_MIN, abs=0.04)
  assert fx[0]["DAS_accelMax"] == pytest.approx(AP1_STANDBY_ACCEL_MAX, abs=0.04)


def test_x_no_standby_while_stock_autopilot_or_not_in_drive():
  x = make_controller(long=True, fingerprint=X, safety_param=X_LONG_STANDSTILL)
  assert _standby_frames(x, stock_ap=True) == []
  x = make_controller(long=True, fingerprint=X, safety_param=X_LONG_STANDSTILL)
  assert _standby_frames(x, gear=GearShifter.park) == []


def test_x_without_openpilot_long_never_standstill_even_with_the_bit():
  off = make_controller(long=False, fingerprint=X, safety_param=X_LONG_STANDSTILL)
  assert off.ap1_standstill is False
  assert _standby_frames(off) == []
  no_bit = make_controller(long=True, fingerprint=X, safety_param=AP1_FLAG | LONG_FLAG)
  assert no_bit.ap1_standstill is False
  assert _standby_frames(no_bit) == []


# CarState: stock Autopilot state read on the X (gates the standby frame)

def _send_cam(parser, values):
  from opendbc.can.packer import CANPacker
  addr, dat, _bus = CANPacker("tesla_ap1_can").make_can_msg("AutopilotStatus", parser.bus, values)
  parser.update([(0, [(addr, dat, parser.bus)])])


@pytest.mark.parametrize("fp", [X, S])
def test_stock_autopilot_active_read_on_x_and_s(fp):
  from opendbc.car import Bus
  cp = SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=True)
  state = CarState(cp)
  parsers = CarState.get_can_parsers(cp)
  _send_cam(parsers[Bus.cam], {"autopilotStatus": 3})
  state.update(parsers)
  assert state.stock_ap_active is True
  _send_cam(parsers[Bus.cam], {"autopilotStatus": 2})
  state.update(parsers)
  assert state.stock_ap_active is False


# Panda: the AP1 safety mode keys only on the flag bits, so the X with 25 gets exactly the Model S standstill rule.

def _libsafety():
  try:
    from opendbc.safety.tests.libsafety import libsafety_py
    return libsafety_py
  except Exception as e:  # libsafety is built by scons (AGNOS VM); a plain checkout may not have it
    pytest.skip(f"libsafety not built: {e}")


def _das(set_speed_kph, acc_state, accel_min, accel_max, jerk_min=-0.46, jerk_max=0.476):
  v = (int(round(set_speed_kph / 0.1)) & 0xFFF) | ((acc_state & 0xF) << 12)
  v |= (int(round((jerk_min + 15.232) / 0.03)) & 0x1FF) << 18
  v |= (int(round(jerk_max / 0.059)) & 0xFF) << 27
  v |= (int(round((accel_min + 15) / 0.04)) & 0x1FF) << 35
  v |= (int(round((accel_max + 15) / 0.04)) & 0x1FF) << 44
  dat = bytearray(v.to_bytes(8, "little"))
  dat[7] = (0xb9 + 0x02 + sum(dat[:7])) & 0xFF
  return bytes(dat)


def test_panda_accepts_the_standby_frame_with_the_x_param_only_with_the_bit():
  lp = _libsafety()
  l = lp.libsafety
  tesla = int(structs.CarParams.SafetyModel.tesla)
  standby = _das(0.0, 4, AP1_STANDBY_ACCEL_MIN, 0.0)
  for param, ok in ((flags_for_candidate(X, standstill=True, x_long=True)[0], True),
                    (flags_for_candidate(X, x_long=True)[0], False),
                    (flags_for_candidate(X, standstill=True)[0], False)):
    l.set_timer(1000)
    assert l.set_safety_hooks(tesla, param) == 0
    l.set_controls_allowed(False)
    assert bool(l.safety_tx_hook(lp.make_CANPacket(0x2b9, 0, standby))) is ok, param
    # Any other shape while not engaged stays blocked, bit or not.
    assert not l.safety_tx_hook(lp.make_CANPacket(0x2b9, 0, _das(0.0, 4, -1.4, 0.5)))
    assert not l.safety_tx_hook(lp.make_CANPacket(0x2b9, 0, _das(30.0, 4, -1.4, 0.0)))
