"""Pre-AP Test Radar and Calibrate Radar screens: live retrofit Bosch radar points while the car is parked.

Idea and constants from NotAutopilot (MIT, Copyright comma.ai) nap-dev selfdrive/ui/radar/radar_view.py and bosch_status.py
(bird's-eye plot, track table, health label, the 2.5-14.5 m / +-1.0 m alignment box). The code here is BogPilot's own.

Why this reads the radar CAN frames itself: the radarTracks that card publishes are filtered by the radar-valid gate
(preap/radar_valid.py), which needs a MOVING track before it lets any point through. A parked radar aimed at a stationary
target would show nothing. These screens decode the same point frames (bus 1, tesla_radar_bosch_generated) from the `can` stream
instead. They are display only: nothing here writes a param, sends a CAN frame, or feeds control, and the `can` subscription lives
only while a screen is open.

What is shown is what openpilot would use: the same point filter (bosch_point_valid) and the same Radar Offset and Flip Radar
corrections as radar_interface.py (offset first, then the flip). Offset and flip are read when the screen opens (they apply
to openpilot at the next car start, which is also when this screen's numbers start to match the driving view).

Pure part (no raylib): RawRadarReader, RadarView, health_label, AimEstimator, suggested_offset, blocked_reason, RadarToolSession.
The raylib part (create_radar_screen, draw_radar_screen) is built lazily so this module imports anywhere.
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.radar_valid import ADJUST_BITS, F2_BITS, short_bit
from opendbc.car.tesla_ap1.preap_radar_filters import bosch_point_valid

TEST, CALIBRATE = "test", "calibrate"
TITLES = {TEST: "Test Radar", CALIBRATE: "Calibrate Radar"}

NUM_POINTS = 32
TRIGGER_ADDR = 878            # RadarPoint31_B: the last frame of a radar cycle (radar_interface.TRIGGER_MSG)
FRESH_S = 0.6                 # no complete radar cycle for this long = the radar is not talking
ALIGN_D_MIN, ALIGN_D_MAX, ALIGN_Y_MAX = 2.5, 14.5, 1.0   # NAP bosch_status.py: the box a target is placed in to aim the radar
CANDIDATE_Y_MAX = 3.0         # a badly aimed radar still shows a reading: pick targets this far to either side (the box stays +-1.0)
ON_TARGET_M = 0.10            # a reading within this of 0.00 m counts as aimed
HINT_MIN_M = 0.05             # below this no offset hint is worth showing
AIM_SAMPLES = 10              # median over the last cycles (about 1 s)
RANGE_M, LATERAL_M = 120.0, 8.0          # Test Radar plot
CAL_RANGE_M, CAL_LATERAL_M = 20.0, 3.0   # Calibrate Radar plot (zoomed on the alignment box)
TABLE_ROWS, TABLE_ROWS_COMPACT = 8, 4
MAX_OFFSET_M = preap_params.RADAR_OFFSET_LIMIT_M

HEALTH = {  # label -> colour key used by the drawing code
  "LIVE": "ok", "NO TRACKS": "muted", "NO RADAR": "bad", "FAULT": "bad", "REJECT": "warn", "ALIGNING": "warn", "STOPPED": "muted",
}


@dataclass(frozen=True)
class Track:
  track_id: int
  d_rel: float      # m ahead of the front bumper
  y_rel: float      # m, positive left, after Radar Offset and Flip Radar
  v_rel: float      # m/s


@dataclass(frozen=True)
class RadarView:
  tracks: tuple = ()
  fresh: bool = False                 # a complete radar cycle arrived within FRESH_S
  hw_fail: bool = False
  sensor_dirty: bool = False
  alerts: tuple = ()                  # 0x501 alert names that reject this radar (vinValidity, radPositionMismatch, ...)
  adjusting: tuple = ()               # 0x501 adjustment bits (adjustmentReq, adjustmentNotDone, adjustmentNotOk)
  age_s: float | None = None


def make_parser():
  """CANParser for the Pre-AP radar bus: the SGU status, the 0x501 alert matrix and the 32 point frame pairs. No alive checks."""
  from opendbc.can import CANParser
  from opendbc.car import Bus
  from opendbc.car.tesla_ap1.values import CANBUS, CAR, DBC
  nan = float("nan")
  messages = [("TeslaRadarSguInfo", nan), ("TeslaRadarAlertMatrix", nan)]
  for i in range(NUM_POINTS):
    messages += [(f"RadarPoint{i}_A", nan), (f"RadarPoint{i}_B", nan)]
  return CANParser(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar], messages, CANBUS.radar)


class RawRadarReader:
  """Decodes `can` entries ((nanos, [(addr, data, src), ...]) tuples) into a RadarView. Never raises on bad data."""

  def __init__(self, parser=None, offset_m: float = 0.0, flip: bool = False):
    self.parser = parser if parser is not None else make_parser()
    self.offset_m, self.flip = float(offset_m), bool(flip)
    self._tracks: tuple = ()
    self._hw_fail = self._dirty = False
    self._alerts: tuple = ()
    self._adjusting: tuple = ()
    self._last_cycle: float | None = None

  def update(self, can_list, now: float) -> RadarView:
    try:
      updated = self.parser.update(can_list) if can_list else set()
    except Exception:
      updated = set()
    if TRIGGER_ADDR in updated:
      self._read_cycle()
      self._last_cycle = now
    if self._last_cycle is None:
      return RadarView()
    age = max(0.0, now - self._last_cycle)
    fresh = age <= FRESH_S
    return RadarView(tracks=self._tracks if fresh else (), fresh=fresh, hw_fail=self._hw_fail if fresh else False,
                     sensor_dirty=self._dirty if fresh else False, alerts=self._alerts if fresh else (),
                     adjusting=self._adjusting if fresh else (), age_s=age)

  def _read_cycle(self) -> None:
    vl = self.parser.vl
    status = vl["TeslaRadarSguInfo"]
    self._hw_fail, self._dirty = bool(status["RADC_HWFail"]), bool(status["RADC_SensorDirty"])
    matrix = vl["TeslaRadarAlertMatrix"]
    self._alerts = tuple(short_bit(b) for b in F2_BITS if matrix[b])
    self._adjusting = tuple(short_bit(b) for b in ADJUST_BITS if matrix[b])
    tracks = []
    for i in range(NUM_POINTS):
      a, b = vl[f"RadarPoint{i}_A"], vl[f"RadarPoint{i}_B"]
      if a["Index"] != b["Index2"] or not a["Tracked"] or not bosch_point_valid(a["LongDist"], a["ProbExist"]):
        continue
      y = a["LatDist"] + self.offset_m          # radar_interface.py: offset first, then the flip
      if self.flip:
        y = -y
      tracks.append(Track(i, float(a["LongDist"]), float(y), float(a["LongSpeed"])))
    self._tracks = tuple(sorted(tracks, key=lambda t: t.d_rel))


class CanRadarSource:
  """Live `can` subscription feeding a RawRadarReader. Opened by the screen, closed with it."""

  def __init__(self, reader: RawRadarReader):
    self.reader = reader
    self._sock = None

  def open(self) -> None:
    from openpilot.cereal import messaging
    self._sock = messaging.sub_sock("can", conflate=False, timeout=0)

  def close(self) -> None:
    self._sock = None

  def poll(self, now: float) -> RadarView:
    can_list = []
    if self._sock is not None:
      try:
        from openpilot.cereal import messaging
        from openpilot.selfdrive.pandad import can_capnp_to_list
        can_list = can_capnp_to_list(messaging.drain_sock_raw(self._sock))
      except Exception:
        can_list = []
    return self.reader.update(can_list, now)


def health_label(view: RadarView) -> str:
  if not view.fresh:
    return "NO RADAR"
  if view.hw_fail:
    return "FAULT"
  if view.alerts:
    return "REJECT"
  if view.adjusting:
    return "ALIGNING"
  return "LIVE" if view.tracks else "NO TRACKS"


def health_detail(view: RadarView) -> str:
  label = health_label(view)
  if label == "NO RADAR":
    return "No radar frames. Check the radar power and that it is on the radar CAN bus."
  if label == "FAULT":
    return "The radar reports a hardware failure."
  if label == "REJECT":
    return "The radar rejects this car: " + ", ".join(view.alerts) + ". See Radar Donor Type, EPAS Type and Donor VIN."
  if label == "ALIGNING":
    return "The radar says it is still aligning (" + ", ".join(view.adjusting) + ")."
  if label == "NO TRACKS":
    return "Radar is talking but sees nothing. Put a target in front of it."
  return f"{len(view.tracks)} tracked point" + ("" if len(view.tracks) == 1 else "s") + "."


def align_candidates(tracks) -> list:
  return [t for t in tracks if ALIGN_D_MIN <= t.d_rel <= ALIGN_D_MAX and abs(t.y_rel) <= CANDIDATE_Y_MAX]


class AimEstimator:
  """Lateral reading of the target in the alignment window: the nearest point each cycle, median of the last AIM_SAMPLES cycles."""

  def __init__(self, samples: int = AIM_SAMPLES):
    self._ys: deque = deque(maxlen=samples)
    self.distance: float | None = None

  def update(self, view: RadarView) -> float | None:
    cands = align_candidates(view.tracks) if view.fresh else []
    if not cands:
      self._ys.clear()
      self.distance = None
      return None
    nearest = min(cands, key=lambda t: t.d_rel)
    self._ys.append(nearest.y_rel)
    self.distance = nearest.d_rel
    return self.reading()

  def reading(self) -> float | None:
    if not self._ys:
      return None
    ys = sorted(self._ys)
    n = len(ys)
    return ys[n // 2] if n % 2 else 0.5 * (ys[n // 2 - 1] + ys[n // 2])


def side_text(y: float) -> str:
  """'0.35 m left', '0.20 m right' or 'centered' (ASCII). Positive y is left."""
  if abs(y) < 0.005:
    return "0.00 m"
  return f"{abs(y):.2f} m {'left' if y > 0 else 'right'}"


def suggested_offset(reading: float, current_offset: float, flip: bool) -> float | None:
  """The Radar Offset (m) that would bring `reading` to 0.00 m: reading = s * (raw + offset), s = -1 with Flip Radar, so
  offset' = offset - s * reading. Rounded to 0.01 m; None when the fix is outside the +-1.00 m the setting allows."""
  s = -1.0 if flip else 1.0
  target = current_offset - s * reading
  target = round(target * 100.0) / 100.0
  if abs(target) > MAX_OFFSET_M + 1e-9:
    return None
  return 0.0 if target == 0 else target


def signed_m(value: float) -> str:
  return f"{abs(value):.2f} m" if abs(value) < 0.005 else f"{'-' if value < 0 else ''}{abs(value):.2f} m"


def blocked_reason(radar_on: bool, started: bool, engaged: bool, moving: bool) -> str:
  """'' when a radar screen may open or keep running. Parked only: car on, in Park, not engaged, Bosch Radar on."""
  if not radar_on:
    return "Turn on Bosch Radar first."
  if engaged:
    return "Disengage first."
  if not started:
    return "Turn the car on (in Park) first. The radar only talks while the car is on."
  if moving:
    return "Put the car in Park first. These screens only run while the car is stopped."
  return ""


@dataclass(frozen=True)
class ScreenState:
  mode: str
  title: str
  phase: str                       # running / stopped / blocked
  health: str
  health_detail: str
  tracks: tuple = ()
  reading: float | None = None     # Calibrate Radar: lateral reading of the target, m (positive left)
  distance: float | None = None
  aim_line: str = ""               # big line: "0.35 m left" / "ON TARGET" / "No target"
  aim_state: str = "none"          # none / on_target / off
  hint: str = ""
  footer: str = ""
  buttons: tuple = ("Close",)
  plot: dict = field(default_factory=dict)


class RadarToolSession:
  """One open Test Radar / Calibrate Radar screen. `source.poll(now)` gives the RadarView; the gates are callables so a
  car that starts moving or engages stops the screen on the next tick (it then shows why and keeps its last picture)."""

  def __init__(self, mode, source, *, radar_on=lambda: True, started=lambda: True, engaged=lambda: False, moving=lambda: False,
               offset_m: float = 0.0, flip: bool = False, now=time.monotonic):
    assert mode in TITLES
    self.mode, self.source, self.now = mode, source, now
    self.radar_on, self.started, self.engaged, self.moving = radar_on, started, engaged, moving
    self.offset_m, self.flip = float(offset_m), bool(flip)
    self.aim = AimEstimator()
    self.stopped_reason = ""
    self._last: ScreenState | None = None
    self._opened = False

  def begin(self) -> None:
    if not self._opened:
      self._opened = True
      if hasattr(self.source, "open"):
        self.source.open()

  def close(self) -> None:
    if hasattr(self.source, "close"):
      self.source.close()
    self._opened = False

  def _plot(self) -> dict:
    if self.mode == CALIBRATE:
      return {"range": CAL_RANGE_M, "lateral": CAL_LATERAL_M, "box": (ALIGN_D_MIN, ALIGN_D_MAX, ALIGN_Y_MAX), "rings": (5.0, 10.0, 15.0)}
    return {"range": RANGE_M, "lateral": LATERAL_M, "box": None, "rings": (20.0, 40.0, 60.0, 80.0, 100.0)}

  def tick(self) -> ScreenState:
    title = TITLES[self.mode]
    if not self.stopped_reason:
      reason = blocked_reason(bool(self.radar_on()), bool(self.started()), bool(self.engaged()), bool(self.moving()))
      if reason:
        self.stopped_reason = reason
    if self.stopped_reason:
      last = self._last
      return ScreenState(mode=self.mode, title=title, phase="stopped", health="STOPPED", health_detail=self.stopped_reason,
                         tracks=last.tracks if last else (), reading=last.reading if last else None,
                         distance=last.distance if last else None, aim_line=last.aim_line if last else "",
                         aim_state=last.aim_state if last else "none", hint="", footer=self.stopped_reason, plot=self._plot())
    view = self.source.poll(self.now())
    label = health_label(view)
    reading = self.aim.update(view) if self.mode == CALIBRATE else None
    aim_line, aim_state, hint, footer = "", "none", "", health_detail(view)
    if self.mode == CALIBRATE:
      if reading is None:
        aim_line = "No target"
        footer = ("Put a car or a large metal object straight ahead, 3 to 14 m from the front bumper." if view.fresh
                  else health_detail(view))
      else:
        aim_state = "on_target" if abs(reading) <= ON_TARGET_M else "off"
        aim_line = "ON TARGET" if aim_state == "on_target" else side_text(reading)
        footer = f"Target {self.aim.distance:.1f} m ahead reads {signed_m(reading)} (positive is left). Aim until it reads 0.00 m."
        if abs(reading) >= HINT_MIN_M:
          fix = suggested_offset(reading, self.offset_m, self.flip)
          hint = (f"Or set Radar Offset to {signed_m(fix)} to cancel it in software." if fix is not None
                  else "Too far off for Radar Offset (it stops at 1.00 m). Re-aim the radar.")
    state = ScreenState(mode=self.mode, title=title, phase="running", health=label, health_detail=health_detail(view),
                        tracks=view.tracks, reading=reading, distance=self.aim.distance, aim_line=aim_line, aim_state=aim_state,
                        hint=hint, footer=footer, plot=self._plot())
    self._last = state
    return state


# --------------------------------------------------------------------------------------------------------------------
# raylib part (3X full screen and the comma 4 page both draw through draw_radar_screen)
# --------------------------------------------------------------------------------------------------------------------
def _colors():
  import pyray as rl
  return {
    "bg": rl.Color(18, 20, 24, 255), "panel": rl.Color(12, 14, 18, 230), "border": rl.Color(255, 255, 255, 70),
    "text": rl.Color(236, 236, 236, 255), "muted": rl.Color(160, 160, 160, 255), "ok": rl.Color(70, 200, 120, 255),
    "warn": rl.Color(235, 180, 60, 255), "bad": rl.Color(226, 60, 60, 255), "track": rl.Color(90, 200, 255, 235),
    "near": rl.Color(128, 216, 166, 255), "box_fill": rl.Color(70, 91, 234, 40), "box_line": rl.Color(70, 91, 234, 190),
    "car": rl.Color(200, 200, 200, 255), "ring": rl.Color(255, 255, 255, 38), "center": rl.Color(255, 255, 255, 90),
  }


def draw_radar_screen(rect, state: ScreenState, compact: bool) -> None:
  """Header (title + health chip), bird's-eye plot, track table, aim readout (Calibrate), footer. rect is the whole screen."""
  import pyray as rl
  from openpilot.system.ui.lib.application import FontWeight, gui_app
  from openpilot.system.ui.lib.text_measure import measure_text_cached
  C = _colors()
  font_b, font = gui_app.font(FontWeight.BOLD), gui_app.font(FontWeight.NORMAL)

  def text(s, x, y, size, color, bold=False):
    rl.draw_text_ex(font_b if bold else font, s, rl.Vector2(x, y), size, 0, color)

  def fit(s, size, width, bold=False):
    f = font_b if bold else font
    while len(s) > 1 and measure_text_cached(f, s, size).x > width:
      s = s[:-2].rstrip() + "."
    return s

  rl.draw_rectangle_rec(rect, C["bg"])
  pad = 10 if compact else 24
  title_size, body, small = (24, 18, 16) if compact else (56, 34, 32)
  x0, y0 = rect.x + pad, rect.y + (16 if compact else 18)
  text(state.title, x0, y0, title_size, C["text"], True)
  chip = state.health
  cw = measure_text_cached(font_b, chip, body).x + 16
  cx = rect.x + rect.width - pad - cw
  rl.draw_rectangle_rounded(rl.Rectangle(cx, y0 + 1, cw, body + 8), 0.4, 6, C[HEALTH.get(chip, "muted")])
  text(chip, cx + 8, y0 + 5, body, rl.Color(10, 10, 10, 255), True)

  head_h = title_size + (26 if compact else 40)
  foot_h = (2 * (small + 4) + 14) if compact else 150
  top, bottom = rect.y + head_h, rect.y + rect.height - foot_h
  plot_w = rect.width * (0.46 if compact else 0.40)
  plot = rl.Rectangle(rect.x + pad, top, plot_w, bottom - top)
  rl.draw_rectangle_rec(plot, C["panel"])
  rl.draw_rectangle_lines_ex(plot, 1, C["border"])
  spec = state.plot or {}
  rng, lat = float(spec.get("range", RANGE_M)), float(spec.get("lateral", LATERAL_M))

  def to_px(d, y):    # y positive left: left of the car is left on screen
    px = plot.x + plot.width / 2 - (y / lat) * (plot.width / 2)
    py = plot.y + plot.height - 14 - (d / rng) * (plot.height - 18)
    return px, py

  for ring in spec.get("rings", ()):
    _, py = to_px(ring, 0)
    if py > plot.y:
      rl.draw_line_ex(rl.Vector2(plot.x, py), rl.Vector2(plot.x + plot.width, py), 1, C["ring"])
      text(f"{ring:g}", plot.x + 3, py - small - 1, small - 2, C["muted"])
  cx0, _ = to_px(0, 0)
  rl.draw_line_ex(rl.Vector2(cx0, plot.y), rl.Vector2(cx0, plot.y + plot.height - 14), 1, C["center"])
  box = spec.get("box")
  if box:
    l, b = to_px(box[0], box[2])
    r, t = to_px(box[1], -box[2])
    rect_box = rl.Rectangle(min(l, r), min(t, b), abs(r - l), abs(b - t))
    rl.draw_rectangle_rec(rect_box, C["box_fill"])
    rl.draw_rectangle_lines_ex(rect_box, 2, C["box_line"])
  car_w = max(8.0, plot.width * 0.06)
  rl.draw_rectangle_rec(rl.Rectangle(cx0 - car_w / 2, plot.y + plot.height - 14, car_w, 10), C["car"])
  radius = 3 if compact else 6
  for i, t in enumerate(state.tracks):
    if t.d_rel > rng or abs(t.y_rel) > lat:
      continue
    px, py = to_px(t.d_rel, t.y_rel)
    rl.draw_circle(int(px), int(py), radius, C["near"] if i == 0 else C["track"])

  # right column
  rx = plot.x + plot.width + pad
  rw = rect.x + rect.width - pad - rx
  y = top
  if state.mode == CALIBRATE:
    big = state.aim_line or ""
    color = C["ok"] if state.aim_state == "on_target" else (C["warn"] if state.aim_state == "off" else C["muted"])
    size = (34 if compact else 120)
    while size > 14 and measure_text_cached(font_b, big, size).x > rw:
      size -= 2
    text(big, rx, y, size, color, True)
    y += size + (6 if compact else 14)
    if state.hint:
      for line in _wrap(font, state.hint, small, rw):
        text(line, rx, y, small, C["muted"])
        y += small + 3
  else:
    cols = (0.0, 0.17, 0.42, 0.70)             # column starts as a fraction of the column width (proportional font: no padding tricks)
    for c, label in zip(cols, ("ID", "dRel m", "yRel m", "vRel m/s")):
      text(label, rx + c * rw, y, small, C["muted"])
    y += small + 4
    rows = TABLE_ROWS_COMPACT if compact else TABLE_ROWS
    for t in state.tracks[:rows]:
      for c, cell in zip(cols, (str(t.track_id), f"{t.d_rel:.1f}", f"{t.y_rel:.2f}", f"{t.v_rel:.1f}")):
        text(cell, rx + c * rw, y, small, C["text"])
      y += small + (3 if compact else 8)
    if not state.tracks:
      text("no tracks", rx, y, small, C["muted"])
    elif len(state.tracks) > rows:
      text(f"+{len(state.tracks) - rows} more", rx, y, small, C["muted"])
  # footer
  fy = bottom + 6
  fsize = small if compact else 36
  lines = _wrap(font, state.footer or state.health_detail, fsize, rect.width - 2 * pad - (0 if compact else 320))
  for line in lines[:2 if compact else 3]:
    text(line, x0, fy, fsize, C["text"] if state.phase == "running" else C["warn"])
    fy += fsize + 4
  if compact and state.phase == "running":
    text("swipe down to close", rect.x + rect.width - pad - measure_text_cached(font, "swipe down to close", small - 2).x,
         rect.y + rect.height - small - 8, small - 2, C["muted"])


def _wrap(font, s, size, width):
  from openpilot.system.ui.lib.text_measure import measure_text_cached
  out, cur = [], ""
  for word in str(s).split():
    trial = f"{cur} {word}" if cur else word
    if cur and measure_text_cached(font, trial, size).x > width:
      out.append(cur)
      cur = word
    else:
      cur = trial
  if cur:
    out.append(cur)
  return out


def create_radar_screen(session: RadarToolSession, on_done=None):
  """3X full-screen Widget (the comma 4 swaps in dialogs.RadarToolPage by this class name). Leaving it closes the session."""
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.button import Button

  class RadarToolScreen(Widget):
    def __init__(self):
      super().__init__()
      self.session = session
      self.state: ScreenState | None = None
      self._close = Button(tr("Close"), self._press_close)

    def _press_close(self):
      self._press("Close")

    def _press(self, label):
      gui_app.pop_widget()
      if on_done:
        on_done(label)

    def show_event(self):
      super().show_event()
      self.session.begin()

    def hide_event(self):
      self.session.close()
      super().hide_event()

    def _render(self, rect):
      self.state = self.session.tick()
      full = rl.Rectangle(0, 0, gui_app.width, gui_app.height)
      draw_radar_screen(full, self.state, compact=False)
      self._close.render(rl.Rectangle(gui_app.width - 280, gui_app.height - 110, 240, 80))
      return None

  return RadarToolScreen()
