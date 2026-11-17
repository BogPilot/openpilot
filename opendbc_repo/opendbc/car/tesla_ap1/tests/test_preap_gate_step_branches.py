"""RadarInterface._preap_gate_step on packets without a CAN log time: a malformed entry is skipped and a 0 timestamp falls back
to 10 ms steps, for both the echo time and the gate time."""
from opendbc.car.tesla_ap1.preap.panda_link import GTW_ECHO_SRC
from opendbc.car.tesla_ap1.tests.test_preap_radar_advisory import ri_on
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import _params_dir, long_paths, store  # noqa: F401

ECHO = (0x109, b"\x00" * 8, GTW_ECHO_SRC)


def _spy(ri):
  seen = []
  real = ri.preap_gate.on_echo
  ri.preap_gate.on_echo = lambda now: (seen.append(now), real(now))
  return seen


def test_malformed_packets_are_skipped_and_time_falls_back_to_steps(long_paths):
  ri = ri_on(long_paths)
  seen = _spy(ri)
  now = ri._preap_gate_step(["junk", (1, 2, 3), None], set())
  assert seen == [] and now == ri._preap_steps * 0.01


def test_zero_timestamp_echo_uses_the_step_clock(long_paths):
  ri = ri_on(long_paths)
  seen = _spy(ri)
  now = ri._preap_gate_step([(0, [ECHO])], set())
  assert seen == [ri._preap_steps * 0.01] and now == seen[0]


def test_log_time_echo_uses_the_log_clock(long_paths):
  ri = ri_on(long_paths)
  seen = _spy(ri)
  now = ri._preap_gate_step([(2_500_000_000, [ECHO])], set())
  assert seen == [2.5] and now == 2.5
