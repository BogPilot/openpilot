"""Pre-AP 0x560 / refusal gates fail closed on a stale pandaStates (card.py preap_panda_states_fresh): valid but not alive, or
no new sample for PREAP_PANDA_STATES_MAX_AGE_S, reads as not in the car's mode, so no 0x560 and no refusal counting.
VINs are synthetic (they contain I, O and Q)."""
from openpilot.selfdrive.car.tests.test_preap_card_real_can import VIN, make_rig  # noqa: F401
from openpilot.selfdrive.car.tests.test_preap_card_mode_gates import _inject_560, _n560, _ps, _stream_up

STALE_STEPS = 51      # rig steps are 10 ms: more than PREAP_PANDA_STATES_MAX_AGE_S (0.5 s) without a new sample


def test_stale_but_valid_car_mode_sends_no_0x560(make_rig):
  rig = make_rig(donor_type=1, donor_vin=VIN)
  i = _stream_up(rig)
  # pandaStates stays valid and keeps showing the car's mode, but no new sample arrives
  out = [_n560(rig.step(ps_fields=_ps(rig), sample=i)) for _ in range(150)]
  assert sum(out[STALE_STEPS:]) == 0
  assert rig.car.preap_car_mode_prev is False                       # refusals are not counted either
  back = [_n560(rig.step(ps_fields=_ps(rig), sample=i + 1 + k)) for k in range(60)]
  assert sum(back) > 0                                             # a fresh sample resumes the stream


def test_valid_but_not_alive_sends_no_0x560(make_rig):
  rig = make_rig(donor_type=1, donor_vin=VIN)
  i = _stream_up(rig)
  out = [_n560(rig.step(ps_fields=_ps(rig), sample=i + 1 + k, ps_alive=False)) for k in range(60)]
  assert sum(out) == 0 and rig.car.preap_car_mode_prev is False


def test_card_gate_alone_drops_0x560_on_stale_pandastates(make_rig, monkeypatch):
  rig = make_rig()
  _inject_560(rig, monkeypatch)
  out = [_n560(rig.step(ps_fields=_ps(rig), sample=1 + k)) for k in range(20)]
  assert all(n >= 1 for n in out)
  dropped = rig.car.preap_560_dropped
  out = [_n560(rig.step(ps_fields=_ps(rig), sample=20)) for _ in range(120)]
  assert sum(out[STALE_STEPS:]) == 0 and rig.car.preap_560_dropped - dropped >= 120 - STALE_STEPS


def test_transition_to_other_mode_while_pandastates_is_stale_sends_no_0x560(make_rig, monkeypatch):
  # the panda leaves the car's mode (here allOutput) but pandaStates freezes on the last car-mode sample: valid, not fresh
  rig = make_rig(donor_type=1, donor_vin=VIN)
  i = _stream_up(rig)
  _inject_560(rig, monkeypatch)
  frozen = [_n560(rig.step(ps_fields=_ps(rig), sample=i)) for _ in range(120)]
  assert sum(frozen[STALE_STEPS:]) == 0
  # the first fresh sample then shows allOutput: still nothing
  after = [_n560(rig.step(ps_fields=_ps(rig, model="allOutput"), sample=i + 1 + k)) for k in range(60)]
  assert sum(after) == 0 and rig.car.preap_car_mode_prev is False
