"""AP105 cluster frames use the DBC the AP1 platform really loads (tesla_ap1_can.dbc).

tesla_can.dbc packs DAS_accSpeedLimit with factor 0.2; the AP1 instrument cluster (and tesla_ap1_can.dbc) read 0.4,
so a 30 mph set speed was shown as 60. Display only: no panda or control frame is involved.
"""
import os

from opendbc import DBC_PATH
from opendbc.car.tesla_ap1 import cluster as c


def _hud(**kw):
  args = dict(enabled=True, fcw=False, steer_required=False, audible=False, human_steering=False,
              left_lane_depart=False, right_lane_depart=False, left_blinker=False, right_blinker=False,
              curvature=0.0, ic_integration=True, model_path=None, cruise_set_mph=None)
  args.update(kw)
  return c.HudInputs(**args)


def test_cluster_loads_the_ap1_dbc_the_platform_uses():
  assert os.path.basename(c._dbc_path()) == "tesla_ap1_can.dbc"
  assert os.path.exists(c._dbc_path())


def test_acc_speed_limit_factor_is_0_4():
  sig = c.SIGNALS[c.DAS_STATUS2]["DAS_accSpeedLimit"]
  assert (sig.start, sig.size, sig.factor, sig.offset) == (0, 10, 0.4, 0.0)
  # the legacy DBC would have doubled it; the cluster must not be built from that file
  legacy = c.load_signals(os.path.join(DBC_PATH, "tesla_can.dbc"))[c.DAS_STATUS2]["DAS_accSpeedLimit"]
  assert legacy.factor == 0.2


def test_30_mph_packs_as_raw_75_and_decodes_back_to_30():
  word = c.build_das_status2({}, _hud(cruise_set_mph=30), "engaged")
  dat = word.to_bytes(8, "little")
  assert c.get_raw(word, 0, 10) == 75
  assert c.unpack(c.DAS_STATUS2, dat)["DAS_accSpeedLimit"] == 30.0
  for mph in (20, 40, 60, 80):
    w = c.build_das_status2({}, _hud(cruise_set_mph=mph), "engaged")
    assert c.get_raw(w, 0, 10) == round(mph / 0.4)
    assert c.unpack(c.DAS_STATUS2, w.to_bytes(8, "little"))["DAS_accSpeedLimit"] == mph


def test_cluster_signals_other_than_the_set_speed_are_unchanged():
  legacy = c.load_signals(os.path.join(DBC_PATH, "tesla_can.dbc"))
  for addr, sigs in c.SIGNALS.items():
    for name, sig in sigs.items():
      if (addr, name) != (c.DAS_STATUS2, "DAS_accSpeedLimit"):
        assert legacy[addr][name] == sig, (hex(addr), name)
