"""AP1 is unchanged by the Pre-AP radar changes: Ignore radar HWFail (radar_interface.py:137-145, inside `if self.preap`) and
silence after the first message is advisory (:118-124, inside `if self.preap`). self.preap is is_preap(CP.carFingerprint) (:59).
On AP1 HWFail / SGUFail / SensorDirty still fault whatever the Ignore radar HWFail setting, an invalid radar parser is still
canError, and a radar that stops publishes nothing, as before these changes."""
import pytest

from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.radar_interface import PREAP_MISSING_RADAR_FRAMES, RadarInterface
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, ap1_cp, frames  # noqa: F401


@pytest.mark.parametrize("ignore", [False, True])
@pytest.mark.parametrize("sgu,fault", [({}, False), ({"RADC_SGUFail": 1}, True), ({"RADC_SensorDirty": 1}, True),
                                       ({"RADC_HWFail": 1}, True)])
def test_ap1_faults_whatever_ignore_hwfail_says(ignore, sgu, fault):
  params.set_bool(K.RADAR_IGNORE_HW_FAIL, ignore)
  ri = RadarInterface(ap1_cp())
  assert not ri.preap and ri.preap_gate is None
  out = ri.update([(1_000_000_000, frames(sgu))])
  assert out is not None and out.errors.radarFault == fault


def test_ap1_radar_that_stops_publishes_nothing_as_before():
  ri = RadarInterface(ap1_cp())
  assert ri.update([(1_000_000_000, frames({}))]) is not None
  outs = [ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES * 6)]
  assert all(o is None for o in outs)                 # no RadarData at all: no new canError, no dropped-points publish
  assert ri.frames_without_radar == 0 and ri.preap_radar_valid is True   # Pre-AP counters untouched (read only under self.preap)


def test_ap1_invalid_parser_is_still_canerror():
  ri = RadarInterface(ap1_cp())
  t = 1_000_000_000
  out = None
  for i in range(40):                                  # trigger only, every other radar message missing: the parser goes invalid
    t += 62_500_000
    out = ri.update([(t, frames({}, trigger=True)[-1:])])
  assert out is not None and out.errors.canError
