"""Pre-AP radar is advisory (NAP / Tinkla): nothing about the radar stops a Pre-AP car engaging.

A radar that is not VALID (never configured, silent from boot, SGUFail, any ITC, radPositionMismatch, a frozen 1-point table)
only keeps its points out of radard (camera leads) and raises carState.bogpilot.preapRadarNotReady (one warning). Only
RADC_HWFail is a radarFault. References: NAP nap-alpha 92b42f772 (opendbc 508d26fcb) radar_interface.py:176-177 (no error
before the trigger message) and :203-214 (SGUFail ignored, HWFail faults); opendbc f29a061c (ignore SGUFail), ebd04ce3 (drop
frozen + SGU tracks instead of faulting)."""
import pytest
from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.ap1_events import PREAP_RADAR_NOT_READY, Ap1Events
from opendbc.car.tesla_ap1.preap import radar_valid as rv
from opendbc.car.tesla_ap1.preap.panda_link import GTW_ECHO_SRC
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, long_paths, preap_cp, store  # noqa: F401
from opendbc.car.tesla_ap1.values import CAR, DBC

DT = 0.0625
PACKER = CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar])


def radar_frames(t, itc=0, sgu=0, hw=0, alert=None, points=((40.0, 0.0, -3.0),), echo=True, frozen=False):
  """One radar cycle at time t: 0x301, all 32 point slots (the given ones tracked, moving unless frozen; the rest untracked, as the
  radar sends every slot each cycle), 0x501 once per second, a gateway echo. RadarPoint31_B is the trigger."""
  msgs = [PACKER.make_can_msg("TeslaRadarSguInfo", 1, {"RADC_SGU_ITC": itc, "RADC_SGUFail": sgu, "RADC_HWFail": hw})]
  for i in range(32):
    if i < len(points):
      d, y, v = points[i]
      a = {"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": d if frozen else d + v * t, "LatDist": y, "LongSpeed": v, "ProbExist": 96.875}
    else:
      a = {"Tracked": 0, "Index": 1}
    msgs += [PACKER.make_can_msg(f"RadarPoint{i}_A", 1, a), PACKER.make_can_msg(f"RadarPoint{i}_B", 1, {"Index2": 1})]
  if int(t) != int(t - DT):
    msgs.append(PACKER.make_can_msg("TeslaRadarAlertMatrix", 1, alert or {}))
  if echo:
    msgs.append((0x109, b"\x00" * 8, GTW_ECHO_SRC))
  return [(int(t * 1e9), msgs)]


def ri_on(long_paths):
  long_paths(True)
  store(radar=True)
  return RadarInterface(preap_cp())


def run(ri, t0, t1, **kw):
  outs, t = [], t0
  while t < t1 - 1e-9:
    outs.append(ri.update(radar_frames(t, **kw)))
    t += DT
  return [o for o in outs if o is not None]


def no_errors(outs):
  return all(not any(o.errors.to_dict().values()) for o in outs)


def test_never_configured_radar_is_the_base_publisher(long_paths):
  long_paths(True)
  cp = preap_cp()                                   # radar toggle never set
  ri = RadarInterface(cp)
  assert cp.radarUnavailable and ri.rcp is None and ri.preap_gate is None
  outs = [o for o in (ri.update([]) for _ in range(1000)) if o is not None]
  assert len(outs) == 200 and no_errors(outs) and not any(o.points for o in outs)


def test_silent_from_boot_never_errors(long_paths):
  ri = ri_on(long_paths)
  outs = [o for o in (ri.update([]) for _ in range(3000)) if o is not None]    # 30 s at 100 Hz, no radar frame at all
  assert len(outs) == 600 and no_errors(outs) and not any(o.points for o in outs)
  assert not ri.preap_radar_valid and not ri.preap_radar_spoke


def test_sgufail_every_frame_no_fault_points_filtered(long_paths):
  ri = ri_on(long_paths)
  outs = run(ri, 1.0, 31.0, sgu=1)
  assert outs and no_errors(outs)                  # no radarFault, canError or radarUnavailableTemporary
  assert all(len(o.points) == 0 for o in outs)     # SGUFail held: PENDING, points kept out of radard
  assert ri.preap_gate.pending and ri.preap_gate.fault is None and not ri.preap_radar_valid


@pytest.mark.parametrize("itc", [96, 67, 68, 70, 83, 90, 1, 255])
def test_any_itc_no_fault(long_paths, itc):
  ri = ri_on(long_paths)
  outs = run(ri, 1.0, 11.0, itc=itc)
  assert outs and no_errors(outs) and all(len(o.points) == 0 for o in outs)


@pytest.mark.parametrize("itc", [0, 107])
def test_healthy_itc_reaches_valid_and_publishes(long_paths, itc):
  ri = ri_on(long_paths)
  outs = run(ri, 1.0, 6.0, itc=itc)
  assert no_errors(outs) and ri.preap_radar_valid and len(outs[-1].points) == 1


def test_rad_position_mismatch_filters_only(long_paths):
  ri = ri_on(long_paths)
  outs = run(ri, 1.0, 11.0, alert={"RADC_a061_radPositionMismatch": 1})
  assert outs and no_errors(outs) and all(len(o.points) == 0 for o in outs)
  assert ri.preap_gate.fault == "F2"


def test_mismatch_after_valid_drops_points_without_an_error(long_paths):
  ri = ri_on(long_paths)
  run(ri, 1.0, 6.0)
  assert ri.preap_radar_valid
  outs = run(ri, 6.0, 10.0, alert={"RADC_a061_radPositionMismatch": 1})
  assert no_errors(outs) and not ri.preap_radar_valid and len(outs[-1].points) == 0


@pytest.mark.parametrize("itc", [96, 67])
def test_frozen_one_point_is_dropped_only(long_paths, itc):
  ri = ri_on(long_paths)
  outs = run(ri, 1.0, 1.0 + 1.5 + 4 * DT, itc=itc, points=((4.62, -0.5, 0.0),), frozen=True)
  assert no_errors(outs) and all(len(o.points) == 0 for o in outs)
  assert "F3" in ri.preap_gate.active


def test_hwfail_still_faults(long_paths):
  ri = ri_on(long_paths)
  outs = run(ri, 1.0, 2.0, hw=1)
  assert outs and all(o.errors.radarFault for o in outs)
  assert not any(o.errors.canError or o.errors.radarUnavailableTemporary for o in outs)
  assert ri.preap_gate.fault == "F4"


def test_status_line_has_no_long_ok(long_paths, monkeypatch):
  import opendbc.car.tesla_ap1.radar_interface as ri_mod
  lines = []
  monkeypatch.setattr(ri_mod.carlog, "info", lambda m: lines.append(m))
  run(ri_on(long_paths), 1.0, 3.0, sgu=1)
  assert lines and all("long_ok" not in m and "camera_lead=1" in m for m in lines)


# ---- the one warning ----

class _Bp:
  ap1DriverYield = False
  ap1HandsOnLevel = 0
  ap1EacInhibited = False

  def __init__(self, **kw):
    for k, v in kw.items():
      setattr(self, k, v)


def test_warning_is_the_only_event_and_only_while_enabled():
  ev = Ap1Events()
  assert ev.update([], True, True, _Bp(preapRadarNotReady=True)) == [PREAP_RADAR_NOT_READY]
  assert ev.update([], False, False, _Bp(preapRadarNotReady=True)) == []
  assert ev.update([], True, True, _Bp(preapRadarNotReady=False)) == []


def test_gate_has_no_engage_api():
  assert not hasattr(rv, "PENDING_LONG_OK")
  for name in ("long_ok", "pending_long_ok"):
    assert not hasattr(rv.RadarValidGate(True), name)
