"""Custom Log Upload Stats: on-screen upload rate and backlog for a manually installed log uploader.

BogPilot ships no uploader and starts none. This only reads the one-line status file that two manually installed
uploader scripts already write, and draws what they report:
  * the rsync uploader (rlogsync.sh, v3.2 and later): finished segments to a private server over ssh + rsync;
  * the Nextcloud uploader bundle (rlogsync.sh, Nextcloud edition): finished rlogs (optionally road video) to the
    user's own Nextcloud with rclone over WebDAV.

Both rewrite /dev/shm/bogpilot_rlogsync_rate every RATE_INTERVAL_SEC (2 s by default) with tmp + mv, so a reader never
sees half a line. /dev/shm is cleared on every boot, so the file only exists once an uploader has run since boot:

  <epoch> <total KB/s> <w1 KB/s|-> <w2 KB/s|-> <iface>
          [<pending bytes> <pending segments> <trend B/min|-> <scan epoch>
           [<extra bytes> <extra segments> L=<bytes>,<segments> V=<bytes>,<files> [SAVED=1]]]

Fields 0-8 are the shared contract (both scripts). The backlog fields (5-8) are written only while the uploader's
backlog scan is recent. The Nextcloud bundle appends fields 9 and up: L= / V= split the backlog into rlogs and road
video, and SAVED=1 marks a last-known backlog read back from an earlier scan (its scanner is not running), which is not
live and is never shown.
  total   bytes/s leaving the default-route interface (everything the device sends), in KiB/s
  wN      one rsync worker's payload rate in KiB/s; "-" when that worker is idle (the Nextcloud bundle always writes "-")
  trend   change of the backlog in bytes per minute over the uploader's trend window; "-" until it has a window

Stale data is hidden, never shown with an old value:
  * LINE_HIDE_S (15 s, about 7 missed 2 s writes): an older status line (uploader stopped or uninstalled) hides the
    whole display, which falls back to the default UI.
  * BACKLOG_HIDE_S (150 s, five missed 30 s backlog scans, the same rule the scripts use): an older backlog scan, or a
    SAVED backlog, hides the pending part and keeps the rate.

Gate: the Custom Log Upload Stats toggle (file-backed, /data/params_bogpilot/CustomLogUploadStats, default OFF). While it
is off the status file is never opened. This module has no pyray import, so it is testable without a display.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

TOGGLE_KEY = "CustomLogUploadStats"
STATUS_PATH = os.getenv("BOGPILOT_UPLOAD_STATS_PATH") or "/dev/shm/bogpilot_rlogsync_rate"
LINE_HIDE_S = 15.0
BACKLOG_HIDE_S = 150.0
READ_INTERVAL_S = 1.0
TOGGLE_TTL_S = 2.0
MAX_LINE_BYTES = 512
# The scripts' own "flat" band for the trend (0.5 MiB per minute): inside it the backlog is neither growing nor draining.
TREND_FLAT_BPM = 524288.0

SOURCE_RSYNC = "rsync"
SOURCE_NEXTCLOUD = "nextcloud"


def _int(s: str) -> int | None:
  try:
    return int(s)
  except ValueError:
    return None


def _num(s: str) -> float | None:
  try:
    v = float(s)
  except ValueError:
    return None
  return v if v == v and v not in (float("inf"), float("-inf")) else None


@dataclass
class Sample:
  valid: bool = False
  epoch: int = 0
  rate_kbs: float = 0.0
  workers: tuple[float | None, float | None] = (None, None)
  iface: str = ""
  has_backlog: bool = False
  pending_bytes: int = 0
  pending_segments: int = 0
  trend_bpm: float | None = None
  scan_epoch: int = 0
  saved: bool = False
  source: str = SOURCE_RSYNC
  tiers: dict[str, tuple[int, int]] = field(default_factory=dict)


def parse(line: str | bytes | None) -> Sample:
  """One status line -> Sample. Anything that does not match the contract is invalid (valid=False), never guessed."""
  s = Sample()
  if line is None:
    return s
  if isinstance(line, bytes):
    line = line.decode("utf-8", "replace")
  f = line.split()
  if len(f) < 5:
    return s
  epoch, rate = _int(f[0]), _num(f[1])
  if epoch is None or rate is None or epoch <= 0 or rate < 0:
    return s
  s.epoch, s.rate_kbs, s.iface = epoch, rate, f[4]
  w = []
  for t in f[2:4]:
    v = None if t == "-" else _num(t)
    w.append(v if v is not None and v >= 0 else None)
  s.workers = (w[0], w[1])
  for t in f[9:]:
    if t == "SAVED=1":
      s.saved = True
    elif t[:2] in ("L=", "V=") and "," in t:
      b, _, n = t[2:].partition(",")
      bi, ni = _int(b), _int(n)
      if bi is not None and ni is not None and bi >= 0 and ni >= 0:
        s.tiers["rlogs" if t[0] == "L" else "video"] = (bi, ni)
      s.source = SOURCE_NEXTCLOUD
  if len(f) >= 9:
    b, n, scan = _int(f[5]), _int(f[6]), _int(f[8])
    if b is not None and n is not None and scan is not None and b >= 0 and n >= 0 and scan > 0:
      s.has_backlog, s.pending_bytes, s.pending_segments, s.scan_epoch = True, b, n, scan
      s.trend_bpm = None if f[7] == "-" else _num(f[7])
  s.valid = True
  return s


def read_status(path: str | None = None) -> Sample:
  try:
    with open(path or STATUS_PATH, "rb") as fh:
      return parse(fh.readline(MAX_LINE_BYTES))
  except OSError:
    return Sample()


def line_fresh(s: Sample, now: float) -> bool:
  return s.valid and abs(now - s.epoch) <= LINE_HIDE_S


def backlog_fresh(s: Sample, now: float) -> bool:
  return s.has_backlog and not s.saved and abs(now - s.scan_epoch) <= BACKLOG_HIDE_S


# ---- text (only what the uploader reported; nothing estimated beyond its own trend) ----
def _round(v: float) -> int:
  return int(v + 0.5) if v >= 0 else -int(-v + 0.5)


def mbps_text(kbs: float) -> str:
  v = kbs * 1024.0 * 8.0 / 1e6
  return (f"{v:.1f}" if v < 99.95 else str(_round(v))) + " Mbps"


def size_text(n_bytes: int) -> str:
  mb = n_bytes / 1048576.0
  if mb < 10:
    return f"{mb:.1f} MB"
  if mb < 1024:
    return f"{_round(mb)} MB"
  gb = mb / 1024.0
  return (f"{gb:.1f}" if gb < 10 else str(_round(gb))) + " GB"


def segments_text(n: int) -> str:
  return f"{n} segment left" if n == 1 else f"{n} segments left"


def eta_text(minutes: float) -> str:
  if minutes < 1:
    return "ETA < 1 min"
  m = _round(minutes)
  if m >= 24 * 60:
    return "ETA > 24 h"
  return f"ETA {m} min" if m < 60 else f"ETA {m // 60} h {m % 60} min"


TONE_DIM, TONE_GOOD, TONE_WARN = "dim", "good", "warn"


@dataclass(frozen=True)
class View:
  """What to draw. backlog_* are None when the backlog is missing or stale."""
  rate: str
  workers: str | None
  backlog_size: str | None
  backlog_segments: str | None
  backlog_note: str | None
  note_tone: str
  caught_up: bool


def make_view(s: Sample, now: float) -> View | None:
  """None = draw nothing (default UI). The rate needs a fresh line; the backlog also needs a fresh, live scan."""
  if not line_fresh(s, now):
    return None
  w1, w2 = s.workers
  workers = None
  if w1 is not None or w2 is not None:
    workers = " \u00b7 ".join(f"w{i} {mbps_text(v) if v is not None else chr(0x2013)}" for i, v in ((1, w1), (2, w2)))
  if not backlog_fresh(s, now):
    return View(mbps_text(s.rate_kbs), workers, None, None, None, TONE_DIM, False)
  if s.pending_bytes == 0 and s.pending_segments == 0:
    return View(mbps_text(s.rate_kbs), workers, "0 MB", segments_text(0), "all sent", TONE_GOOD, True)
  note, tone = None, TONE_DIM
  t = s.trend_bpm
  if t is not None and t < -TREND_FLAT_BPM:
    note, tone = eta_text(s.pending_bytes / -t), TONE_GOOD
  elif t is not None and t > TREND_FLAT_BPM:
    note, tone = "growing", TONE_WARN
  return View(mbps_text(s.rate_kbs), workers, size_text(s.pending_bytes), segments_text(s.pending_segments), note, tone, False)


class ToggleGate:
  """Cached read of the Custom Log Upload Stats toggle (display only, never writes). A read failure means off."""

  def __init__(self, store=None, clock=time.monotonic, ttl: float = TOGGLE_TTL_S):
    self._store, self.clock, self.ttl = store, clock, ttl
    self._next = -1.0
    self._value = False

  def get(self) -> bool:
    now = self.clock()
    if now >= self._next:
      self._next = now + self.ttl
      try:
        if self._store is None:
          from openpilot.common.bogpilot_store import ParamStore
          self._store = ParamStore()
        self._store.invalidate(TOGGLE_KEY)
        self._value = bool(self._store.get_bool(TOGGLE_KEY))
      except Exception:
        self._value = False
    return self._value


class UploadStatsReader:
  """Polls the status file at most once per READ_INTERVAL_S, and only while the toggle is on."""

  def __init__(self, path: str | None = None, gate=None, clock=time.monotonic, wall=time.time):
    self._path = path
    self._gate = gate if gate is not None else ToggleGate(clock=clock)
    self._clock, self._wall = clock, wall
    self._next = -1.0
    self.sample = Sample()

  @property
  def enabled(self) -> bool:
    return self._gate.get()

  def update(self) -> View | None:
    if not self._gate.get():
      self.sample = Sample()
      self._next = -1.0
      return None
    now = self._clock()
    if now >= self._next:
      self._next = now + READ_INTERVAL_S
      self.sample = read_status(self._path)
    return make_view(self.sample, self._wall())
