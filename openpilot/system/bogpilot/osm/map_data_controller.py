"""Map Data page logic (slice 3): everything the page does, with no raylib in it, so it is tested without a window.

Port of the 0.9.7 `FrogPilotMapsPanel` (maps_settings.cc) onto the slice-1 store / process:

  Map Sources      -> `MapsSelected` JSON ({"nations": [...], "states": [...]}, the same Params key mapd reads)
  Automatically Update Maps -> `PreferredSchedule` (0 Manually, 1 Weekly, 2 Monthly; default 1 Weekly), read by `scheduler.py`
  Download / Cancel -> mapd's `OSMDownloadLocations` / `OSMDownloadProgress` (downloads.DownloadController)
  Remove Maps      -> storage.remove_maps();  Repair Map Downloads (was Reset Downloader) -> kill mapd, delete /data/media/0/osm, reboot (0.9.7)
  Storage Used     -> size of /data/media/0/osm/offline;  Last Updated -> `LastMapsUpdate`

Nothing here runs on import. Every side effect goes through an injected callable (spawn, kill_mapd, reboot, fetch, clocks), so
the tests never start a thread, kill a process, reboot or touch the network.
"""
from __future__ import annotations

import datetime
import subprocess
import threading
import time
from dataclasses import dataclass

from openpilot.system.bogpilot.osm import installer, regions
from openpilot.system.bogpilot.osm.downloads import SCHEDULE_LABELS, SCHEDULE_WEEKLY, DownloadController, date_label
from openpilot.system.bogpilot.osm.memparams import MemParams
from openpilot.system.bogpilot.osm.storage import OsmStorage

ADOPTION_MARKER = "Phase3MapDataEnabled"     # the same file marker supervisor.py reads (written only by the user's own Map Data action)
SELECTION_KEY = "MapsSelected"
SCHEDULE_KEY = "PreferredSchedule"
LAST_UPDATE_KEY = "LastMapsUpdate"
CANCEL_SETTLE_S = 2.5          # 0.9.7 cancelDownload(): QTimer::singleShot(2500)
RESET_STEP_S = 2.5             # 0.9.7 reset: 2.5 s "Repaired!" then 2.5 s "Rebooting..." before Hardware::reboot()
WAITING_FOR_DOWNLOADER_S = 45  # active request with no progress after this long: say so instead of "Calculating..." forever
HEARTBEAT_KEY = "BogPilotMapdHeartbeat"   # refreshed every 2 s by the bogpilot_mapd supervisor (supervisor.HEARTBEAT_S)
HEARTBEAT_STALE_S = 30.0       # older (or missing) = the supervisor is not running; a synchronous binary install can take a while
WAITING_FOR_DOWNLOADER_TEXT = "Waiting for the map downloader..."  # no heartbeat: the supervisor is not running
SIZE_TTL_S = 1.0               # cache of the cheap "does the offline folder exist" stat
KIND_KEYS = ("nations", "states")
SLC_KEY = "SpeedLimitController"
SLC_OFF_TEXT = "Turn on Speed Limit Controller to download maps"     # the full sentence: the notice banner and the schedule help
SLC_OFF_SHORT = "Speed Limit Controller is off"                       # the Download row value (it must fit beside the DOWNLOAD button)
SLC_PAUSED_TEXT = "Paused: Speed Limit Controller is off"          # progress row for a request left over from before it was turned off
DEFAULT_SCHEDULE = SCHEDULE_WEEKLY                                   # Weekly (matches the AP1 profile); a saved choice always wins

# Map downloads may start and keep running while driving (pick a state at a charger, the download continues on
# the road). Only Remove / Repair still need the car off or in Park. Other BogPilot downloads keep the Park rule.
DOWNLOAD_NEEDS_PARK = False
NO_SPACE_TEXT = "Stopped: not enough storage"

NEVER_TEXT = "Never"           # 0.9.7 shows "Never" until LastMapsUpdate is written
CALCULATING = "Calculating..."
NOT_PARKED = "Not parked"
OFFLINE = "Offline..."


# ------------------------------------------------------------------------------------------------------------ formatting
def format_elapsed(elapsed_ms: float) -> str:
  """Exact port of 0.9.7 formatElapsedTime(): '1 hour 2 minutes 5 seconds' (zero hours/minutes are left out)."""
  total = int(max(0.0, elapsed_ms) / 1000)
  hours, minutes, seconds = total // 3600, (total % 3600) // 60, total % 60
  out = ""
  if hours > 0:
    out += f"{hours}" + (" hour " if hours == 1 else " hours ")
  if minutes > 0:
    out += f"{minutes}" + (" minute " if minutes == 1 else " minutes ")
  out += f"{seconds}" + (" second" if seconds == 1 else " seconds")
  return out.strip()


def clock_text(dt: datetime.datetime) -> str:
  """Qt 'h:mm AP' ('3:07 PM')."""
  hour = dt.hour % 12 or 12
  return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


class EtaEstimator:
  """0.9.7 formatETA(): finish = start + elapsed * total / downloaded, refreshed whenever a file completes.

  Deviation: 0.9.7 also moved the finish time earlier by every elapsed tick between completions, so the remaining time ran
  down about twice as fast as the clock; here the finish time only moves when a file completes.
  """

  def __init__(self, start: datetime.datetime):
    self.start = start
    self.finish: datetime.datetime | None = None
    self._last_downloaded: int | None = None

  def update(self, elapsed_ms: float, downloaded: int, total: int, now: datetime.datetime) -> str:
    if downloaded <= 0 or total <= 0:
      return CALCULATING
    if self.finish is None or downloaded != self._last_downloaded:
      self.finish = self.start + datetime.timedelta(milliseconds=elapsed_ms * total / downloaded)
      self._last_downloaded = downloaded
    remaining = max(0.0, (self.finish - now).total_seconds())
    return f"{format_elapsed(remaining * 1000)} ({clock_text(self.finish)})"


# ------------------------------------------------------------------------------------------------------------ helpers
def downloads_allowed(store) -> bool:
  """Map downloads exist only while the Speed Limit Controller is on: the `bogpilot_mapd` process (which does the downloading and
  is the only producer of the map speed limit) runs only then. Under the older adoption policy the SLC is not the gate.
  Any read problem -> False (fail closed)."""
  from openpilot.system.bogpilot.osm import supervisor
  if supervisor.ACTIVATION_POLICY != "default_on":
    return True
  try:
    return bool(store.get_bool(SLC_KEY))
  except Exception:
    return False


def finish_download(store, mem: MemParams, today: datetime.date) -> None:
  """A download ended: stamp Last Updated (0.9.7 `LastMapsUpdate`) and drop the progress. Idempotent."""
  store.put(LAST_UPDATE_KEY, date_label(today))
  mem.remove("OSMDownloadProgress")


def default_kill_mapd() -> None:
  """0.9.7 `pkill mapd`: stops the downloader process (the supervisor restarts it). Exact name match, so
  the python `bogpilot_mapd` supervisor is never signalled."""
  try:
    subprocess.run(["pkill", "-x", "mapd"], check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  except (OSError, subprocess.SubprocessError):
    pass


def default_reboot() -> None:
  from openpilot.common.hardware import HARDWARE
  HARDWARE.reboot()


def default_spawn(fn) -> None:
  threading.Thread(target=fn, daemon=True).start()


@dataclass(frozen=True)
class View:
  """Everything the page draws for one frame."""
  download_text: str           # DOWNLOAD | CANCEL
  download_enabled: bool
  download_value: str          # '' | 'Not parked' | 'Offline...' | ...
  downloading: bool
  show_last_updated: bool
  last_updated: str
  show_remove: bool
  remove_enabled: bool
  show_reset: bool
  reset_enabled: bool
  reset_value: str
  progress: str
  elapsed: str
  eta: str
  storage: str
  schedule: int
  slc_on: bool = True          # False: Download and the schedule are disabled (the page says why)


class MapDataController:
  def __init__(self, store, *, mem: MemParams | None = None, storage: OsmStorage | None = None, manifest: dict | None = None,
               fetch=None, kill_mapd=None, reboot=None, spawn=None, sleep=time.sleep, monotonic=time.monotonic,
               now=datetime.datetime.now, keep_awake=None, wall=time.time):
    self.store = store
    self.mem = mem or MemParams()
    self.storage = storage or OsmStorage()
    self._manifest = manifest
    self._fetch = fetch or installer.urllib_fetch
    self._kill_mapd = kill_mapd or default_kill_mapd
    self._reboot = reboot or default_reboot
    self._spawn = spawn or default_spawn
    self._sleep = sleep
    self._mono = monotonic
    self._now = now
    self._keep_awake = keep_awake or (lambda on: None)
    self.dl = DownloadController(self.mem, self.storage)
    self.phase = "idle"          # idle | installing | cancelling | removing | resetting
    self._message = ("", 0.0)    # (text, expires): a failure shown as the Download row value for a few seconds
    self.reset_text = ""
    self._cancel_until = 0.0
    self._dl_start_mono: float | None = None
    self._eta: EtaEstimator | None = None
    self._prev_downloaded = -1
    self._size_text = "0 MB"
    self._maps_exist = False
    self._maps_checked = -1e9
    self._ready_checked = -1e9
    self._ready = False
    self._slc_checked = -1e9
    self._slc = True
    self._wall = wall
    self._alive_checked = -1e9
    self._alive = False
    self.refresh_storage()

  # ---------------------------------------------------------------------------------------------------- selection
  def selection(self) -> regions.Selection:
    return regions.parse_selection(self.store.get(SELECTION_KEY, ""))

  def has_selection(self) -> bool:
    return not self.selection().is_empty()

  def is_selected(self, kind: str, code: str) -> bool:
    return code in getattr(self.selection(), kind)

  def set_region(self, kind: str, code: str, on: bool) -> bool:
    """Select / deselect one country ('nations') or U.S. state ('states'), as 0.9.7 MapSelectionControl did.
    Returns True when the saved selection now matches the request."""
    if kind not in KIND_KEYS:
      return False
    cat = regions.catalog()["nation" if kind == "nations" else "state"]
    if code not in cat:
      return False
    sel = self.selection()
    cur = list(getattr(sel, kind))
    if on and code not in cur:
      if len(sel.nations) + len(sel.states) >= regions.MAX_SELECTED_REGIONS:
        self._say("Too many regions selected")
        return False
      cur.append(code)
    elif not on and code in cur:
      cur.remove(code)
    new = regions.Selection(**{**{"nations": sel.nations, "states": sel.states}, kind: tuple(cur)})
    if new == sel:
      return True
    self.store.put(SELECTION_KEY, new.to_param())
    if on:
      self._mark_adopted()
    return True

  def _mark_adopted(self) -> None:
    """The user's own Map Data action: lets the gated `bogpilot_mapd` process exist (marker is a file, never a Params key)."""
    try:
      if not self.store.get_bool(ADOPTION_MARKER, False):
        self.store.put_bool(ADOPTION_MARKER, True)
    except Exception:
      pass

  # ---------------------------------------------------------------------------------------------------- schedule
  def schedule(self) -> int:
    try:
      v = self.store.get_int(SCHEDULE_KEY, DEFAULT_SCHEDULE)
    except (TypeError, ValueError):
      v = DEFAULT_SCHEDULE
    return max(0, min(len(SCHEDULE_LABELS) - 1, v))

  def set_schedule(self, index: int) -> bool:
    if not 0 <= int(index) < len(SCHEDULE_LABELS):
      return False
    self.store.put(SCHEDULE_KEY, int(index))
    return True

  def last_updated(self) -> str:
    return self.store.get(LAST_UPDATE_KEY, "") or NEVER_TEXT

  # ---------------------------------------------------------------------------------------------------- storage
  def refresh_storage(self, block: bool = False) -> None:
    def work():
      self._size_text = self.storage.size_text()
    if block:
      work()
    else:
      self._spawn(work)

  def _maps_dir_exists(self) -> bool:
    t = self._mono()
    if t - self._maps_checked >= SIZE_TTL_S:
      self._maps_exist = self.storage.offline_dir.exists()
      self._maps_checked = t
    return self._maps_exist

  MESSAGE_S = 8.0

  def _say(self, text: str) -> None:
    self._message = (text, self._mono() + self.MESSAGE_S)

  @property
  def message(self) -> str:
    text, until = self._message
    return text if text and self._mono() < until else ""

  def slc_on(self) -> bool:
    """Downloads are possible (Speed Limit Controller on). Re-read at most once a second."""
    t = self._mono()
    if t - self._slc_checked >= SIZE_TTL_S:
      self._slc = downloads_allowed(self.store)
      self._slc_checked = t
    return self._slc

  def _engine_manifest(self) -> dict:
    """The injected manifest (tests), else the pinned manifest of the engine the MapdV2 toggle selects (v1 by default)."""
    if self._manifest is not None:
      return self._manifest
    from openpilot.system.bogpilot.osm import mapd_v2
    return installer.load_engine_manifest(mapd_v2.engine_v2(self.store))

  def mapd_ready(self) -> bool:
    t = self._mono()
    if t - self._ready_checked >= SIZE_TTL_S:
      try:
        self._ready = installer.verify_installed(self.storage, self._engine_manifest(), cached=True)
      except Exception:
        self._ready = False
      self._ready_checked = t
    return self._ready

  def downloader_alive(self) -> bool:
    """The bogpilot_mapd supervisor refreshed its heartbeat recently. Re-read at most once a second."""
    t = self._mono()
    if t - self._alive_checked >= SIZE_TTL_S:
      age = self.mem.age_s(HEARTBEAT_KEY, now=self._wall())
      self._alive = age is not None and age <= HEARTBEAT_STALE_S
      self._alive_checked = t
    return self._alive

  # ---------------------------------------------------------------------------------------------------- downloads
  def downloading(self) -> bool:
    p = self.dl.progress()
    return p.active

  def can_download(self, online: bool, parked: bool) -> tuple[bool, str]:
    """0.9.7: enabled when a map is selected, the device is online and parked. The text is the Download row's value."""
    if not self.slc_on():
      return False, SLC_OFF_TEXT
    sel = self.selection()
    if sel.is_empty():
      return False, "Select a region first"
    if not online:
      return False, OFFLINE
    if DOWNLOAD_NEEDS_PARK and not parked:
      return False, NOT_PARKED
    if not self.storage.enough_space(regions.estimate(sel).est_bytes):
      return False, "Not enough storage"
    return True, ""

  def start_download(self, online: bool, parked: bool) -> bool:
    """DOWNLOAD pressed. Installs the pinned mapd first when it is missing (hash-verified), then asks mapd for the selection."""
    if self.phase != "idle" or self.downloading():
      return False
    ok, _why = self.can_download(online, parked)
    if not ok:
      return False
    self._message = ("", 0.0)
    sel = self.selection()
    self._mark_adopted()
    if self.mapd_ready():
      if not self.dl.start(sel):
        self._say("Could not start the download")
        return False
      self._begin_tracking()
      return True
    self.phase = "installing"
    self._begin_tracking()
    self._spawn(lambda: self._install_then_start(sel))
    return True

  def _install_then_start(self, sel: regions.Selection) -> None:
    try:
      manifest = self._engine_manifest()
      installer.install(self.storage, manifest, self._fetch)
      self._ready_checked = -1e9
    except Exception:
      self._say("Downloader install failed")
      self.phase = "idle"
      self._reset_tracking()
      return
    self.phase = "idle"
    if not self.dl.start(sel):
      self._say("Could not start the download")
      self._reset_tracking()

  def cancel_download(self) -> None:
    """CANCEL (after the page's confirmation): drop the request and progress, stop mapd, settle 2.5 s (0.9.7)."""
    self.dl.cancel()
    self._kill_mapd()
    self.phase = "cancelling"
    self._cancel_until = self._mono() + CANCEL_SETTLE_S
    self._reset_tracking()

  def _begin_tracking(self) -> None:
    self._dl_start_mono = self._mono()
    self._eta = EtaEstimator(self._now())
    self._prev_downloaded = -1

  def _reset_tracking(self) -> None:
    self._dl_start_mono = None
    self._eta = None
    self._prev_downloaded = -1

  # ---------------------------------------------------------------------------------------------------- remove / reset
  def remove_maps(self) -> bool:
    """REMOVE (after the page's confirmation): delete the downloaded tiles, keep the pinned mapd binary."""
    if self.phase != "idle" or self.downloading():
      return False
    self.phase = "removing"
    self._size_text = "0 MB"

    def work():
      try:
        self.dl.jobs.clear()                  # a download that stopped at the storage floor is dropped with the maps
        self.storage.remove_maps()
      finally:
        self._maps_checked = -1e9
        self.phase = "idle"
        self.refresh_storage(block=True)
    self._spawn(work)
    return True

  def reset_downloader(self) -> bool:
    """RESET (after the page's confirmation): 0.9.7 killed mapd, deleted /data/media/0/osm and rebooted the device."""
    if self.phase != "idle" or self.downloading():
      return False
    self.phase = "resetting"
    self.reset_text = "Repairing..."
    self._spawn(self._reset_worker)
    return True

  def _reset_worker(self) -> None:
    self._keep_awake(True)
    try:
      self.dl.cancel()
      self._kill_mapd()
      ok = self.storage.reset()
      self._maps_checked = -1e9
      self._ready_checked = -1e9
      if not ok:
        self.reset_text = "Repair failed"
        return
      self.reset_text = "Repaired!"
      self._sleep(RESET_STEP_S)
      self.reset_text = "Rebooting..."
      self._sleep(RESET_STEP_S)
      self._reboot()
      self.reset_text = "Reboot unavailable"      # only reached when the reboot call returns (a real reboot ends this process)
    except Exception:
      self.reset_text = "Repair failed"
    finally:
      self.phase = "idle"
      self._keep_awake(False)
      self.refresh_storage(block=True)

  # ---------------------------------------------------------------------------------------------------- per-frame
  def update(self) -> None:
    """Called once per rendered frame: finish a cancel, notice a finished download, keep the size current."""
    now = self._mono()
    if self.phase == "cancelling" and now >= self._cancel_until:
      self.mem.remove("OSMDownloadProgress")     # a dying mapd can write one last progress file after the cancel
      self.phase = "idle"
    p = self.dl.progress()
    if p.done and self.phase in ("idle", "installing"):
      finish_download(self.store, self.mem, self._now().date())
      self._reset_tracking()
      self._maps_checked = -1e9
      self.refresh_storage()
      return
    if p.active:
      if self._dl_start_mono is None:       # a download somebody else started (the schedule): still show it
        self._begin_tracking()
      if p.downloaded_files != self._prev_downloaded:
        self._prev_downloaded = p.downloaded_files
        self.refresh_storage()

  def view(self, online: bool, parked: bool) -> View:
    p = self.dl.progress()
    cancelling = self.phase == "cancelling"
    progress = elapsed = eta = ""
    if p.active or cancelling:
      progress = elapsed = eta = CALCULATING
    if p.active and not cancelling:
      start = self._dl_start_mono if self._dl_start_mono is not None else self._mono()
      elapsed_ms = (self._mono() - start) * 1000.0
      elapsed = format_elapsed(elapsed_ms)
      if p.total_files > 0:
        progress = f"{p.downloaded_files} / {p.total_files} ({p.percent}%)"
        eta = self._eta.update(elapsed_ms, p.downloaded_files, p.total_files, self._now()) if self._eta else CALCULATING
      elif not self.slc_on():
        progress = SLC_PAUSED_TEXT
      elif elapsed_ms / 1000.0 > WAITING_FOR_DOWNLOADER_S:
        # alive: mapd v1 reports nothing until its first 2x2 degree cell (up to ~55 MB) is in, so keep "Calculating..."
        progress = CALCULATING if self.downloader_alive() else WAITING_FOR_DOWNLOADER_TEXT
    if p.active or cancelling:
      button, enabled, value = "CANCEL", p.active and not cancelling, ""
    else:
      ok, why = self.can_download(online, parked)
      button = "DOWNLOAD"
      enabled = ok and self.phase == "idle"
      if self.phase == "installing":
        value = "Installing downloader..."
      elif not self.slc_on():
        value = SLC_OFF_SHORT
      elif p.stopped == "no_space" and not self.message:
        value = NO_SPACE_TEXT
      else:
        value = self.message or why
    show_main = not (p.active or cancelling or self.phase == "installing")
    # Remove / Reset need the maps folder and a parked, idle device; 0.9.7 hid them while a download ran
    can_touch = parked and self.phase == "idle"
    return View(
      download_text=button, download_enabled=bool(enabled), download_value=value, downloading=p.active or cancelling,
      show_last_updated=show_main, last_updated=self.last_updated(),
      show_remove=show_main and self._maps_dir_exists(), remove_enabled=can_touch,
      show_reset=show_main, reset_enabled=can_touch, reset_value=self.reset_text if (self.phase == "resetting" or self.reset_text in ("Repair failed", "Reboot unavailable")) else "",
      progress=progress, elapsed=elapsed, eta=eta, storage=self._size_text, schedule=self.schedule(), slc_on=self.slc_on())
