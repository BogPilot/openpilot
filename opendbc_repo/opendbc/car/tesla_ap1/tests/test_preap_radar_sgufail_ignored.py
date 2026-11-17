"""Pre-AP Bosch radar: RADC_SGUFail is ignored (points kept, no fault), as in Tinkla and NAP; AP1 still faults on it.
docs/tesla/DIVERGENCES_preap_radar_filters.md (1). Filter-level: the radar-valid gate is off here (no_gate); its warm-up and
its SGUFail-after-valid behaviour are in test_preap_radar_valid.py."""
from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, ap1_cp, long_paths, no_gate, preap_cp, store  # noqa: F401
from opendbc.car.tesla_ap1.values import CAR, DBC

DT = 0.0625  # 16 Hz radar cycle


def cycle(packer, t, sgu):
  return [(int(t * 1e9), [packer.make_can_msg("TeslaRadarSguInfo", 1, sgu),
                          packer.make_can_msg("RadarPoint0_A", 1, {"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": 40.0,
                                                                   "ProbExist": 96.875}),
                          packer.make_can_msg("RadarPoint0_B", 1, {"Index2": 1}),
                          packer.make_can_msg("RadarPoint31_B", 1, {})])]


def drive(ri, pattern):
  """pattern: list of (seconds, sgu dict). Returns [(t, RadarData)] for every radar cycle."""
  packer = CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar])
  out, t = [], 1.0
  for dur, sgu in pattern:
    for _ in range(int(round(dur / DT))):
      out.append((t, ri.update(cycle(packer, t, sgu))))
      t += DT
  return out


def preap_ri(long_paths):
  long_paths(True)
  store(radar=True)
  return no_gate(RadarInterface(preap_cp()))


def test_preap_keeps_points_while_sgufail_is_set(long_paths):
  out = drive(preap_ri(long_paths), [(1.0, {}), (3.0, {"RADC_SGUFail": 1}), (3.0, {})])
  ctrl = drive(preap_ri(long_paths), [(7.0, {})])                    # same stream, SGUFail never set
  assert all(o is not None and not o.errors.radarFault for _, o in out)
  assert [o.errors.to_dict() for _, o in out] == [o.errors.to_dict() for _, o in ctrl]
  assert all(len(o.points) == 1 for _, o in out)
  assert len({o.points[0].trackId for _, o in out}) == 1             # same track the whole time


def test_preap_hwfail_still_faults_with_sgufail(long_paths):
  out = drive(preap_ri(long_paths), [(2.0, {"RADC_SGUFail": 1, "RADC_HWFail": 1})])
  assert all(o.errors.radarFault for _, o in out)


def test_ap1_sgufail_still_faults():
  out = drive(RadarInterface(ap1_cp()), [(2.0, {"RADC_SGUFail": 1})])
  assert all(o.errors.radarFault and len(o.points) == 1 for _, o in out)
