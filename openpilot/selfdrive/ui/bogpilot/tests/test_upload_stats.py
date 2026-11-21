"""Custom Log Upload Stats: toggle, status parsing for both known uploaders, staleness and fallback (no display needed)."""
import pytest

from openpilot.selfdrive.ui.bogpilot import upload_stats as US

NOW = 1_700_000_000


class _Params:
  def all_keys(self):
    return []


@pytest.fixture
def store(monkeypatch, tmp_path):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  from openpilot.common.bogpilot_store import ParamStore
  return ParamStore(params=_Params())


def _ui_import(name):
  """UI modules pull in the display stack; skip (not fail) where it cannot load, e.g. a headless container that looks like
  a device but has no device tree."""
  import importlib
  try:
    return importlib.import_module(name)
  except (ImportError, OSError) as e:
    pytest.skip(f"UI stack unavailable here: {type(e).__name__}")


def _reader(store, path, now=NOW):
  return US.UploadStatsReader(path=str(path), gate=US.ToggleGate(store=store, clock=lambda: 0.0),
                              clock=lambda: 0.0, wall=lambda: now)


# Lines in the exact shape each script's ratemon printf writes:
#   rsync      '%s %s %s %s %s' + ' $disp $pn $trend $scan'
#   Nextcloud  '%s %s %s %s %s' + ' $disp $n $trend $scan $psb $psn L=b,n V=b,n' (+ ' SAVED=1' for a last-known backlog)
RSYNC_RATE_ONLY = f"{NOW - 1} 1536 512 - wlan0"
RSYNC_FULL = f"{NOW - 1} 1536 512 1024 wlan0 2147483648 34 -16777216 {NOW - 20}"
NEXTCLOUD_FULL = f"{NOW - 1} 2048 - - wlan0 104857600 12 0 {NOW - 20} 0 0 L=104857600,12 V=0,0"
NEXTCLOUD_SAVED = f"{NOW - 1} 3 - - wlan0 104857600 12 - {NOW - 4000} 0 0 L=104857600,12 V=0,0 SAVED=1"


def test_toggle_default_off_and_registered_file_only(store):
  from openpilot.common.bogpilot_toggles import FILE_ONLY_UI_KEYS, FILE_TOGGLES
  from openpilot.common.bogpilot_shipping_defaults import FILE_TOGGLE_DEFAULTS
  assert FILE_TOGGLES[US.TOGGLE_KEY][0] is False
  assert FILE_TOGGLE_DEFAULTS[US.TOGGLE_KEY] is False
  assert US.TOGGLE_KEY in FILE_ONLY_UI_KEYS
  assert store.get_bool(US.TOGGLE_KEY) is False
  assert US.ToggleGate(store=store).get() is False


def test_off_never_opens_the_status_file(store, tmp_path, monkeypatch):
  status = tmp_path / "rate"
  status.write_text(RSYNC_FULL + "\n")
  opened = []
  monkeypatch.setattr(US, "read_status", lambda p=None: opened.append(p) or US.Sample())
  r = _reader(store, status)
  assert r.update() is None
  assert opened == []


def test_old_show_upload_rate_is_not_migrated(store, tmp_path):
  (tmp_path / "ShowUploadRate").write_text("1")
  assert US.ToggleGate(store=store).get() is False
  assert not (tmp_path / US.TOGGLE_KEY).exists()


def test_hidden_when_no_uploader(store, tmp_path):
  store.put_bool(US.TOGGLE_KEY, True)
  assert US.ToggleGate(store=store).get() is True
  assert _reader(store, tmp_path / "missing").update() is None      # nothing installed / not run since boot
  empty = tmp_path / "empty"
  empty.write_text("")
  assert _reader(store, empty).update() is None
  junk = tmp_path / "junk"
  junk.write_text("hello world\n")
  assert _reader(store, junk).update() is None


def test_parses_rsync_status(store, tmp_path):
  s = US.parse(RSYNC_FULL)
  assert s.valid and s.source == US.SOURCE_RSYNC
  assert (s.rate_kbs, s.workers, s.iface) == (1536.0, (512.0, 1024.0), "wlan0")
  assert (s.has_backlog, s.pending_bytes, s.pending_segments, s.trend_bpm) == (True, 2147483648, 34, -16777216.0)
  v = US.make_view(s, NOW)
  assert v.rate == "12.6 Mbps"
  assert v.workers == "w1 4.2 Mbps \u00b7 w2 8.4 Mbps"
  assert (v.backlog_size, v.backlog_segments) == ("2.0 GB", "34 segments left")
  assert v.backlog_note == "ETA 2 h 8 min"   # 2048 MiB at 16 MiB/min, the script's own trend
  assert US.eta_text(3000) == "ETA > 24 h"
  assert v.note_tone == US.TONE_GOOD
  # backlog off in the uploader (PENDING_SEC=0): the line stays 5 fields, rate only
  v = US.make_view(US.parse(RSYNC_RATE_ONLY), NOW)
  assert v.rate == "12.6 Mbps" and v.backlog_size is None and v.workers == "w1 4.2 Mbps \u00b7 w2 \u2013"
  # end to end through the reader with the toggle on
  store.put_bool(US.TOGGLE_KEY, True)
  f = tmp_path / "rate"
  f.write_text(RSYNC_FULL + "\n")
  assert _reader(store, f).update() == US.make_view(US.parse(RSYNC_FULL), NOW)


def test_parses_nextcloud_status(store, tmp_path):
  s = US.parse(NEXTCLOUD_FULL)
  assert s.valid and s.source == US.SOURCE_NEXTCLOUD
  assert s.workers == (None, None)
  assert s.tiers == {"rlogs": (104857600, 12), "video": (0, 0)}
  assert (s.pending_bytes, s.pending_segments, s.trend_bpm, s.saved) == (104857600, 12, 0.0, False)
  v = US.make_view(s, NOW)
  assert (v.rate, v.workers, v.backlog_size, v.backlog_segments, v.backlog_note) == \
         ("16.8 Mbps", None, "100 MB", "12 segments left", None)
  done = US.make_view(US.parse(f"{NOW} 0 - - wlan0 0 0 0 {NOW} 0 0 L=0,0 V=0,0"), NOW)
  assert done.caught_up and done.backlog_note == "all sent" and done.backlog_segments == "0 segments left"
  growing = US.make_view(US.parse(f"{NOW} 10 - - wlan0 5242880 1 2097152 {NOW} 0 0 L=5242880,1 V=0,0"), NOW)
  assert growing.backlog_note == "growing" and growing.note_tone == US.TONE_WARN
  assert growing.backlog_segments == "1 segment left"
  # SAVED=1 is a last-known backlog from an earlier scan: never shown, the live rate still is
  saved = US.parse(NEXTCLOUD_SAVED)
  assert saved.saved
  v = US.make_view(saved, NOW)
  assert v.rate == "0.0 Mbps" and v.backlog_size is None


def test_stale_hides(store, tmp_path):
  assert US.LINE_HIDE_S == 15.0 and US.BACKLOG_HIDE_S == 150.0
  assert US.make_view(US.parse(f"{NOW - 14} 100 - - wlan0"), NOW) is not None
  assert US.make_view(US.parse(f"{NOW - 16} 100 - - wlan0"), NOW) is None          # uploader stopped
  assert US.make_view(US.parse(f"{NOW + 60} 100 - - wlan0"), NOW) is None          # clock jumped
  old_scan = US.make_view(US.parse(f"{NOW} 100 - - wlan0 1000 2 - {NOW - 151}"), NOW)
  assert old_scan is not None and old_scan.backlog_size is None                    # stale backlog hidden, rate kept
  fresh_scan = US.make_view(US.parse(f"{NOW} 100 - - wlan0 1000 2 - {NOW - 149}"), NOW)
  assert fresh_scan.backlog_segments == "2 segments left" and fresh_scan.backlog_note is None
  store.put_bool(US.TOGGLE_KEY, True)
  f = tmp_path / "rate"
  f.write_text(f"{NOW - 30} 100 - - wlan0 1000 2 - {NOW - 30}\n")
  assert _reader(store, f).update() is None


def test_rejects_malformed_lines():
  for line in ("", "x", "0 10 - - wlan0", "-5 10 - - wlan0", f"{NOW} -1 - - wlan0", f"{NOW} nan - - wlan0",
               f"{NOW} 10 - -", b"\xff\xfe"):
    assert not US.parse(line).valid, line
  s = US.parse(f"{NOW} 10 x -3 wlan0 abc 2 - {NOW}")
  assert s.valid and s.workers == (None, None) and not s.has_backlog


def test_appearance_row_and_help():
  from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP
  from openpilot.selfdrive.ui.bogpilot.tuning_level import UI_ROW_LEVELS
  e = HELP[US.TOGGLE_KEY]
  assert e.default == "Off" and "rsync" in e.what and "Nextcloud" in e.what
  assert US.TOGGLE_KEY in UI_ROW_LEVELS
  bv = _ui_import("openpilot.selfdrive.ui.layouts.settings.bogpilot_visuals")
  assert US.TOGGLE_KEY in bv.APPEARANCE_KEYS
  assert any(k == US.TOGGLE_KEY for k, _ in bv.TREE)


def test_screens_draw_nothing_without_an_uploader(store, tmp_path):
  card_mod = _ui_import("openpilot.selfdrive.ui.widgets.bogpilot_upload_stats")
  paint_mod = _ui_import("openpilot.selfdrive.ui.onroad.bogpilot.upload_stats_paint")
  store.put_bool(US.TOGGLE_KEY, True)
  card = card_mod.UploadStatsCard(reader=_reader(store, tmp_path / "missing"))
  assert card.refresh() is False and card.height() == 0       # home keeps its default layout
  assert paint_mod.paint(None, None, False) is None           # onroad: nothing drawn
  f = tmp_path / "rate"
  f.write_text(NEXTCLOUD_FULL + "\n")
  card = card_mod.UploadStatsCard(reader=_reader(store, f))
  assert card.refresh() is True
  texts = [t for t, *_ in card_mod.card_lines(card.view)]
  assert texts == ["Uploading", "UPLOAD RATE", "16.8 Mbps \u2191", "PENDING", "100 MB", "12 segments left"]
  onroad = [t for t, *_ in paint_mod.lines(card.view)]
  assert onroad == ["UPLOAD", "16.8 Mbps \u2191", "PENDING 100 MB \u00b7 12 segments left"]
