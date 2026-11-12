import os
import tempfile
import unittest
from pathlib import Path


class TestCrashLog(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    os.environ["BOGPILOT_ERROR_LOGS"] = self.tmp.name
    # Import after the env is set; also re-read via logs_dir() on every call.
    from openpilot.system.bogpilot import crash_log
    self.m = crash_log

  def tearDown(self):
    os.environ.pop("BOGPILOT_ERROR_LOGS", None)
    self.tmp.cleanup()

  def test_save_writes_error_txt_and_timestamped_copy(self):
    text = "Traceback (most recent call last):\n" + "\n".join(f"  line {i}" for i in range(15)) + "\nRuntimeError: boom"
    self.assertTrue(self.m.save_crash_log(text))
    self.assertTrue(self.m.error_log_present())
    # error.txt keeps the last 10 lines
    saved = self.m.error_log_path().read_text().splitlines()
    self.assertEqual(len(saved), 10)
    self.assertEqual(saved[-1], "RuntimeError: boom")
    stamped = list(Path(self.tmp.name).glob("*.log"))
    self.assertEqual(len(stamped), 1)
    self.assertEqual(stamped[0].read_text(), text)

  def test_skip_phrases_and_empty_are_ignored(self):
    self.assertFalse(self.m.save_crash_log(""))
    self.assertFalse(self.m.save_crash_log("file already exists. To overwrite it, set 'overwrite' to True"))
    self.assertFalse(self.m.save_crash_log("the download failed after retry"))
    self.assertFalse(self.m.error_log_present())

  def test_clear_removes_only_the_current_marker(self):
    self.assertTrue(self.m.save_crash_log("Traceback\nError"))
    stamped = list(Path(self.tmp.name).glob("*.log"))
    self.assertTrue(stamped)
    self.m.clear_error_log()
    self.assertFalse(self.m.error_log_present())
    self.assertTrue(stamped[0].is_file())

  def test_process_launcher_calls_save_crash_log(self):
    src = Path(__file__).resolve().parents[2] / "manager" / "process.py"
    text = src.read_text()
    self.assertIn("from openpilot.system.bogpilot.crash_log import save_crash_log", text)
    crash = text[text.index("except Exception:"):]
    crash = crash[:crash.index("raise")]
    self.assertIn("cloudlog.exception(\"crash\")", crash)
    self.assertIn("save_crash_log(traceback.format_exc())", crash)


if __name__ == "__main__":
  unittest.main()
