"""The Comma Pedal row (Settings > Vehicle Controls) follows the CAN stream even when the Pre-AP CarController never runs.

PedalDetected / PedalSeenTs are written by PreApCarState (display only). Before this, only PreApCarController wrote them,
so with the openpilot toggle off, passive/dashcam, or controlsd not up the row said "Not detected" with a live pedal.
Synthetic frames from the DBC packer only; the clock is faked so the 0.5 s IDX timeout and the 3 s UI freshness are real.
"""
from types import SimpleNamespace

import pytest

from opendbc.can import CANDefine
from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.preap import calib, params
from opendbc.car.tesla_ap1.preap import carstate as cs_mod
from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys
from opendbc.car.tesla_ap1.values import CAR, DBC

STEP_S = 0.01   # card.py rate


class _Clock:
  """Wall clock (time.time) and monotonic clock (time.monotonic) advance together; the wall clock can also jump."""
  def __init__(self):
    self.t = 1_700_000_000.0
    self.m = 500_000.0

  def time(self):
    return self.t

  def monotonic(self):
    return self.m

  def live(self, dt=0.0, dm=None):
    return calib.pedal_live(self.t + dt, self.m + (dt if dm is None else dm))


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  clk = _Clock()
  monkeypatch.setattr(cs_mod, "time", SimpleNamespace(time=clk.time, monotonic=clk.monotonic))
  return clk


class _Car:
  def __init__(self, clk, ibooster=False):
    if ibooster:
      params.set_bool(PreApParamKeys.HAS_IBOOSTER, True)
    self.clk = clk
    self.ibooster = ibooster
    CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
    self.cs = PreApCarState(CP)
    self.parsers = PreApCarState.get_can_parsers(CP)
    dbc = DBC[CAR.TESLA_PREAP_MODELS][Bus.chassis]
    self.pk = CANPacker(dbc)
    dv = CANDefine(dbc).dv
    park = next(k for k, v in dv["DI_torque2"]["DI_gear"].items() if v == "DI_GEAR_P")
    self.base = {"DI_torque2": {"DI_gear": park}, "BrakeMessage": {"driverBrakeStatus": 1}, "SDM1": {}, "DI_state": {},
                 "EPAS_sysStatus": {}, "ESP_B": {}, "DI_torque1": {}, "STW_ANGLHP_STAT": {}, "GTW_carState": {}, "STW_ACTN_RQ": {}}
    self.idx = 0
    self.nanos = 0
    self.i = 0

  def run(self, steps, pedal_bus=2, idx_moves=True):
    for _ in range(steps):
      self.clk.t += STEP_S
      self.clk.m += STEP_S
      self.nanos += int(STEP_S * 1e9)
      frames = []
      for n, v in self.base.items():
        a, dat, _ = self.pk.make_can_msg(n, 0, v)
        frames.append((a, dat, 0))
      if self.ibooster and self.i % 2 == 0:
        a, dat, _ = self.pk.make_can_msg("ECU_BrakeStatus", 0, {"BrakeOK": 1, "Status": 0, "BrakePedalPosition": 3.0})
        frames.append((a, dat, 0))
      if pedal_bus is not None and self.i % 2 == 0:
        if idx_moves:
          self.idx = (self.idx + 1) % 16
        a, dat, _ = self.pk.make_can_msg("GAS_SENSOR", pedal_bus, {"INTERCEPTOR_GAS": 0.0, "INTERCEPTOR_GAS2": 0.0, "STATE": 0, "IDX": self.idx})
        frames.append((a, dat, pedal_bus))
      for p in self.parsers.values():
        p.update([(self.nanos, frames)])
      self.cs.op_enabled = False
      self.cs.update(self.parsers)   # CarState only: no CarController anywhere in this file
      self.i += 1


@pytest.mark.parametrize("ibooster", [False, True])
@pytest.mark.parametrize("bus", [0, 2])
def test_status_is_written_with_no_controller(_env, ibooster, bus):
  car = _Car(_env, ibooster)
  car.run(200, pedal_bus=bus)
  assert car.cs.preap_pedal_detected
  assert params.get_bool(PreApParamKeys.PEDAL_DETECTED)
  assert _env.live()


@pytest.mark.parametrize("ibooster", [False, True])
def test_no_pedal_or_a_stuck_counter_is_not_detected(_env, ibooster):
  car = _Car(_env, ibooster)
  car.run(200, pedal_bus=None)
  assert not params.get_bool(PreApParamKeys.PEDAL_DETECTED)
  assert not _env.live()
  car2 = _Car(_env, ibooster)
  car2.run(200, pedal_bus=2, idx_moves=False)   # IDX never changes after the first frame: times out
  assert not car2.cs.preap_pedal_detected
  assert not params.get_bool(PreApParamKeys.PEDAL_DETECTED)


def test_a_pedal_that_stops_goes_not_detected(_env):
  car = _Car(_env)
  car.run(200, pedal_bus=2)
  assert params.get_bool(PreApParamKeys.PEDAL_DETECTED)
  car.run(200, pedal_bus=None)   # 2 s of silence: the 0.5 s IDX timeout clears it
  assert not car.cs.preap_pedal_detected
  assert not params.get_bool(PreApParamKeys.PEDAL_DETECTED)
  assert not _env.live()


def test_the_ui_goes_stale_3_s_after_the_car_process_stops(_env):
  car = _Car(_env)
  car.run(200, pedal_bus=2)
  age = _env.t - params.get_float(PreApParamKeys.PEDAL_SEEN_TS)
  assert _env.live(calib.PEDAL_LIVE_S - 0.1 - age)
  assert not _env.live(calib.PEDAL_LIVE_S + 0.1)   # PedalDetected stays latched, the heartbeat does not


def test_the_heartbeat_is_throttled_to_once_a_second(_env, monkeypatch):
  writes = []
  real = cs_mod.set_float
  monkeypatch.setattr(cs_mod, "set_float", lambda k, v: (writes.append((k, v)), real(k, v)))
  car = _Car(_env)
  car.run(500, pedal_bus=2)   # 5 s
  ts = [v for k, v in writes if k == PreApParamKeys.PEDAL_SEEN_TS]
  assert 4 <= len(ts) <= 6
  assert all(b - a >= 1.0 - 1e-6 for a, b in zip(ts, ts[1:], strict=False))


@pytest.mark.parametrize("jump_s", [-3600.0, -2.0, 3600.0])
def test_a_wall_clock_jump_does_not_stop_the_heartbeat_or_hide_a_live_pedal(_env, monkeypatch, jump_s):
  writes = []
  real = cs_mod.set_float
  monkeypatch.setattr(cs_mod, "set_float", lambda k, v: (writes.append((k, v)), real(k, v)))
  car = _Car(_env)
  car.run(200, pedal_bus=2)
  before = len(writes)
  _env.t += jump_s   # GPS / NTP sets the wall clock; time.monotonic() does not move
  car.run(300, pedal_bus=2)   # 3 s more
  mono = [v for k, v in writes[before:] if k == PreApParamKeys.PEDAL_SEEN_MONO]
  assert 2 <= len(mono) <= 4   # still about once a second
  assert _env.live()
  # The reader alone: a wall stamp from before a backward jump (negative age) still reads live on the monotonic stamp.
  params.set_float(PreApParamKeys.PEDAL_SEEN_TS, _env.t + 3600.0)
  assert _env.live()
  # ... and a stale monotonic stamp with no fresh wall stamp does not.
  assert not _env.live(dt=0.0, dm=calib.PEDAL_LIVE_S + 0.1)


def test_a_read_only_params_dir_does_not_stop_carstate(_env, monkeypatch):
  def boom(*_a, **_k):
    raise OSError("read-only")
  monkeypatch.setattr(cs_mod, "set_bool", boom)
  car = _Car(_env)
  car.run(50, pedal_bus=2)
  assert car.cs.preap_pedal_detected


def test_the_controller_no_longer_writes_the_status(_env):
  from opendbc.car.tesla_ap1.preap.carcontroller import PreApCarController
  CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
  cc = PreApCarController(DBC[CAR.TESLA_PREAP_MODELS], CP)
  assert cc._update_detection_and_calib(SimpleNamespace(preap_pedal_detected=True, preap_pedal_raw=0.8, di_gas=0.0)) is True
  assert not (params._params_dir / PreApParamKeys.PEDAL_DETECTED).exists()
  assert not (params._params_dir / PreApParamKeys.PEDAL_SEEN_TS).exists()
