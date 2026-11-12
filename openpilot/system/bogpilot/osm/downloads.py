"""Region download management: schedule (0.9.7 update_maps), start/cancel, progress and completion.

mapd v1.12.0 performs the downloads itself when OSMDownloadLocations is written. 0.9.7 completion detection
(downloaded_files == total_files) can hang forever when a cell is missing on the server (mapd skips it without
counting), so completion here is "mapd emptied OSMDownloadLocations after writing progress".
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

from openpilot.system.bogpilot.osm import regions
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage

SCHEDULE_NEVER, SCHEDULE_WEEKLY, SCHEDULE_MONTHLY = 0, 1, 2     # PreferredSchedule values (0.9.7 labels: Manually / Weekly / Monthly)
SCHEDULE_LABELS = ("Manually", "Weekly", "Monthly")             # 0.9.7 Qt panel; the raylib metadata says "Never"


def date_label(d: datetime.date) -> str:
  """0.9.7 LastMapsUpdate format: 'November 9th, 2026'."""
  day = d.day
  suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
  return d.strftime(f"%B {day}{suffix}, %Y")


def scheduled_update_due(now: datetime.datetime, schedule: int, maps_downloaded: bool, last_update: str | None,
                         sel: regions.Selection) -> bool:
  """Exact port of bogpilot_utilities.update_maps decision (minus the mapd-exists wait).

  First download (nothing on disk yet) is always due when regions are selected, then weekly on Sunday / monthly on the
  1st, at most once per calendar day. Manual (0) never auto-updates once maps exist.
  """
  if sel.is_empty():
    return False
  if maps_downloaded and (schedule == SCHEDULE_NEVER or (schedule == SCHEDULE_WEEKLY and now.weekday() != 6) or
                          (schedule == SCHEDULE_MONTHLY and now.day != 1)):
    return False
  if maps_downloaded and last_update == date_label(now.date()):
    return False
  return True


@dataclass(frozen=True)
class Progress:
  active: bool
  done: bool
  total_files: int = 0
  downloaded_files: int = 0

  @property
  def percent(self) -> int:
    return 0 if self.total_files <= 0 else min(100, (self.downloaded_files * 100) // self.total_files)


def parse_progress(text) -> tuple[int, int]:
  try:
    d = json.loads(text) if text else {}
    return max(0, int(d.get("total_files", 0))), max(0, int(d.get("downloaded_files", 0)))
  except (ValueError, TypeError, AttributeError):
    return 0, 0


class DownloadController:
  """UI-facing controller over mapd's download params. All writes go through MemParams (fixed key set)."""

  def __init__(self, mem: MemParams, storage: OsmStorage):
    self.mem = mem
    self.storage = storage

  def can_start(self, sel: regions.Selection, online: bool, parked: bool, mapd_ready: bool) -> tuple[bool, str]:
    """0.9.7 enabled the DOWNLOAD button only when maps selected + online + parked; the extra checks are new."""
    if sel.is_empty():
      return False, "Select a region first"
    if not online:
      return False, "Offline..."
    if not parked:
      return False, "Not parked"
    if not mapd_ready:
      return False, "Map downloader not installed"
    est = regions.estimate(sel)
    if not self.storage.enough_space(est.est_bytes):
      return False, "Not enough storage"
    return True, ""

  def start(self, sel: regions.Selection) -> bool:
    if sel.is_empty():
      return False
    self.mem.remove("OSMDownloadProgress")
    return self.mem.put("OSMDownloadLocations", sel.to_param())

  def cancel(self) -> None:
    """0.9.7 cancel = drop the request + progress and kill mapd (the supervisor restarts it)."""
    self.mem.remove("OSMDownloadLocations")
    self.mem.remove("OSMDownloadProgress")

  def progress(self) -> Progress:
    locations = (self.mem.get_text("OSMDownloadLocations") or "").strip()
    prog = self.mem.get_text("OSMDownloadProgress")
    total, done = parse_progress(prog)
    if locations:
      return Progress(True, False, total, done)
    if prog:
      return Progress(False, True, total, done)
    return Progress(False, False)
