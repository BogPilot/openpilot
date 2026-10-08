"""AP1 milestone 3 / 4 wiring (BogPilot bogpilot-tesla fe06ec7a), StarPilot (BogStar) layout.

Runs the AP1 CarInterface with the real opendbc CANParser / CANPacker (harness from
test_tesla_ap1_milestone2.py) for the pieces BogPilot added after milestone 2:
accel smoothing and the standstill hold floor, comfort jerk limits, the neutral DAS_control on a
gas press, 0x488 counter sync with the stock DAS, the EPB EAC revoke fault, DI_cruiseSet as the
cruise set, the raw SpdCtrlLvr_Stat level, the FWD-hold Experimental toggle and the cluster set
speed overlay (DAS_accSpeedLimit, DBC factor 0.4).

Unit tests only. Not a drive test, not road-tested.
"""

import pytest

from opendbc.can import CANParser
from opendbc.car import structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla import ap1_cluster as c
from opendbc.car.tesla.ap1_long_smooth import (
  AP1_COMFORT_JERK_LIMIT, AP1_FULL_JERK_LIMIT, AP1_RISE_JERK, AP1_STANDSTILL_HOLD_ACCEL,
)
from opendbc.car.tesla.ap1_steer_counter import COUNTER_LEAD
from opendbc.car.tesla.tests.test_tesla_ap1_milestone2 import Car, make_ci, make_cc, steer_frames, warm

VisualAlert = structs.CarControl.HUDControl.VisualAlert


class Car4(Car):
  """Milestone-2 harness plus the frames the milestone-4 code reads."""

  def __init__(self):
    super().__init__()
    self.v_kph = 60.0
    self.gas = 0
    self.cruise_set = 0.0
    self.speed_units = 0  # MPH
    self.epb_allow = None  # None: no 0x214 frame at all
    self.stock_steer_every = 0  # >0: stock DAS_steeringControl on bus 2 every N steps
    self.stock_steer_counter = 0

  def frames(self):
    f = super().frames()
    out = []
    for addr, dat, bus in f:
      if addr == 0x368:  # DI_state: rebuild with cruise set / units
        continue
      if addr == 0x108:  # DI_torque1: pedal
        continue
      if addr == 0x155 and bus == 0:  # ESP_B: speed
        continue
      out.append((addr, dat, bus))
    out.append(self._msg("ESP_B", 0, {"ESP_vehicleSpeed": self.v_kph}))
    out.append(self._msg("DI_torque1", 0, {"DI_pedalPos": self.gas}))
    out.append(self._msg("DI_state", 0, {"DI_cruiseState": self.cruise_state, "DI_speedUnits": self.speed_units,
                                         "DI_digitalSpeed": 40, "DI_cruiseSet": self.cruise_set}))
    if self.epb_allow is not None:
      out.append(self._msg("EPB_epasControl", 0, {"EPB_epasEACAllow": self.epb_allow}))
    if self.stock_steer_every and self.step % self.stock_steer_every == 0:
      self.stock_steer_counter = (self.stock_steer_counter + 1) % 16
      out.append(self.packer.make_can_msg("DAS_steeringControl", 2, {
        "DAS_steeringControlCounter": self.stock_steer_counter, "DAS_steeringAngleRequest": -self.angle,
        "DAS_steeringControlType": 1}))
    return out


def make_long_cc(accel, enabled=True, fcw=False, stopping=False, set_speed=0.0):
  CC = structs.CarControl()
  CC.enabled = enabled
  CC.latActive = enabled
  CC.longActive = enabled
  CC.actuators.steeringAngleDeg = 5.0
  CC.actuators.accel = float(accel)
  if stopping:
    CC.actuators.longControlState = structs.CarControl.Actuators.LongControlState.stopping
  if fcw:
    CC.hudControl.visualAlert = VisualAlert.fcw
  CC.hudControl.setSpeed = float(set_speed)
  return CC.as_reader()


class DasReader:
  """Decode openpilot's chassis DAS_control (0x2b9, bus 0) with the real parser."""

  def __init__(self):
    self.cp = CANParser("tesla_can", [("DAS_control", float("nan"))], 0)
    self.t = 0

  def read(self, sends):
    frames = [(a, d, b) for a, d, b in sends if a == 0x2b9 and b == 0]
    if not frames:
      return None
    self.t += 10_000_000
    self.cp.update([(self.t, frames)])
    return dict(self.cp.vl["DAS_control"])


def run_long(car, ci, accels, **kw):
  das = DasReader()
  out = []
  for a in accels:
    cs, _, sends = car.tick(ci, make_long_cc(a, **kw))
    out.append((das.read(sends), cs))
  return out


# --- DI_cruiseSet, raw SpdCtrlLvr_Stat, FWD hold -----------------------------

def test_cruise_speed_is_di_cruise_set_not_digital_speed():
  ci, car = make_ci(), Car4()
  car.cruise_set = 36.0
  cs = warm(car, ci)
  assert cs.cruiseState.speed == pytest.approx(36.0 * CV.MPH_TO_MS, abs=0.01)
  car.speed_units = 1  # KPH
  car.cruise_set = 60.0
  cs, _, _ = car.tick(ci, make_cc(enabled=False, lat=False))
  assert cs.cruiseState.speed == pytest.approx(60.0 * CV.KPH_TO_MS, abs=0.01)


def test_raw_spd_ctrl_lvr_level():
  ci, car = make_ci(), Car4()
  warm(car, ci)
  for raw in (4, 8, 16, 32, 2, 1, 0):
    car.spd_lvr = raw
    car.tick(ci, make_cc(enabled=False, lat=False))
    assert ci.CS.spd_ctrl_lvr == raw


def test_fwd_hold_while_disengaged_fires_once_and_never_while_engaged():
  ci, car = make_ci(), Car4()
  car.cruise_state = 1  # STANDBY: disengaged
  warm(car, ci)
  car.spd_lvr = 1  # FWD
  fired = []
  for _ in range(400):
    car.tick(ci, make_cc(enabled=False, lat=False))
    fired.append(ci.CS.stalk_fwd_toggle)
  assert sum(fired) == 1
  assert 190 <= fired.index(True) <= 210  # ~2 s at 100 Hz
  # Engaged FWD (cancel) never toggles
  ci, car = make_ci(), Car4()
  warm(car, ci)  # ENABLED
  car.spd_lvr = 1
  for _ in range(400):
    car.tick(ci, make_cc())
    assert not ci.CS.stalk_fwd_toggle


# --- EPB EAC revoke -----------------------------------------------------------

def test_epb_revoke_is_permanent_steer_fault_only_when_seen():
  ci, car = make_ci(), Car4()
  cs = warm(car, ci)
  assert cs.canValid and not cs.steerFaultPermanent  # no 0x214 at all: no fault, CAN still valid
  car.epb_allow = 1
  for _ in range(5):
    cs, _, _ = car.tick(ci, make_cc(enabled=False, lat=False))
  assert not cs.steerFaultPermanent
  car.epb_allow = 0
  cs, _, _ = car.tick(ci, make_cc(enabled=False, lat=False))
  assert cs.steerFaultPermanent and ci.CS.epb_eac_revoked
  assert cs.canValid


# --- 0x488 counter follows the stock DAS --------------------------------------

def test_steer_counter_follows_stock_with_lead():
  ci, car = make_ci(), Car4()
  car.stock_steer_every = 2  # stock 0x488 at 50 Hz on bus 2
  warm(car, ci)
  pairs = []
  for _ in range(40):
    _, _, sends = car.tick(ci, make_cc())
    for addr, dat, bus in sends:
      if addr == 0x488 and bus == 0:
        pairs.append((car.stock_steer_counter, dat[2] & 0x0F))
  assert pairs
  # Our counter is the newest stock counter plus the lead (the stock frame of this step is in the batch).
  assert all(ours == (stock + COUNTER_LEAD) % 16 for stock, ours in pairs), pairs


# --- Accel smoothing, jerk limits, standstill floor, gas neutral ---------------

def test_gas_step_is_slewed_and_written_back():
  ci, car = make_ci(), Car4()
  warm(car, ci)
  das = DasReader()
  sent, outs = [], []
  for a in [0.0] * 5 + [0.5] * 5:
    _, _, sends = car.tick(ci, make_long_cc(a))
    d = das.read(sends)
    if d is not None:
      sent.append(d["DAS_accelMax"])
  # DAS_control follows the stock 40 Hz counter, so look at the largest single-frame rise.
  rises = [b - a for a, b in zip(sent, sent[1:], strict=False)]
  assert max(rises) <= 4 * AP1_RISE_JERK * 0.01 + 0.041  # never the 0.5 step at once (DBC step 0.04)
  assert sent[-1] < 0.5


def test_hard_brake_reaches_das_control_same_step_with_full_jerk():
  ci, car = make_ci(), Car4()
  warm(car, ci)
  out = run_long(car, ci, [0.2] * 10 + [-2.0] * 6)
  frames = [d for d, _ in out[10:] if d is not None]
  assert frames and frames[0]["DAS_accelMin"] == pytest.approx(-2.0, abs=0.041)
  assert frames[0]["DAS_jerkMin"] == pytest.approx(-AP1_FULL_JERK_LIMIT, abs=0.031)


def test_comfort_jerk_band_while_cruising():
  ci, car = make_ci(), Car4()
  warm(car, ci)
  out = run_long(car, ci, [0.1] * 300)
  last = [d for d, _ in out if d is not None][-1]
  assert last["DAS_jerkMin"] == pytest.approx(-AP1_COMFORT_JERK_LIMIT, abs=0.031)
  assert last["DAS_jerkMax"] == pytest.approx(AP1_COMFORT_JERK_LIMIT, abs=0.06)


def test_standstill_hold_floor_relaxes_toward_minus_one():
  ci, car = make_ci(), Car4()
  car.v_kph = 0.0
  warm(car, ci)
  out = run_long(car, ci, [-2.0] * 300)
  mins = [d["DAS_accelMin"] for d, _ in out if d is not None]
  assert out[-1][1].standstill
  assert mins[-1] == pytest.approx(AP1_STANDSTILL_HOLD_ACCEL, abs=0.041)
  assert min(mins[-20:]) >= AP1_STANDSTILL_HOLD_ACCEL - 0.041
  # FCW at standstill passes the full request
  ci, car = make_ci(), Car4()
  car.v_kph = 0.0
  warm(car, ci)
  out = run_long(car, ci, [-2.0] * 10, fcw=True)
  mins = [d["DAS_accelMin"] for d, _ in out if d is not None]
  assert mins[-1] == pytest.approx(-2.0, abs=0.041)


def test_gas_press_sends_neutral_das_control_even_with_long_active():
  ci, car = make_ci(), Car4()
  warm(car, ci)
  car.gas = 20
  out = run_long(car, ci, [0.8] * 12)
  frames = [d for d, cs in out if d is not None]
  assert out[-1][1].gasPressed
  assert frames
  for d in frames:
    assert d["DAS_accelMin"] == pytest.approx(0.0, abs=0.041)
    assert d["DAS_accelMax"] == pytest.approx(0.0, abs=0.041)


def test_smoothed_accel_is_returned_in_actuators():
  ci, car = make_ci(), Car4()
  warm(car, ci)
  car.tick(ci, make_long_cc(0.0))
  car.t += 10_000_000
  ci.update([(car.t, car.frames())], None)
  new_actuators, _ = ci.apply(make_long_cc(0.5), car.t, None)
  assert 0.0 < new_actuators.accel < 0.5
  assert new_actuators.accel == pytest.approx(AP1_RISE_JERK * 0.01, abs=1e-6)


# --- Cluster set speed (DAS_accSpeedLimit on 0x389) -------------------------------

def test_dbc_acc_speed_limit_factor_is_0p4():
  sig = c.SIGNALS[c.DAS_STATUS2]["DAS_accSpeedLimit"]
  assert sig.factor == pytest.approx(0.4)


def test_cluster_acc_speed_limit_follows_openpilot_set():
  ci, car = make_ci(), Car4()
  car.cluster = True
  warm(car, ci)
  got = {}
  for _ in range(30):
    _, _, sends = car.tick(ci, make_long_cc(0.0, set_speed=30 * CV.MPH_TO_MS))
    got.update({a: d for a, d, b in sends if a == c.DAS_STATUS2 and b == 0})
  assert c.DAS_STATUS2 in got
  st = c.unpack(c.DAS_STATUS2, got[c.DAS_STATUS2])
  assert st["DAS_accSpeedLimit"] == pytest.approx(30.0, abs=0.41)
  # UNSET (255 kph) keeps the stock value
  stock = c.unpack(c.DAS_STATUS2, bytes.fromhex(c_stock_status2()))["DAS_accSpeedLimit"]
  got = {}
  for _ in range(30):
    _, _, sends = car.tick(ci, make_long_cc(0.0, set_speed=255 * CV.KPH_TO_MS))
    got.update({a: d for a, d, b in sends if a == c.DAS_STATUS2 and b == 0})
  st = c.unpack(c.DAS_STATUS2, got[c.DAS_STATUS2])
  assert st["DAS_accSpeedLimit"] == pytest.approx(stock, abs=0.41)


def c_stock_status2():
  from opendbc.car.tesla.tests.fixtures.ap1_cluster_frames import DAS_STATUS2_HEX
  return DAS_STATUS2_HEX[0]
