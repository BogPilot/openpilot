"""Every Pre-AP TX, by bus and address: 0x560 goes to the panda only (bus 0, refused by the tx hook, so never onto the car), also
with an empty donor VIN (17 spaces, NAP f00c8cb9 streams it without a donor), and nothing is ever written to the radar bus from
the CarController. The only host frame for bus 1 is the manual Read Radar VIN button's 0x641 (card, not the CarController;
test_preap_radar_donor.py covers that it never starts without the button)."""
import pytest

from opendbc.car.tesla_ap1.preap.panda_link import LinkInput
from opendbc.car.tesla_ap1.preap.radar_donor import RADAR_VIN_ADDR, RadarDonorStream, create_radar_vin_msg
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import PULL, _params_dir, params  # noqa: F401
from opendbc.car.tesla_ap1.tests.test_preap_full_demote import Car
from opendbc.car.tesla_ap1.values import CANBUS

# the CarController's possible TX: tesla_preap.h TESLA_PREAP_TX_MSGS without the radar UDS entry
CAR_TX = {(0x488, 0), (0x214, 0), (0x45, 0), (0x551, 0), (0x551, 2), (0x560, 0)}
KEY = (10, 480)


def _addr_bus(sd):
  return (sd.address, sd.src) if hasattr(sd, "address") else (sd[0], sd[2])


def _link(f):
  return LinkInput(safety_ok=True, safety_key=KEY, uptime=100, controls_allowed=False, new_sample=(f % 10 == 0), gtw_echo=False)


@pytest.mark.parametrize("vin", ["", "TESTQQQ4OIQ000001"])
def test_every_carcontroller_tx_bus_and_address(vin):
  c = Car(pedal=True)
  c.ctl.radar_donor = RadarDonorStream(True, vin, 0)          # radar flag 256, the panda in the car's mode, gateway closed
  c.ctl.radar_donor.update(0, False, False, link=LinkInput(safety_ok=False, new_sample=True))   # card started before the switch
  sends = []
  orig = c.ctl.update

  def update(cc, cs, nanos):
    cs.preap_link = _link(c.n)
    out = orig(cc, cs, nanos)
    sends.extend(out[1])
    return out
  c.ctl.update = update
  for _ in range(100):                                        # disengaged: the 0x560 stream runs
    c.step()
  c.step(stalk=PULL)
  for _ in range(9):
    c.step()
  c.step(stalk=PULL)
  for _ in range(200):                                        # engaged: pedal + steering, no 0x560
    c.step()
  seen = {_addr_bus(sd) for sd in sends}
  assert seen <= CAR_TX, seen - CAR_TX
  assert not any(bus == CANBUS.radar for _, bus in seen)     # never a frame on the radar bus
  m560 = [sd for sd in sends if _addr_bus(sd)[0] == RADAR_VIN_ADDR]
  assert m560 and all(_addr_bus(sd) == (RADAR_VIN_ADDR, 0) for sd in m560)
  assert c.enabled_frames > 100                               # it did engage and drive the pedal (ENABLE=1 frames)
  if vin == "":
    vin_bytes = b"".join(bytes(sd.dat)[5:8] if bytes(sd.dat)[0] == 0 else bytes(sd.dat)[1:8] for sd in m560[:3])
    assert vin_bytes == b" " * 17


@pytest.mark.parametrize("vin", ["", "TESTQQQ4OIQ000001"])
@pytest.mark.parametrize("controls_allowed", [False, True])
def test_panda_never_puts_0x560_on_the_car(vin, controls_allowed):
  from opendbc.car.structs import CarParams
  from opendbc.safety.tests.libsafety import libsafety_py
  from opendbc.safety.tests.test_tesla_preap import PREAP, pkt
  from opendbc.safety.tests.test_tesla_preap_radar import RADAR
  lib = libsafety_py.libsafety
  assert lib.set_safety_hooks(int(CarParams.SafetyModel.tesla), PREAP | RADAR) == 0
  lib.init_tests()
  lib.set_controls_allowed(controls_allowed)
  for rec in range(3):
    addr, dat, _ = tuple(create_radar_vin_msg(rec, vin, True, 0, 0))
    for bus in (0, 1, 2):
      assert not lib.safety_tx_hook(pkt(addr, bytearray(dat), bus)), (rec, bus)   # consumed (bus 0) or not allowed at all
