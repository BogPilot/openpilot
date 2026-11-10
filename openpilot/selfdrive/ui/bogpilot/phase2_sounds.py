"""Phase 2 / t994 soundsUI: Alert Volume Controller (BogPilot > Alerts and Sounds).

Source: bogpilot-tesla 0.9.7 @ 04d560f3 frogpilot/ui/qt/offroad/sounds_settings.cc:44-80.
Lane base: feae0292 (prior model @ 3d0bfa9b / c6582fc3). t996: ASCII '-' + Mute toggle.

Every offered key is read by selfdrive/ui/soundd.py via _bogpilot_read_param and applied per
AudibleAlert by alert_volumes.resolve_alert_gain in soundd_thread.

File-store vs Params precedence (do not change without INT + soundd review)
---------------------------------------------------------------------------
1. UI writes ONLY through openpilot.common.bogpilot_store.write_text ->
   /data/params_bogpilot/<key> (or $BOGPILOT_PARAMS_DIR/<key> in tests).
2. soundd._bogpilot_read_param reads the FILE STORE FIRST, then falls back to
   compiled Params.get(key). Volume keys are NOT compiled Params keys on this tip,
   so the file is the effective consumer source.
3. Reads never write. Saved on-disk values are preserved (out-of-range shown
   clamped in the UI but not rewritten until the user moves a control).
4. Defaults come from FROGPILOT_VOLUME_DEFAULTS (controller OFF, volumes 101=Auto).
5. Mute restore uses companion file <key>PreMute in the same file store so a restart
   can unmute back to the prior level.

Font atlas note (t996): Inter is loaded with ASCII 32-126 plus EXTRA_FONT_CHARS.
U+2212 MINUS SIGN is NOT in the atlas (renders as '?'). This panel uses ASCII '-' (U+002D).

Not owned here: BogPilot Alerts rows (alertsAudio lane), GoatScream (skipped),
test-play buttons (0.9.7 ffplay; unverified), settings.py / bogpilot.py registration (INT),
soundd.py live-reload (see PROPOSED_shared.patch). U+2014 on drive stats = driveStats lane.
"""
from __future__ import annotations

import time

HISTORICAL_REVISION = "04d560f3ece97797b8f1ee2f714e682e6d0ef40e"
AUDITED_BASE = "c6582fc3efc1038b4e0e6bca8a6841b657e8ccf6"
LANE_BASE = "feae029245e281e37667457a74387671458d716f"
BACKEND_COMMIT = "3d0bfa9b3b01c37d04e19cc36b2f05e29b891bfe"

PARENT_KEY = "AlertVolumeControl"
AUTO = 101
IDLE_REFRESH_S = 1.0
# ASCII hyphen-minus - Inter atlas has U+002D; U+2212 MINUS SIGN is missing (shows as '?').
MINUS_GLYPH = "-"  # U+002D
PLUS_GLYPH = "+"
PREMUTE_SUFFIX = "PreMute"

VOLUME_ROWS: tuple[tuple[str, str, int, int], ...] = (
  ("DisengageVolume", "Disengage Volume", 0, AUTO),
  ("EngageVolume", "Engage Volume", 0, AUTO),
  ("PromptVolume", "Prompt Volume", 25, AUTO),
  ("PromptDistractedVolume", "Prompt Distracted Volume", 25, AUTO),
  ("RefuseVolume", "Refuse Volume", 0, AUTO),
  ("WarningSoftVolume", "Warning Soft Volume", 25, AUTO),
  ("WarningImmediateVolume", "Warning Immediate Volume", 25, AUTO),
)
VOLUME_KEYS = tuple(r[0] for r in VOLUME_ROWS)
WARNING_FLOOR_KEYS = ("PromptVolume", "PromptDistractedVolume", "WarningSoftVolume", "WarningImmediateVolume")  # safety alert categories
WARNING_FLOOR = 25
OMITTED = (
  ("CustomAlerts/GreenLightAlert/LeadDepartingAlert/LoudBlindspotAlert/SpeedLimitChangedAlert", "alertsAudio lane"),
  ("GoatScream", "owner: skip"),
  ("per-row test-play button", "0.9.7 ffplay path; no verified raylib/device audio path"),
)

FILE_STORE_PRECEDENCE = (
  "UI write_text -> /data/params_bogpilot/<key>; "
  "soundd._bogpilot_read_param reads file first, then Params; "
  "volume keys are not compiled Params keys, so file is the live source; "
  "mute restore uses <key>PreMute in the same file store."
)


def _sd():
  from openpilot.selfdrive.ui import soundd
  return soundd


def label(value: int) -> str:
  return "Muted" if value == 0 else "Auto" if value == AUTO else f"{value}%"


def row_bounds(key: str) -> tuple[int, int]:
  return next((r[2], r[3]) for r in VOLUME_ROWS if r[0] == key)


def premute_key(key: str) -> str:
  return f"{key}{PREMUTE_SUFFIX}"


def read_controller() -> bool:
  sd = _sd()
  return sd._bogpilot_bool(sd._bogpilot_read_param(PARENT_KEY),
                           sd._bogpilot_bool(sd.FROGPILOT_VOLUME_DEFAULTS.get(PARENT_KEY), False))


def raw_volume(key: str) -> int:
  """Exactly the integer soundd loads (stored, else default 101; non-numeric -> default)."""
  sd = _sd()
  return sd._bogpilot_int(sd._bogpilot_read_param(key), int(float(sd.FROGPILOT_VOLUME_DEFAULTS.get(key, "101"))))


def read_volume(key: str) -> int:
  """UI value: soundd's value clamped to the 0.9.7 range. Out-of-range stored values are
  displayed clamped but NOT rewritten (saved prefs preserved)."""
  return clamp(key, raw_volume(key))


def raw_out_of_range(key: str) -> bool:
  return raw_volume(key) != read_volume(key)


def clamp(key: str, value: int) -> int:
  lo, hi = row_bounds(key)
  return max(lo, min(hi, int(value)))


def clamp_range(lo: int, hi: int, value: int) -> int:
  return max(lo, min(hi, int(value)))


def slider_fraction(value: int, lo: int, hi: int) -> float:
  if hi <= lo:
    return 0.0
  return max(0.0, min(1.0, (int(value) - lo) / float(hi - lo)))


def slider_value_from_x(x: float, track_x: float, track_w: float, lo: int, hi: int) -> int:
  if track_w <= 0:
    return lo
  t = max(0.0, min(1.0, (float(x) - float(track_x)) / float(track_w)))
  return clamp_range(lo, hi, int(round(lo + t * (hi - lo))))


def mute_button_title(key: str) -> str:
  """Warning/critical rows cannot go silent; button says Min to show the floor clearly."""
  return "Min" if key in WARNING_FLOOR_KEYS else "Mute"


def _write(key: str, text: str) -> None:
  from openpilot.common.bogpilot_store import write_text
  if not write_text(key, text):
    raise OSError(f"could not write {key}")


def _remove(key: str) -> None:
  from openpilot.common.bogpilot_store import remove_file
  remove_file(key)


def read_premute(key: str) -> int | None:
  sd = _sd()
  text = sd._bogpilot_read_param(premute_key(key))
  if text is None:
    return None
  try:
    return int(float(text))
  except (TypeError, ValueError):
    return None


def is_muted(key: str) -> bool:
  """True when volume is at the row floor AND a PreMute restore value is stored."""
  lo, _ = row_bounds(key)
  return read_volume(key) == lo and read_premute(key) is not None


def set_controller(on: bool) -> None:
  _write(PARENT_KEY, "1" if on else "0")


def set_volume(key: str, value: int) -> int:
  if key not in VOLUME_KEYS:
    raise KeyError(key)
  v = clamp(key, value)
  _write(key, str(v))
  # Manual adjust clears mute-restore memory so Mute is a fresh snapshot next time.
  if read_premute(key) is not None and v != row_bounds(key)[0]:
    _remove(premute_key(key))
  return v


def toggle_mute(key: str) -> int:
  """Mute: save current level to PreMute and set volume to row minimum (warning floor kept).
  Unmute: restore PreMute and clear it. Returns the new volume."""
  if key not in VOLUME_KEYS:
    raise KeyError(key)
  lo, hi = row_bounds(key)
  if is_muted(key):
    prev = read_premute(key)
    target = clamp(key, AUTO if prev is None else prev)
    _write(key, str(target))
    _remove(premute_key(key))
    return target
  current = read_volume(key)
  # Already at floor with no premute: still snapshot a sensible restore (Auto) so unmute works.
  snapshot = current if current > lo else (read_premute(key) or AUTO)
  snapshot = clamp_range(lo, hi, snapshot)
  if snapshot == lo:
    snapshot = AUTO  # never remember "already at floor" as the restore target
  _write(premute_key(key), str(snapshot))
  _write(key, str(lo))
  return lo


def rows() -> list[dict]:
  """Panel model: parent toggle; children visible when on. Each volume row is a slider control."""
  on = read_controller()
  out = [{"key": PARENT_KEY, "title": "Alert Volume Controller", "type": "toggle", "value": on, "visible": True}]
  for key, title, lo, hi in VOLUME_ROWS:
    v = read_volume(key)
    muted = is_muted(key)
    out.append({
      "key": key, "title": title, "type": "slider", "min": lo, "max": hi,
      "value": v, "label": label(v), "visible": on,
      "muted": muted, "mute_title": mute_button_title(key),
      "can_silence": lo == 0,
      "buttons": [mute_button_title(key), MINUS_GLYPH, label(v), PLUS_GLYPH],
    })
  return out


def effective_gain(key: str, ambient: float) -> float:
  sd = _sd()
  return sd.resolve_alert_gain(alert_volume_control=read_controller(), percent=raw_volume(key),
                               ambient=ambient, key=key)


def create_volume_layout():
  """Raylib Alert Volume Controller: [Mute|Min] [ASCII -] [label] [+] per category.

  Mute sits LEFT of minus. Warning/critical rows use Min and clamp to 25% so safety
  alerts stay audible. Without PROPOSED_shared.patch, soundd loads volumes at process
  start; the UI re-reads the store about once per second while idle.
  """
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import toggle_item, multiple_button_item, text_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

  class VolumeLayout(Widget):
    def __init__(self):
      super().__init__()
      self._last_idle_refresh = 0.0
      self.controller = toggle_item(
        lambda: tr("Alert Volume Controller"),
        lambda: tr(
          "Per-category alert volumes. File store (/data/params_bogpilot) is the live source "
          "(soundd reads file before Params). Mute saves the current level and jumps to the "
          "row minimum; tap again to restore (survives restart). Prompt, Prompt Distracted and Warning rows use "
          "Min and cannot go below 25%. Without the soundd live-reload patch, a new value "
          "applies at the next sound service start. Auto follows ambient."
        ),
        read_controller(), callback=self.set_controller, enabled=ui_state.is_offroad,
      )
      attach_help(self.controller, "AlertVolumeControl")
      self.note = text_item(
        lambda: tr("Warning minimum"),
        lambda: tr(f"{WARNING_FLOOR}% floor - Prompt, Prompt Distracted and Warning alerts cannot be muted"),
      )
      attach_help(self.note, "AlertVolumeFloor")
      self.precedence = text_item(
        lambda: tr("Storage"),
        lambda: tr("File store first, then Params. Volume keys are file-only on this build."),
      )
      self.volumes = {}
      items = [self.controller, self.note, self.precedence]
      for key, title, _, _ in VOLUME_ROWS:
        row = multiple_button_item(
          lambda title=title: tr(title),
          lambda key=key: tr(self._desc(key)),
          [
            lambda key=key: tr(mute_button_title(key)),
            MINUS_GLYPH,  # ASCII U+002D - never U+2212
            lambda key=key: label(read_volume(key)),
            PLUS_GLYPH,
          ],
          1,
          callback=lambda index, key=key: self.on_button(key, index),
          button_width=150,
        )
        row.set_enabled(ui_state.is_offroad)
        attach_help(row, key)
        self.volumes[key] = row
        items.append(row)
      self.scroller = Scroller(items, line_separator=True, spacing=0)
      self.refresh(force=True)

    def _desc(self, key: str) -> str:
      if raw_out_of_range(key):
        return "Stored value is outside the range; shown clamped, not rewritten."
      if key in WARNING_FLOOR_KEYS:
        return ("Min sets 25% (critical alerts stay audible). Tap again to restore the previous "
                "level. 101 is Auto.")
      return ("Mute sets 0% (Muted) and remembers the previous level for unmute across restart. "
              "101 is Auto.")

    def set_controller(self, value):
      if ui_state.is_offroad():
        set_controller(bool(value))
      self.refresh(force=True)

    def on_button(self, key, index):
      if not ui_state.is_offroad():
        self.refresh(force=True)
        return
      if index == 0:
        toggle_mute(key)
      elif index == 1:
        set_volume(key, read_volume(key) - 1)
      elif index == 3:
        set_volume(key, read_volume(key) + 1)
      # index 2 is the live label
      self.refresh(force=True)

    def refresh(self, force: bool = False):
      now = time.monotonic()
      if not force and (now - self._last_idle_refresh) < IDLE_REFRESH_S:
        return
      self._last_idle_refresh = now
      enabled = read_controller()
      self.controller.action_item.set_state(enabled)
      for key, row in self.volumes.items():
        row.set_visible(enabled)
        # Highlight Mute/Min when the row is in the muted/floor-with-restore state.
        action = row.action_item
        if hasattr(action, "set_selected_button"):
          action.set_selected_button(0 if is_muted(key) else 1)

    def show_event(self):
      super().show_event()
      self.scroller.show_event()
      self.refresh(force=True)

    def _render(self, rect):
      self.refresh(force=False)
      self.scroller.render(rect)

  return VolumeLayout()
