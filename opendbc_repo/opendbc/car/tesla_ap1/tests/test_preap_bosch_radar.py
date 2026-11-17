"""Pre-AP Bosch radar retrofit, host half: toggles -> CarParams / safety param, radar faults and fail-closed."""
import pytest
from opendbc.can import CANPacker
from opendbc.car import Bus, gen_empty_fingerprint, structs
from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.radar_interface import (PREAP_MISSING_RADAR_FRAMES, RadarInterface, get_radar_can_parser)
from opendbc.car.tesla_ap1.safety_flags import flags_for_preap
from opendbc.car.tesla_ap1.values import AP1_CHASSIS_SIGNATURE, CAR, CANBUS, DBC


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path / "params_bogpilot")
  yield tmp_path


@pytest.fixture
def long_paths(tmp_path, monkeypatch):
  def set_long(pedal):
    f = tmp_path / ("long_on" if pedal else "long_off")
    f.write_text("0" if pedal else "1")
    monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (f,))
  return set_long


def store(radar=None, nosecone=None):
  for key, value in ((K.RADAR_ENABLED, radar), (K.RADAR_BEHIND_NOSECONE, nosecone)):
    if value is not None:
      params.set_bool(key, value)


def preap_cp():
  return CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)


def ap1_cp():
  fp = gen_empty_fingerprint()
  fp[0] = dict(AP1_CHASSIS_SIGNATURE)
  fp[2] = {0x399: 8, 0x2B9: 8, 0x488: 4}
  return CarInterface.get_params(CAR.TESLA_AP1_MODELS, fp, [], False, False, False)


# ---- toggle off: identical to the build before the retrofit ----

@pytest.mark.parametrize("pedal,param", [(True, 96), (False, 32)])
def test_off_matches_today(long_paths, pedal, param):
  long_paths(pedal)
  cp = preap_cp()
  assert cp.radarUnavailable
  assert cp.safetyConfigs[0].safetyParam == param
  assert get_radar_can_parser(cp) is None
  assert RadarInterface(cp).rcp is None


@pytest.mark.parametrize("pedal", [True, False])
def test_off_carparams_bytes_identical_missing_explicit_off_and_nosecone_alone(long_paths, pedal):
  long_paths(pedal)
  missing = preap_cp().as_reader().as_builder().to_bytes()
  store(radar=False, nosecone=False)
  explicit = preap_cp().as_reader().as_builder().to_bytes()
  store(radar=False, nosecone=True)
  nosecone_alone = preap_cp().as_reader().as_builder().to_bytes()
  assert missing == explicit == nosecone_alone


def test_off_radar_interface_is_the_base_empty_publisher(long_paths):
  long_paths(True)
  ri = RadarInterface(preap_cp())
  out = [ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES * 2)]
  published = [o for o in out if o is not None]
  assert len(published) == len(out) // 5                         # RadarInterfaceBase: 20 Hz empty RadarData
  assert all(not o.points and not any(o.errors.to_dict().values()) for o in published)


# ---- toggle on ----

@pytest.mark.parametrize("pedal,param", [(True, 352), (False, 288)])
def test_on(long_paths, pedal, param):
  long_paths(pedal)
  store(radar=True)
  cp = preap_cp()
  assert not cp.radarUnavailable
  assert cp.safetyConfigs[0].safetyParam == param
  rcp = get_radar_can_parser(cp)
  assert rcp is not None and rcp.bus == CANBUS.radar == 1


@pytest.mark.parametrize("pedal,param", [(True, 480), (False, 416)])
def test_on_with_nosecone(long_paths, pedal, param):
  long_paths(pedal)
  store(radar=True, nosecone=True)
  cp = preap_cp()
  assert not cp.radarUnavailable
  assert cp.safetyConfigs[0].safetyParam == param


def test_flags_for_preap_table():
  assert [flags_for_preap(p, r, n) for p in (False, True) for r in (False, True) for n in (False, True)] == \
    [32, 32, 288, 416, 96, 96, 352, 480]


def test_ap1_unchanged_by_toggles(long_paths):
  before = ap1_cp().as_reader().as_builder().to_bytes()
  store(radar=True, nosecone=True)
  after = ap1_cp()
  assert after.as_reader().as_builder().to_bytes() == before
  assert after.safetyConfigs[0].safetyParam == 25


# ---- radar faults ----

def frames(sgu, trigger=True):
  packer = CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar])
  out = [packer.make_can_msg("TeslaRadarSguInfo", 1, sgu),
         packer.make_can_msg("RadarPoint0_A", 1, {"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": 40.0, "ProbExist": 96.875}),
         packer.make_can_msg("RadarPoint0_B", 1, {"Index2": 1})]
  if trigger:
    out.append(packer.make_can_msg("RadarPoint31_B", 1, {}))
  return out


def preap_on_radar(long_paths):
  long_paths(True)
  store(radar=True)
  return RadarInterface(preap_cp())


def no_gate(ri):
  """Point/fault tests here check the filters, not the radar-valid gate (test_preap_radar_valid.py covers that)."""
  assert ri.preap_gate is not None
  ri.preap_gate, ri.preap_radar_valid = None, True
  return ri


@pytest.mark.parametrize("sgu,fault", [({}, False), ({"RADC_SGUFail": 1}, False), ({"RADC_SensorDirty": 1}, False),
                                       ({"RADC_HWFail": 1}, True)])
def test_preap_faults_on_hwfail_only(long_paths, sgu, fault):
  out = preap_on_radar(long_paths).update([(1_000_000_000, frames(sgu))])
  assert out is not None and out.errors.radarFault == fault


@pytest.mark.parametrize("sgu,fault", [({}, False), ({"RADC_SGUFail": 1}, True), ({"RADC_SensorDirty": 1}, True),
                                       ({"RADC_HWFail": 1}, True)])
def test_ap1_fault_rule_unchanged(sgu, fault):
  out = RadarInterface(ap1_cp()).update([(1_000_000_000, frames(sgu))])
  assert out is not None and out.errors.radarFault == fault


# ---- fail closed: toggle on, radar silent ----

def test_preap_silent_radar_fails_closed(long_paths):
  ri = preap_on_radar(long_paths)
  outs = [ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES - 1)]
  assert all(o is None for o in outs)                           # 0.49 s grace: nothing published yet
  out = ri.update([])                                            # frame 50
  assert out is not None and out.errors.canError and not out.points
  later = [ri.update([]) for _ in range(20)]
  errs = [o for o in later if o is not None]
  assert len(errs) == 4 and all(o.errors.canError for o in errs)  # keeps failing closed at 20 Hz


def test_preap_radar_dropout_clears_tracks_and_recovers(long_paths):
  ri = no_gate(preap_on_radar(long_paths))
  t = 1_000_000_000
  first = ri.update([(t, frames({}))])
  assert first is not None and len(first.points) == 1
  for _ in range(PREAP_MISSING_RADAR_FRAMES):
    out = ri.update([])
  assert out is not None and out.errors.canError and not out.points and not ri.pts
  back = ri.update([(t + 10**9, frames({}))])
  assert back is not None and len(back.points) == 1 and ri.frames_without_radar == 0


def test_ap1_silent_radar_publishes_nothing_new():
  ri = RadarInterface(ap1_cp())
  assert all(ri.update([]) is None for _ in range(PREAP_MISSING_RADAR_FRAMES * 3))
