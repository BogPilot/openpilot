"""Ignore radar HWFail (NotAutopilot NAPRadarIgnoreHwFail, opendbc a4c8a40f; nap_params.py:32,67 and radar_interface.py:186-187,211
@ opendbc 508d26fcb). Default OFF: RADC_HWFail is a radarFault (selfdrived: no entry + soft disable, events.py radarFault). ON: HWFail
is advisory only: no radarFault, the radar-valid gate still holds F4 (points kept out of radard) and card raises the one warning."""
from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import DEFAULTS, PreApParamKeys as K
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, long_paths  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_radar_advisory import no_errors, ri_on, run


def test_default_off_and_nap_mapping():
  assert DEFAULTS[K.RADAR_IGNORE_HW_FAIL] is False
  assert K.RADAR_IGNORE_HW_FAIL == "TeslaRadarIgnoreHwFail"        # NAPRadarIgnoreHwFail without the NAP prefix, as the other keys
  assert params.get_bool(K.RADAR_IGNORE_HW_FAIL) is False


def test_off_hwfail_still_faults(long_paths):
  ri = ri_on(long_paths)
  outs = run(ri, 1.0, 3.0, hw=1)
  assert outs and all(o.errors.radarFault for o in outs)
  assert all(len(o.points) == 0 for o in outs) and ri.preap_gate.fault == "F4" and not ri.preap_radar_valid


def test_on_hwfail_is_advisory(long_paths):
  ri = ri_on(long_paths)
  params.set_bool(K.RADAR_IGNORE_HW_FAIL, True)
  outs = run(ri, 1.0, 11.0, hw=1)
  assert outs and no_errors(outs)                                    # no radarFault, canError or radarUnavailableTemporary
  assert all(len(o.points) == 0 for o in outs)                       # points filtered (gate F4)
  assert ri.preap_gate.fault == "F4" and not ri.preap_radar_valid    # card raises preapRadarNotReady from this (the one warning)


def test_toggle_is_read_live_each_cycle(long_paths):
  ri = ri_on(long_paths)
  on = run(ri, 1.0, 2.0, hw=1)
  params.set_bool(K.RADAR_IGNORE_HW_FAIL, True)
  off = run(ri, 2.0, 3.0, hw=1)
  params.set_bool(K.RADAR_IGNORE_HW_FAIL, False)
  again = run(ri, 3.0, 4.0, hw=1)
  assert all(o.errors.radarFault for o in on) and no_errors(off) and all(o.errors.radarFault for o in again)


def test_on_without_hwfail_unchanged(long_paths):
  ri = ri_on(long_paths)
  params.set_bool(K.RADAR_IGNORE_HW_FAIL, True)
  outs = run(ri, 1.0, 6.0)
  assert no_errors(outs) and ri.preap_radar_valid and len(outs[-1].points) == 1
