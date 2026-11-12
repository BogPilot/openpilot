"""The Pre-AP <-> AOL seam (selfdrive/car/preap_aol.py): fail-closed, asks only, never enables anything."""
import types
import unittest
from unittest import mock

from opendbc.car.tesla_ap1.preap import params as pp
from openpilot.selfdrive.car import ap1_runtime, preap_aol

PREAP = types.SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS")
AP1 = types.SimpleNamespace(carFingerprint="TESLA_AP1_MODELS")


class TestPreapAolSeam(unittest.TestCase):
  def tearDown(self):
    pp.register_aol_provider(None)

  def test_closed_in_this_build_the_function_does_not_exist(self):
    self.assertFalse(hasattr(ap1_runtime, "preap_aol_available"))
    self.assertFalse(preap_aol.preap_aol_available(PREAP))
    preap_aol.install(PREAP)
    self.assertFalse(pp.aol_available())
    self.assertFalse(pp.double_pull_enabled())

  def test_open_only_when_the_aol_lane_function_answers_true_for_a_preap_car(self):
    seen = []
    def fn(cp):
      seen.append(cp)
      return True
    with mock.patch.object(ap1_runtime, "preap_aol_available", fn, create=True):
      self.assertTrue(preap_aol.preap_aol_available(PREAP))
      self.assertFalse(preap_aol.preap_aol_available(AP1))          # AP1 has its own AOL path; never routed through here
      preap_aol.install(PREAP)
      self.assertTrue(pp.aol_available())
    self.assertEqual(seen[0], PREAP)

  def test_anything_but_true_or_a_crash_is_closed(self):
    for answer in (False, None, 1, "True"):
      with mock.patch.object(ap1_runtime, "preap_aol_available", lambda cp, a=answer: a, create=True):
        self.assertFalse(preap_aol.preap_aol_available(PREAP), answer)
    def boom(cp):
      raise RuntimeError("x")
    with mock.patch.object(ap1_runtime, "preap_aol_available", boom, create=True):
      self.assertFalse(preap_aol.preap_aol_available(PREAP))

  def test_the_seam_never_reads_or_writes_the_aol_param(self):
    src = open(preap_aol.__file__).read()
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    body = code.split('"""')[2]               # after the module docstring
    for needle in ("Params(", "put_bool", "get_bool", "AlwaysOnLateral\""):
      self.assertNotIn(needle, body)


if __name__ == "__main__":
  unittest.main()
