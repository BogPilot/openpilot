"""Pre-AP pull FSM in FULL vs our own 0x560 radar config frames: refusals are read per address from the panda's rejected echoes.

The panda refuses every host 0x560 by design (it consumes it) and echoes each refused frame back with src = bus + 0xC0.
card.py feeds the FSM only refusals of our 0x551 / 0x488 (preap/panda_link.py TxRefusalWatch); the all-address
pandaStates.safetyTxBlocked total is a cross-check for lost echoes. These run the real FSM to FULL (double pull) and feed it
exactly what card would, from a modelled panda: a counter, rejected echoes that can be late or lost, and our 0x560.
"""
import pytest

from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.preap.panda_link import EchoCounts, TxRefusalWatch, scan_echoes
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_pedal_authority import _ready
from opendbc.car.tesla_ap1.tests.test_preap_pedal_guard import _run

AT = 300        # well inside FULL
PULLS = {20, 45}


def _feed(own560=None, refused=None, lost=(), late=(), lost_ctl=(), late_ctl=(), frames=420):
  """own560 / refused: {step: n} frames the panda refused (our 0x560 / our 0x551). lost / late: steps whose 0x560 echoes never
  arrive / arrive one 10 Hz sample later; lost_ctl / late_ctl: the same for the 0x551 echoes. The counter counts every refusal at once."""
  own560, refused = own560 or {}, refused or {}
  w = TxRefusalWatch()
  st = {"total": 0, "pending": []}
  fed = []
  rig, ctl = _ready()

  def hook(n, r):
    st["total"] += own560.get(n, 0) + refused.get(n, 0)
    for kind, k, ls, lt in (("rejected_560", own560.get(n, 0), lost, late), ("rejected_control", refused.get(n, 0), lost_ctl, late_ctl)):
      if k and n not in ls:
        st["pending"].append((n + (10 if n in lt else 0), kind, k))
    e = EchoCounts()
    for item in list(st["pending"]):
      if item[0] <= n:
        st["pending"].remove(item)
        setattr(e, item[1], getattr(e, item[1]) + item[2])
    refusals, _ = w.step(e, own560.get(n, 0), [st["total"]] if n % 10 == 0 else None)
    fed.append(refusals)
    r.cs.preap_panda_tx_blocked = refusals
  _, outs = _run(rig, ctl, frames, pulls=PULLS, long_active_always=False, hook=hook)
  return rig, outs, fed


def _full_before(outs, at=AT):
  return outs[at - 1][0] and not outs[at - 1][1].bogpilot.preapLatOnly


def _still_full(rig, outs):
  op, out = outs[-1]
  return op and not out.bogpilot.preapLatOnly and rig.cs.preap_fsm_mode == int(Mode.FULL)


def _dropped_to_steering(rig, outs):
  op, out = outs[-1]
  return op and out.bogpilot.preapLatOnly and rig.cs.decision.speed_blocked and rig.cs.preap_fsm_mode == int(Mode.LAT_ONLY)


def _drop_step(outs):
  return next((i for i, (op, out) in enumerate(outs) if i > 100 and op and out.bogpilot.preapLatOnly), None)


def test_0x560_refusals_never_drop_full_in_any_timing():
  for kw in ({}, {"late": {AT, AT + 3}}, {"lost": {AT}}, {"lost": {AT, AT + 7}, "late": {AT + 3}}):
    rig, outs, fed = _feed(own560={AT: 1, AT + 3: 1, AT + 7: 1}, **kw)
    assert _full_before(outs) and _still_full(rig, outs) and sum(fed) == 0, kw


def test_real_0x551_refusal_drops_full_on_its_own_echo_step():
  for k in (1, 3, 25):
    rig, outs, fed = _feed(refused={AT + 4: k})
    assert _full_before(outs) and _dropped_to_steering(rig, outs), k
    assert fed[AT + 4] == k and _drop_step(outs) == AT + 4


def test_lost_or_uncounted_0x560_never_hides_a_real_refusal():
  # (a) a 0x560 lost or never counted next to a real 0x551 refusal in the same sample: the refusal still demotes, at once.
  for kw in ({"lost": {AT + 2}}, {"late": {AT + 2}}):
    rig, outs, fed = _feed(own560={AT + 2: 1}, refused={AT + 4: 1}, **kw)
    assert _dropped_to_steering(rig, outs) and _drop_step(outs) == AT + 4, kw


def test_real_refusal_is_not_delayed_by_0x560_timing():
  # (b) the refusal's own echo is the trigger, whatever our 0x560 frames do around it.
  base = _drop_step(_feed(refused={AT + 5: 1})[1])
  for own in ({AT + 5: 1}, {AT + 1: 1, AT + 9: 1}, {AT: 3}):
    for kw in ({}, {"late": set(own)}, {"lost": set(own)}):
      assert _drop_step(_feed(own560=own, refused={AT + 5: 1}, **kw)[1]) == base == AT + 5, (own, kw)


def test_refusal_with_lost_echo_still_demotes_fail_safe():
  # The echo of a refused 0x551 is lost (rx overflow): the counter cross-check passes it on two samples later at most.
  rig, outs, fed = _feed(refused={AT + 4: 1}, lost_ctl={AT + 4})
  d = _drop_step(outs)
  assert _dropped_to_steering(rig, outs) and d is not None and AT + 4 < d <= AT + 4 + 20


def test_late_refusal_echo_is_not_counted_twice():
  rig, outs, fed = _feed(refused={AT + 8: 1}, late_ctl={AT + 8})
  assert sum(fed) == 1 and _dropped_to_steering(rig, outs)


def test_scan_echoes_by_address_and_src():
  frames = [(0x551, b"", 0xC0), (0x551, b"", 0xC2), (0x488, b"", 0xC0), (0x488, b"", 0xC2), (0x560, b"", 0xC0), (0x214, b"", 0xC0),
            (0x2A9, b"", 0x81), (0x2A9, b"", 1), (0x551, b"", 0x80), (0x551, b"", 0)]
  e = scan_echoes([(0, frames)])
  assert (e.rejected_control, e.rejected_560, e.rejected_other, e.gtw) == (3, 1, 2, 1)


@pytest.mark.parametrize("start", [10, 0xFFFFFFFF])
def test_counter_reset_and_wrap(start):
  w = TxRefusalWatch()
  assert w.step(EchoCounts(), 0, [start]) == (0, 0)
  assert w.step(EchoCounts(rejected_control=2), 0, [(start + 2) & 0xFFFFFFFF]) == (2, 0)   # start 0xFFFFFFFF wraps to 1
  assert w.step(EchoCounts(), 0, [0]) == (0, 0)            # panda init / reboot reset: nothing passed on
  assert w.step(EchoCounts(), 0, [0]) == (0, 0)
  assert w.step(EchoCounts(), 0, [1]) == (0, 0)            # a blocked frame whose echo is late: carried one sample
  assert w.step(EchoCounts(), 0, [1]) == (1, 0)            # still no echo: lost, passed on (fail-safe)
  w.step(EchoCounts(), 1, None)                            # an own 0x560 nearby: a lost echo is logged only
  assert w.step(EchoCounts(), 0, [2]) == (0, 0)
  assert w.step(EchoCounts(), 0, [2]) == (0, 1)


def test_real_libsafety_refuses_our_pedal_frame_and_0x560():
  """The rejected echoes the FSM reads come from the real tx hook: an ENABLE 0x551 without controls_allowed is refused,
  like every 0x560; the 0x551 refusal reads as a refusal, the 0x560 never does."""
  from opendbc.car.structs import CarParams
  from opendbc.safety.tests.libsafety import libsafety_py
  from opendbc.safety.tests.test_tesla_preap import PREAP, pkt
  from opendbc.safety.tests.test_tesla_preap_radar import RADAR
  from opendbc.car.tesla_ap1.preap.radar_donor import create_radar_vin_msg
  lib = libsafety_py.libsafety
  assert lib.set_safety_hooks(int(CarParams.SafetyModel.tesla), PREAP | RADAR) == 0
  lib.init_tests()
  lib.set_controls_allowed(False)
  from opendbc.car.tesla_ap1.preap.pedal_can import PedalCommandCounter, create_pedal_command
  enable = create_pedal_command(20.0, 1, PedalCommandCounter(), 2)
  m560 = create_radar_vin_msg(0, "", True, 0, 0)
  echoes = []
  for addr, dat, bus in (tuple(enable), tuple(m560)):
    if not lib.safety_tx_hook(pkt(addr, bytearray(dat), bus)):
      echoes.append((addr, dat, bus + 0xC0))
  e = scan_echoes([(0, echoes)])
  assert e.rejected_control == 1 and e.rejected_560 == 1
  assert TxRefusalWatch().step(e, 1, None) == (1, 0)
