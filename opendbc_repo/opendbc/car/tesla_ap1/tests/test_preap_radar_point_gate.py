"""Pre-AP Bosch point gate (docs/tesla/DIVERGENCES_preap_radar_filters.md (4)); AP1 keeps every tracked point."""
import pytest
from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.preap_radar_filters import BOSCH_MAX_DIST, OBJECT_MIN_PROBABILITY, bosch_point_valid
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, ap1_cp, long_paths, preap_cp, store  # noqa: F401
from opendbc.car.tesla_ap1.values import CAR, DBC


def one_point(ri, long_dist, prob_exist):
  packer = CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar])
  msgs = [packer.make_can_msg("TeslaRadarSguInfo", 1, {}),
          packer.make_can_msg("RadarPoint0_A", 1, {"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": long_dist, "ProbExist": prob_exist}),
          packer.make_can_msg("RadarPoint0_B", 1, {"Index2": 1}),
          packer.make_can_msg("RadarPoint31_B", 1, {})]
  return ri.update([(1_000_000_000, msgs)])


@pytest.mark.parametrize("d,pe,ok", [(40.0, 96.875, True), (40.0, 50.0, True), (40.0, 46.875, False), (40.0, 3.125, False),
                                     (0.0, 96.875, False), (250.0, 96.875, True), (255.9375, 96.875, False)])
def test_gate_unit(d, pe, ok):
  assert bosch_point_valid(d, pe) == ok


def test_constants_match_tinkla_and_nap():
  assert (BOSCH_MAX_DIST, OBJECT_MIN_PROBABILITY) == (250.0, 50.0)


@pytest.mark.parametrize("d,pe,kept", [(40.0, 96.875, True), (40.0, 18.75, False), (0.0, 96.875, False), (255.9375, 96.875, False)])
def test_preap_drops_invalid_points(long_paths, d, pe, kept):
  long_paths(True)
  store(radar=True)
  out = one_point(RadarInterface(preap_cp()), d, pe)
  assert out is not None and len(out.points) == (1 if kept else 0) and not out.errors.radarFault


@pytest.mark.parametrize("d,pe", [(40.0, 96.875), (40.0, 18.75), (40.0, 0.0), (255.9375, 96.875)])
def test_ap1_keeps_every_tracked_point(d, pe):
  out = one_point(RadarInterface(ap1_cp()), d, pe)
  assert out is not None and len(out.points) == 1
