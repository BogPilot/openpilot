"""Guided Comma Pedal calibration for Pre-AP.

Replaces the 0.9.7 one-shot confirm (clipped to 3 of 6 lines, closed on Yes, no live guidance, long failures elided).

Pure part (no raylib): `read_snapshot`, `screen_for`, `status_text`, `blocked_reason`, `PedalCalSession`. The state-to-screen mapping is
tested without a window. The raylib part (`create_intro_dialog`, `create_calibration_screen`) is built lazily so this module imports
anywhere.

The car process (preap/carcontroller.py) owns the capture. It publishes progress through file-backed params under /data/params_bogpilot
(PedalCalibArmed / Stage / Message, PedalCalibDone / Zero / Factor, PedalDetected + PedalSeenTs). The UI only reads those and arms or
disarms with calib.arm_calibration / calib.cancel_calibration. Cancel, a UI timeout, the car moving, and leaving the screen all disarm
and never write a calibration value. The calibration logic itself (coast frames, press thresholds, span/factor validation) is unchanged.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from opendbc.car.tesla_ap1.preap import calib
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys, get_bool, get_float, get_str

# Overall UI limit for one attempt. The car-side capture has no timeout of its own (noted in the port notes).
TIMEOUT_S = 90.0

# Step markers
TODO, ACTIVE, DONE, FAILED = "todo", "active", "done", "failed"
# Phases
BLOCKED, COAST, PRESS, SAVED, FAIL, TIMED_OUT, PEDAL_LOST, MOVED = (
  "blocked", "coast", "press", "saved", "failed", "timeout", "pedal_lost", "moved")
TERMINAL = (SAVED, FAIL, TIMED_OUT, MOVED, BLOCKED)

STEP_LABELS = ("Feet off both pedals", "Press the accelerator fully", "Saved")

INTRO_TITLE = "Calibrate Comma Pedal"
INTRO_PARAGRAPHS = (
  "Put the car in Park with the ignition on. Keep your foot off the accelerator and brake pedals. Keep the car stopped for the whole calibration.",
  "Step 1: Keep your foot off the accelerator and brake pedals. BogPilot waits until the pedal reading is steady and the car sees no input. "
  "This takes about half a second.",
  "Step 2: Press the accelerator pedal fully once, hold it for a moment, then let go. A small twitch is ignored.",
  "BogPilot saves the new calibration only if the reading is sensible. If it is not, nothing is changed and you can try again.",
  "Cancel, running out of time (%d seconds), the car moving, or leaving the screen all leave your current calibration exactly as it "
  "was. Pedal longitudinal needs a calibrated pedal." % int(TIMEOUT_S),
)
INTRO_BUTTONS = ("Start", "Cancel")


def intro_html(translate=None) -> str:
  t = translate if translate is not None else (lambda s: s)
  parts = ["<h2>" + t(INTRO_TITLE) + "</h2>"] + ["<p>" + t(p) + "</p>" for p in INTRO_PARAGRAPHS]
  return "".join(parts)


@dataclass(frozen=True)
class Snapshot:
  armed: bool = False
  stage: str = ""
  message: str = ""
  live: bool = False          # the car has heard the pedal in the last few seconds
  calibrated: bool = False
  out_of_range: bool = False  # a calibration is saved, but its pedal scale is outside the accepted window (recalibrate; values untouched)
  factor: float = 1.0
  zero: float = 0.0


def read_snapshot(now: float | None = None) -> Snapshot:
  return Snapshot(
    armed=get_bool(PreApParamKeys.PEDAL_CALIB_ARMED),
    stage=get_str(PreApParamKeys.PEDAL_CALIB_STAGE),
    message=get_str(PreApParamKeys.PEDAL_CALIB_MESSAGE),
    live=calib.pedal_live(now),
    calibrated=calib.is_pedal_calibrated(),
    out_of_range=calib.saved_calibration_out_of_range(),
    factor=get_float(PreApParamKeys.PEDAL_CALIB_FACTOR),
    zero=get_float(PreApParamKeys.PEDAL_CALIB_ZERO),
  )


def status_text(s: Snapshot) -> str:
  """One short line for the Comma Pedal row (never long enough to be elided)."""
  if s.armed:
    return "Calibrating"
  if not s.live:
    return "Not detected (calibrated)" if s.calibrated else "Not detected"
  if s.calibrated:
    return "Calibrated"
  if s.out_of_range:
    return "Recalibrate: scale out of range"
  return "Needs calibration (last try failed)" if s.message else "Needs calibration"


def blocked_reason(live: bool, moving: bool) -> str:
  """'' when a calibration may start. Parked (or offroad with the pedal still being heard) only."""
  if moving:
    return "Put the car in Park first. Calibration only runs while the car is stopped."
  if not live:
    return ("The Comma Pedal is not being heard. Turn the car on in Park with the pedal connected, "
            "then try again. Pedal CAN bus 2 is the usual install.")
  return ""


# Below this speed (m/s) the car counts as stopped for the calibration gate (the same 0.1 m/s that AP1 CarState uses for standstill).
STOPPED_V_EGO = 0.1


def car_moving(started: bool, v_ego, gear) -> bool:
  """True when calibration must not start or must stop: onroad and either rolling or not in Park.

  carState.standstill is deliberately not used. On Pre-AP it is the DI STANDSTILL cruise state
  (opendbc_repo/opendbc/car/tesla_ap1/preap/carstate.py:241, from fce00b1dd), not a speed test, so it is False in Park
  with cruise off and would block calibration whenever the car is on. `gear` is the carState.gearShifter enum and is
  compared with the GearShifter enum from the car structs. An unknown gear, or a missing or non-finite speed, counts as
  moving. Offroad (not started) is never moving, as before.
  """
  if not started:
    return False
  try:
    speed = abs(float(v_ego))
  except (TypeError, ValueError):
    return True
  if not math.isfinite(speed) or speed >= STOPPED_V_EGO:
    return True
  return not _is_park(gear)


def _is_park(gear) -> bool:
  from opendbc.car.structs import car
  try:
    return bool(gear == car.CarState.GearShifter.park)
  except Exception:
    return False


def car_state_moving(started: bool, car_state) -> bool:
  """`car_moving` for a carState message (what the Vehicle Settings page and the calibration session use)."""
  return car_moving(started, getattr(car_state, "vEgo", None), getattr(car_state, "gearShifter", None))


@dataclass(frozen=True)
class Screen:
  phase: str
  title: str
  instruction: str
  detail: str
  steps: tuple            # ((label, state), ...) for the three steps
  buttons: tuple          # button labels, left to right; the last one is the primary action
  terminal: bool
  factor: float | None = None


def _steps(a, b, c):
  return tuple(zip(STEP_LABELS, (a, b, c), strict=True))


def screen_for(snap: Snapshot, *, phase_hint: str = "", elapsed: float = 0.0, reason: str = "") -> Screen:
  """Map the calibration state to what the screen shows. `phase_hint` carries a latched UI-only outcome
  (timeout, moved, blocked, saved, failed); otherwise the live params decide."""
  remaining = max(0, int(TIMEOUT_S - elapsed + 0.999))
  if phase_hint == BLOCKED:
    return Screen(BLOCKED, "Cannot calibrate", "Not now", reason, _steps(TODO, TODO, TODO), ("Close",), True)
  if phase_hint == TIMED_OUT:
    return Screen(TIMED_OUT, "Timed out", "No complete calibration in %d seconds" % int(TIMEOUT_S),
                  "Nothing was changed. Your previous calibration is still in use.",
                  _steps(TODO, TODO, TODO), ("Close", "Try again"), True)
  if phase_hint == MOVED:
    return Screen(MOVED, "Stopped", "The car moved",
                  "Calibration was cancelled for safety and nothing was changed. Put the car in Park and try again.",
                  _steps(TODO, TODO, TODO), ("Close", "Try again"), True)
  if phase_hint == SAVED:
    return Screen(SAVED, "Saved", "Calibration saved",
                  "The Comma Pedal is ready for openpilot to control your speed.\nPedal scale: %.3f (1.000 = no adjustment)" % snap.factor,
                  _steps(DONE, DONE, DONE), ("Done",), True, factor=snap.factor)
  if phase_hint == FAIL:
    why = (snap.message or "The calibration check failed").strip().rstrip(".;, ")
    # a failure is only ever decided after the press, so step 1 (foot off) was completed
    return Screen(FAIL, "Failed", "Calibration was not saved", why + ". Your previous calibration was not changed.",
                  _steps(DONE, FAILED, TODO), ("Close", "Try again"), True)
  # live phases
  if not snap.live:
    return Screen(PEDAL_LOST, "Calibrate Comma Pedal", "Waiting for the Comma Pedal",
                  "The pedal is not being heard right now. Check its connection. %d s left." % remaining,
                  _steps(ACTIVE, TODO, TODO), ("Cancel",), False)
  if snap.stage == calib.STAGE_COAST_OK:
    return Screen(PRESS, "Step 2 of 2", "Press the accelerator pedal fully once, then let go",
                  "Press the accelerator pedal all the way down, hold it for a moment, then let go. %d s left." % remaining,
                  _steps(DONE, ACTIVE, TODO), ("Cancel",), False)
  return Screen(COAST, "Step 1 of 2", "Keep your foot off the accelerator and brake pedals",
                "Keep your foot off the accelerator and brake pedals until the check mark appears. %d s left." % remaining,
                _steps(ACTIVE, TODO, TODO), ("Cancel",), False)


class PedalCalSession:
  """One guided attempt. All inputs are injectable so tests and renders drive it without a car."""

  def __init__(self, *, monotonic=time.monotonic, wall=time.time, moving=lambda: False, timeout_s: float = TIMEOUT_S):
    self.monotonic, self.wall, self.moving, self.timeout_s = monotonic, wall, moving, timeout_s
    self.started_at: float | None = None
    self.latched = ""          # terminal outcome: saved / failed / timeout / moved / blocked
    self.reason = ""
    self.armed_by_me = False
    self.snap = Snapshot()

  # -- control ---------------------------------------------------------------------------------------
  def begin(self) -> bool:
    snap = read_snapshot(self.wall())
    self.reason = blocked_reason(snap.live, bool(self.moving()))
    if self.reason:
      self.latched = BLOCKED
      self.armed_by_me = False
      return False
    self.latched = ""
    self.started_at = self.monotonic()
    calib.arm_calibration()
    self.armed_by_me = True
    return True

  def cancel(self) -> None:
    """Disarm. Never touches a stored calibration value."""
    if self.armed_by_me:
      calib.cancel_calibration()
    self.armed_by_me = False

  close = cancel   # leaving the screen for any reason

  def retry(self) -> bool:
    self.cancel()
    return self.begin()

  def elapsed(self) -> float:
    return 0.0 if self.started_at is None else self.monotonic() - self.started_at

  # -- state -----------------------------------------------------------------------------------------
  def tick(self) -> Screen:
    self.snap = read_snapshot(self.wall())
    if not self.latched and self.armed_by_me:
      if self.snap.stage == calib.STAGE_SAVED and not self.snap.armed and self.snap.calibrated:
        self.latched = SAVED
        self.armed_by_me = False
      elif self.snap.stage == calib.STAGE_FAILED and not self.snap.armed:
        self.latched = FAIL
        self.armed_by_me = False
      elif self.moving():
        self.cancel()
        self.latched = MOVED
      elif self.elapsed() >= self.timeout_s:
        self.cancel()
        self.latched = TIMED_OUT
    return screen_for(self.snap, phase_hint=self.latched, elapsed=self.elapsed(), reason=self.reason)


# ----------------------------------------------------------------------------------------------------------
# raylib widgets (lazy)
# ----------------------------------------------------------------------------------------------------------
def create_intro_dialog(callback):
  """Scrollable intro with the full text and Start / Cancel. Callback gets DialogResult.CONFIRM for Start."""
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.html_render import ElementType, HtmlRenderer
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import POPUP_FONT_SIZE

  html = intro_html(tr)

  class PedalCalIntro(ConfirmDialog):
    def __init__(self):
      super().__init__(html, tr(INTRO_BUTTONS[0]), cancel_text=tr(INTRO_BUTTONS[1]), rich=True, callback=callback)
      self.html = html
      self._html_renderer = HtmlRenderer(text=html, text_size={ElementType.P: POPUP_FONT_SIZE})
      self._scroller = Scroller([self._html_renderer], line_separator=False, spacing=0)

  return PedalCalIntro()


def create_calibration_screen(session: PedalCalSession, on_done=None):
  import pyray as rl
  from openpilot.system.ui.lib.application import FontWeight, TextAlignment, TextAlignmentVertical, gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.lib.wrap_text import wrap_text
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.button import Button, ButtonStyle
  from openpilot.system.ui.widgets.label import gui_label

  BG = rl.Color(27, 27, 27, 255)
  WHITE = rl.Color(235, 235, 235, 255)
  GREY = rl.Color(150, 150, 150, 255)
  GREEN = rl.Color(70, 190, 100, 255)
  RED = rl.Color(220, 80, 70, 255)
  AMBER = rl.Color(235, 180, 60, 255)
  MARGIN, BUTTON_H = 100, 150

  class PedalCalibrationScreen(Widget):
    def __init__(self):
      super().__init__()
      self.session = session
      self.screen: Screen | None = None
      self._buttons = [Button("", self._press_left), Button("", self._press_right, button_style=ButtonStyle.PRIMARY)]

    def show_event(self):
      super().show_event()
      self.session.begin()

    def hide_event(self):
      self.session.close()   # leaving the screen always disarms
      super().hide_event()

    # button handlers act on the labels last drawn
    def _press(self, label):
      if label in ("Cancel", "Close", "Done"):
        if label == "Cancel":
          self.session.cancel()
        gui_app.pop_widget()
        if on_done:
          on_done(label)
      elif label == "Try again":
        self.session.retry()

    def _press_left(self):
      if self.screen:
        self._press(self.screen.buttons[0])

    def _press_right(self):
      if self.screen and len(self.screen.buttons) == 2:
        self._press(self.screen.buttons[1])

    def _text(self, rect, text, size, color, weight=FontWeight.NORMAL, align=None):
      gui_label(rect, text, font_size=size, color=color, font_weight=weight,
                alignment=align if align is not None else TextAlignment.LEFT, alignment_vertical=TextAlignmentVertical.TOP, elide_right=False)

    def _marker(self, cx, cy, state):
      r = 34
      if state == DONE:
        rl.draw_circle(int(cx), int(cy), r, GREEN)
        rl.draw_line_ex(rl.Vector2(cx - 15, cy + 2), rl.Vector2(cx - 4, cy + 14), 7, BG)
        rl.draw_line_ex(rl.Vector2(cx - 4, cy + 14), rl.Vector2(cx + 17, cy - 12), 7, BG)
      elif state == FAILED:
        rl.draw_circle(int(cx), int(cy), r, RED)
        rl.draw_line_ex(rl.Vector2(cx - 13, cy - 13), rl.Vector2(cx + 13, cy + 13), 7, BG)
        rl.draw_line_ex(rl.Vector2(cx + 13, cy - 13), rl.Vector2(cx - 13, cy + 13), 7, BG)
      elif state == ACTIVE:
        rl.draw_circle(int(cx), int(cy), r, AMBER)
        rl.draw_circle(int(cx), int(cy), 12, BG)
      else:
        rl.draw_circle(int(cx), int(cy), r, rl.Color(70, 70, 70, 255))

    def _fit(self, text, width, height, start=46, floor=30):
      """Wrap `text` so it fits width x height with no elision: shrink the font until it does.
      Explicit newlines in the detail slot stay as line breaks (used for the saved-screen scale line)."""
      font = gui_app.font(FontWeight.NORMAL)
      size = start
      while True:
        lines = []
        for para in text.split("\n"):
          lines.extend(wrap_text(font, para, size, int(width)) or [""])
        if len(lines) * int(size * 1.25) <= height or size <= floor:
          return size, lines
        size -= 2

    def _render(self, rect):
      scr = self.session.tick()
      self.screen = scr
      rl.draw_rectangle_rec(rl.Rectangle(0, 0, gui_app.width, gui_app.height), BG)
      x, w = MARGIN, gui_app.width - 2 * MARGIN
      y = 70
      self._text(rl.Rectangle(x, y, w, 80), tr(scr.title), 64, GREY, FontWeight.BOLD)
      y += 110
      for i, (label, state) in enumerate(scr.steps):
        cy = y + 40 + i * 100
        self._marker(x + 40, cy, state)
        color = WHITE if state in (ACTIVE, DONE) else (RED if state == FAILED else GREY)
        self._text(rl.Rectangle(x + 110, cy - 28, w - 110, 60), tr(label), 50, color,
                   FontWeight.BOLD if state == ACTIVE else FontWeight.NORMAL)
      y += 3 * 100 + 40
      head_color = {SAVED: GREEN, FAIL: RED, TIMED_OUT: RED, MOVED: RED, BLOCKED: RED, PEDAL_LOST: AMBER}.get(scr.phase, WHITE)
      self._text(rl.Rectangle(x, y, w, 90), tr(scr.instruction), 72, head_color, FontWeight.BOLD)
      y += 100
      bottom = gui_app.height - BUTTON_H - 2 * 50
      size, lines = self._fit(tr(scr.detail), w, bottom - y)
      for i, line in enumerate(lines):
        self._text(rl.Rectangle(x, y + i * int(size * 1.25), w, size * 1.3), line, size, WHITE)
      by = gui_app.height - BUTTON_H - 50
      n = len(scr.buttons)
      bw = (w - (n - 1) * 50) // n if n > 1 else 700
      for i, label in enumerate(scr.buttons):
        b = self._buttons[0] if n == 1 else self._buttons[i]
        b.set_text(tr(label))
        b.set_button_style(ButtonStyle.PRIMARY if (i == n - 1 and label != "Cancel") else ButtonStyle.NORMAL)
        bx = x + i * (bw + 50) if n > 1 else x + (w - bw) // 2
        b.render(rl.Rectangle(bx, by, bw, BUTTON_H))
      return None

  return PedalCalibrationScreen()
