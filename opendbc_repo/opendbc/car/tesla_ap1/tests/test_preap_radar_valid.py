"""Pre-AP radar-valid gate (preap/radar_valid.py): no radar points and no speed control until the radar ACCEPTED its config
(ITC 0, 0x501 clear, moving tracks), and while it is unconfigured (no gateway echo), starved (0x501 MIA), rejecting its config
(0x501 position / VIN / xWD validity) or frozen with SGUFail. Echoed and accepted are separate. Lateral is untouched."""
from types import SimpleNamespace

import pytest
from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.tesla_ap1.preap import radar_valid as rv
from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.preap.panda_link import GTW_ECHO_SRC
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, long_paths, preap_cp, store  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_full_demote import Car, _double_pull
from opendbc.car.tesla_ap1.values import CAR, DBC

CLEAN = {b: 0 for b in rv.MIA_BITS + rv.REJECT_BITS}
DT = 0.06


def moving(t, n=2):
  return [SimpleNamespace(dRel=40.0 + i - 2.0 * t, yRel=0.5 * i, vRel=-2.0) for i in range(n)]


def still(n=1):
  return [SimpleNamespace(dRel=40.0 + i, yRel=0.5 * i, vRel=0.0) for i in range(n)]


def run(g, t0, t1, echo=True, sgu=False, itc=0, alert=CLEAN, points=moving):
  """points: callable(t) -> list, or a fixed list. 0x501 at 1 Hz."""
  t = t0
  while t < t1 - 1e-9:
    if echo:
      g.on_echo(t)
    if alert is not None and int(t) != int(t - DT):
      g.on_alert_matrix(t, alert)
    g.on_points(t, points(t) if callable(points) else points, sgu, itc)
    g.update(t, sgu)
    t += DT
  return g


def valid_gate(emu=True):
  g = run(rv.RadarValidGate(emu), 0.0, rv.CLEAR_S + 0.3)
  assert g.valid and g.accepted and g.echoed
  return g


# ---- acceptance ----

def test_starts_invalid_and_needs_acceptance_for_clear_s():
  g = run(rv.RadarValidGate(True), 0.0, rv.CLEAR_S - 0.1)
  assert not g.valid and g.echoed and not g.accepted
  run(g, rv.CLEAR_S - 0.1, rv.CLEAR_S + 0.3)
  assert g.valid and g.accepted and g.faults == 0


def test_healthy_radar_with_sgufail_while_aligning_still_reaches_valid():
  """The 2 s rule is on acceptance (ITC 0, 0x501 clear, moving tracks), not on SGUFail: alignment can't block long forever."""
  g = run(rv.RadarValidGate(True), 0.0, 60.0, sgu=True)
  assert g.valid and g.accepted and g.reasons == 0


@pytest.mark.parametrize("kw,label", [(dict(itc=96), "itc"), (dict(alert=dict(CLEAN, RADC_a061_radPositionMismatch=1)), "a061"),
                                      (dict(points=still(3)), "no moving track"), (dict(points=[]), "no points")])
def test_echoed_but_not_accepted_never_valid_and_labelled_after_20_s(kw, label):
  g = run(rv.RadarValidGate(True), 0.0, rv.ACCEPT_S - 0.5, **kw)
  assert g.echoed and not g.accepted and not g.valid and not g.reasons & rv.NOT_ACCEPTED
  run(g, rv.ACCEPT_S - 0.5, rv.ACCEPT_S + 1.0, **kw)
  assert g.echoed and not g.accepted and not g.valid and g.reasons & rv.NOT_ACCEPTED
  st = g.status()
  assert st["echoed"] and not st["accepted"]


def test_status_reports_echoed_and_accepted_separately():
  g = rv.RadarValidGate(True)
  assert g.status()["echoed"] is False and g.status()["accepted"] is False
  run(g, 0.0, 1.0, itc=96)
  assert g.status()["echoed"] is True and g.status()["accepted"] is False and g.status()["itc"] == 96
  run(g, 1.0, 4.0)
  assert g.status()["echoed"] is True and g.status()["accepted"] is True


def test_sgufail_with_live_tracks_keeps_a_valid_gate():
  g = valid_gate()
  run(g, 3.0, 30.0, sgu=True)
  assert g.valid


# ---- invalidating conditions ----

def test_d1_no_gateway_echo_drops_acceptance():
  g = valid_gate()
  run(g, 2.4, 2.4 + rv.HOLD_S - 0.1, echo=False)
  assert g.valid
  run(g, 4.3, 4.8, echo=False)
  assert not g.valid and not g.accepted and not g.echoed and g.reasons & rv.D1 and g.faults == 1
  run(g, 4.8, 4.8 + rv.CLEAR_S - 0.1)
  assert not g.valid
  run(g, 6.7, 7.3)
  assert g.valid


def test_d1_off_without_the_gateway_flag():
  g = run(rv.RadarValidGate(False), 0.0, 30.0, echo=False)
  assert g.valid and g.echoed and g.faults == 0


@pytest.mark.parametrize("bit,reason", [("RADC_a013_gtwMIA", rv.D2), ("RADC_a011_bdyMIA", rv.D2),
                                        ("RADC_a061_radPositionMismatch", rv.D3), ("RADC_a037_vinValidity", rv.D3),
                                        ("RADC_a042_xwdValidity", rv.D3)])
def test_d2_d3_need_two_frames_held_2_s(bit, reason):
  g = valid_gate()
  bad = dict(CLEAN, **{bit: 1})
  g.on_alert_matrix(3.0, bad); g.on_alert_matrix(4.0, CLEAN)       # one-frame glitch
  run(g, 4.05, 8.0, alert=None)
  assert g.valid
  g.on_alert_matrix(10.0, bad); run(g, 10.0, 10.9, alert=None)
  g.on_alert_matrix(11.0, bad); run(g, 11.0, 11.9, alert=None)
  assert g.valid                                                  # 2 frames but held < 2 s
  g.on_alert_matrix(12.0, bad); run(g, 12.0, 12.2, alert=None)
  assert not g.valid and g.reasons & reason


@pytest.mark.parametrize("n", [1, 3])
def test_d6_frozen_one_or_more_points_with_sgufail(n):
  assert rv.FROZEN_MIN_POINTS == 1
  g = valid_gate()
  frozen = [SimpleNamespace(dRel=30.0 + i, yRel=0.0, vRel=-1.0) for i in range(n)]    # moving vRel, table unchanged
  run(g, 3.0, 3.0 + rv.FROZEN_S - 0.2, sgu=True, points=frozen)
  assert g.valid
  run(g, 7.8, 8.3, sgu=True, points=frozen)
  assert not g.valid and g.reasons & rv.D6


def test_d6_needs_sgufail():
  g = valid_gate()
  frozen = [SimpleNamespace(dRel=30.0, yRel=0.0, vRel=-1.0)]
  run(g, 3.0, 15.0, sgu=False, points=frozen)
  assert g.valid


# ---- radar_interface: points dropped while invalid, status line ----

def _frames(packer, t, echo=True, itc=0):
  msgs = [packer.make_can_msg("TeslaRadarSguInfo", 1, {"RADC_SGU_ITC": itc}),
          packer.make_can_msg("RadarPoint0_A", 1, {"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": 40.0, "LongSpeed": -3.0,
                                                   "ProbExist": 96.875}),
          packer.make_can_msg("RadarPoint0_B", 1, {"Index2": 1}),
          packer.make_can_msg("RadarPoint31_B", 1, {})]
  if echo:
    msgs.append((0x109, b"\x00" * 8, GTW_ECHO_SRC))   # returned echo of a gateway frame on bus 1
  return [(int(t * 1e9), msgs)]


def _ri(long_paths):
  long_paths(True)
  store(radar=True)
  cp = preap_cp()
  assert cp.safetyConfigs[-1].safetyParam & 256
  return RadarInterface(cp), CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar])


def test_radar_interface_drops_points_until_accepted_and_on_lost_echo(long_paths, monkeypatch):
  import opendbc.car.tesla_ap1.radar_interface as ri_mod
  lines = []
  monkeypatch.setattr(ri_mod.carlog, "info", lambda m: lines.append(m))
  ri, packer = _ri(long_paths)
  outs, t = [], 1.0
  while t < 5.0:
    outs.append((t, ri.update(_frames(packer, t)))); t += 0.0625
  early = [o for tt, o in outs if tt < 1.0 + rv.CLEAR_S - 0.1]
  late = [o for tt, o in outs if tt > 1.0 + rv.CLEAR_S + 0.3]
  assert early and all(len(o.points) == 0 for o in early)
  assert late and all(len(o.points) == 1 for o in late) and ri.preap_radar_valid
  while t < 8.0:
    o = ri.update(_frames(packer, t, echo=False)); t += 0.0625
  assert not ri.preap_radar_valid and len(o.points) == 0 and not o.errors.radarFault   # gate, not a radar fault
  assert ri.preap_gate.reasons & rv.D1
  assert any("echoed=1 accepted=0" in m for m in lines) and any("echoed=1 accepted=1 valid=1" in m for m in lines)
  assert any("echoed=0 accepted=0 valid=0" in m for m in lines)
  assert len(lines) < 12                                          # rate-limited: changes plus one line per 5 s


def test_radar_interface_itc_nonzero_is_echoed_not_accepted(long_paths):
  ri, packer = _ri(long_paths)
  t = 1.0
  while t < 6.0:
    o = ri.update(_frames(packer, t, itc=96)); t += 0.0625
  assert ri.preap_gate.echoed and not ri.preap_gate.accepted and not ri.preap_radar_valid and len(o.points) == 0


def test_ap1_has_no_gate():
  from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import ap1_cp
  ri = RadarInterface(ap1_cp())
  assert ri.preap_gate is None and ri.preap_radar_valid


# ---- pull FSM: no speed control while invalid, steering kept ----

def test_full_refused_while_radar_invalid():
  c = Car(pedal=True)
  c.rig.cs.preap_radar_ok = False
  out = _double_pull(c)
  assert c.mode != Mode.FULL and c.enabled_frames == 0 and not (out.cruiseState.enabled and not out.bogpilot.preapLatOnly)


def test_full_drops_to_steering_only_when_radar_goes_invalid():
  c = Car(pedal=True)
  _double_pull(c)
  assert c.mode == Mode.FULL
  c.rig.cs.preap_radar_ok = False
  for _ in range(5):
    out = c.step()
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly and c.op
