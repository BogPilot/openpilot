"""Pre-AP no Comma Pedal at car start (CarParams.flags PREAP_NO_PEDAL): the steering-only banner says why; otherwise unchanged."""
from types import SimpleNamespace

from openpilot.selfdrive.selfdrived import events as ev
from opendbc.car.tesla_ap1.values import TeslaAp1Flags


def _cp(flags=0, brand="tesla_ap1"):
  return SimpleNamespace(brand=brand, flags=flags)


def _alert(cp):
  return ev.preap_steer_only_alert(cp, SimpleNamespace(), None, False, 0, 0)


def test_flag_value_matches_opendbc():
  assert ev.PREAP_NO_PEDAL_FLAG == int(TeslaAp1Flags.PREAP_NO_PEDAL)


def test_no_pedal_banner_names_the_cause():
  a = _alert(_cp(int(TeslaAp1Flags.PREAP_NO_PEDAL)))
  assert a.alert_text_1 == "Steering only: no Comma Pedal found" and a.alert_text_2 == "Double pull for stock cruise"


def test_normal_banner_unchanged():
  a = _alert(_cp(0))
  assert a.alert_text_1 == "Steering only" and a.alert_text_2 == "Double pull for speed control"


def test_other_brands_never_read_the_bit():
  assert not ev.preap_no_pedal(_cp(1, brand="tesla"))


def test_event_uses_the_callback():
  assert ev.EVENTS[ev.EventName.preapSteerOnly][ev.ET.PERMANENT] is ev.preap_steer_only_alert
