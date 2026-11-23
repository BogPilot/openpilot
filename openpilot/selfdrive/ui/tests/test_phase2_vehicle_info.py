"""Synthetic fixtures only; no real Params or personal vehicle data."""
import unittest
from types import SimpleNamespace as NS
from openpilot.selfdrive.ui.bogpilot.phase2_vehicle_info import (
  INFO_KEYS, NOT_DETECTED, LAST_UNVERIFIED, CURRENT, vehicle_info, refresh_info_items,
  AIR_SUSPENSION, ALL_INFO_KEYS, AIR_DETECTED, AIR_NOT_DETECTED, AIR_UNKNOWN, read_air_suspension,
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


class TestAirSuspensionRow(unittest.TestCase):
  def test_ap1_model_s_and_x_show_the_three_states(self):
    for fp in ("TESLA_AP1_MODELS", "TESLA_AP1_MODELX"):
      self.assertEqual(vehicle_info(cp(carFingerprint=fp), air_suspension=True)[AIR_SUSPENSION], AIR_DETECTED)
      self.assertEqual(vehicle_info(cp(carFingerprint=fp), air_suspension=False)[AIR_SUSPENSION], AIR_NOT_DETECTED)
      self.assertEqual(vehicle_info(cp(carFingerprint=fp), air_suspension=None)[AIR_SUSPENSION], AIR_UNKNOWN)
      self.assertEqual(vehicle_info(cp(carFingerprint=fp), air_suspension=lambda: True)[AIR_SUSPENSION], AIR_DETECTED)
    self.assertEqual(AIR_UNKNOWN, "Unknown (not reported yet)")

  def test_other_cars_and_no_car_have_no_row(self):
    for obj in (None, cp(carFingerprint="TESLA_PREAP_MODELS"), cp(carFingerprint="TEST_PLATFORM"), cp(notCar=True),
                cp(carFingerprint="")):
      self.assertNotIn(AIR_SUSPENSION, vehicle_info(obj, air_suspension=True))

  def test_existing_rows_unchanged_and_last_detected_wording_kept(self):
    rows = vehicle_info(cp(), air_suspension=True)
    self.assertEqual(tuple(rows), INFO_KEYS + (AIR_SUSPENSION,))
    self.assertEqual(rows["Vehicle Info"], LAST_UNVERIFIED)
    self.assertEqual(ALL_INFO_KEYS[:len(INFO_KEYS)], INFO_KEYS)

  def test_reads_the_air_suspension_detected_file(self):
    import tempfile
    from pathlib import Path
    from opendbc.car.tesla_ap1 import ride_height
    with tempfile.TemporaryDirectory() as d:
      f = Path(d) / ride_height.DETECTED_KEY
      self.assertIsNone(read_air_suspension(f))
      f.write_text("1")
      self.assertTrue(read_air_suspension(f))
      f.write_text("0")
      self.assertFalse(read_air_suspension(f))
      self.assertEqual(ride_height._detected_path.name, "AirSuspensionDetected")

  def test_refresh_hides_the_row_for_other_cars(self):
    class Item:
      def __init__(self):
        self.action_item = self
      def set_visible(self, value):
        self.visible = value
      def set_text(self, value):
        self.text = value
    items = {key: Item() for key in ALL_INFO_KEYS}
    refresh_info_items(items, cp(), air_suspension=None)
    self.assertTrue(items[AIR_SUSPENSION].visible)
    self.assertEqual(items[AIR_SUSPENSION].text, AIR_UNKNOWN)
    refresh_info_items(items, cp(carFingerprint="TESLA_PREAP_MODELS"), air_suspension=True)
    self.assertFalse(items[AIR_SUSPENSION].visible)
    refresh_info_items(items, None, air_suspension=True)
    self.assertFalse(items[AIR_SUSPENSION].visible)
    self.assertTrue(items["Vehicle Info"].visible)

  def test_help_entry_exists_and_layout_attaches_it(self):
    from pathlib import Path
    from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve
    entry = resolve("AirSuspensionInfo")
    self.assertIsNotNone(entry)
    self.assertEqual(entry.title, "Air Suspension")
    for word in ("Detected", "Not Detected", "Unknown (not reported yet)", "Auto Height"):
      self.assertIn(word, entry.what + entry.when + entry.note)
    src = (Path(__file__).resolve().parents[1] / "layouts/settings/bogpilot.py").read_text()
    self.assertIn('attach_help(self.items[AIR_SUSPENSION], "AirSuspensionInfo")', src)
    self.assertIn("for key in ALL_INFO_KEYS", src)


if __name__ == "__main__":
  unittest.main()
