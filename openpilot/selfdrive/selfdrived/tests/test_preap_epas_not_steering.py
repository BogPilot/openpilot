"""Pre-AP "EPAS Not Steering" is a warning only (events.py), raised through car events (ap1_events.py), never by selfdrived."""
import pathlib

from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import EVENTS, ET, AlertStatus, AlertSize, Priority
from opendbc.car.structs import car

EventName = log.OnroadEvent.EventName
ROOT = pathlib.Path(__file__).resolve().parents[4]


def test_warning_only():
  e = EVENTS[EventName.preapEpasNotSteering]
  assert set(e) == {ET.WARNING}
  a = e[ET.WARNING]
  assert a.alert_text_1 == "EPAS Not Steering"
  assert a.alert_text_2 == "Steer manually. The EPAS is not accepting commands"
  assert a.alert_status == AlertStatus.userPrompt and a.alert_size == AlertSize.mid and a.priority == Priority.MID
  assert a.visual_alert == car.CarControl.HUDControl.VisualAlert.steerRequired
  assert a.audible_alert == car.CarControl.HUDControl.AudibleAlert.promptRepeat


def test_only_car_events_raise_it():
  sd = (ROOT / "openpilot/selfdrive/selfdrived/selfdrived.py").read_text()
  assert "preapEpasNotSteering" not in sd
  ev = (ROOT / "opendbc_repo/opendbc/car/tesla_ap1/ap1_events.py").read_text()
  assert 'PREAP_EPAS_NOT_STEERING = "preapEpasNotSteering"' in ev


def test_car_events_passes_it_through():
  from types import SimpleNamespace
  from opendbc.car.tesla_ap1.ap1_events import Ap1Events
  ev = Ap1Events()
  bp = SimpleNamespace(ap1DriverYield=False, ap1HandsOnLevel=0, ap1EacInhibited=False, preapEpasNotActive=True)
  out = []
  for _ in range(200):
    out = ev.update([], True, True, bp, False)
  assert [EventName.schema.enumerants[n] for n in out] == [EventName.preapEpasNotSteering]
