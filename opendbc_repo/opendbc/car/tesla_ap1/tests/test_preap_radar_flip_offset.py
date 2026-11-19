"""Pre-AP radar mounting corrections: Flip Radar (TeslaRadarUpsideDown) and Radar Offset (TeslaRadarOffset).
Tinkla radar_interface.py:67-69,145-151 @501c7de. Both default off / 0.0 and change nothing; AP1 never reads them."""
import math

import pytest

from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.radar_interface import NUM_POINTS, RadarInterface
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import (_params_dir, ap1_cp, long_paths, no_gate, preap_cp,  # noqa: F401
                                                                 preap_on_radar, store)
from opendbc.car.tesla_ap1.values import CAR, DBC

LAT, LATSPEED = 3.0, 2.5      # LatSpeed is on the bus but RadarPoint has no live yvRel, so it must never leak into the output


def table(lat=LAT, lat_speed=LATSPEED, car=CAR.TESLA_PREAP_MODELS):
  """Full 32 point table, point 0 tracked at 40 m with a lateral position and speed, plus the trigger."""
  packer = CANPacker(DBC[car][Bus.radar])
  out = [packer.make_can_msg("TeslaRadarSguInfo", 1, {})]
  for i in range(NUM_POINTS):
    a = ({"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": 40.0, "ProbExist": 96.875, "LatDist": lat} if i == 0
         else {"Tracked": 0, "Index": 1})
    b = {"Index2": 1, "LatSpeed": lat_speed} if i == 0 else {"Index2": 1}
    out += [packer.make_can_msg(f"RadarPoint{i}_A", 1, a), packer.make_can_msg(f"RadarPoint{i}_B", 1, b)]
  return out


def point(ri):
  out = ri.update([(1_000_000_000, table())])
  assert out is not None and len(out.points) == 1
  return out.points[0]


def test_params_registered_with_defaults():
  assert K.RADAR_FLIP == "TeslaRadarUpsideDown" and K.RADAR_OFFSET == "TeslaRadarOffset"
  assert params.DEFAULTS[K.RADAR_FLIP] is False and params.DEFAULTS[K.RADAR_OFFSET] == 0.0
  assert params.get_bool(K.RADAR_FLIP) is False and params.radar_offset_m() == 0.0


@pytest.mark.parametrize("text,expected", [("0.25", 0.25), ("-0.4", -0.4), ("5", 1.0), ("-7", -1.0), ("nan", 0.0), ("inf", 0.0),
                                           ("-inf", 0.0), ("abc", 0.0), ("", 0.0)])
def test_offset_is_clamped_and_bad_values_are_zero(text, expected):
  params._write_text(K.RADAR_OFFSET, text)
  assert math.isclose(params.radar_offset_m(), expected, abs_tol=1e-9)


def test_defaults_are_a_no_op(long_paths):
  ri = no_gate(preap_on_radar(long_paths))
  assert (ri.preap_flip, ri.preap_offset) == (False, 0.0)
  p = point(ri)
  assert p.yRel == pytest.approx(LAT, abs=0.07)


def test_flip_negates_lateral_position_only(long_paths):
  long_paths(True)
  store(radar=True)
  params.set_bool(K.RADAR_FLIP, True)
  p = point(no_gate(RadarInterface(preap_cp())))
  assert p.yRel == pytest.approx(-LAT, abs=0.07)
  assert p.dRel == pytest.approx(40.0, abs=0.07)                         # longitudinal untouched


def test_offset_is_added_to_lateral_position_only(long_paths):
  long_paths(True)
  store(radar=True)
  params.set_float(K.RADAR_OFFSET, 0.5)
  p = point(no_gate(RadarInterface(preap_cp())))
  assert p.yRel == pytest.approx(LAT + 0.5, abs=0.07)


def test_flip_and_offset_together_offset_first_then_flip(long_paths):
  long_paths(True)
  store(radar=True)
  params.set_bool(K.RADAR_FLIP, True)
  params.set_float(K.RADAR_OFFSET, -0.25)
  p = point(no_gate(RadarInterface(preap_cp())))
  assert p.yRel == pytest.approx(-(LAT - 0.25), abs=0.07)


def test_settings_are_read_once_when_the_car_starts(long_paths):
  ri = no_gate(preap_on_radar(long_paths))
  params.set_bool(K.RADAR_FLIP, True)
  params.set_float(K.RADAR_OFFSET, 0.5)
  assert point(ri).yRel == pytest.approx(LAT, abs=0.07)


def test_ap1_ignores_both_settings():
  params.set_bool(K.RADAR_FLIP, True)
  params.set_float(K.RADAR_OFFSET, 0.5)
  ri = RadarInterface(ap1_cp())
  assert not ri.preap and (ri.preap_flip, ri.preap_offset) == (False, 0.0)
  out = ri.update([(1_000_000_000, table(car=CAR.TESLA_AP1_MODELS))])
  assert out is not None and len(out.points) == 1
  assert out.points[0].yRel == pytest.approx(LAT, abs=0.07)
