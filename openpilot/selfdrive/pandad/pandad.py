#!/usr/bin/env python3
# simple pandad wrapper that updates the panda first
import os
import signal
import subprocess
import time

from panda import Panda, PandaDFU
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.common.hardware import HARDWARE
from openpilot.common.swaglog import cloudlog


def record_panda_firmware(text: str) -> None:
  """Write what pandad found to the file-backed Pre-AP param the Vehicle screen shows. Never raises (a read-only /data must not stop pandad)."""
  try:
    from opendbc.car.tesla_ap1.preap import params as preap_params
    preap_params.set_str(preap_params.PreApParamKeys.PANDA_FIRMWARE, text)
  except Exception:
    cloudlog.exception("pandad.record_panda_firmware_failed")


def panda_firmware_text(version, bootstub: bool = False, up_to_date: bool = True) -> str:
  """The firmware version as shown to the driver: the version string, plus a note when the panda is not running the shipped app."""
  text = version.decode("utf-8", "replace") if isinstance(version, (bytes, bytearray)) else str(version)
  text = text.strip() or "unknown"
  if bootstub:
    return text + " (bootloader only)"
  if not up_to_date:
    return text + " (out of date)"
  return text


# Cold start. Upstream gives the panda 1 s to enumerate after the reset and otherwise goes straight to a DFU recover
# and a full reflash, then resets and tries again. A cold-powered panda can need longer than 1 s, so a cold start
# could loop through needless reflashes for tens of seconds before ./pandad ran (and the car stayed offroad).
# Here: the panda is polled (every 0.1 s, Panda.wait_for_panda) for up to COLD_START_WAIT_S on the first look and
# RETRY_WAIT_S on later ones, with a backoff between attempts. Only a panda that is found in its bootstub, on other
# firmware, or that cannot be read (old firmware, SPI protocol mismatch) is reflashed. A panda that is not found at
# all is only recovered through DFU after MISSING_BEFORE_RECOVER attempts in a row, so a dead or wedged panda is
# still recovered as upstream does. The "Connecting to panda..." offroad alert is shown once the panda has not
# answered within ALERT_AFTER_S, and cleared as soon as it is ready.
COLD_START_WAIT_S = 10.0
RETRY_WAIT_S = 3.0
# Measured on 82 AP1 boots (wrapper start to ./pandad start, so the reset and firmware check are included): p50 0.72 s,
# p90 2.98 s, then nothing between 3.02 s and 7.51 s; the 8 longer ones (p95 26.7 s, p99 82.0 s, max 87.7 s) are the slow
# cold power-ups. At 2.0 s the alert showed on 16 of 82 boots, 8 of them normal starts. 6.0 s is twice the slowest
# normal start and still below the quickest slow one.
ALERT_AFTER_S = 6.0
RETRY_BACKOFF_S = (0.5, 1.0, 2.0, 4.0)
MISSING_BEFORE_RECOVER = 3
CONNECTING_ALERT = "Offroad_ConnectingPanda"

READY, MISSING, BOOTSTUB, OUT_OF_DATE, UNREADABLE = "ready", "missing", "bootstub", "out_of_date", "unreadable"
NEEDS_FLASH = (BOOTSTUB, OUT_OF_DATE, UNREADABLE)


def log_step(step: str, t_step: float, t_start: float, **kw) -> None:
  """Per-step timing (ms) for the cold start, in the swaglog."""
  now = time.monotonic()
  cloudlog.event("pandad.timing", step=step, step_ms=round((now - t_step) * 1000), total_ms=round((now - t_start) * 1000), **kw)


def show_connecting_alert(show: bool) -> None:
  """Never raises: the alert is a hint for the driver, it must not stop pandad."""
  try:
    from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
    set_offroad_alert(CONNECTING_ALERT, show)
  except Exception:
    cloudlog.exception("pandad.connecting_alert_failed")


def wait_for_panda(wait_s: float, alert_after_s: float | None = None, on_slow=None) -> bool:
  """Poll for the panda for up to wait_s. on_slow() runs once if it has not answered within alert_after_s."""
  t0 = time.monotonic()
  first = wait_s if alert_after_s is None or on_slow is None else min(alert_after_s, wait_s)
  if Panda.wait_for_panda(None, timeout=first):
    return True
  if on_slow is not None:
    on_slow()
  remaining = wait_s - (time.monotonic() - t0)
  return remaining > 0 and bool(Panda.wait_for_panda(None, timeout=remaining))


def panda_state(wait_s: float = 1.0, alert_after_s: float | None = None, on_slow=None) -> str:
  """READY, MISSING, BOOTSTUB, OUT_OF_DATE or UNREADABLE (records what it found for the Vehicle screen)."""
  try:
    if not wait_for_panda(wait_s, alert_after_s, on_slow):
      cloudlog.warning("no panda found")
      record_panda_firmware("Not found")
      return MISSING
    with Panda(cli=False) as p:
      record_panda_firmware(panda_firmware_text(p.get_version(), bootstub=bool(p.bootstub), up_to_date=bool(p.bootstub) or p.up_to_date()))
      if p.bootstub:
        cloudlog.warning(f"panda stuck in bootstub, version {p.get_version()}")
        return BOOTSTUB
      if not p.up_to_date():
        cloudlog.warning(f"panda firmware out of date, version {p.get_version()}")
        return OUT_OF_DATE
      return READY
  except Exception:
    # e.g. SPI protocol mismatch with old firmware
    cloudlog.exception("pandad.panda_check_failed")
    return UNREADABLE


def panda_ready(wait_s: float = 1.0) -> bool:
  """Is the panda up and running the firmware we ship?"""
  return panda_state(wait_s) == READY


def next_action(state: str, missing_in_a_row: int) -> str:
  """What the loop does with a panda_state result: run ./pandad, reflash, or wait and retry."""
  if state == READY:
    return "run"
  if state in NEEDS_FLASH:
    return "flash"
  return "flash" if missing_in_a_row >= MISSING_BEFORE_RECOVER else "retry"


def backoff_s(attempt: int) -> float:
  return RETRY_BACKOFF_S[min(max(attempt, 0), len(RETRY_BACKOFF_S) - 1)]


def flash_panda() -> None:
  """Reflash bootstub + app from the ST bootloader. Works from any state the panda can be in."""
  cloudlog.warning("flashing panda")
  HARDWARE.recover_internal_panda()
  assert Panda.wait_for_dfu(None, timeout=5), "panda didn't enter DFU"
  with PandaDFU(None) as dfu:
    dfu.recover()

  assert Panda.wait_for_panda(None, timeout=5), "panda didn't boot into bootstub"
  with Panda(cli=False) as p:
    p.flash()
  cloudlog.warning("done flashing panda")


def main() -> None:
  # signal pandad to close the relay and exit
  def signal_handler(signum, frame):
    cloudlog.info(f"Caught signal {signum}, exiting")
    nonlocal do_exit
    do_exit = True
    if process is not None:
      process.send_signal(signal.SIGINT)

  process = None
  do_exit = False
  signal.signal(signal.SIGINT, signal_handler)

  # check health for lost heartbeat
  try:
    for s in Panda.list():
      with Panda(s) as p:
        health = p.health()
        if p.is_internal() and health["heartbeat_lost"]:
          Params().put_bool("PandaHeartbeatLost", True, block=True)
          cloudlog.event("heartbeat lost", deviceState=health)
  except Exception:
    cloudlog.exception("pandad.uncaught_exception")

  count = 0
  missing = 0
  failures = 0
  alert_shown = False
  t_start = time.monotonic()

  def set_alert(show: bool) -> None:
    nonlocal alert_shown
    if show != alert_shown:
      show_connecting_alert(show)
      alert_shown = show

  def sleep_unless_exit(seconds: float) -> None:
    end = time.monotonic() + seconds
    while not do_exit and time.monotonic() < end:
      time.sleep(min(0.1, max(0.0, end - time.monotonic())))

  while not do_exit:
    try:
      cloudlog.event("pandad.flash_and_connect", count=count)
      first = count == 0
      count += 1

      t = time.monotonic()
      HARDWARE.reset_internal_panda()
      log_step("reset", t, t_start, count=count)

      t = time.monotonic()
      state = panda_state(COLD_START_WAIT_S if first else RETRY_WAIT_S, ALERT_AFTER_S, lambda: set_alert(True))
      missing = missing + 1 if state == MISSING else 0
      action = next_action(state, missing)
      log_step("wait_for_panda", t, t_start, count=count, state=state, action=action)

      if action == "retry":
        set_alert(True)
        sleep_unless_exit(backoff_s(missing - 1))
        continue
      if action == "flash":
        set_alert(True)
        t = time.monotonic()
        flash_panda()
        missing = 0
        log_step("flash", t, t_start, count=count)
        assert panda_ready(RETRY_WAIT_S), "panda not ready after flashing"

      set_alert(False)
      failures = 0
      log_step("ready", t_start, t_start, count=count)

      # run real pandad
      os.environ['MANAGER_DAEMON'] = 'pandad'
      process = subprocess.Popen(["./pandad"], cwd=os.path.join(BASEDIR, "openpilot/selfdrive/pandad"))
      process.wait()
      t_start = time.monotonic()
    except Exception:
      cloudlog.exception("pandad.uncaught_exception")
      set_alert(True)
      sleep_unless_exit(backoff_s(failures))
      failures += 1

  set_alert(False)


if __name__ == "__main__":
  main()
