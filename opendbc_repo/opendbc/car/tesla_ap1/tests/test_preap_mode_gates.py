"""Pre-AP host gates keyed on the panda's reported safety mode (pandaStates safetyModel / safetyParam, car.capnp SafetyModel):
the pull FSM counts refusals of our own 0x551 / 0x488 only in the car's mode, and the 0x560 donor config is sent only in it.

The car's mode is SafetyModel.tesla with the PREAP flag and exactly the param card set (panda_link.preap_mode_ok). Before the
switch the panda runs ELM327 and refuses every bus-0 frame; in allOutput no tx hook would stop a 0x560 (safety.h:249-250)."""
import pytest

from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.preap.panda_link import (FLAG_AP1, FLAG_PREAP, SAFETY_TESLA, EchoCounts, LinkInput, TxRefusalWatch,
                                                    preap_mode_ok)
from opendbc.car.tesla_ap1.preap.radar_donor import Link, RadarDonorStream

VIN = "TESTQQQ4OIQ000001"
PARAM = FLAG_PREAP | 64 | 256          # PREAP | PEDAL | RADAR_EMULATION (values.py TeslaAp1SafetyFlags)
EXPECT = (SAFETY_TESLA, PARAM)
OTHER_MODES = ["elm327", "allOutput", "noOutput", "silent"]


def _model(name):
  return int(getattr(CarParams.SafetyModel, name))


def test_tesla_is_the_capnp_enum():
  assert SAFETY_TESLA == int(CarParams.SafetyModel.tesla) == 10


def test_mode_ok_only_in_the_preap_car_mode():
  assert preap_mode_ok(SAFETY_TESLA, PARAM, EXPECT)
  for name in OTHER_MODES:
    for param in (0, 1, PARAM):
      assert not preap_mode_ok(_model(name), param, EXPECT), (name, param)
  assert not preap_mode_ok(SAFETY_TESLA, PARAM & ~256, EXPECT)          # another param (flag 256 missing)
  assert not preap_mode_ok(SAFETY_TESLA, PARAM, None)                   # no expectation: fail closed
  # even if CarParams expected them: no PREAP flag, or the AP1 flag, is never the Pre-AP mode
  assert not preap_mode_ok(SAFETY_TESLA, 256, (SAFETY_TESLA, 256))
  assert not preap_mode_ok(SAFETY_TESLA, PARAM | FLAG_AP1, (SAFETY_TESLA, PARAM | FLAG_AP1))
  assert not preap_mode_ok(_model("allOutput"), PARAM, (_model("allOutput"), PARAM))


# ---- refusals ----

def _rej(n):
  return EchoCounts(rejected_control=n)


def test_refusals_before_the_switch_are_ignored_and_after_still_count():
  w = TxRefusalWatch()
  fed = [w.step(_rej(1), 0, [k], car_mode=False)[0] for k in range(1, 151)]   # ELM327: 150 refused, totals rising
  assert sum(fed) == 0 and w.ignored_pre_mode == 150
  # the switch: totals keep the pre-switch count, nothing from before is carried into the cross-check
  out = [w.step(EchoCounts(), 0, [150])]
  out += [w.step(EchoCounts(), 0, [150]) for _ in range(5)]
  assert sum(r for r, _ in out) == 0 and w.unexplained == 0
  # 3 real refusals after the switch, each with its echo and the counter: exactly 3
  got = []
  for k in range(3):
    got.append(w.step(_rej(1), 0, None)[0])
    got.append(w.step(EchoCounts(), 0, [151 + k])[0])
  assert sum(got) == 3 and w.ignored_pre_mode == 150 and w.unexplained == 0


def test_lost_echo_after_the_switch_still_passed_on():
  w = TxRefusalWatch()
  for k in range(1, 20):
    w.step(_rej(1), 0, [k], car_mode=False)
  w.step(EchoCounts(), 0, [19])
  w.step(EchoCounts(), 0, [20])          # one blocked frame, no echo
  r, _ = w.step(EchoCounts(), 0, [20])   # carried one sample, then passed on (fail-safe)
  assert r == 1 and w.unexplained == 1


def test_default_is_counting():
  # callers that do not say counts (fail-safe default); card always passes car_mode
  assert TxRefusalWatch().step(_rej(2), 0, None) == (2, 0)


# ---- 0x560 stream ----

def _link(ok, new_sample, key=EXPECT, **kw):
  return LinkInput(safety_ok=ok, safety_key=key if ok else (_model("elm327"), 1), uptime=5, new_sample=new_sample, **kw)


def _streaming():
  s = RadarDonorStream(True, VIN, 1)
  s.update(1, False, link=_link(False, True))       # first sample: ELM327 (fresh start, not inherited)
  s.update(2, False, link=_link(True, True))        # switch seen: STREAM
  assert s.state == Link.STREAM
  sent = [m for f in range(3, 40) for m in s.update(f, False, link=_link(True, f % 10 == 0))]
  assert sent and all(m.address == 0x560 and m.src == 0 for m in sent)
  return s


def test_stream_stops_at_once_when_the_mode_changes_between_samples():
  s = _streaming()
  # same pandaStates sample time (no new sample), entry now shows another mode: nothing on the very next 10 Hz slot
  out = [m for f in range(40, 120) for m in s.update(f, False, link=_link(False, False))]
  assert out == [] and s.held_mode > 0


@pytest.mark.parametrize("name", OTHER_MODES + ["tesla_other_param"])
def test_stream_never_in_another_mode(name):
  s = RadarDonorStream(True, VIN, 1)
  key = (SAFETY_TESLA, PARAM & ~256) if name == "tesla_other_param" else (_model(name), 0)
  out = [m for f in range(1, 400) for m in s.update(f, False, link=LinkInput(safety_ok=False, safety_key=key, uptime=5,
                                                                              new_sample=f % 10 == 0))]
  assert out == []


def test_stream_resumes_only_when_the_mode_is_back():
  s = _streaming()
  assert [m for f in range(40, 80) for m in s.update(f, False, link=_link(False, f % 10 == 0))] == []
  back = [m for f in range(80, 140) for m in s.update(f, False, link=_link(True, f % 10 == 0))]
  assert back and all(m.address == 0x560 for m in back)
