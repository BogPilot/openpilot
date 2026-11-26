"""Pre-AP stock gasPressed threshold: DI_pedalPos raw 5 (2.0%) is not pressed, raw 6 (2.4%) is.

Packs RAW DI_pedalPos through the real DBC packer (factor 0.4) and parses through the
real CarState. Interceptor and AP1 paths are unchanged. At raw 1-5 the Pre-AP stock
host says not pressed, but the panda still treats data[6] != 0 as pressed and blocks
gas / longitudinal TX; that stricter panda side is intentional.
"""
from types import SimpleNamespace

import pytest

from opendbc.can import CANDefine
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, structs
from opendbc.car.tesla_ap1.carstate import CarState as Ap1CarState
from opendbc.car.tesla_ap1.preap import calib, params
from opendbc.car.tesla_ap1.preap.carstate import PreApCarState
from opendbc.car.tesla_ap1.values import CAR, DBC

DBC_NAME = DBC[CAR.TESLA_PREAP_MODELS][Bus.chassis]
# tesla_ap1_can.dbc: SG_ DI_pedalPos : 48|8@1+ (0.4,0) [0|100] "%"
DI_PEDAL_FACTOR = 0.4
CLOCK = [1000.0]


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path)
  CLOCK[0] = 1000.0
  monkeypatch.setattr("opendbc.car.tesla_ap1.preap.carstate.time.monotonic", lambda: CLOCK[0])
  yield tmp_path


def _inv(msg, sig, name):
  dv = CANDefine(DBC_NAME).dv[msg][sig]
  return next(k for k, v in dv.items() if v == name)


def pack_di_pedal_raw(packer, raw):
  """Pack a RAW 8-bit DI_pedalPos value via the DBC packer. Returns (addr, dat)."""
  physical = raw * DI_PEDAL_FACTOR
  addr, dat, _bus = packer.make_can_msg("DI_torque1", 0, {"DI_pedalPos": physical})
  assert dat[6] == raw, f"packer wrote data[6]={dat[6]} for requested raw {raw}"
  return addr, dat


class StockRig:
  """Pre-AP stock-TACC (no interceptor): pedal_long is False."""

  def __init__(self):
    self.CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=False)
    self.cs = PreApCarState(self.CP)
    self.parsers = PreApCarState.get_can_parsers(self.CP)
    self.packer = CANPacker(DBC_NAME)
    self.nanos = 0
    self.base = {
      "DI_torque2": {"DI_gear": _inv("DI_torque2", "DI_gear", "DI_GEAR_D")},
      "BrakeMessage": {"driverBrakeStatus": 1},
      "SDM1": {"SDM_bcklDrivStatus": 1},
      "DI_state": {
        "DI_cruiseState": _inv("DI_state", "DI_cruiseState", "STANDBY"),
        "DI_speedUnits": _inv("DI_state", "DI_speedUnits", "MPH"),
      },
      "EPAS_sysStatus": {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0},
      "ESP_B": {"ESP_vehicleSpeed": 50.0},
      "DI_torque1": {},
      "STW_ANGLHP_STAT": {"StW_AnglHP_Spd": 0.0},
      "GTW_carState": {},
      "STW_ACTN_RQ": {},
    }

  def send(self, name, **values):
    v = dict(self.base.get(name, {}))
    v.update(values)
    addr, dat, bus = self.packer.make_can_msg(name, 0, v)
    self.parsers[Bus.chassis].update([(self.nanos, [(addr, dat, 0)])])
    return addr, dat

  def frame(self, raw_pedal=0):
    self.nanos += 10_000_000
    CLOCK[0] += 0.01
    packed = None
    for n in self.base:
      if n == "DI_torque1":
        packed = pack_di_pedal_raw(self.packer, raw_pedal)
        self.parsers[Bus.chassis].update([(self.nanos, [(packed[0], packed[1], 0)])])
      elif n == "ESP_B":
        self.send(n, ESP_vehicleSpeed=50.0)
      else:
        self.send(n)
    out = self.cs.update(self.parsers)
    return out, packed


class InterceptorRig:
  """Pre-AP with Comma Pedal longitudinal: gasPressed comes from the interceptor."""

  def __init__(self):
    calib.apply_calibration_result(calib.compute_calibration(0.8, 107.0))
    self.CP = SimpleNamespace(carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
    self.cs = PreApCarState(self.CP)
    self.parsers = PreApCarState.get_can_parsers(self.CP)
    self.packer = CANPacker(DBC_NAME)
    self.nanos = 0
    self.base = {
      "DI_torque2": {"DI_gear": _inv("DI_torque2", "DI_gear", "DI_GEAR_D")},
      "BrakeMessage": {"driverBrakeStatus": 1},
      "SDM1": {"SDM_bcklDrivStatus": 1},
      "DI_state": {
        "DI_cruiseState": _inv("DI_state", "DI_cruiseState", "STANDBY"),
        "DI_speedUnits": _inv("DI_state", "DI_speedUnits", "MPH"),
      },
      "EPAS_sysStatus": {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0},
      "ESP_B": {"ESP_vehicleSpeed": 50.0},
      "DI_torque1": {},
      "STW_ANGLHP_STAT": {"StW_AnglHP_Spd": 0.0},
      "GTW_carState": {},
      "STW_ACTN_RQ": {},
    }
    self._idx = 0

  def send(self, name, **values):
    v = dict(self.base.get(name, {}))
    v.update(values)
    addr, dat, bus = self.packer.make_can_msg(name, 0, v)
    self.parsers[Bus.chassis].update([(self.nanos, [(addr, dat, 0)])])

  def send_pedal(self, interceptor_gas):
    self._idx = (self._idx + 1) % 16
    addr, dat, _ = self.packer.make_can_msg(
      "GAS_SENSOR", 2,
      {"INTERCEPTOR_GAS": interceptor_gas, "INTERCEPTOR_GAS2": interceptor_gas * 2, "STATE": 0, "IDX": self._idx},
    )
    self.parsers[Bus.cam].update([(self.nanos, [(addr, dat, 2)])])

  def frame(self, raw_pedal=0, interceptor_gas=0.8):
    self.nanos += 10_000_000
    CLOCK[0] += 0.01
    pack_addr, pack_dat = pack_di_pedal_raw(self.packer, raw_pedal)
    self.parsers[Bus.chassis].update([(self.nanos, [(pack_addr, pack_dat, 0)])])
    for n in self.base:
      if n == "DI_torque1":
        continue
      elif n == "ESP_B":
        self.send(n, ESP_vehicleSpeed=50.0)
      else:
        self.send(n)
    self.send_pedal(interceptor_gas)
    return self.cs.update(self.parsers)


def _ap1_send(parser, packer, name, values):
  addr, dat, _bus = packer.make_can_msg(name, parser.bus, values)
  parser.update([(0, [(addr, dat, parser.bus)])])
  return addr, dat


def test_stock_raw_0_and_5_not_pressed_raw_6_pressed():
  r = StockRig()
  out0, packed0 = r.frame(raw_pedal=0)
  assert packed0[1][6] == 0
  assert out0.gasPressed is False
  assert (r.cs.di_gas > 0.02) is False

  out5, packed5 = r.frame(raw_pedal=5)
  assert packed5[1][6] == 5
  # Raw 5 is 2.0% on the wire (factor 0.4). di_gas is physical/100 == 0.02, and 0.02 > 0.02 is False.
  # Guard the rounding: 5/100.0 > 0.02 is True (wrong unit). The real expression must stay False.
  assert (5 / 100.0 > 0.02) is True
  physical = 5 * DI_PEDAL_FACTOR
  assert (physical / 100.0 > 0.02) is False
  assert (r.cs.di_gas > 0.02) is False
  assert out5.gasPressed is False
  assert r.cs.di_gas == pytest.approx(0.02, abs=1e-12)

  out6, packed6 = r.frame(raw_pedal=6)
  assert packed6[1][6] == 6
  assert out6.gasPressed is True
  assert r.cs.di_gas == pytest.approx(0.024, abs=1e-12)


def test_interceptor_path_unchanged_ignores_stock_di_pedal():
  r = InterceptorRig()
  # IDX must advance once so the pedal is detected, then the second frame is the one we assert on.
  r.frame(raw_pedal=0, interceptor_gas=0.8)
  # Stock raw 6 would be pressed on the stock path; interceptor idle must still be not pressed.
  out_idle = r.frame(raw_pedal=6, interceptor_gas=0.8)
  assert r.cs.preap_pedal_detected is True
  assert r.cs.pedal_long is True
  assert out_idle.gasPressed is False
  # Interceptor clearly pressed, stock raw 0 would be not pressed on the stock path.
  out_press = r.frame(raw_pedal=0, interceptor_gas=50.0)
  assert out_press.gasPressed is True


def test_ap1_unchanged_raw_1_still_pressed():
  cp = SimpleNamespace(carFingerprint=CAR.TESLA_AP1_MODELS)
  state = Ap1CarState(cp)
  parsers = Ap1CarState.get_can_parsers(cp)
  packer = CANPacker(DBC[CAR.TESLA_AP1_MODELS][Bus.chassis])
  chassis = parsers[Bus.chassis]

  def feed(raw):
    addr, dat = pack_di_pedal_raw(packer, raw)
    chassis.update([(0, [(addr, dat, chassis.bus)])])
    _ap1_send(chassis, packer, "ESP_B", {"ESP_vehicleSpeed": 50.0})
    _ap1_send(chassis, packer, "BrakeMessage", {"driverBrakeStatus": 1})
    _ap1_send(chassis, packer, "EPAS_sysStatus", {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0})
    _ap1_send(chassis, packer, "STW_ANGLHP_STAT", {"StW_AnglHP_Spd": 0.0})
    _ap1_send(chassis, packer, "DI_torque2", {"DI_gear": 4})
    _ap1_send(chassis, packer, "DI_state", {})
    _ap1_send(chassis, packer, "SDM1", {"SDM_bcklDrivStatus": 1})
    return state.update(parsers), dat

  out0, dat0 = feed(0)
  assert dat0[6] == 0
  assert out0.gasPressed is False

  out1, dat1 = feed(1)
  assert dat1[6] == 1
  assert out1.gasPressed is True

  out5, dat5 = feed(5)
  assert dat5[6] == 5
  assert out5.gasPressed is True


def test_host_panda_mismatch_raw_1_to_5_panda_blocks_gas_tx():
  """At raw 1-5 the Pre-AP stock host is not pressed; the panda still blocks gas TX.

  This mismatch is intentional: panda tesla_preap.h uses data[6] != 0, which is the
  stricter side. Host uses di_gas > 0.02 (raw > 5).
  """
  libsafety_py = pytest.importorskip("opendbc.safety.tests.libsafety.libsafety_py")
  from opendbc.car.structs import CarParams
  from opendbc.safety.tests import test_tesla_preap as preap_safety

  l = libsafety_py.libsafety
  SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
  PREAP = 32
  # Stock path: DI_torque1 is the panda gas source only when the pedal flag is clear.
  assert l.set_safety_hooks(SAFETY_TESLA, PREAP) == 0
  l.init_tests()
  l.set_timer(1_000_000)

  case = preap_safety.PreapCase()
  case.PARAM = PREAP
  case.t = 1_000_000
  case.feed_all()
  case.engage()
  assert l.get_controls_allowed()
  assert l.get_longitudinal_allowed()

  packer = CANPacker(DBC_NAME)
  host = StockRig()
  for raw in (1, 2, 3, 4, 5):
    out, packed = host.frame(raw_pedal=raw)
    assert packed[1][6] == raw
    assert out.gasPressed is False, raw
    pkt = libsafety_py.make_CANPacket(packed[0], 0, bytes(packed[1]))
    for _ in range(2):
      assert l.safety_rx_hook(pkt)
    assert l.get_controls_allowed()
    # get_longitudinal_allowed is the gas/long TX gate (controls_allowed && !gas_pressed_prev).
    assert not l.get_longitudinal_allowed(), raw
    assert case.tx(preap_safety.steer(0))

  # Raw 0 clears the panda gas_pressed bit; longitudinal is allowed again.
  out0, packed0 = host.frame(raw_pedal=0)
  assert out0.gasPressed is False
  pkt0 = libsafety_py.make_CANPacket(packed0[0], 0, bytes(packed0[1]))
  for _ in range(2):
    assert l.safety_rx_hook(pkt0)
  assert l.get_longitudinal_allowed()
