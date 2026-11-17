"""Pre-AP pull FSM in FULL vs the panda blocked-TX count with our own 0x560 radar config frames in it.

The panda consumes every host 0x560 as a blocked TX and reports only a running total for all addresses (pandaStates.safetyTxBlocked,
10 Hz). card.py takes the 0x560 frames it sent back out (preap/radar_donor.py OwnBlockedTx) before the FSM reads the delta. These
run the real FSM to FULL (double pull) and feed it exactly what card would. A real refusal must still drop FULL to steering only.
"""
from opendbc.car.tesla_ap1.preap.engagement import Mode
from opendbc.car.tesla_ap1.preap.radar_donor import OwnBlockedTx
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_pedal_authority import _ready
from opendbc.car.tesla_ap1.tests.test_preap_pedal_guard import _run

AT = 300   # step of the counter sample, well inside FULL


def _full_with(own560, real, sent_before=5, subtract=True):
  """own560 of our 0x560 frames sent sent_before steps before the sample, plus real other blocked frames, in one counter delta."""
  own = OwnBlockedTx()
  rig, ctl = _ready()

  def hook(n, r):
    if n == AT - sent_before:
      own.sent(own560, n)
    if n == AT:
      delta = own560 + real
      r.cs.preap_panda_tx_blocked = own.take(delta, n) if subtract else delta
  _, outs = _run(rig, ctl, 420, pulls={20, 45}, long_active_always=False, hook=hook)
  assert not outs[AT - 1][1].bogpilot.preapLatOnly and outs[AT - 1][0]   # FULL before the sample
  return rig, outs


def _still_full(rig, outs):
  op, out = outs[-1]
  return op and not out.bogpilot.preapLatOnly and rig.cs.preap_fsm_mode == int(Mode.FULL)


def _dropped_to_steering(rig, outs):
  op, out = outs[-1]
  return op and out.bogpilot.preapLatOnly and rig.cs.decision.speed_blocked and rig.cs.preap_fsm_mode == int(Mode.LAT_ONLY)


def test_pure_0x560_blocks_never_drop_full():
  for n in (1, 3):
    for lag in (1, 12, 30):            # counted in the next sample, one sample late, at the credit TTL
      rig, outs = _full_with(n, 0, sent_before=lag)
      assert _still_full(rig, outs), (n, lag)


def test_without_the_subtraction_our_frames_would_drop_full():
  rig, outs = _full_with(3, 0, subtract=False)
  assert _dropped_to_steering(rig, outs)


def test_real_refusal_with_0x560_in_the_same_delta_still_drops_full():
  for own560, real in ((1, 1), (3, 1), (3, 2), (1, 25), (0, 1)):   # e.g. refused pedal 0x551 frames
    rig, outs = _full_with(own560, real)
    assert _dropped_to_steering(rig, outs), (own560, real)


def test_expired_credit_does_not_hide_a_real_block():
  rig, outs = _full_with(1, 1, sent_before=31)    # older than the TTL: the whole delta is passed on
  assert _dropped_to_steering(rig, outs)
