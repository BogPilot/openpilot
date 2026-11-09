"""UI apply_choice -> Params -> get_car fingerprint_override -> CarParams.

Exercises the same consumer path PROPOSED_shared.patch wires into get_car/card.
When the shared patch is not yet applied, a local wrapper identical to that patch
is used so the lane can verify the contract natively. Prefer real get_car when
fingerprint_override is present.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

from opendbc.car import car_helpers
from opendbc.car.structs import CarParams
from openpilot.selfdrive.ui.bogpilot import phase2_car_selection as cs


AP1 = cs.AP1_S_PLATFORM
SOURCE_CAN = CarParams.FingerprintSource.can
SOURCE_FIXED = CarParams.FingerprintSource.fixed


class FakeParams:
  """Minimal Params stand-in; also used when real Params key registry is awkward."""
  def __init__(self):
    self.v = {}
  def get(self, key):
    return self.v.get(key)
  def get_bool(self, key):
    return bool(self.v.get(key, False))
  def put(self, key, value, block=False):
    self.v[key] = value
  def put_bool(self, key, value, block=False):
    self.v[key] = bool(value)
  def remove(self, key):
    self.v.pop(key, None)


def _finger_result(detected):
  return (detected, {0: {}, 1: {}, 2: {}}, "0" * 17, [], SOURCE_CAN, True)


def _get_car_cp(detected, params):
  """Drive get_car (or patch-equivalent) with fingerprint returning `detected`."""
  override = lambda d: cs.selected_fingerprint(params, d)

  with mock.patch.object(car_helpers, "fingerprint", side_effect=lambda *a, **k: _finger_result(detected)):
    sig = inspect.signature(car_helpers.get_car)
    if "fingerprint_override" in sig.parameters:
      CI = car_helpers.get_car(None, None, None, False, False, None, fingerprint_override=override)
      return CI.CP

    # Lane-native equivalent of PROPOSED_shared.patch get_car body (must stay in sync)
    candidate, fingerprints, vin, car_fw, source, exact_match = car_helpers.fingerprint(
      None, None, None, None)
    if candidate is None:
      from opendbc.car.tesla_ap1.values import CAR as AP1CAR, match_ap1_chassis
      if match_ap1_chassis(fingerprints):
        candidate = AP1CAR.TESLA_AP1_MODELS
        source = SOURCE_CAN
    candidate, used_saved = override(candidate)
    if used_saved:
      source = SOURCE_FIXED
      car_helpers.carlog.error({"event": "using saved fingerprint", "candidate": str(candidate)})
    if candidate is None:
      car_helpers.carlog.error({"event": "car doesn't match any fingerprints", "fingerprints": repr(fingerprints)})
      candidate = "MOCK"
    CarInterface = car_helpers.interfaces[candidate]
    CP = CarInterface.get_params(candidate, fingerprints, car_fw, False, False, docs=False)
    CP.carVin = vin
    CP.carFw = car_fw
    CP.fingerprintSource = source
    CP.fuzzyFingerprint = not exact_match
    return CP


class TestGetCarSelectionConsumer(unittest.TestCase):
  def setUp(self):
    self.p = FakeParams()

  def test_detected_ap1_forced_detected_wins(self):
    self.assertTrue(cs.apply_choice(self.p, cs.AP1_S, offroad=True))
    CP = _get_car_cp(AP1, self.p)
    self.assertEqual(CP.carFingerprint, AP1)
    self.assertEqual(CP.fingerprintSource, SOURCE_CAN)  # detected wins, not fixed

  def test_detected_other_forced_detected_wins(self):
    self.assertTrue(cs.apply_choice(self.p, cs.AP1_S, offroad=True))
    # Use a platform that exists in interfaces
    other = "MOCK"
    # MOCK via detection: fingerprint returns MOCK string — interfaces has MOCK
    CP = _get_car_cp("MOCK", self.p)
    self.assertEqual(CP.carFingerprint, "MOCK")
    self.assertNotEqual(CP.fingerprintSource, SOURCE_FIXED)

  def test_none_detected_forced_model_s(self):
    self.assertTrue(cs.apply_choice(self.p, cs.AP1_S, offroad=True))
    CP = _get_car_cp(None, self.p)
    self.assertEqual(CP.carFingerprint, AP1)
    self.assertEqual(CP.fingerprintSource, SOURCE_FIXED)

  def test_auto_no_override(self):
    cs.apply_choice(self.p, cs.AP1_S, offroad=True)
    self.assertTrue(cs.apply_choice(self.p, cs.AUTO, offroad=True))
    self.assertFalse(bool(cs._text(self.p.get(cs.MODEL_KEY))))
    self.assertFalse(self.p.get_bool(cs.FORCE_KEY))
    CP = _get_car_cp(None, self.p)
    self.assertEqual(CP.carFingerprint, "MOCK")
    self.assertNotEqual(CP.fingerprintSource, SOURCE_FIXED)

  def test_ui_store_consumer_roundtrip(self):
    """UI apply_choice -> store -> get_car consumer (FakeParams; same writers as real Params)."""
    self.assertTrue(cs.apply_choice(self.p, cs.AP1_S, offroad=True))
    self.assertEqual(self.p.get(cs.MODEL_KEY), AP1)
    CP = _get_car_cp(None, self.p)
    self.assertEqual(CP.carFingerprint, AP1)
    self.assertEqual(CP.fingerprintSource, SOURCE_FIXED)
    self.assertTrue(cs.apply_choice(self.p, cs.AUTO, offroad=True))
    self.assertFalse(bool(cs._text(self.p.get(cs.MODEL_KEY))))
    self.assertFalse(self.p.get_bool(cs.FORCE_KEY))
    CP2 = _get_car_cp(None, self.p)
    self.assertEqual(CP2.carFingerprint, "MOCK")
    self.assertNotEqual(CP2.fingerprintSource, SOURCE_FIXED)


if __name__ == "__main__":
  unittest.main()
