"""Pre-AP "Pedal Not Responding": the event exists, has the right alert types and plain wording, and CarEvents raises it."""
import unittest

from opendbc.car import structs
from openpilot.cereal import log
from openpilot.selfdrive.car.car_events import CarEvents
from openpilot.selfdrive.selfdrived.events import Alert, EVENTS, ET

EventName = log.OnroadEvent.EventName
AlertStatus = log.SelfdriveState.AlertStatus


def _cs(not_responding, available=False):
  cs = structs.CarState.new_message()
  cs.cruiseState.available = available
  cs.gearShifter = structs.CarState.GearShifter.drive
  cs.bogpilot.preapPedalNotResponding = not_responding
  return cs.as_reader()


def _events(cs, enabled=False):
  from opendbc.car.tesla_ap1.values import CAR
  cp = structs.CarParams.new_message(brand="tesla_ap1", carFingerprint=CAR.TESLA_PREAP_MODELS, openpilotLongitudinalControl=True)
  cc = structs.CarControl.new_message(enabled=enabled, latActive=enabled).as_reader()
  ev = CarEvents(cp).update(cs, _cs(False), cc)
  by_value = {v: k for k, v in EventName.schema.enumerants.items()}
  return {by_value[e] for e in ev.names}


class TestPedalNotResponding(unittest.TestCase):
  def test_event_is_defined_with_the_three_alert_types(self):
    e = EventName.pedalNotResponding
    types = EVENTS[e]
    self.assertEqual(set(types), {ET.IMMEDIATE_DISABLE, ET.PERMANENT, ET.NO_ENTRY})
    self.assertEqual(types[ET.IMMEDIATE_DISABLE].alert_status, AlertStatus.critical)   # same class as accFaulted / canBusMissing

  def test_wording_is_plain_and_mentions_the_wiring(self):
    texts = []
    for a in EVENTS[EventName.pedalNotResponding].values():
      self.assertIsInstance(a, Alert)
      texts += [a.alert_text_1, a.alert_text_2]
    joined = " | ".join(texts)
    self.assertIn("Pedal Not Responding", joined)
    self.assertIn("Check the Comma Pedal wiring", joined)
    self.assertIn("The Comma Pedal is not responding", joined)
    for bad in ("factor", "gas", "GAS_SENSOR", "0x552", "interceptor", "timeout"):
      self.assertNotIn(bad.lower(), joined.lower())

  def test_car_events_raises_it_and_drops_cruise_mode_disabled(self):
    names = _events(_cs(True, available=False))
    self.assertIn("pedalNotResponding", names)
    self.assertNotIn("wrongCarMode", names)

  def test_not_raised_while_the_pedal_responds(self):
    names = _events(_cs(False, available=False))
    self.assertNotIn("pedalNotResponding", names)
    self.assertIn("wrongCarMode", names)             # an uncalibrated / faulted car still gets the generic message

  def test_engaged_also_raises_it(self):
    self.assertIn("pedalNotResponding", _events(_cs(True), enabled=True))


class TestPedalRetrying(unittest.TestCase):
  """The pedal did not take authority; the alert names the real cause and does not disengage."""
  CAUSES = {1: "wiring", 2: "fault", 3: "mismatch", 4: "not moving", 5: "Pull the stalk again", 6: "not answering"}

  def _alert(self, cause):
    cs = structs.CarState.new_message()
    cs.bogpilot.preapPedalFailCause = cause
    fn = EVENTS[EventName.pedalRetrying][ET.WARNING]
    return fn(None, cs.as_reader(), None, False, 0, None)

  def test_warning_only_never_a_disengage(self):
    self.assertEqual(set(EVENTS[EventName.pedalRetrying]), {ET.WARNING})

  def test_every_cause_has_its_own_plain_detail_under_the_pedal_title(self):
    seen = set()
    for cause, word in self.CAUSES.items():
      a = self._alert(cause)
      self.assertIsInstance(a, Alert)
      self.assertEqual(a.alert_text_1, "Pedal Not Responding")
      self.assertIn(word, a.alert_text_2)
      seen.add(a.alert_text_2)
      for bad in ("factor", "gas", "0x552", "interceptor", "timeout", "panda", "DBC"):
        self.assertNotIn(bad.lower(), a.alert_text_2.lower())
    self.assertEqual(len(seen), len(self.CAUSES))

  def test_unknown_cause_is_still_plain(self):
    self.assertEqual(self._alert(0).alert_text_2, "Retrying")
    self.assertEqual(self._alert(99).alert_text_2, "Retrying")

  def test_detail_fits_the_mid_alert_line(self):
    for cause in self.CAUSES:
      self.assertLessEqual(len(self._alert(cause).alert_text_2), 46)

  def test_car_events_raises_it_while_engaged(self):
    cs = _cs(False, available=True)
    cs = structs.CarState.new_message()
    cs.cruiseState.available = True
    cs.gearShifter = structs.CarState.GearShifter.drive
    cs.bogpilot.preapPedalUnavailable = True
    self.assertIn("pedalRetrying", _events(cs.as_reader(), enabled=True))
    self.assertNotIn("pedalRetrying", _events(cs.as_reader(), enabled=False))


if __name__ == "__main__":
  unittest.main()
