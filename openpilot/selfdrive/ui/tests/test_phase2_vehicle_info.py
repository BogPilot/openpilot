"""Synthetic fixtures only; no real Params or personal vehicle data."""
import unittest
from types import SimpleNamespace as NS
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle_info import (
  INFO_KEYS, NOT_DETECTED, LAST_UNVERIFIED, CURRENT, vehicle_info, refresh_info_items,
)


def cp(**changes):
  values = dict(brand="tesla", carFingerprint="TESLA_AP1_MODELS", notCar=False,
                openpilotLongitudinalControl=True, radarUnavailable=False, autoResumeSng=True)
  values.update(changes)
  return NS(**values)


class TestVehicleInfo(unittest.TestCase):
  def test_missing_is_not_detected(self):
    rows = vehicle_info(None)
    self.assertEqual(tuple(rows), INFO_KEYS)
    self.assertEqual(rows["Vehicle Info"], NOT_DETECTED)
    self.assertEqual(rows["Radar Support"], "Unavailable")

  def test_persisted_last_detected_unverified(self):
    rows = vehicle_info(cp())
    self.assertEqual(rows["Vehicle Info"], LAST_UNVERIFIED)
    self.assertEqual(rows["Detected Make"], "tesla")
    self.assertEqual(rows["Detected Model / Fingerprint"], "TESLA_AP1_MODELS")

  def test_explicit_current(self):
    self.assertEqual(vehicle_info(cp(), current=True)["Vehicle Info"], CURRENT)

  def test_support(self):
    rows = vehicle_info(cp(openpilotLongitudinalControl=False, radarUnavailable=True, autoResumeSng=False))
    for key in INFO_KEYS[3:]:
      self.assertEqual(rows[key], "No")
      self.assertEqual(vehicle_info(cp())[key], "Yes")

  def test_missing_fields_not_false(self):
    rows = vehicle_info(NS(carFingerprint="TEST_PLATFORM"))
    for key in INFO_KEYS[3:]:
      self.assertEqual(rows[key], "Unavailable")
    self.assertEqual(rows["Detected Make"], "Unavailable")

  def test_legacy_schema(self):
    self.assertEqual(vehicle_info(NS(carName="tesla", carFingerprint="TEST_PLATFORM"))["Detected Make"], "tesla")

  def test_mock_and_unidentified(self):
    for obj in (cp(notCar=True), cp(brand="mock"), cp(carFingerprint="mock")):
      rows = vehicle_info(obj)
      self.assertIn("Unavailable", rows["Vehicle Info"])
      self.assertEqual(rows["Radar Support"], "Unavailable")
    # empty fingerprint -> not detected (honest no-id)
    rows = vehicle_info(cp(carFingerprint=""))
    self.assertEqual(rows["Vehicle Info"], NOT_DETECTED)

  def test_no_writes_or_private_fields(self):
    obj = cp(carVin="SYNTHETIC_PRIVATE", serial="SYNTHETIC_SERIAL")
    before = vars(obj).copy()
    rows = vehicle_info(obj)
    self.assertEqual(vars(obj), before)
    self.assertNotIn("SYNTHETIC", str(rows))

  def test_refresh_clears_stale(self):
    class Item:
      def __init__(self):
        self.action_item = self
      def set_visible(self, value):
        self.visible = value
      def set_text(self, value):
        self.text = value
    items = {key: Item() for key in INFO_KEYS}
    refresh_info_items(items, cp())
    refresh_info_items(items, None)
    self.assertEqual(items["Vehicle Info"].text, NOT_DETECTED)
    self.assertEqual(items["Detected Make"].text, "Unavailable")
    self.assertTrue(all(item.visible for item in items.values()))


if __name__ == "__main__":
  unittest.main()
