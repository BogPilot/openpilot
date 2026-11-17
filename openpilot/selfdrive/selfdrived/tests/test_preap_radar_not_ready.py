"""Pre-AP radar is advisory (NAP / Tinkla): its one alert is a warning, and nothing about the radar reaches engage or disable.

Code trace checked here (file:line in the commit message): card.py sets carState.bogpilot.preapRadarNotReady after RI.update;
opendbc ap1_events.py turns it into preapRadarNotReady while enabled; events.py gives that event ET.WARNING only. The pull FSM
(opendbc tesla_ap1/preap/carstate.py) has no radar input. selfdrived's radar events stay the stock ones (canError,
radarTempUnavailable, radarFault from radarState.radarErrors), and the Pre-AP RadarInterface sets none of them unless RADC_HWFail
(radarFault) or its radar parser goes invalid while frames still arrive (canError). A radar that goes quiet is advisory."""
import pathlib

from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import EVENTS, ET

EventName = log.OnroadEvent.EventName
ROOT = pathlib.Path(__file__).resolve().parents[4]


def code(path):
  """The file without comments (a comment may name the radar; code may not read it)."""
  return "\n".join(line.split("#", 1)[0] for line in (ROOT / path).read_text().splitlines())


def test_warning_only():
  e = EVENTS[EventName.preapRadarNotReady]
  assert set(e) == {ET.WARNING}
  assert e[ET.WARNING].alert_text_1 == "Radar not ready – using camera lead"


def test_no_engage_path_reads_the_radar_state():
  cs = code("opendbc_repo/opendbc/car/tesla_ap1/preap/carstate.py")
  assert "radar_ok" not in cs and "radar_valid" not in cs and "preap_gate" not in cs
  card = code("openpilot/selfdrive/car/card.py")
  assert "preap_radar_ok" not in card
  i_rd = card.index("RD: structs.RadarDataT | None = self.RI.update(can_list)")
  i_flag = card.index("CS.bogpilot.preapRadarNotReady = ")
  assert i_rd < i_flag


def test_selfdrived_radar_events_are_stock():
  sd = (ROOT / "openpilot/selfdrive/selfdrived/selfdrived.py").read_text()
  block = sd[sd.index("if self.CP.openpilotLongitudinalControl:\n      if self.sm['radarState'].radarErrors.canError:"):]
  block = block[:block.index("if CS.canTimeout:")]
  assert "preap" not in block.lower()
  assert "preapRadarNotReady" not in sd                    # only through car events (ap1_events.py)
