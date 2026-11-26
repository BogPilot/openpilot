"""0x560 path, end to end in libsafety (test only, no safety change): the host's 0x560 records on bus 0 are consumed by
tesla_preap_tx_hook (the donor config is applied) and refused, so the board's can_send never queues them for a transceiver;
on buses 1 and 2 they are not on the TX list, refused and not applied. The panda's own bus-1 gateway frames never use 0x560.
Other safety modes: NOOUTPUT and ELM327 refuse 0x560; ALLOUTPUT would pass it, and the host stream only runs while a panda
reports the car's safety model and param (radar_donor.py RadarDonorStream: no 0x560 without link.safety_ok)."""
import pytest

from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.preap.panda_link import LinkInput
from opendbc.car.tesla_ap1.preap.radar_donor import RADAR_VIN_ADDR, RadarDonorStream, create_radar_vin_msg
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_tesla_preap import PREAP, pkt
from opendbc.safety.tests.test_tesla_preap_radar import RADAR, sent

lib = libsafety_py.libsafety
GTW_CONFIG_SRC = (0x398, bytes.fromhex("0281555300000000"))   # chassis 0x398 -> panda's bus-1 0x2A9 once the config is complete


def _preap(controls_allowed=False):
  assert lib.set_safety_hooks(int(CarParams.SafetyModel.tesla), PREAP | RADAR) == 0
  lib.init_tests()
  lib.set_timer(1_000_000)
  lib.set_controls_allowed(controls_allowed)
  lib.safety_can_send_log_reset()


def _records(vin):
  return [tuple(create_radar_vin_msg(rec, vin, True, 0, 0))[:2] for rec in range(3)]


def _gateway_frames():
  lib.safety_can_send_log_reset()
  lib.safety_rx_hook(pkt(GTW_CONFIG_SRC[0], bytearray(GTW_CONFIG_SRC[1]), 0))
  return sent()


@pytest.mark.parametrize("vin", ["", "TESTQQQ4OIQ000001"])
def test_bus0_records_are_consumed_and_never_queued(vin):
  _preap()
  assert not [f for f in _gateway_frames() if f[0] == 0x2A9]           # gateway closed before the config
  log = []
  for addr, dat in _records(vin):
    assert not lib.safety_tx_hook(pkt(addr, bytearray(dat), 0))        # refused: can_send counts it blocked, never queues it
    log += sent()
  out = _gateway_frames()
  assert [f for f in out if f[0] == 0x2A9 and f[1] == 1]                # consumed: the config opened the gateway
  assert all(f[0] != RADAR_VIN_ADDR for f in log + out)                 # no 0x560 in anything the panda itself sends


@pytest.mark.parametrize("bus", [1, 2])
def test_other_bus_records_are_refused_and_not_applied(bus):
  _preap()
  for addr, dat in _records(""):
    assert not lib.safety_tx_hook(pkt(addr, bytearray(dat), bus))
  assert not [f for f in _gateway_frames() if f[0] == 0x2A9]           # not on the TX list: the hook never saw it


def test_refused_while_controls_allowed():
  _preap(controls_allowed=True)
  for addr, dat in _records(""):
    for bus in (0, 1, 2):
      assert not lib.safety_tx_hook(pkt(addr, bytearray(dat), bus))


def test_panda_gateway_frames_never_use_0x560():
  _preap()
  for addr, dat in _records(""):
    lib.safety_tx_hook(pkt(addr, bytearray(dat), 0))
  frames = []
  for src in (0x45, 0x108, 0x145, 0x20A, 0x308, 0x30A, 0x398, 0x405, 0x118, 0x168, 0x175, 0x2E5, 0x101):
    for d in (bytes(8), bytes((0x11, 0, 0, 0, 0, 0, 0, 0))):
      lib.safety_can_send_log_reset()
      lib.safety_rx_hook(pkt(src, bytearray(d), 0))
      frames += sent()
  assert frames and all(f[0] != RADAR_VIN_ADDR and f[1] == 1 for f in frames)


@pytest.mark.parametrize("mode,passes", [("noOutput", False), ("elm327", False), ("allOutput", True)])
def test_other_safety_modes(mode, passes):
  assert lib.set_safety_hooks(int(getattr(CarParams.SafetyModel, mode)), 0) == 0
  lib.init_tests()
  addr, dat = _records("")[0]
  assert bool(lib.safety_tx_hook(pkt(addr, bytearray(dat), 0))) is passes


def test_host_stream_needs_the_panda_in_the_cars_mode():
  s = RadarDonorStream(True, "", 0)
  out = []
  for f in range(2000):
    out += s.update(f, False, link=LinkInput(safety_ok=False, safety_key=(17, 0), uptime=10 + f, new_sample=(f % 50 == 0)))
  assert out == []
