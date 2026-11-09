"""t994 INT: Car Selection UI -> real Params -> get_car(fingerprint_override) -> CarParams consumer contract.

Drives the real car_helpers.get_car with detection stubbed to fail/succeed. Requires the native
(AGNOS/py3.12 with tqdm, capnp, compiled Params) environment.
"""
import os
import tempfile
import unittest
from unittest import mock

from opendbc.car import car_helpers
from opendbc.car.car_helpers import get_car
from openpilot.selfdrive.ui.bogpilot import phase2_car_selection as sel

CPS = car_helpers.CarParams.FingerprintSource


def _run(params, detected=None, source=None):
  fp = (detected, {}, "", [], source if source is not None else CPS.can, True)
  with mock.patch.object(car_helpers, "fingerprint", return_value=fp):
    return get_car(lambda *a, **k: [], lambda *a, **k: None, lambda *_: None, False, False, None,
                   fingerprint_override=lambda d: sel.selected_fingerprint(params, d))


class TestGetCarOverride(unittest.TestCase):
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()
    self._old = os.environ.get("PARAMS_ROOT")
    os.environ["PARAMS_ROOT"] = self._tmp.name
    from openpilot.common.params import Params
    self.p = Params()

  def tearDown(self):
    if self._old is None:
      os.environ.pop("PARAMS_ROOT", None)
    else:
      os.environ["PARAMS_ROOT"] = self._old
    self._tmp.cleanup()

  def test_fresh_install_is_auto_and_unchanged(self):
    self.assertEqual(sel.current_choice(self.p), sel.AUTO)
    self.assertEqual(_run(self.p).CP.carFingerprint, "MOCK")

  def test_ui_apply_model_s_forces_ap1_when_detection_fails(self):
    self.assertTrue(sel.apply_choice(self.p, sel.AP1_S, offroad=True))
    CI = _run(self.p)
    self.assertEqual(CI.CP.carFingerprint, "TESLA_AP1_MODELS")
    self.assertEqual(CI.CP.fingerprintSource, CPS.fixed)

  def test_ui_auto_clears_params_and_returns_mock(self):
    sel.apply_choice(self.p, sel.AP1_S, offroad=True)
    sel.apply_choice(self.p, sel.AUTO, offroad=True)
    self.assertFalse(self.p.get(sel.MODEL_KEY))
    self.assertFalse(self.p.get_bool(sel.FORCE_KEY))
    self.assertEqual(_run(self.p).CP.carFingerprint, "MOCK")

  def test_detected_car_never_overridden_even_when_forced(self):
    from types import SimpleNamespace
    sel.apply_choice(self.p, sel.AP1_S, offroad=True)

    class FakeInterface:
      def __init__(self, CP):
        self.CP = CP

      @staticmethod
      def get_params(candidate, *a, **k):
        return SimpleNamespace(carFingerprint=candidate, fingerprintSource=None)

    with mock.patch.dict(car_helpers.interfaces, {"FAKE_DETECTED_CAR": FakeInterface}):
      CI = _run(self.p, detected="FAKE_DETECTED_CAR")
    self.assertEqual(CI.CP.carFingerprint, "FAKE_DETECTED_CAR")
    self.assertNotEqual(CI.CP.fingerprintSource, CPS.fixed)

  def test_onroad_apply_refused_no_params_written(self):
    self.assertFalse(sel.apply_choice(self.p, sel.AP1_S, offroad=False))
    self.assertEqual(_run(self.p).CP.carFingerprint, "MOCK")

  def test_model_x_refused(self):
    self.assertFalse(sel.apply_choice(self.p, sel.AP1_X, offroad=True))
    self.assertEqual(_run(self.p).CP.carFingerprint, "MOCK")

  def test_default_signature_without_override_unchanged(self):
    fp = (None, {}, "", [], CPS.can, True)
    with mock.patch.object(car_helpers, "fingerprint", return_value=fp):
      CI = get_car(lambda *a, **k: [], lambda *a, **k: None, lambda *_: None, False, False, None)
    self.assertEqual(CI.CP.carFingerprint, "MOCK")


if __name__ == "__main__":
  unittest.main()
