"""Developer Sidebar widget (raylib): the 300 px panel on the right of the driving screen, display only.

0.9.7 DeveloperSidebar: up to seven tiles in the sidebar tile style, each showing one metric chosen in Visuals. The metric table
and the per-drive tracker are in bogpilot/developer_sidebar_logic. The widget never takes a tap and writes nothing.
"""
import pyray as rl

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.bogpilot import developer_sidebar_logic as L
from openpilot.selfdrive.ui.onroad.bogpilot.overlay_gate import OverlayGate
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

BACKGROUND = rl.Color(57, 57, 57, 255)
TILE_X, TILE_W, TILE_H = 12, 275, 126
BORDER = rl.Color(255, 255, 255, 85)
FONT_SIZE = 35
MIN_FONT_SIZE = 20


class DeveloperSidebar(Widget):
  def __init__(self, store=None, gate=None):
    super().__init__()
    self._store = store
    self._gate = gate if gate is not None else OverlayGate("DeveloperSidebar", store=store)
    self._tracker = L.Tracker()
    self._drive = None
    self._values: dict[int, str] = {}
    self._slots: list[int] = []
    self._slots_next = -1.0
    self._font = gui_app.font(FontWeight.SEMI_BOLD)

  def wanted(self) -> bool:
    """True while the setting is on and a drive is running; the main layout gives the panel its 300 px."""
    try:
      return bool(ui_state.started and self._gate.get())
    except Exception:
      return False

  def _read_slots(self) -> list[int]:
    import time
    now = time.monotonic()
    if now >= self._slots_next:
      self._slots_next = now + 2.0
      try:
        if self._store is None:
          from openpilot.common.bogpilot_store import ParamStore
          self._store = ParamStore()
        self._slots = L.slot_assignments([self._store.toggle_int(key) for key in L.metric_keys()], L.torque_steering(ui_state.CP))
      except Exception:
        self._slots = []
    return self._slots

  def _update_state(self):
    if not self.wanted():
      self._drive = None
      return
    if self._drive != ui_state.started_frame:   # a new drive: engagement shares and the maximum start over
      self._drive = ui_state.started_frame
      self._tracker.reset()
    try:
      inputs = L.inputs_from_messages(ui_state.sm, ui_state.started_frame, ui_state.CP)
      self._values = self._tracker.update(inputs) if inputs is not None else {}
    except Exception:
      cloudlog.exception("developer sidebar update failed")
      self._values = {}

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, BACKGROUND)
    slots = self._read_slots()
    for metric, top in zip(slots, L.layout_slots(len(slots), rect.height, TILE_H), strict=True):
      try:
        self._draw_tile(rect.x + TILE_X, rect.y + top, L.METRICS[metric][0], self._values.get(metric, "-"))
      except Exception:
        cloudlog.exception("developer sidebar tile failed")
        return

  def _draw_tile(self, x: float, y: float, label: str, value: str):
    tile = rl.Rectangle(x, y, TILE_W, TILE_H)
    edge = rl.Rectangle(tile.x + tile.width - 4 - 100, tile.y + 4, 100, 118)
    rl.begin_scissor_mode(int(tile.x + tile.width - 4 - 18), int(tile.y), 18, int(tile.height))
    rl.draw_rectangle_rounded(edge, 0.3, 10, rl.WHITE)
    rl.end_scissor_mode()
    rl.draw_rectangle_rounded_lines_ex(tile, 0.3, 10, 2, BORDER)

    inner_w = tile.width - 22 - 14
    texts = [tr(label), value]
    text_y = tile.y + (tile.height / 2 - len(texts) * FONT_SIZE * FONT_SCALE)
    for text in texts:
      size = FONT_SIZE
      width = measure_text_cached(self._font, text, size).x
      if width > inner_w:
        size = max(MIN_FONT_SIZE, int(size * inner_w / width))
      dim = measure_text_cached(self._font, text, size)
      text_y += dim.y
      rl.draw_text_ex(self._font, text, rl.Vector2(tile.x + (tile.width - 22 - dim.x) / 2, text_y), size, 0, rl.WHITE)
