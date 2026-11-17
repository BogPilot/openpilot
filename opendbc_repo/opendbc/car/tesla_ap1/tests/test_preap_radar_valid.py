"""Pre-AP radar-valid gate (preap/radar_valid.py). Numbers come from the CAN analysis of the recorded Drive captures, a 0.9.7 Pre-AP log
and 67 AP1 power-ups (radar accepted criteria v1): F1 ITC starved / position-rejected held 1.0 s, F2 0x501 alerts in 2 frames,
F3 a frozen table (1 point, 1.5 s, only while the ITC is in the F1 set), F4 HWFail; VALID = ITC {0, 107}, flags and 0x501 clear and
a moving track, held 2.0 s, latched until a fault; PENDING otherwise. Advisory only: it filters radar points, it never blocks
engage or speed control (test_preap_radar_advisory.py)."""
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

CLEAN = {b: 0 for b in rv.ALERT_BITS}
DT = 0.0625                                                    # one radar cycle
F1_S, VALID_S, FROZEN_S, DEADLINE_S = 1.0, 2.0, 1.5, 20.0      # the analysis' numbers, not the module's constants
PHANTOMS = ((2.56, 0.0, 0.0), (3.06, 0.5, 0.0), (4.62, -0.5, 0.0))   # one recorded Drive capture's frozen table (vRel 0.00, no distance change)


def bits(**on):
  return {**CLEAN, **{f"RADC_{k}": 1 for k in on}}


def moving(t, n=2):
  return {i: (40.0 + i - 2.0 * t, 0.5 * i, -2.0) for i in range(n)}


def static(t, rows=((40.0, 0.0, 0.0), (55.0, 1.5, 0.0), (70.0, -2.0, 0.0))):
  return dict(enumerate(rows))


def phantoms(t):
  return dict(enumerate(PHANTOMS))


def feed(g, t0, t1, itc=0, sgu=False, hw=False, dirty=False, alert=CLEAN, points=moving, echo=True, v_ego=0.0, each=None):
  """0x301 + points every cycle, 0x501 once per second (alert None = no 0x501 at all)."""
  t = t0
  while t < t1 - 1e-9:
    if echo:
      g.on_echo(t)
    g.on_ego(t, v_ego(t) if callable(v_ego) else v_ego)
    if alert is not None and int(t) != int(t - DT):
      g.on_alert_matrix(t, alert(t) if callable(alert) else alert)
    g.on_sgu(t, itc(t) if callable(itc) else itc, sgu(t) if callable(sgu) else sgu, hw, dirty)
    g.on_points(t, points(t))
    g.update(t)
    if each is not None:
      each(t, g)
    t += DT
  return g


def first(g, t0, t1, cond, **kw):
  hit = []
  feed(g, t0, t1, each=lambda t, gg: hit.append(t) if not hit and cond(gg) else None, **kw)
  return hit[0] if hit else None


# ---- VALID ----

def test_starts_pending_and_needs_2_s_held():
  g = rv.RadarValidGate(True)
  t = first(g, 0.0, 6.0, lambda gg: gg.valid)
  assert t is not None and VALID_S - DT <= t <= VALID_S + 1.0 + 2 * DT   # first 0x501 at t=0, 2.0 s held
  g2 = feed(rv.RadarValidGate(True), 0.0, VALID_S - 2 * DT)
  assert g2.pending and not g2.valid and g2.fault is None


def test_itc_107_healthy_reaches_valid():
  g = feed(rv.RadarValidGate(True), 0.0, 5.0, itc=107)
  assert g.valid and g.fault is None


@pytest.mark.parametrize("itc", [90, 1, 255])
def test_other_itc_stays_pending(itc):
  g = feed(rv.RadarValidGate(True), 0.0, 30.0, itc=itc)
  assert g.pending and not g.valid and g.fault is None


def test_sgufail_aligning_with_moving_tracks_is_pending_then_valid():
  g = feed(rv.RadarValidGate(True), 0.0, 30.0, sgu=True)
  assert g.pending and g.fault is None and g.faults == 0
  t = first(g, 30.0, 40.0, lambda gg: gg.valid)
  assert t is not None and 30.0 + VALID_S - DT <= t <= 30.0 + VALID_S + 2 * DT


@pytest.mark.parametrize("adj", ["a004_adjustmentNotDone", "a005_adjustmentReq", "a006_adjustmentNotOk"])
def test_adjustment_bits_alone_are_pending_not_a_fault(adj):
  g = feed(rv.RadarValidGate(True), 0.0, 20.0, alert=bits(**{adj: 1}))
  assert g.pending and g.fault is None and not g.valid


@pytest.mark.parametrize("flag", ["hw", "dirty"])
def test_valid_needs_hwfail_and_sensordirty_clear(flag):
  g = feed(rv.RadarValidGate(True), 0.0, 10.0, **{flag: True})
  assert not g.valid


def test_no_0x501_never_valid():
  """The 0.9.7 Pre-AP log has no 0x501 at all: VALID is impossible there by design."""
  g = feed(rv.RadarValidGate(True), 0.0, 30.0, alert=None)
  assert g.pending and not g.valid


def test_valid_latches_through_a_long_no_motion_gap():
  """Once VALID it stays until a fault fires: AP1's longest moving-ego gap with no moving track was 22.5 s."""
  g = feed(rv.RadarValidGate(True), 0.0, 5.0)
  assert g.valid
  feed(g, 5.0, 5.0 + 23.0, points=static)
  assert g.valid and g.fault is None and g.faults == 0


def test_moving_by_distance_change_alone():
  slow = lambda t: {0: (60.0 - 0.3 * t, 0.0, -0.3)}       # |vRel| < 0.5, 0.6 m in 2 s
  creep = lambda t: {0: (60.0 - 0.2 * t, 0.0, -0.2)}      # 0.4 m in 2 s: not moving
  assert feed(rv.RadarValidGate(True), 0.0, 8.0, points=slow).valid
  assert not feed(rv.RadarValidGate(True), 0.0, 8.0, points=creep).valid


def test_no_pending_long_setting_left():
  # advisory only: no PENDING_LONG_OK, no long_ok output, nothing for speed control to read
  assert not hasattr(rv, "PENDING_LONG_OK")
  with pytest.raises(TypeError):
    rv.RadarValidGate(True, pending_long_ok=True)
  g = feed(rv.RadarValidGate(True), 0.0, 10.0, sgu=True)
  assert g.pending and not hasattr(g, "long_ok") and "long_ok" not in g.status()


# ---- FAULTS ----

@pytest.mark.parametrize("itc", sorted(rv.ITC_FAULT))
def test_f1_itc_fault_set_held_1_s(itc):
  g = feed(rv.RadarValidGate(True), 0.0, 5.0)
  assert g.valid
  t = first(g, 5.0, 8.0, lambda gg: "F1" in gg.active, itc=itc, points=moving)
  assert t is not None and 5.0 + F1_S - DT <= t <= 5.0 + F1_S + DT
  assert not g.valid and g.faults == 1
  feed(g, 8.0, 8.0 + 3 * DT, itc=0)
  assert g.pending and not g.valid                         # not latching; VALID must be earned again
  assert feed(g, 8.2, 11.0).valid


def test_f1_short_blip_is_not_a_fault():
  g = feed(rv.RadarValidGate(True), 0.0, 5.0)
  feed(g, 5.0, 5.0 + F1_S - 2 * DT, itc=67)
  assert g.valid and g.fault is None


@pytest.mark.parametrize("bit", [b[len("RADC_"):] for b in rv.F2_BITS])
def test_f2_needs_two_consecutive_frames_and_two_clear_frames_to_clear(bit):
  g = rv.RadarValidGate(True)
  g.on_alert_matrix(0.0, bits(**{bit: 1}))
  g.on_alert_matrix(1.0, CLEAN)
  g.on_alert_matrix(2.0, bits(**{bit: 1}))
  g.update(2.0)
  assert "F2" not in g.active
  g.on_alert_matrix(3.0, bits(**{bit: 1}))
  g.update(3.0)
  assert "F2" in g.active
  g.on_alert_matrix(4.0, CLEAN)
  g.update(4.0)
  assert "F2" in g.active
  g.on_alert_matrix(5.0, CLEAN)
  g.update(5.0)
  assert "F2" not in g.active


def test_f4_hwfail_is_immediate():
  g = feed(rv.RadarValidGate(True), 0.0, 5.0)
  feed(g, 5.0, 5.0 + DT, hw=True)
  assert g.fault == "F4" and not g.valid


def test_no_echo_with_the_gateway_flag_only():
  g = feed(rv.RadarValidGate(True), 0.0, 5.0)
  feed(g, 5.0, 5.0 + rv.ECHO_S + DT, echo=False)
  assert g.fault == "NO_ECHO" and not g.echoed and not g.valid
  assert feed(rv.RadarValidGate(False), 0.0, 5.0, echo=False).valid


# ---- F3 frozen table: the numbers behind 1 point, 1.5 s and the ITC gate ----

def _f3_time(g, itc=67, points=phantoms, t1=5.0):
  return first(g, 0.0, t1, lambda gg: "F3" in gg.active, itc=itc, points=points, alert=bits(a012_espMIA=1))


def test_f3_one_point_fires_on_tester_2_phantoms_and_four_does_not():
  assert _f3_time(rv.RadarValidGate(True)) is not None
  assert _f3_time(rv.RadarValidGate(True, frozen_min_points=4), t1=30.0) is None   # only 3 phantoms


def test_f3_1_5_s_meets_the_2_s_target_and_2_4_s_misses_it():
  t = _f3_time(rv.RadarValidGate(True))
  assert t is not None and FROZEN_S - DT <= t <= 2.0
  t24 = _f3_time(rv.RadarValidGate(True, frozen_s=2.4))
  assert t24 is not None and t24 > 2.0


def test_f3_ungated_false_faults_on_a_parked_ap1_scene_gated_does_not():
  """Parked healthy radar: ITC 0, a static scene unchanged for up to 9.81 s on AP1."""
  ungated = rv.RadarValidGate(True, frozen_gated=False)
  assert first(ungated, 0.0, 9.81, lambda gg: "F3" in gg.active, points=static) is not None
  gated = rv.RadarValidGate(True)
  assert first(gated, 0.0, 9.81, lambda gg: gg.fault is not None, points=static) is None
  assert gated.pending                                     # parked with no moving track yet: PENDING, not a fault


def test_tester_2_like_radar_faults_by_about_1_s_and_never_reaches_valid():
  g = rv.RadarValidGate(True)
  t = first(g, 0.0, 30.0, lambda gg: gg.fault is not None, itc=67, points=phantoms, alert=bits(a012_espMIA=1))
  assert t is not None and t <= F1_S + DT
  feed(g, t + DT, 30.0, itc=67, points=phantoms, alert=bits(a012_espMIA=1))
  assert {"F1", "F2", "F3"} <= g.active and not g.valid and g.faults == 0


# ---- late label ----

def test_late_counts_from_the_later_of_radar_start_and_first_moving():
  g = feed(rv.RadarValidGate(True), 0.0, 25.0, points=static)                     # parked 25 s
  assert not g.late and g.pending
  feed(g, 25.0, 25.0 + DEADLINE_S - 1.0, points=static, v_ego=5.0)                # moving, but no moving track
  assert not g.late and not g.valid                                               # 19 s after moving off: not yet
  feed(g, 25.0 + DEADLINE_S - 1.0, 25.0 + DEADLINE_S + 1.0, points=static, v_ego=5.0)
  assert g.late and not g.valid
  g2 = feed(rv.RadarValidGate(True), 0.0, 25.0, points=static)
  t = first(g2, 25.0, 30.0, lambda gg: gg.valid, v_ego=5.0)                       # moves off with real tracks
  assert t is not None and t <= 25.0 + VALID_S + 1.0 + 2 * DT and not g2.late


def test_status_reports_echoed_pending_valid_and_fault_separately():
  g = feed(rv.RadarValidGate(True), 0.0, 1.0)
  st = g.status()
  assert (st["echoed"], st["pending"], st["valid"], st["fault"]) == (True, True, False, "-")
  feed(g, 1.0, 5.0)
  st = g.status()
  assert (st["echoed"], st["pending"], st["valid"], st["fault"]) == (True, False, True, "-")
  feed(g, 5.0, 5.0 + rv.ECHO_S + DT, echo=False)
  st = g.status()
  assert (st["echoed"], st["pending"], st["valid"], st["fault"]) == (False, False, False, "NO_ECHO")


# ---- radar_interface: points dropped while invalid, status line ----

def _frames(packer, t, echo=True, itc=0):
  msgs = [packer.make_can_msg("TeslaRadarSguInfo", 1, {"RADC_SGU_ITC": itc}),
          packer.make_can_msg("RadarPoint0_A", 1, {"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": 40.0, "LongSpeed": -3.0,
                                                   "ProbExist": 96.875}),
          packer.make_can_msg("RadarPoint0_B", 1, {"Index2": 1}),
          packer.make_can_msg("RadarPoint31_B", 1, {})]
  if int(t) != int(t - 0.0625):
    msgs.append(packer.make_can_msg("TeslaRadarAlertMatrix", 1, {}))   # clean 0x501, ~1 Hz
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
  early = [o for tt, o in outs if tt < 1.0 + VALID_S - 0.1]
  late = [o for tt, o in outs if tt > 1.0 + VALID_S + 0.3]
  assert early and all(len(o.points) == 0 for o in early)
  assert late and all(len(o.points) == 1 for o in late) and ri.preap_radar_valid
  while t < 8.0:
    o = ri.update(_frames(packer, t, echo=False)); t += 0.0625
  assert not ri.preap_radar_valid and len(o.points) == 0 and not o.errors.radarFault   # gate, not a radar fault
  assert ri.preap_gate.fault == "NO_ECHO"
  assert any("echoed=1 pending=1 valid=0 fault=-" in m for m in lines)
  assert any("echoed=1 pending=0 valid=1 fault=-" in m for m in lines)
  assert any("echoed=0 pending=0 valid=0 fault=NO_ECHO" in m for m in lines)
  assert len(lines) < 12                                          # rate-limited: changes plus one line per 5 s


def test_radar_interface_position_rejected_itc_is_echoed_and_faulted(long_paths):
  ri, packer = _ri(long_paths)
  t = 1.0
  while t < 6.0:
    o = ri.update(_frames(packer, t, itc=96)); t += 0.0625
  g = ri.preap_gate
  assert g.echoed and g.fault == "F1" and not g.valid and not ri.preap_radar_valid and len(o.points) == 0


def test_radar_interface_itc_107_reaches_valid(long_paths):
  ri, packer = _ri(long_paths)
  t = 1.0
  while t < 6.0:
    o = ri.update(_frames(packer, t, itc=107)); t += 0.0625
  assert ri.preap_gate.valid and ri.preap_radar_valid and len(o.points) == 1


def test_card_feeds_v_ego_to_the_gate_before_the_radar_update():
  import pathlib
  src = (pathlib.Path(__file__).resolve().parents[5] / "openpilot/selfdrive/car/card.py").read_text()
  a = src.index("self.RI.preap_v_ego = float(CS.vEgo)")
  assert a < src.index("RD: structs.RadarDataT | None = self.RI.update(can_list)")


def test_ap1_has_no_gate():
  from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import ap1_cp
  ri = RadarInterface(ap1_cp())
  assert ri.preap_gate is None and ri.preap_radar_valid


# ---- pull FSM: the radar is not an input (NAP / Tinkla), FULL engages and stays ----

def test_pull_fsm_has_no_radar_input():
  c = Car(pedal=True)
  assert not hasattr(c.rig.cs, "preap_radar_ok")
  out = _double_pull(c)
  assert c.mode == Mode.FULL and out.cruiseState.enabled and not out.bogpilot.preapLatOnly
  for _ in range(50):
    out = c.step()
  assert c.mode == Mode.FULL and not out.bogpilot.preapLatOnly
