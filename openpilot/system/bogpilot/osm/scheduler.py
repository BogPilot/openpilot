"""Scheduled map updates: the consumer of the Map Data page's "Automatically Update Maps" row (`PreferredSchedule`).

0.9.7 `frogpilot_utilities.update_maps()` asked mapd for the selected regions when the schedule was due (first download, Sunday
for Weekly, the 1st for Monthly, never for Manually once maps exist, at most once per calendar day) and stamped
`LastMapsUpdate` when the download ended. `downloads.scheduled_update_due()` (slice 1) is that decision; this class is the
tick that applies it. It runs inside the `bogpilot_mapd` supervisor, so it only exists while mapd does, only acts while the
car is off and the device is on unmetered Wi-Fi (as upstream FrogPilot's map_scheduler: automatic updates never
use the hotspot or mobile data; a manual Download press works on any connection), and never starts a second download.
"""
from __future__ import annotations

import datetime
import socket

from openpilot.system.bogpilot.osm import regions
from openpilot.system.bogpilot.osm.downloads import DownloadController, date_label, scheduled_update_due
from openpilot.system.bogpilot.osm.map_data_controller import (DEFAULT_SCHEDULE, LAST_UPDATE_KEY, SCHEDULE_KEY, SELECTION_KEY, downloads_allowed,
                                                                finish_download)
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage

TICK_S = 60.0                              # how often the supervisor asks (0.9.7 polled once a minute while waiting)
TILE_HOST = ("map-data.pfeifer.dev", 443)  # where mapd v1.12.0 downloads the 2x2 degree tiles from


def default_online() -> bool:
  try:
    with socket.create_connection(TILE_HOST, timeout=3.0):
      return True
  except OSError:
    return False


def default_unmetered_wifi() -> bool:
  """Connected over Wi-Fi (or Ethernet) and NetworkManager does not flag the link as metered. A phone hotspot normally reports
  metered (Android advertises it). Any read problem counts as metered (no automatic download)."""
  try:
    from openpilot.common.hardware import HARDWARE
    from openpilot.common.hardware.base import NetworkType
    nt = HARDWARE.get_network_type()
    return nt in (NetworkType.wifi, NetworkType.ethernet) and not HARDWARE.get_network_metered(nt)
  except Exception:
    return False


def default_offroad() -> bool:
  """Offroad = the manager says the car is not started. Any read problem counts as 'not offroad' (no scheduled download)."""
  try:
    from openpilot.common.params import Params
    return not Params().get_bool("IsOnroad")
  except Exception:
    return False


class UpdateScheduler:
  def __init__(self, store, mem: MemParams | None = None, storage: OsmStorage | None = None, now=datetime.datetime.now,
               online=default_online, offroad=default_offroad, allowed=None, unmetered=default_unmetered_wifi):
    self.store = store
    self.mem = mem or MemParams()
    self.storage = storage or OsmStorage()
    self.dl = DownloadController(self.mem, self.storage)
    self._now = now
    self._online = online
    self._offroad = offroad
    self._unmetered = unmetered
    self._allowed = allowed or (lambda: downloads_allowed(store))   # Speed Limit Controller on
    self._attempted_on: str | None = None     # one scheduled request per calendar day, whatever happens to it

  def tick(self) -> str:
    """One scheduling step. Returns what happened (for the logs and tests)."""
    now = self._now()
    p = self.dl.progress()
    if p.done:
      finish_download(self.store, self.mem, now.date())
      return "finished"
    if p.active:
      return "running"
    if not self._allowed():
      return "slc_off"
    sel = regions.parse_selection(self.store.get(SELECTION_KEY, ""))
    if sel.is_empty():
      return "no_regions"
    try:
      schedule = self.store.get_int(SCHEDULE_KEY, DEFAULT_SCHEDULE)
    except (TypeError, ValueError):
      schedule = DEFAULT_SCHEDULE
    last = self.store.get(LAST_UPDATE_KEY, "") or None
    # "maps exist" also counts maps the user removed on purpose (Last Updated is still set): Remove Maps must not be undone by the
    # first-download rule at the next tick. Weekly / Monthly still refresh them on their day, as the user asked.
    if not scheduled_update_due(now, max(0, min(2, schedule)), self.storage.has_maps() or bool(last), last, sel):
      return "not_due"
    today = date_label(now.date())
    if self._attempted_on == today:
      return "already_tried"
    if not self._offroad():
      return "onroad"
    if not self.storage.enough_space(regions.estimate(sel).est_bytes):
      return "no_space"
    if not self._unmetered():
      return "metered"
    if not self._online():
      return "offline"
    if not self.dl.start(sel, auto=True):
      return "start_failed"
    self._attempted_on = today
    return "started"
