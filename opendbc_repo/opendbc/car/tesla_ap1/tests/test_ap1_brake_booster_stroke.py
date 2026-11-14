"""0x39D brake booster rod stroke (BogPilot divergence from drive logs): DBC parse / pack, checksum and counter, the
normalized level in CarState.deprecated.brake on AP1 (scaling, clamp, peg at TOP, staleness, bad checksum), and Pre-AP
unchanged."""
from types import SimpleNamespace

import pytest

from opendbc.can import CANParser
from opendbc.can.packer import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1 import brake_level as BL
from opendbc.car.tesla_ap1.carstate import CarState as Ap1CarState
from opendbc.car.tesla_ap1.values import CAR, DBC
from opendbc.car.tesla_ap1.tests.test_preap_gas_threshold import StockRig, _params_dir  # noqa: F401

DBC_AP1 = "tesla_ap1_can"
MSG = "BrakeBoosterStroke"
SPAN = BL.BRAKE_STROKE_TOP - BL.BRAKE_STROKE_REST

# Frames as logged (bytes 0-3): rest, and the hardest press logged (byte 3 = 21).
REST_FRAME = bytes([0x54, 0x06, 0xAE, 0x00])          # counter 6, stroke 174
FIRM_FRAME = bytes([0x18, 0x05, 0x5E, 0x15])          # counter 5, stroke 5470


def parse(frames, t0=1_000_000_000):
  cp = CANParser(DBC_AP1, [(MSG, float("nan"))], 0)
  for i, dat in enumerate(frames):
    cp.update([(t0 + i * 40_000_000, [(BL.ADDR, dat, 0)])])
  return cp


def pack(stroke, counter, checksum=None):
  ck = BL.stroke_checksum(counter, stroke) if checksum is None else checksum
  addr, dat, _ = CANPacker(DBC_AP1).make_can_msg(MSG, 0, {"brakeRodStroke": stroke, "brakeBoosterCounter": counter,
                                                          "brakeBoosterChecksum": ck})
  assert addr == BL.ADDR
  return dat


class TestDbc:
  def test_logged_frames_decode(self):
    v = parse([REST_FRAME]).vl[MSG]
    assert (v["brakeBoosterChecksum"], v["brakeBoosterCounter"], v["brakeRodStroke"]) == (0x54, 6, 174)
    v = parse([FIRM_FRAME]).vl[MSG]
    assert (v["brakeBoosterChecksum"], v["brakeBoosterCounter"], v["brakeRodStroke"]) == (0x18, 5, 5470)
    assert int(v["brakeRodStroke"]) >> 8 == 21                       # byte 3 is only the high byte

  def test_pack_round_trip_and_layout(self):
    assert pack(174, 6) == REST_FRAME
    assert pack(5470, 5) == FIRM_FRAME
    for stroke, ctr in ((0, 0), (174, 15), (2030, 9), (5631, 3), (65535, 15)):
      dat = pack(stroke, ctr)
      assert len(dat) == 4
      assert dat[1] == ctr and dat[2] | (dat[3] << 8) == stroke  # counter low nibble of byte 1, stroke LE in 2-3
      v = parse([dat]).vl[MSG]
      assert (v["brakeRodStroke"], v["brakeBoosterCounter"], v["brakeBoosterChecksum"]) == (stroke, ctr, dat[0])

  def test_checksum_is_the_tesla_sum(self):
    for dat in (REST_FRAME, FIRM_FRAME):
      assert (dat[1] + dat[2] + dat[3] + 0xA0) & 0xFF == dat[0]
      assert BL.stroke_checksum(dat[1] & 0x0F, dat[2] | (dat[3] << 8)) == dat[0]

  def test_counter_sequence_parses(self):
    seq = [pack(174, i % 16) for i in range(40)]
    cp = CANParser(DBC_AP1, [(MSG, float("nan"))], 0)
    got = []
    for i, dat in enumerate(seq):
      cp.update([(1_000_000_000 + i * 40_000_000, [(BL.ADDR, dat, 0)])])
      got.append(int(cp.vl[MSG]["brakeBoosterCounter"]))
    assert got == [i % 16 for i in range(40)]


class TestLevel:
  def test_constants(self):
    assert (BL.BRAKE_STROKE_REST, BL.BRAKE_STROKE_TOP) == (174, 5631)
    assert BL.BRAKE_STROKE_TOP == 21 * 256 + 255
    assert BL.BRAKE_LEVEL_MISSING == -1.0

  def lvl(self, stroke, fresh=True, ctr=3, ck=None):
    return BL.brake_level(stroke, ctr, BL.stroke_checksum(ctr, stroke) if ck is None else ck, fresh)

  def test_scaling_and_clamp(self):
    assert self.lvl(174) == 0.0
    assert self.lvl(168) == 0.0                                 # rest a few counts low: clamps at 0
    assert self.lvl(0) == 0.0
    assert self.lvl(174 + SPAN // 2) == pytest.approx(0.5, abs=1e-3)
    assert self.lvl(5631) == 1.0

  def test_logged_percentiles_map_inside_the_bar(self):
    # brakePressed byte-3 spread over the AP1 logs: p50 9, p95 13, p99 14, max 21 (stroke peak 5470)
    for b3, lo, hi in ((9, 0.39, 0.44), (13, 0.57, 0.63), (14, 0.62, 0.68), (21, 0.95, 1.0)):
      assert lo <= self.lvl(b3 * 256) <= hi and lo <= self.lvl(b3 * 256 + 255) <= hi, b3
    assert self.lvl(5470) == pytest.approx((5470 - 174) / SPAN)

  def test_panic_stop_past_top_pegs(self):
    for stroke in (5632, 8000, 13606, 65535):
      assert self.lvl(stroke) == 1.0

  def test_stale_bad_checksum_and_junk_are_missing(self):
    assert self.lvl(2000, fresh=False) == BL.BRAKE_LEVEL_MISSING
    assert self.lvl(2000, ck=(BL.stroke_checksum(3, 2000) + 1) & 0xFF) == BL.BRAKE_LEVEL_MISSING
    assert BL.brake_level(float("nan"), 3, 0, True) == BL.BRAKE_LEVEL_MISSING
    assert BL.brake_level(None, 3, 0, True) == BL.BRAKE_LEVEL_MISSING


def ap1_feed(car, frames, gap_s=0.04, pressed=False):
  """Feed the AP1 chassis parser one booster frame (or None = not sent) per step, with real timestamps."""
  cp = SimpleNamespace(carFingerprint=car)
  state, parsers = Ap1CarState(cp), Ap1CarState.get_can_parsers(cp)
  packer = CANPacker(DBC[car][Bus.chassis])
  chassis = parsers[Bus.chassis]
  base = {"ESP_B": {"ESP_vehicleSpeed": 50.0}, "BrakeMessage": {"driverBrakeStatus": 2 if pressed else 1},
          "EPAS_sysStatus": {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0}, "STW_ANGLHP_STAT": {"StW_AnglHP_Spd": 0.0},
          "DI_torque2": {"DI_gear": 4}, "DI_state": {}, "SDM1": {"SDM_bcklDrivStatus": 1}, "DI_torque1": {}}
  out, t = [], 1_000_000_000
  for dat in frames:
    t += int(gap_s * 1e9)
    msgs = [packer.make_can_msg(n, chassis.bus, v)[:2] for n, v in base.items()]
    if dat is not None:
      msgs.append((BL.ADDR, dat))
    chassis.update([(t, [(a, d, chassis.bus) for a, d in msgs])])
    out.append(state.update(parsers))
  return out


@pytest.mark.parametrize("car", [CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX])
class TestAp1CarState:
  def test_parser_registers_the_frame_rx_only(self, car):
    parsers = Ap1CarState.get_can_parsers(SimpleNamespace(carFingerprint=car))
    assert MSG in parsers[Bus.chassis].vl and parsers[Bus.chassis].bus == 0

  def test_publishes_the_normalized_stroke(self, car):
    outs = ap1_feed(car, [pack(s, i % 16) for i, s in enumerate((174, 168, 174 + SPAN // 2, 5470, 9000))], pressed=True)
    got = [round(o.deprecated.brake, 3) for o in outs]
    assert got == [0.0, 0.0, 0.5, round((5470 - 174) / SPAN, 3), 1.0]
    assert all(o.brakePressed for o in outs)

  def test_missing_or_stale_is_minus_one(self, car):
    assert ap1_feed(car, [None, None])[-1].deprecated.brake == BL.BRAKE_LEVEL_MISSING           # never sent
    outs = ap1_feed(car, [pack(2000, 1)] + [None] * 14)                                         # 25 Hz frame stops
    assert outs[0].deprecated.brake > 0
    assert outs[10].deprecated.brake > 0                                                        # 0.4 s: still fresh
    assert outs[-1].deprecated.brake == BL.BRAKE_LEVEL_MISSING                                  # 0.56 s: stale
    bad = bytearray(pack(2000, 1))
    bad[0] ^= 0x01
    assert ap1_feed(car, [bytes(bad)])[-1].deprecated.brake == BL.BRAKE_LEVEL_MISSING           # bad checksum

  def test_missing_frame_does_not_trip_can_valid(self, car):
    outs = ap1_feed(car, [None] * 30)
    assert outs[-1].deprecated.brake == BL.BRAKE_LEVEL_MISSING
    cp = SimpleNamespace(carFingerprint=car)
    parsers = Ap1CarState.get_can_parsers(cp)
    assert MSG in parsers[Bus.chassis].vl

  def test_lag_stroke_without_brake_pressed_is_published_but_not_pressed(self, car):
    # the rod lags brakePressed; carstate reports both as they are and the UI keys colour off brakePressed
    o = ap1_feed(car, [pack(1182, 2)], pressed=False)[-1]
    assert not o.brakePressed and o.deprecated.brake == pytest.approx((1182 - 174) / SPAN)


def test_preap_unchanged():
  rig = StockRig()
  for _ in range(3):
    out, _ = rig.frame(0)
  assert out.deprecated.brake == 0.0                               # Pre-AP does not fill the slot
  assert MSG not in rig.parsers[Bus.chassis].vl
