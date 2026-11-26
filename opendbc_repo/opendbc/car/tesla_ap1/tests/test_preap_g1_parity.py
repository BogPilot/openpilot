"""Pre-AP G1 parity: the car state resets the engagement on exactly the inputs on which the panda drops controls.

The panda side is a line-by-line Python mirror of opendbc/safety/modes/tesla_preap.h (with the G1 change):
tesla_preap_epas_state (0x370 decode + drop, which also sets tesla_preap_need_fresh_pull), tesla_preap_stalk (0x45 pull,
ignored while held through a drop until a release and a new pull; cancel with the 600 ms echo window) and pcm_cruise_check
(opendbc/safety/safety.h). test_c_source_matches_the_mirror pins the C lines the mirror copies, so a change to
the panda conditions fails here until the mirror (and preap_steer_drop) follow. The G1 conditions are the ones in NAP
tesla_preap.h (NAP @ e99f4dc75, opendbc submodule @ cc39c7fa) and BogPilot na-preap safety_tesla_preap.h @ 568fea947
(hands on / EPAS rejecting disengage).

Both sides get the SAME raw frames: every frame the car-state rig packs is captured and fed to the mirror in bus order. Each tick
checks:
  - decision parity: on every tick with an EPAS_sysStatus frame, the mirror's drop decision == carstate.preap_panda_drop, and
    the mirror's blocking state == carstate.preap_epas_refusing;
  - openpilot never shows engaged (cruiseState.enabled) while the panda has controls_allowed False;
  - the host never sends ANGLE the panda would reject (controls_allowed False or EPAS blocking);
  - carState.steeringDisengage equals the panda's EPAS blocking state on every EPAS frame (hands 3 / refusal).
Not a replay of the compiled panda: libsafety is not built here (no scons). Gear and doors are held at D / closed.
"""
from pathlib import Path

import pytest

import opendbc
from opendbc.car import structs
from opendbc.car.tesla_ap1.hso import AP1_RESUME_HOLD_FRAMES
from opendbc.car.tesla_ap1.preap.engagement import preap_steer_drop
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import (  # noqa: F401  (autouse fixture)
  CANCEL, PULL, _act, _inv, _pedal_frame, _ready_rig, _params_dir)

PANDA_SRC = Path(opendbc.__file__).parent / "safety" / "modes" / "tesla_preap.h"
EAC_INHIBITED, EAC_AVAILABLE, EAC_ACTIVE, EAC_FAULT, EAC_SNA = 0, 1, 2, 3, 4


class PandaPreapMirror:
  """tesla_preap.h state relevant to G1 (tesla_preap_init_config values at start)."""
  def __init__(self):
    self.controls_allowed = False
    self.cruise_engaged_prev = False
    self.epas_blocking = False
    self.lever_engage_prev = False
    self.need_fresh_pull = False
    self.last_stalk_engage_us = 0
    self.steer_armed = False
    self.steer_brake_seen = False
    self.gear_d, self.doors_open = True, False
    self.now_us = 0
    self.last_drop = None          # decision of the last 0x370 frame (None before the first one)

  def pcm_cruise_check(self, cruise_engaged):
    if not cruise_engaged:
      self.controls_allowed = False
    if cruise_engaged and not self.cruise_engaged_prev:
      self.controls_allowed = True
    self.cruise_engaged_prev = cruise_engaged

  def epas_state(self, d):
    hands_on_level = d[4] >> 6
    eac_status = d[6] >> 5
    eac_error_code = d[2] >> 4
    epas_rejecting = (eac_status == 0) and (6 <= eac_error_code <= 9)
    self.epas_blocking = (hands_on_level >= 3) or epas_rejecting
    drop = self.epas_blocking or (eac_status == 3)
    if drop:
      self.controls_allowed = False
      self.pcm_cruise_check(False)
      self.need_fresh_pull = True
      self.steer_armed = False
      self.steer_brake_seen = False
    self.last_drop = drop

  def stalk(self, d):
    lever = d[0] & 0x3F
    if lever == 2:
      if self.need_fresh_pull and self.lever_engage_prev:
        pass                       # pull held through an EPAS drop: ignored until a release and a new pull
      elif self.gear_d and not self.doors_open:
        self.need_fresh_pull = False
        if not self.lever_engage_prev:
          self.cruise_engaged_prev = False
        self.pcm_cruise_check(True)
        self.last_stalk_engage_us = self.now_us
        self.steer_armed = True
        self.steer_brake_seen = False
    elif lever == 1:
      if (self.now_us - self.last_stalk_engage_us) > 600000:
        self.pcm_cruise_check(False)
        self.steer_armed = False
        self.steer_brake_seen = False
    self.lever_engage_prev = (lever == 2)

  def rx(self, addr, bus, d):
    if bus != 0:
      return
    if addr == 0x370:
      self.epas_state(d)
    elif addr == 0x45:
      self.stalk(d)

  def angle_ok(self):
    return self.controls_allowed and not self.epas_blocking


def fresh_pull_parity(cs, panda, hold, stalk):
  """carstate.preap_fresh_pull_pending vs tesla_preap_need_fresh_pull after the same frames. Returns (ok, hold).

  Equal on every tick, with one allowed difference, always in the stricter direction (carstate pending, panda not): carstate decides
  the drop from the latest EPAS_sysStatus values, so a pull in the same update as a drop (the panda sees 0x370 then 0x45 and clears),
  or a pull while EPAS frames are missing after a drop, leaves carstate pending until a release and a new pull. hold tracks that window:
  it starts on a tick where carstate's drop decision is set and lasts while the lever stays pulled.
  """
  hold = bool(cs.preap_panda_drop) or (hold and stalk == PULL)
  pending, need = bool(cs.preap_fresh_pull_pending), bool(panda.need_fresh_pull)
  return pending == need or (pending and not need and hold), hold


class Parity:
  def __init__(self, hands=0, status=EAC_AVAILABLE, err=0):
    self.rig, self.ctl = _ready_rig(double=False)
    self.panda = PandaPreapMirror()
    self.hands, self.status, self.err = hands, status, err
    self.epas_on = True
    self.corrupt = False           # bad checksum byte and a stuck counter on 0x370 (neither side checks them)
    self.op = False
    self.n = 0
    self.out = None
    self.ticks = []                # (epas frame this tick, panda drop, cs drop, panda blocking, cs refusing)
    self.violations = []
    self.fresh_hold = False
    self._rx = []
    orig = self.rig.packer.make_can_msg

    def capture(name, bus, values):
      addr, dat, b = orig(name, bus, values)
      if addr == 0x370 and self.corrupt:
        dat = bytes(dat[:6]) + bytes([dat[6] & 0xE0, dat[7] ^ 0xFF])
      self._rx.append((addr, bus, bytes(dat)))
      return addr, dat, b
    self.rig.packer.make_can_msg = capture

  def step(self, n=1, stalk=0):
    sent = []
    for _ in range(n):
      self._rx = []
      if self.epas_on:
        self.rig.base["EPAS_sysStatus"] = {"EPAS_torsionBarTorque": 0.0, "EPAS_internalSAS": 0.0, "EPAS_handsOnLevel": self.hands,
                                           "EPAS_eacStatus": self.status, "EPAS_eacErrorCode": self.err}
      else:
        self.rig.base.pop("EPAS_sysStatus", None)
      _pedal_frame(self.rig, self.n)
      self.out = self.rig.frame(stalk=stalk, op=self.op)
      self.rig.cs.out = self.out
      self.panda.now_us += 10_000
      epas_frame = False
      for addr, bus, dat in self._rx:
        self.panda.rx(addr, bus, dat)
        epas_frame = epas_frame or (addr == 0x370 and bus == 0)
      cs = self.rig.cs
      enable_req = cs.update_button_enable(self.out.buttonEvents)
      self.op = bool(self.op and self.out.cruiseState.enabled) or bool(enable_req and self.out.cruiseState.available)
      self.ticks.append((epas_frame, self.panda.last_drop, cs.preap_panda_drop, self.panda.epas_blocking, cs.preap_epas_refusing))
      if epas_frame and (self.panda.last_drop != cs.preap_panda_drop or self.panda.epas_blocking != cs.preap_epas_refusing):
        self.violations.append((self.n, "decision mismatch", self.panda.last_drop, cs.preap_panda_drop))
      if epas_frame and bool(self.out.steeringDisengage) != self.panda.epas_blocking:
        self.violations.append((self.n, "steeringDisengage differs from the panda's EPAS blocking on this frame"))
      if self.out.cruiseState.enabled and not self.panda.controls_allowed:
        self.violations.append((self.n, "openpilot engaged while the panda has controls off"))
      ok, self.fresh_hold = fresh_pull_parity(cs, self.panda, self.fresh_hold, stalk)
      if not ok:
        self.violations.append((self.n, "fresh-pull mirror differs from need_fresh_pull", cs.preap_fresh_pull_pending,
                                self.panda.need_fresh_pull))
      cc = structs.CarControl.new_message(enabled=self.op, latActive=self.op, longActive=self.op, actuators=_act(0.3)).as_reader()
      _, sends = self.ctl.update(cc, cs, self.rig.nanos)
      for sd in sends:
        addr, dat = (sd.address, sd.dat) if hasattr(sd, "address") else (sd[0], sd[1])
        if addr == 0x488:
          typ = dat[2] >> 6
          sent.append(typ)
          if typ == 1 and not self.panda.angle_ok():
            self.violations.append((self.n, "ANGLE the panda rejects"))
      self.n += 1
    return sent

  def engage(self):
    self.step(20)
    self.step(1, stalk=PULL)
    self.step(300)
    assert self.op and self.out.cruiseState.enabled and self.panda.controls_allowed

  @property
  def engaged(self):
    return bool(self.op or self.out.cruiseState.enabled)


def test_c_source_matches_the_mirror():
  src = PANDA_SRC.read_text()
  for line in ("const int hands_on_level = msg->data[4] >> 6;",
               "const int eac_status = msg->data[6] >> 5;",
               "const int eac_error_code = msg->data[2] >> 4;",
               "const bool epas_rejecting = (eac_status == 0) && (eac_error_code >= 6) && (eac_error_code <= 9);",
               "tesla_preap_epas_blocking = (hands_on_level >= 3) || epas_rejecting;",
               "if (tesla_preap_epas_blocking || (eac_status == 3)) {",
               "static bool tesla_preap_need_fresh_pull = false;",
               "if (tesla_preap_need_fresh_pull && tesla_preap_lever_engage_prev) {",
               "} else if ((tesla_preap_gear == 4) && !tesla_preap_doors_open) {",
               "tesla_preap_need_fresh_pull = false;\n      if (!tesla_preap_lever_engage_prev) {",
               "const int lever = msg->data[0] & 0x3FU;",
               "const uint32_t cancel_echo_window_us = 600000U;",
               "cruise_engaged_prev = false;"):
    assert line in src, f"tesla_preap.h changed, update the G1 mirror: {line}"
  body = src[src.index("if (tesla_preap_epas_blocking || (eac_status == 3)) {"):]
  body = body[:body.index("}")]
  for stmt in ("controls_allowed = false;", "pcm_cruise_check(false);", "tesla_preap_need_fresh_pull = true;",
               "tesla_preap_steer_armed = false;",
               "tesla_preap_steer_brake_seen = false;"):
    assert stmt in body
  assert "msg->addr == 0x370U" in src and "tesla_preap_epas_state(msg);" in src
  init = src[src.index("static safety_config tesla_preap_init_config"):]
  assert "tesla_preap_need_fresh_pull = false;" in init[:init.index("TESLA_PREAP_TX_MSGS")], "init clears need_fresh_pull"


def test_every_epas_value_decodes_and_drops_identically():
  # all 4 x 8 x 16 hands / status / error combinations, packed with the DBC and read back by both sides
  p = Parity()
  p.step(2)
  for hands in range(4):
    for status in range(8):
      for err in range(16):
        p.hands, p.status, p.err = hands, status, err
        p.step(1)
        want = status == 3 or hands >= 3 or (status == 0 and 6 <= err <= 9)
        assert p.panda.last_drop == want == p.rig.cs.preap_panda_drop == preap_steer_drop(status, hands, err), (hands, status, err)
  assert p.violations == []


def test_startup_without_epas_frames_and_with_a_clean_first_frame():
  p = Parity()
  p.epas_on = False
  p.step(5)
  assert p.panda.last_drop is None and not p.panda.epas_blocking and not p.panda.controls_allowed
  assert not p.rig.cs.preap_panda_drop, "no EPAS frame yet: the parser default (0 / 0 / 0) is not a drop, nor is init in the panda"
  p.epas_on = True
  p.step(5)
  assert p.panda.last_drop is False and not p.rig.cs.preap_panda_drop
  assert p.violations == []


def test_startup_with_hands_on_from_the_first_frame_never_engages():
  p = Parity(hands=3)
  p.step(20)
  p.step(1, stalk=PULL)
  sent = p.step(100)
  assert not p.engaged and 1 not in sent
  assert not p.panda.controls_allowed, "the next 0x370 drops the pull"
  assert p.violations == []


def test_hands_level_3_onset_drops_both_on_the_same_frame():
  p = Parity()
  p.engage()
  p.hands = 3
  p.step(1)
  assert p.ticks[-1][:3] == (True, True, True)
  assert not p.panda.controls_allowed and not p.out.cruiseState.enabled
  sent = p.step(100)
  assert not p.engaged and 1 not in sent[1:]
  assert p.violations == []


@pytest.mark.parametrize("hands", [1, 2])
def test_hands_below_3_is_not_a_drop(hands):
  p = Parity()
  p.engage()
  p.hands = hands
  p.step(100)
  assert not p.rig.cs.preap_panda_drop and p.panda.controls_allowed and p.out.cruiseState.enabled
  assert p.violations == []


@pytest.mark.parametrize("err", [6, 7, 8, 9])
def test_epas_refusal_drops_both(err):
  p = Parity()
  p.engage()
  p.status, p.err = EAC_INHIBITED, err
  p.step(1)
  assert p.ticks[-1][:3] == (True, True, True)
  p.step(50)
  assert not p.engaged and not p.panda.controls_allowed
  assert p.violations == []


@pytest.mark.parametrize("status,err", [(EAC_INHIBITED, 4), (EAC_INHIBITED, 5), (EAC_INHIBITED, 10), (EAC_INHIBITED, 15),
                                        (EAC_ACTIVE, 7), (EAC_AVAILABLE, 6), (EAC_SNA, 7), (5, 0), (7, 9)])
def test_not_a_refusal_is_not_a_drop(status, err):
  p = Parity()
  p.engage()
  p.status, p.err = status, err
  p.step(50)
  assert not p.rig.cs.preap_panda_drop and p.panda.last_drop is False
  assert p.panda.controls_allowed and p.out.cruiseState.enabled
  assert p.violations == []


def test_eac_fault_drops_both():
  p = Parity()
  p.engage()
  p.status = EAC_FAULT
  p.step(1)
  assert p.ticks[-1][:3] == (True, True, True)
  assert p.violations == []


@pytest.mark.parametrize("cause", ["hands", "refusal", "fault"])
def test_repull_rearms_both_on_the_same_tick(cause):
  p = Parity()
  p.engage()
  if cause == "hands":
    p.hands = 3
  elif cause == "refusal":
    p.status, p.err = EAC_INHIBITED, 8
  else:
    p.status = EAC_FAULT
  p.step(50)
  p.hands, p.status, p.err = 0, EAC_ACTIVE, 0
  p.step(AP1_RESUME_HOLD_FRAMES * 3)
  assert not p.engaged and not p.panda.controls_allowed, "neither side resumes on its own"
  p.step(1, stalk=PULL)
  assert p.panda.controls_allowed and p.out.cruiseState.enabled, "the pull edge re-arms both on the same tick"
  sent = p.step(300)
  assert p.op and sent[-1] == 1
  assert p.violations == []


def test_pull_while_hands_on_does_not_survive_on_either_side():
  p = Parity()
  p.engage()
  p.hands = 3
  p.step(50)
  p.step(1, stalk=PULL)
  assert not p.out.cruiseState.enabled, "carstate drops it on the same tick"
  p.step(1)
  assert not p.panda.controls_allowed, "the panda drops it on the next 0x370"
  p.hands = 0
  sent = p.step(200)
  assert not p.engaged and not p.panda.controls_allowed and 1 not in sent
  assert p.violations == []


def _drop(p, cause):
  if cause == "hands":
    p.hands = 3
  elif cause == "refusal":
    p.status, p.err = EAC_INHIBITED, 7
  else:
    p.status = EAC_FAULT


@pytest.mark.parametrize("cause", ["hands", "refusal", "fault"])
def test_held_pull_through_a_drop_rearms_neither_side_until_a_release_and_a_new_pull(cause):
  # tesla_preap_need_fresh_pull: every EPAS drop makes the panda ignore a pull held through it. carstate needs a new pull edge.
  # Exact parity: controls_allowed == cruiseState.enabled on every tick from the drop to the re-arm.
  p = Parity()
  p.engage()
  p.step(1, stalk=PULL)                        # the driver pulls and keeps holding
  _drop(p, cause)
  p.step(30, stalk=PULL)
  assert p.panda.need_fresh_pull and not p.panda.controls_allowed and not p.engaged
  p.hands, p.status, p.err = 0, EAC_ACTIVE, 0
  start = len(p.ticks)
  trace = []
  for _ in range(100):                         # drop cleared, lever still held: neither side re-arms
    sent = p.step(1, stalk=PULL)
    trace.append((p.panda.controls_allowed, bool(p.out.cruiseState.enabled)))
    assert 1 not in sent
  for _ in range(5):                           # release
    p.step(1)
    trace.append((p.panda.controls_allowed, bool(p.out.cruiseState.enabled)))
  assert all(t == (False, False) for t in trace), "no re-arm on a held pull or on the release"
  assert p.panda.need_fresh_pull, "only a new pull clears it"
  p.step(1, stalk=PULL)                        # the new pull
  assert (p.panda.controls_allowed, bool(p.out.cruiseState.enabled)) == (True, True), "both re-arm on the same tick"
  assert not p.panda.need_fresh_pull
  for _ in range(300):
    p.step(1)
    assert p.panda.controls_allowed and p.out.cruiseState.enabled
  assert p.op
  assert len(p.ticks) > start and p.violations == []


def test_held_pull_with_the_drop_still_active_never_flaps_the_panda():
  # before need_fresh_pull, each held PULL frame re-entered controls between two blocking 0x370 frames
  p = Parity()
  p.engage()
  p.step(1, stalk=PULL)
  p.hands = 3
  p.step(1, stalk=PULL)
  for _ in range(50):
    p.step(1, stalk=PULL)
    assert not p.panda.controls_allowed and not p.out.cruiseState.enabled
  assert p.violations == []


def test_missing_epas_frames_hold_the_last_decision_on_both_sides():
  p = Parity()
  p.engage()
  p.hands = 3
  p.step(1)
  p.epas_on = False
  p.hands = 0
  p.step(20)
  assert p.rig.cs.preap_panda_drop and p.panda.epas_blocking, "both hold the last frame (parser vl / panda static state)"
  p.step(1, stalk=PULL)
  sent = p.step(50)
  assert not p.engaged and 1 not in sent
  assert p.violations == []


def test_missing_epas_frames_after_a_clean_frame_are_not_a_drop():
  p = Parity()
  p.engage()
  p.epas_on = False
  p.step(20)
  assert not p.rig.cs.preap_panda_drop and not p.panda.epas_blocking   # stale stream: canValid / panda rx lag handle it
  assert p.violations == []


def test_bad_checksum_and_stuck_counter_frames_count_on_both_sides():
  # The panda ignores checksum and counter on 0x370 (rx check flags); the parser checks neither for tesla_ap1_can.
  p = Parity()
  p.engage()
  p.corrupt = True
  p.hands = 3
  p.step(3)
  assert all(t[:3] == (True, True, True) for t in p.ticks[-3:])
  assert not p.engaged
  assert p.violations == []


def test_stalk_cancel_parity():
  p = Parity()
  p.engage()
  p.step(1, stalk=CANCEL)
  p.step(5)
  assert not p.panda.controls_allowed and not p.engaged
  assert p.violations == []
