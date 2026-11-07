"""Gate-tool self-tests. Recorder acceptance is the explicit actual-module CLI."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("_recorder_gate_test_tool", Path(__file__).resolve().parents[1] / "rc_recorder_gate.py")
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


class TestRecorderGateTool(unittest.TestCase):
  def test_missing_subject_is_pending_never_pass(self):
    report = gate.run_gate("/nonexistent/neutral-recorder-fixture.py")
    self.assertEqual(report["counts"], {"PASS": 0, "FAIL": 0, "PENDING": 1})
    self.assertEqual(gate.exit_code(report), 2)

  def test_failure_dominates_pending(self):
    self.assertEqual(gate.exit_code({"counts": {"PASS": 10, "FAIL": 1, "PENDING": 1}}), 1)
    self.assertEqual(gate.exit_code({"counts": {"PASS": 10, "FAIL": 0, "PENDING": 0}}), 0)

  def test_require_never_optimizes_away(self):
    with self.assertRaisesRegex(AssertionError, "fixture"):
      gate.require(False, "fixture")

  def test_worker_wait_is_bounded(self):
    with self.assertRaisesRegex(AssertionError, "bounded"):
      gate.wait_for(lambda: False, timeout=0.01)
    gate.wait_for(lambda: True, timeout=0.1)

  def test_synthetic_encoder_success_not_real_video(self):
    with tempfile.TemporaryDirectory(prefix="bp-gate-unit-") as tmp:
      path = Path(tmp) / "neutral.mp4"
      enc = gate.FakeEncoder(str(path), 16, 16)
      self.assertTrue(enc.open())
      self.assertTrue(enc.write(gate.FRAME))
      self.assertTrue(enc.close())
      self.assertFalse(Path(str(path) + ".lock").exists())
      self.assertIn(b"synthetic-not-video", path.read_bytes())

  def test_synthetic_enospc_discards_output(self):
    with tempfile.TemporaryDirectory(prefix="bp-gate-unit-") as tmp:
      path = Path(tmp) / "neutral.mp4"
      enc = gate.FakeEncoder(str(path), 16, 16, fault="enospc")
      self.assertTrue(enc.open())
      self.assertFalse(enc.write(gate.FRAME))
      self.assertFalse(enc.close())
      self.assertFalse(path.exists())
      self.assertFalse(Path(str(path) + ".lock").exists())
      self.assertTrue(enc.error)


if __name__ == "__main__":
  unittest.main()
