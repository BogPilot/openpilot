"""Pre-AP speed control ends without ending steering: from FULL a brake press or a single pull drops to steering only (never OFF),
hands-on still disengages fully (LOCKOUT, fresh pull). FULL needs BogPilot's own pedal checks (detected + BogPilot calibration,
preap/calib.py); NAP's pedal calibration is not ported. NAP preap/engagement.py:100-110,126-173 @ e99f4dc75."""
import pytest

from opendbc.car import structs
from opendbc.car.tesla_ap1.preap import calib
from opendbc.car.tesla_ap1.preap.engagement import WINDOW_MS, Mode
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, Rig, _act, _inv, _params_dir, _pedal_frame, _ready_rig, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import EAC_ACTIVE


class Car:
  """Real CarState + CarController, controlsd-style enable/longActive."""
  def __init__(self, pedal=True, detected=True, gas_bus=2):
    if pedal:
      self.rig, self.ctl = _ready_rig(double=False)
    else:
      self.rig, self.ctl = Rig(long=False), None
    self.pedal, self.detected, self.op, self.n, self.enabled_frames = pedal, detected, False, 0, 0
    self.gas_bus, self._also_bus = gas_bus, None

  def step(self, stalk=0, brake=False):
    if self.pedal and self.detected:
      _pedal_frame(self.rig, self.n, bus=self.gas_bus)
      if self._also_bus is not None:
        _pedal_frame(self.rig, self.n, bus=self._also_bus)
    out = self.rig.frame(stalk=stalk, op=self.op, brake=brake)
    self.rig.cs.out = out
    req = self.rig.cs.update_button_enable(out.buttonEvents)
    if self.pedal:
      self.op = bool(self.op and out.cruiseState.enabled) or bool(req and out.cruiseState.available)
    else:
      self.op = bool(out.cruiseState.enabled)          # pcmCruise: openpilot follows cruiseState.enabled
    if self.ctl is not None:
      cc = structs.CarControl.new_message(enabled=self.op, latActive=self.op, longActive=self.op and not out.bogpilot.preapLatOnly,
                                          actuators=_act(0.3)).as_reader()
      _, sends = self.ctl.update(cc, self.rig.cs, self.rig.nanos)
      self.enabled_frames += sum(1 for sd in sends if (sd.address if hasattr(sd, "address") else sd[0]) == 0x551
                                 and (sd.dat if hasattr(sd, "dat") else sd[1])[4] & 0x80)
    self.n += 1
    return out

  @property
  def mode(self):
    return Mode(self.rig.cs.preap_fsm_mode)

  def di(self, state):
    self.rig.base["DI_state"]["DI_cruiseState"] = _inv("DI_state", "DI_cruiseState", state)


def _full(pedal=True):
  c = Car(pedal=pedal)
  for _ in range(20):
    c.step()
  c.step(stalk=PULL)
  for _ in range(9):
    c.step()
  if not pedal:
    c.di("ENABLED")                                   # the driver's real second pull arms stock cruise
  c.step(stalk=PULL)
  for _ in range(60):
    out = c.step()
  assert c.mode == Mode.FULL and c.op and not out.bogpilot.preapLatOnly
  return c


# ---- 1) one pull = steering only, double pull = FULL ----
@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "nopedal"])
def test_single_pull_is_steering_only(pedal):
  c = Car(pedal=pedal)
  for _ in range(20):
    c.step()
  c.step(stalk=PULL)
  for _ in range(WINDOW_MS // 10 + 20):
    out = c.step()
  assert c.mode == Mode.LAT_ONLY and c.op and out.bogpilot.preapLatOnly
  assert c.enabled_frames == 0


# ---- 2) from FULL: brake or a single pull -> steering only (not OFF); hands-on -> LOCKOUT ----
def test_pedal_brake_in_full_keeps_steering():
  c = _full(True)
  out = c.step(brake=True)
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly and out.cruiseState.enabled and c.op
  frames = c.enabled_frames
  for _ in range(50):
    out = c.step()                                    # brake released: speed control stays off until a new double pull
  assert c.mode == Mode.LAT_ONLY and c.op and c.enabled_frames == frames


def test_nopedal_brake_in_full_keeps_steering_while_the_di_cancels_stock_cruise():
  c = _full(False)
  out = c.step(brake=True)                            # DI still reports cruise on this frame: demote on the brake edge itself
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly and out.cruiseState.enabled
  for _ in range(3):
    out = c.step(brake=True)
    assert c.mode == Mode.LAT_ONLY, "the DI's last frames of cruise on are not a driver re-arm"
  c.di("STANDBY")                                     # expected: the DI cancels stock cruise on the brake (bench check B10)
  for _ in range(80):
    out = c.step()
  assert c.mode == Mode.LAT_ONLY and out.cruiseState.enabled and not c.rig.cs.preap_cc_cancel_needed


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "nopedal"])
def test_single_pull_in_full_drops_to_steering_only(pedal):
  c = _full(pedal)
  out = c.step(stalk=PULL)
  assert out.bogpilot.preapLatOnly and out.cruiseState.enabled
  if not pedal:
    assert c.rig.cs.preap_cc_cancel_needed            # NAP: the demoting pull cancels stock cruise (engagement.py:164-173)
    c.di("STANDBY")                                   # the CANCEL took
  for _ in range(WINDOW_MS // 10 + 80):
    out = c.step()
  assert c.mode == Mode.LAT_ONLY and out.cruiseState.enabled and c.op


@pytest.mark.parametrize("pedal", [True, False], ids=["pedal", "nopedal"])
def test_hands_on_in_full_disengages_fully(pedal):
  c = _full(pedal)
  c.rig.base["EPAS_sysStatus"] = dict(c.rig.base["EPAS_sysStatus"], EPAS_handsOnLevel=3, EPAS_eacStatus=EAC_ACTIVE)
  out = c.step()
  assert c.mode == Mode.LOCKOUT and not out.cruiseState.enabled


# ---- 4) FULL needs BogPilot's own pedal checks; NAP pedal calibration is not ported ----
def _double_pull(c):
  for _ in range(20):
    c.step()
  c.step(stalk=PULL)
  for _ in range(9):
    c.step()
  c.step(stalk=PULL)
  for _ in range(60):
    out = c.step()
  return out


def test_full_refused_without_bogpilot_calibration(monkeypatch):
  import opendbc.car.tesla_ap1.preap.carstate as cs_mod
  monkeypatch.setattr(cs_mod, "is_pedal_calibrated", lambda: False)
  c = Car(pedal=True)
  out = _double_pull(c)
  assert c.mode != Mode.FULL and c.enabled_frames == 0 and not (out.cruiseState.enabled and not out.bogpilot.preapLatOnly)


def test_full_refused_without_a_detected_pedal():
  c = Car(pedal=True, detected=False)
  out = _double_pull(c)
  assert c.mode != Mode.FULL and c.enabled_frames == 0 and not (out.cruiseState.enabled and not out.bogpilot.preapLatOnly)


def test_full_with_bogpilot_checks_passing_drives_the_pedal():
  c = Car(pedal=True)
  _double_pull(c)
  assert c.mode == Mode.FULL and c.enabled_frames > 20


def test_no_nap_pedal_calibration_module():
  import pathlib
  preap = pathlib.Path(calib.__file__).parent
  srcs = {p.name: p.read_text() for p in preap.glob("*.py")}
  assert "calib.py" in srcs                           # BogPilot's calibration
  # the FSM's only pedal input is BogPilot's long_allowed (detected + calib.is_pedal_calibrated), nothing calibrates in the FSM
  assert "calib" not in srcs["engagement.py"].split('"""', 2)[-1].replace("long_allowed", "")


def test_never_seen_pedal_refuses_full():
  c = Car(pedal=True, detected=False)
  out = _double_pull(c)
  assert c.mode != Mode.FULL and c.enabled_frames == 0 and not (out.cruiseState.enabled and not out.bogpilot.preapLatOnly)
  assert c.rig.cs.preap_pedal_bus_ok is False and c.rig.cs._preap_pedal_bus_latched is False


def test_pedal_on_bus_zero_reaches_full():
  c = Car(pedal=True, gas_bus=0)
  _double_pull(c)
  assert c.mode == Mode.FULL and c.enabled_frames > 20
  assert c.rig.cs.pedal_bus == 0 and c.rig.cs.preap_pedal_bus_ok


def test_seen_on_one_bus_then_the_other_demotes_and_never_enables():
  c = Car(pedal=True, gas_bus=0)
  _double_pull(c)
  assert c.mode == Mode.FULL and c.enabled_frames > 20
  frames = c.enabled_frames
  c._also_bus = 2
  out = c.step()
  assert c.mode == Mode.LAT_ONLY and out.bogpilot.preapLatOnly and c.rig.cs.preap_pedal_bus_mismatch
  for _ in range(50):
    out = c.step()
  assert c.mode == Mode.LAT_ONLY and c.op and c.enabled_frames == frames
