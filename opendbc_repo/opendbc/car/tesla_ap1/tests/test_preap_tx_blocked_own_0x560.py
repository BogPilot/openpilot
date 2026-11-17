"""Pre-AP pull FSM in FULL vs the panda blocked-TX count with our own 0x560 radar config frames in it.

The panda consumes every host 0x560 as a blocked TX and reports only a running total for all addresses (pandaStates.safetyTxBlocked,
10 Hz). Once per sample, card.py takes back out the 0x560 frames it sent since the previous sample (preap/radar_donor.py
OwnBlockedTx), never more than the increase, with nothing carried to the next sample. These run the real FSM to FULL (double
pull) and feed it exactly what card would. A real refusal must still drop FULL to steering only.
"""
from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.preap.radar_donor import OwnBlockedTx
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_pedal_authority import _ready
from opendbc.car.tesla_ap1.tests.test_preap_pedal_guard import _run

AT = 300        # step of a counter sample, well inside FULL
PULLS = {20, 45}


def _feed(samples, subtract=True, frames=420):
  """samples: {step: (own 0x560 sent in the window before it, counted by the panda in its increase, real other blocks)}."""
  own = OwnBlockedTx()
  rig, ctl = _ready()

  def hook(n, r):
    if n + 5 in samples:
      own.sent(samples[n + 5][0])
    if n in samples:
      _, counted, real = samples[n]
      delta = counted + real
      r.cs.preap_panda_tx_blocked = own.take(delta)[0] if subtract else delta
  _, outs = _run(rig, ctl, frames, pulls=PULLS, long_active_always=False, hook=hook)
  return rig, outs


def _full_before(outs, at=AT):
  return outs[at - 1][0] and not outs[at - 1][1].bogpilot.preapLatOnly


def _still_full(rig, outs):
  op, out = outs[-1]
  return op and not out.bogpilot.preapLatOnly and rig.cs.preap_fsm_mode == int(Mode.FULL)


def _dropped_to_steering(rig, outs):
  op, out = outs[-1]
  return op and out.bogpilot.preapLatOnly and rig.cs.decision.speed_blocked and rig.cs.preap_fsm_mode == int(Mode.LAT_ONLY)


def test_pure_0x560_counted_in_its_sample_never_drops_full():
  for n in (1, 3):
    rig, outs = _feed({AT: (n, n, 0), AT + 10: (n, n, 0), AT + 20: (n, n, 0)})
    assert _full_before(outs) and _still_full(rig, outs), n


def test_without_the_subtraction_our_frames_would_drop_full():
  rig, outs = _feed({AT: (3, 3, 0)}, subtract=False)
  assert _full_before(outs) and _dropped_to_steering(rig, outs)


def test_real_refusal_with_0x560_in_the_same_sample_still_drops_full():
  for own560, real in ((1, 1), (3, 1), (3, 2), (1, 25), (0, 1)):   # e.g. refused pedal 0x551 frames
    rig, outs = _feed({AT: (own560, own560, real)})
    assert _full_before(outs) and _dropped_to_steering(rig, outs), (own560, real)


def test_fewer_counted_than_sent_feeds_nothing_and_carries_nothing():
  rig, outs = _feed({AT: (3, 1, 0)})
  assert _full_before(outs) and _still_full(rig, outs)               # clamp: 0, not negative
  rig, outs = _feed({AT: (3, 0, 0), AT + 10: (0, 0, 1)})               # 3 uncounted, then 1 real block with no 0x560 sent
  assert _dropped_to_steering(rig, outs)                               # no leftover credit hides it


def test_0x560_counted_a_sample_late_between_the_pulls_is_harmless():
  # Our stream stops at the first pull (steering); a frame counted one sample late lands before FULL, where it is not a refusal.
  rig, outs = _feed({30: (1, 0, 0), 40: (0, 1, 0)})
  assert _still_full(rig, outs)


def test_0x560_counted_a_sample_late_in_full_is_passed_on_fail_safe():
  rig, outs = _feed({AT: (1, 0, 0), AT + 10: (0, 1, 0)})
  assert _full_before(outs) and _dropped_to_steering(rig, outs)
