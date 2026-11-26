"""preap/panda_link.py against the panda source it reads: the radar gateway's bus-1 addresses and the echo offsets."""
import pathlib
import re

from opendbc.car.tesla_ap1.preap import panda_link

ROOT = pathlib.Path(panda_link.__file__).resolve().parents[3]


def test_gtw_echo_addrs_are_exactly_what_the_gateway_sends_on_bus_1():
  src = (ROOT / "safety/modes/tesla_preap_radar.h").read_text()
  readdr = {int(x, 16) for x in re.findall(r"tesla_preap_radar_readdr\(to_fwd,\s*(0x[0-9A-Fa-f]+)\)", src)}
  built = {int(x, 16) for x in re.findall(r"pkt\.addr\s*=\s*(0x[0-9A-Fa-f]+)U?;", src)}
  assert readdr and built
  assert panda_link.GTW_ECHO_ADDRS == frozenset(readdr | built)
  assert "can_send(pkt, 1, true)" in src


def test_echo_offsets_match_pandad():
  h = (ROOT.parent / "openpilot/selfdrive/pandad/panda.h")
  if h.exists():
    t = h.read_text()
    assert re.search(r"CAN_REJECTED_BUS_OFFSET\s+0xC0U", t) and re.search(r"CAN_RETURNED_BUS_OFFSET\s+0x80U", t)
  assert panda_link.GTW_ECHO_SRC == 129


def test_rate_limited_log():
  out = []
  log = panda_link.RateLimitedLog(out.append, 10.0)
  for t in range(0, 300):
    log(t * 0.1, "x")
  assert len(out) == 3 and out[1].endswith("(+99 suppressed)")
