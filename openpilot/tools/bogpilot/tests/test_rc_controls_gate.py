"""Stdlib tooling tests only: no native libs, Params, daemons, or live paths."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpilot.tools.bogpilot import rc_controls_gate as gate


class GateTests(unittest.TestCase):
  def test_acceptance_is_strict(self):
    good = dict(tests=10, failures=0, errors=0, skipped=0)
    self.assertTrue(gate.acceptance(0, 0, good))
    self.assertFalse(gate.acceptance(1, 0, good))
    self.assertFalse(gate.acceptance(0, 5, good))
    for key in ("failures", "errors", "skipped"):
      self.assertFalse(gate.acceptance(0, 0, dict(good, **{key: 1})))
    self.assertFalse(gate.acceptance(0, 0, dict(good, tests=0)))

  def test_junit_includes_collection_errors_and_skips(self):
    with tempfile.TemporaryDirectory() as tmp:
      path = Path(tmp) / "junit.xml"
      path.write_text('<testsuites><testsuite><error/><testcase><skipped/></testcase><testcase><failure/></testcase></testsuite></testsuites>')
      self.assertEqual(gate.junit_counts(path), dict(tests=2, errors=1, failures=1, skipped=1))

  def test_plan_is_pending_and_does_not_execute(self):
    with tempfile.TemporaryDirectory() as tmp, patch.object(gate.subprocess, "run") as run:
      with contextlib.redirect_stdout(io.StringIO()):
        self.assertEqual(gate.main(["--sandbox-root", tmp, "--plan"]), 2)
      run.assert_not_called()
      self.assertEqual(list(Path(tmp).iterdir()), [])

  def test_wrong_platform_is_pending(self):
    with tempfile.TemporaryDirectory() as tmp, patch.object(gate, "is_agnos19", return_value=False), patch.object(gate.subprocess, "run") as run:
      with contextlib.redirect_stdout(io.StringIO()):
        self.assertEqual(gate.main(["--sandbox-root", tmp]), 2)
      run.assert_not_called()

  def test_live_roots_refused(self):
    for root in ("/", "/data", "/data/params", "/cache/test"):
      with self.subTest(root=root), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
        gate.main(["--sandbox-root", root, "--plan"])

  def test_execution_reports_failures_skips_and_pass_explicitly(self):
    import json
    from types import SimpleNamespace
    for outcome in ("pass", "skip", "fail", "collection-error", "import-fail"):
      with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        (root / ".bogpilot_locks").mkdir()
        (root / ".bogpilot_locks/agnos_vm_build.lock").mkdir()
        def execute(command, **kwargs):
          self.assertTrue(Path(kwargs["env"]["PARAMS_ROOT"]).is_relative_to(root))
          self.assertTrue(Path(kwargs["env"]["BOGPILOT_PARAMS_DIR"]).is_relative_to(root))
          if "-c" in command:
            return SimpleNamespace(returncode=int(outcome == "import-fail"), stdout="", stderr="")
          path = Path(command[command.index("--junitxml") + 1])
          content = {"pass": "<testcase/>", "skip": "<testcase><skipped/></testcase>",
                     "fail": "<testcase><failure/></testcase>", "collection-error": "<error/>"}[outcome]
          path.write_text("<testsuites><testsuite>" + content + "</testsuite></testsuites>")
          return SimpleNamespace(returncode=int(outcome in ("fail", "collection-error")), stdout="", stderr="")
        with patch.object(gate, "is_agnos19", return_value=True), patch.object(gate.Path, "home", return_value=root), patch.object(gate.subprocess, "run", side_effect=execute):
          with contextlib.redirect_stdout(io.StringIO()):
            code = gate.main(["--sandbox-root", tmp, "--lock-owner", "test-owner"])
        report = json.loads(next(root.glob("controls-gate-*/report.json")).read_text())
        self.assertEqual(code, 0 if outcome == "pass" else 1)
        self.assertEqual(report["status"], "passed" if outcome == "pass" else "failed")
        self.assertFalse(report["hardware_validated"])

  def test_existing_suites_are_required_not_reimplemented(self):
    self.assertTrue(all((gate.REPO / p).is_file() for p in gate.SUITES))
    self.assertEqual(len(gate.SUITES), 4)


if __name__ == "__main__":
  unittest.main()
