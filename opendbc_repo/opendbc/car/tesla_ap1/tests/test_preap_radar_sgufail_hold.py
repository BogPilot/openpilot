"""Pre-AP Bosch radar: RADC_SGUFail held for SGUFAIL_HOLD_S -> camera only (no points, no error); AP1 unchanged.
docs/tesla/DIVERGENCES_preap_radar_filters.md (1)."""
from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.preap_radar_filters import SGUFAIL_HOLD_S, SGUFAIL_RELEASE_S, SguFailHold
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, ap1_cp, long_paths, preap_cp, store  # noqa: F401
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
  return RadarInterface(preap_cp())


def test_hold_unit():
  h = SguFailHold()
  assert not h.update(True, 0.0)
  assert not h.update(True, SGUFAIL_HOLD_S - 0.01)
  assert h.update(True, SGUFAIL_HOLD_S)
  assert h.update(False, SGUFAIL_HOLD_S + 0.1)                       # still camera only until clear for RELEASE
  assert not h.update(False, SGUFAIL_HOLD_S + 0.1 + SGUFAIL_RELEASE_S)


def test_hold_unit_blip_resets():
  h = SguFailHold()
  for k in range(10):
    assert not h.update(k % 2 == 0, k * 0.5 * SGUFAIL_HOLD_S)           # never held for the full time


def test_preap_sgufail_held_goes_camera_only_without_error(long_paths):
  out = drive(preap_ri(long_paths), [(1.0, {}), (3.0, {"RADC_SGUFail": 1}), (3.0, {})])
  ctrl = drive(preap_ri(long_paths), [(7.0, {})])                    # same stream, SGUFail never set
  assert all(o is not None and not o.errors.radarFault for _, o in out)                 # never a fault
  assert [o.errors.to_dict() for _, o in out] == [o.errors.to_dict() for _, o in ctrl]   # errors identical to no SGUFail
  t_on, t_off = 2.0, 5.0
  before = [o for t, o in out if t < t_on + SGUFAIL_HOLD_S - 0.1]
  held = [o for t, o in out if t_on + SGUFAIL_HOLD_S + 0.1 < t < t_off]
  back = [o for t, o in out if t > t_off + SGUFAIL_RELEASE_S + 0.1]
  assert before and all(len(o.points) == 1 for o in before)
  assert held and all(len(o.points) == 0 for o in held)
  assert back and all(len(o.points) == 1 for o in back)
  assert back[0].points[0].trackId != before[0].points[0].trackId     # new track id after camera-only


def test_preap_hwfail_still_faults_while_held(long_paths):
  out = drive(preap_ri(long_paths), [(3.0, {"RADC_SGUFail": 1, "RADC_HWFail": 1})])
  assert all(o.errors.radarFault for _, o in out)
  assert len(out[-1][1].points) == 0


def test_ap1_has_no_hold_and_sgufail_still_faults():
  ri = RadarInterface(ap1_cp())
  assert ri.sgu_fail_hold is None
  out = drive(ri, [(3.0, {"RADC_SGUFail": 1})])
  assert all(o.errors.radarFault and len(o.points) == 1 for _, o in out)
