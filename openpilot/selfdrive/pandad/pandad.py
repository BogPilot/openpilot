#!/usr/bin/env python3
# simple pandad wrapper that updates the panda first
import os
import signal
import subprocess

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


def panda_ready() -> bool:
  """Is the panda up and running the firmware we ship?"""
  try:
    # a healthy panda answers on SPI within ~200ms of reset
    if not Panda.wait_for_panda(None, timeout=1):
      cloudlog.warning("no panda found")
      record_panda_firmware("Not found")
      return False
    with Panda(cli=False) as p:
      record_panda_firmware(panda_firmware_text(p.get_version(), bootstub=bool(p.bootstub), up_to_date=bool(p.bootstub) or p.up_to_date()))
      if p.bootstub:
        cloudlog.warning(f"panda stuck in bootstub, version {p.get_version()}")
        return False
      if not p.up_to_date():
        cloudlog.warning(f"panda firmware out of date, version {p.get_version()}")
        return False
      return True
  except Exception:
    # e.g. SPI protocol mismatch with old firmware
    cloudlog.exception("pandad.panda_check_failed")
    return False


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
  while not do_exit:
    try:
      cloudlog.event("pandad.flash_and_connect", count=count)
      count += 1

      HARDWARE.reset_internal_panda()
      if not panda_ready():
        flash_panda()
        assert panda_ready(), "panda not ready after flashing"

      # run real pandad
      os.environ['MANAGER_DAEMON'] = 'pandad'
      process = subprocess.Popen(["./pandad"], cwd=os.path.join(BASEDIR, "openpilot/selfdrive/pandad"))
      process.wait()
    except Exception:
      cloudlog.exception("pandad.uncaught_exception")


if __name__ == "__main__":
  main()
