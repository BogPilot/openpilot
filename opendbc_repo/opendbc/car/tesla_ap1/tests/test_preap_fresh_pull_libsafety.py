"""Pre-AP fresh-pull parity against the compiled panda code (libsafety, built from opendbc/safety by the safety test harness).

The same raw bus-0 frames the car-state rig packs go to libsafety (SAFETY_TESLA, pre-AP flag, stock cruise) and to the Python mirror
of tesla_preap.h. tesla_preap_need_fresh_pull is static, so the check is on its effect: on every tick the stalk is pulled in D with the
doors closed, libsafety arms controls exactly when carstate.preap_fresh_pull_pending is clear, and libsafety's controls_allowed matches
the mirror on every tick. Skipped where libsafety cannot be built (no cffi / C compiler); it runs in the docker test environment.
"""
import pytest

from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, _inv, _params_dir  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_steer_disengage import EAC_ACTIVE, EAC_FAULT, EAC_INHIBITED, Drive

try:
  from opendbc.safety.tests.libsafety import libsafety_py
  LIB = libsafety_py.libsafety
except Exception as e:  # noqa: BLE001
  pytest.skip(f"libsafety not available here: {e}", allow_module_level=True)

SAFETY_TESLA = int(CarParams.SafetyModel.tesla)
PREAP = 32
DROPS = [("hands", (3, EAC_ACTIVE, 0)), ("refusal6", (0, EAC_INHIBITED, 6)), ("refusal9", (0, EAC_INHIBITED, 9)),
         ("fault", (0, EAC_FAULT, 0))]


class Bench:
  def __init__(self):
    assert LIB.set_safety_hooks(SAFETY_TESLA, PREAP) == 0
    LIB.init_tests()
    self.t = 1_000_000
    LIB.set_timer(self.t)
    self.d = Drive(pedal=False)
    self.d.panda.now_us = self.t
    self.gear_d = True
    self.checked_pulls = 0
    self.armed_pulls = 0

  def gear(self, d_gear):
    self.gear_d = d_gear
    self.d.rig.base["DI_torque2"]["DI_gear"] = _inv("DI_torque2", "DI_gear", "DI_GEAR_D" if d_gear else "DI_GEAR_N")
    self.d.panda.gear_d = d_gear

  def step(self, stalk=0):
    self.t += 10_000
    LIB.set_timer(self.t)
    self.d.step(stalk=stalk, op=False)
    for addr, bus, dat in self.d._rx:
      if bus == 0:
        LIB.safety_rx_hook(libsafety_py.make_CANPacket(addr, 0, bytes(dat)))
    lib_allowed = bool(LIB.get_controls_allowed())
    cs = self.d.rig.cs
    assert lib_allowed == self.d.panda.controls_allowed, (self.d.n, "libsafety vs mirror", lib_allowed)
    assert cs.preap_fresh_pull_pending or not self.d.panda.need_fresh_pull, (self.d.n, "carstate clear while the panda is pending")
    if stalk == PULL and self.gear_d and not cs.preap_panda_drop:
      self.checked_pulls += 1
      self.armed_pulls += lib_allowed
      assert lib_allowed == (not cs.preap_fresh_pull_pending), (self.d.n, "libsafety arms iff carstate's mirror is clear", lib_allowed)
    return lib_allowed


@pytest.mark.parametrize("cause,epas", DROPS, ids=[c for c, _ in DROPS])
def test_libsafety_arms_exactly_when_the_carstate_mirror_clears(cause, epas):
  b = Bench()
  for _ in range(20):
    b.step()
  assert b.step(stalk=PULL), "first pull arms the compiled panda"
  for _ in range(30):
    b.step(stalk=PULL)
  b.d.epas(*epas)                       # drop with the pull held
  for _ in range(5):
    assert not b.step(stalk=PULL)
  b.d.epas(0, EAC_ACTIVE, 0)
  for _ in range(10):
    assert not b.step(stalk=PULL), "a pull held through the drop arms neither side"
  assert b.d.rig.cs.preap_fresh_pull_pending
  for _ in range(3):
    b.step()
  assert b.step(stalk=PULL) and not b.d.rig.cs.preap_fresh_pull_pending, "a fresh pull arms both on the same tick"
  for _ in range(10):
    b.step()
  b.d.epas(*epas)                       # single-frame drop, no pull
  b.step()
  b.d.epas(0, EAC_ACTIVE, 0)
  for _ in range(10):
    assert not b.step()
  b.gear(False)
  assert not b.step(stalk=PULL) and b.d.rig.cs.preap_fresh_pull_pending, "a pull out of D clears neither"
  b.step()
  b.gear(True)
  b.step()
  assert b.step(stalk=PULL) and not b.d.rig.cs.preap_fresh_pull_pending
  assert b.checked_pulls > 20 and b.armed_pulls > 0
  assert b.d.mirror_mismatch == 0
