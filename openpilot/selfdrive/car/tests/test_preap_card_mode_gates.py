"""Pre-AP card gates keyed on the panda's reported mode (pandaStates safetyModel / safetyParam), on the real-CAN rig:
- the host-side 0x560 gate (card.py preap_gate_560 + preap/radar_donor.py): 0x560 only while the panda it goes to shows the
  Pre-AP car mode, never in allOutput, noOutput, ELM327, silent or another param, and it stops on the very next step;
- pedal / steering refusals (rejected 0x551 / 0x488 echoes) count only once the car's mode is shown (preap/panda_link.py).
VINs are synthetic (they contain I, O and Q)."""
import pytest

from opendbc.car.structs import CarParams
from openpilot.selfdrive.car.tests.test_preap_card_real_can import (GEAR_D, GEAR_P, REJ, SWITCH, VIN, _drive_from, _matrix, _Panda,
                                                                     make_rig)  # noqa: F401

OTHER = ["elm327", "allOutput", "noOutput", "silent"]


def _ps(rig, model=None, param=None, controls=False):
  em, ep = rig.car.preap_safety_expect
  return {"safetyModel": em if model is None else int(getattr(CarParams.SafetyModel, model)),
          "safetyParam": ep if param is None else param, "uptime": 3, "controlsAllowed": controls}


def _n560(out):
  return sum(1 for m in out if m[0] == 0x560)


def _stream_up(rig, i0=0):
  """Car's mode until the stream sends; returns the next step index."""
  i, seen = i0, 0
  while seen == 0 and i < i0 + 60:
    seen += _n560(rig.step(ps_fields=_ps(rig), sample=1 + i))
    i += 1
  assert seen
  return i


@pytest.mark.parametrize("mode", OTHER + ["tesla_other_param"])
@pytest.mark.parametrize("param_kind", ["zero", "car"])
def test_no_0x560_in_any_other_mode(make_rig, mode, param_kind):
  rig = make_rig(donor_type=1, donor_vin=VIN)
  ep = rig.car.preap_safety_expect[1]
  if mode == "tesla_other_param":
    ps = _ps(rig, param=ep & ~256 if param_kind == "car" else 0)
  else:
    ps = _ps(rig, model=mode, param=ep if param_kind == "car" else 0)
  out = [_n560(rig.step(gear=GEAR_P if i < 150 else GEAR_D, ps_fields=ps, sample=1 + i)) for i in range(300)]
  assert sum(out) == 0


@pytest.mark.parametrize("mode", OTHER)
def test_mode_change_stops_0x560_on_the_next_step(make_rig, mode):
  rig = make_rig(donor_type=1, donor_vin=VIN)
  i = _stream_up(rig)
  # the same pandaStates sample time (no new sample yet), the entry now shows another mode: nothing from the next step on
  after = [_n560(rig.step(ps_fields=_ps(rig, model=mode), sample=i)) for _ in range(60)]
  assert sum(after) == 0
  after = [_n560(rig.step(ps_fields=_ps(rig, model=mode), sample=i + 1 + k)) for k in range(60)]
  assert sum(after) == 0
  back = [_n560(rig.step(ps_fields=_ps(rig), sample=i + 100 + k)) for k in range(60)]
  assert sum(back) > 0                                             # resumes once the car's mode is back


def _inject_560(rig, monkeypatch, bus=0):
  apply = rig.car.CI.apply

  def with_560(cc, now):
    act, sends = apply(cc, now)
    return act, list(sends) + [(0x560, bytes(8), bus)]
  monkeypatch.setattr(rig.car.CI, "apply", with_560)


@pytest.mark.parametrize("mode", OTHER)
def test_card_gate_alone_drops_a_0x560_in_another_mode(make_rig, monkeypatch, mode):
  # whatever the CarController returns: card's own gate on the final sendcan
  rig = make_rig()
  _inject_560(rig, monkeypatch)
  out = [_n560(rig.step(ps_fields=_ps(rig, model=mode), sample=1 + i)) for i in range(20)]
  assert sum(out) == 0 and rig.car.preap_560_dropped >= 20
  out = [_n560(rig.step(ps_fields=_ps(rig), sample=100 + i)) for i in range(20)]
  assert all(n >= 1 for n in out)


def test_card_gate_checks_the_panda_the_frame_goes_to(make_rig, monkeypatch):
  rig = make_rig()
  _inject_560(rig, monkeypatch, bus=4)                             # panda 1: no pandaStates entry, no expectation
  outs = [rig.step(ps_fields=_ps(rig), sample=1 + i) for i in range(20)]
  assert not any(m[0] == 0x560 and m[2] == 4 for out in outs for m in out)
  assert any(m[0] == 0x560 and m[2] == 0 for out in outs for m in out)   # the stream's own 0x560 to panda 0 still goes


def test_card_gate_fails_closed_without_valid_pandastates(make_rig, monkeypatch):
  rig = make_rig()
  _inject_560(rig, monkeypatch)
  assert sum(_n560(rig.step(ps_valid=False)) for _ in range(20)) == 0


# ---- refusals ----

def _fed(rig, steps):
  ci, update, fed = rig.car.CI, rig.car.CI.update, []

  def spy(*a, **kw):
    fed.append(int(ci.CS.preap_panda_tx_blocked))
    ret = update(*a, **kw)
    ci.CS.preap_panda_tx_blocked = 0
    return ret
  ci.update = spy
  for frames, ps, sample in steps:
    rig.step(frames, ps_fields=ps, sample=sample)
  ci.update = update
  return fed


def test_refusals_before_the_switch_ignored_after_counted(make_rig):
  rig = make_rig()
  rej = [(0x488, bytes(4), 0 + REJ)]

  def ps(k, **kw):
    return dict(_ps(rig, **kw), safetyTxBlocked=k)                # the panda's blocked-TX total grows with each refusal
  fed = _fed(rig, [(rej, ps(1 + i, model="elm327", param=1), 2 + i // 10) for i in range(50)])
  assert sum(fed) == 0 and rig.car.preap_refusals.ignored_pre_mode == 50
  # first step in the car's mode: echoes of frames sent before it are still ignored; from the next step on each counts
  fed = _fed(rig, [(rej, ps(51 + i), 100 + i // 10) for i in range(10)])
  assert fed[0] == 0 and fed[1:] == [1] * 9


def test_real_matrix_150_pre_switch_ignored_3_after_counted(make_rig):
  rig = make_rig()
  panda = _Panda(rig.car.CP.safetyConfigs[-1].safetyParam)
  inject = (SWITCH + 2, SWITCH + 13, SWITCH + 27)
  opened, fed, s560 = _matrix(rig, panda, SWITCH + 200, _drive_from(0), {SWITCH: "switch"}, inject_551=inject)
  ign = rig.car.preap_refusals.ignored_pre_mode             # the panda's ELM327 refusals of our idle 0x488 before the switch
  print(f"matrix: refusals ignored before the car's mode {ign}, counted after {sum(fed)}")
  assert ign in (150, 151)                                  # 150 echoes in the window, plus the one arriving on the switch step
  assert sum(fed) == 3 and all(fed[i + 1] == 1 for i in inject)
  assert sum(s560[:SWITCH]) == 0 and opened[SWITCH] is not None and panda.consumed >= 3


def test_card_gate_mutation_is_caught(make_rig, monkeypatch):
  # mutation check in the suite: with card's gate removed, the injected 0x560 escapes in allOutput, so the tests above can see it
  from openpilot.selfdrive.car import card
  monkeypatch.setattr(card.Car, "preap_gate_560", lambda self, sends: list(sends))
  rig = make_rig()
  _inject_560(rig, monkeypatch)
  assert sum(_n560(rig.step(ps_fields=_ps(rig, model="allOutput"), sample=1 + i)) for i in range(5)) == 5
