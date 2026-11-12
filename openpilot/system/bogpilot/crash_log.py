"""Local crash log for the on-screen 'openpilot crashed' alert.

When a managed Python process dies, the last lines of the traceback are written
to /data/error_logs/error.txt (and a timestamped copy). selfdrived shows the
crash alert while that file exists, and removes the current-drive marker at
start so a previous session cannot re-raise it. Nothing here leaves the device.
"""
from datetime import datetime
from pathlib import Path
import os

ERROR_TXT = "error.txt"
DEFAULT_ERROR_LOGS_PATH = Path("/data/error_logs")


def logs_dir():
  return Path(os.environ.get("BOGPILOT_ERROR_LOGS", str(DEFAULT_ERROR_LOGS_PATH)))

# Matching the 0.9.7 capture_exception filter: these are retry/overwrite messages, not a process crash.
_SKIP_PHRASES = (
  "already exists. To overwrite it, set 'overwrite' to True",
  "failed after retry",
)


def error_log_path():
  return logs_dir() / ERROR_TXT


def error_log_present():
  try:
    return error_log_path().is_file()
  except OSError:
    return False


def clear_error_log():
  """Drop the current-drive marker. Timestamped copies are left for the Error Log viewer."""
  path = error_log_path()
  try:
    if path.is_file():
      path.unlink()
  except OSError:
    pass


def save_crash_log(exc_text, crash_log=True):
  """Write a timestamped full traceback and, when crash_log is set, the last 10 lines to error.txt."""
  if not exc_text or any(phrase in exc_text for phrase in _SKIP_PHRASES):
    return False
  try:
    logs_dir().mkdir(parents=True, exist_ok=True)
    stamp = logs_dir() / f"{datetime.now().astimezone().strftime('%Y-%m-%d--%H-%M-%S')}.log"
    stamp.write_text(exc_text)
    if crash_log:
      lines = exc_text.splitlines()[-10:]
      error_log_path().write_text("\n".join(lines))
    return True
  except OSError:
    return False
