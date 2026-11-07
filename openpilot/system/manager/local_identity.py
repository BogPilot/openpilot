"""BogPilot local device identity. No registration, no network.

Replaces comma athena registration. Reuses an already stored DongleId param or the
factory /persist/comma/dongle_id file; never contacts a server, never deletes credentials.
"""
from pathlib import Path

from openpilot.common.params import Params
from openpilot.common.hardware.hw import Paths

UNREGISTERED_DONGLE_ID = "UnregisteredDevice"


def is_registered_device() -> bool:
  return Params().get("DongleId") not in (None, UNREGISTERED_DONGLE_ID)


def local_dongle_id(params: Params | None = None) -> str:
  params = params or Params()
  dongle_id = params.get("DongleId")
  if dongle_id:
    return dongle_id
  persist = Path(Paths.persist_root()) / "comma" / "dongle_id"
  if persist.is_file():
    dongle_id = persist.read_text().strip()
  dongle_id = dongle_id or UNREGISTERED_DONGLE_ID
  params.put("DongleId", dongle_id, block=True)
  return dongle_id
