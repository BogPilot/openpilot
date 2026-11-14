import pyray as rl
from dataclasses import dataclass
from collections.abc import Callable
from openpilot.cereal import log
from openpilot.common.params import Params
from openpilot.selfdrive.ui.bogpilot.sidebar_metrics import (device_readings, metric_visibility_from_params, slot_choices,
                                                              slot_flags_from_params, chip_reading, storage_reading, data_usage_gb,
                                                              IpReader, cycle_chip, cycle_memory, cycle_temp, temp_mode,
                                                              read_vehicle_slot, write_vehicle_slot, cycle_vehicle_slot,
                                                              vehicle_slot_shown)
from openpilot.selfdrive.ui.onroad.bogpilot.overlay_gate import OverlayGate
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

SIDEBAR_WIDTH = 300
METRIC_HEIGHT = 126
METRIC_WIDTH = 240
METRIC_MARGIN = 30
FONT_SIZE = 35

SETTINGS_BTN = rl.Rectangle(50, 35, 200, 117)
HOME_BTN = rl.Rectangle(60, 860, 180, 180)

ThermalStatus = log.DeviceState.ThermalStatus
NetworkType = log.DeviceState.NetworkType


# Color scheme
class Colors:
  WHITE = rl.WHITE
  WHITE_DIM = rl.Color(255, 255, 255, 85)
  GRAY = rl.Color(84, 84, 84, 255)

  # Status colors
  GOOD = rl.WHITE
  WARNING = rl.Color(218, 202, 37, 255)
  DANGER = rl.Color(201, 34, 49, 255)

  # UI elements
  METRIC_BORDER = rl.Color(255, 255, 255, 85)
  BUTTON_NORMAL = rl.WHITE
  BUTTON_PRESSED = rl.Color(255, 255, 255, 166)


NETWORK_TYPES = {
  NetworkType.none: tr_noop("--"),
  NetworkType.wifi: tr_noop("Wi-Fi"),
  NetworkType.ethernet: tr_noop("ETH"),
  NetworkType.cell2G: tr_noop("2G"),
  NetworkType.cell3G: tr_noop("3G"),
  NetworkType.cell4G: tr_noop("LTE"),
  NetworkType.cell5G: tr_noop("5G"),
}


@dataclass(slots=True)
class MetricData:
  label: str
  value: str
  color: rl.Color

  def update(self, label: str, value: str, color: rl.Color):
    self.label = label
    self.value = value
    self.color = color


class Sidebar(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._offroad_temp_status = MetricData(tr_noop("TEMP"), "--", Colors.GRAY)
    self._cpu_status = MetricData(tr_noop("CPU"), "--", Colors.GRAY)
    self._ram_status = MetricData(tr_noop("RAM"), "--", Colors.GRAY)
    self._net_type = NETWORK_TYPES[NetworkType.none]
    self._net_strength = 0
    self._ip_gate = OverlayGate("ShowIP")   # ShowIP: the Wi-Fi address replaces the signal dots
    self._ip_reader = IpReader()
    self._ip_text = ""

    self._temp_status = MetricData(tr_noop("TEMP"), tr_noop("GOOD"), Colors.GOOD)
    self._panda_status = MetricData(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)
    self._recording_audio = False
    self._hw_args = (None, False)        # (deviceState, fresh) of the last metrics update, to redraw at once after a tap
    self._metric_hits: list = []         # (rect, kind) of the boxes drawn last frame; kind is "temp", "chip", "memory" or "vehicle"

    # Load BogPilot home mark at native PNG resolution (360x360). Forcing a CPU
    # image_resize down to HOME_BTN (180) then drawing with GPU bilinear double-filters
    # the arc AA and looks like clipped/smudged pixels on the lower-left sidebar logo.
    # Draw at HOME_BTN with an explicit scale so only one filter step runs.
    # button_home_ring.png is button_home.png with the ring's top half replaced by the mirror of its bottom half (the
    # shipped ring is thinner and hard-edged at the top, which reads as a clipped top at 2160x1080); every other pixel
    # is the shipped asset's. The shipped file stays the fallback.
    self._home_img = gui_app.texture("bogpilot/button_home_ring.png")
    if not (self._home_img.width > 0 and self._home_img.height > 0):
      self._home_img = gui_app.texture("bogpilot/button_home.png")
    if not (self._home_img.width > 0 and self._home_img.height > 0):
      # ui is a managed process (selfdrived raises processNotRunning if it is down): never crash on an asset failure.
      # Fall back to the other BogPilot mark, never to the stock comma logo or flag images; if that fails too draw nothing.
      self._home_img = gui_app.texture("icons/bogpilot/icon_bogpilot.png")
    self._home_valid = self._home_img.width > 0 and self._home_img.height > 0
    self._home_draw_scale = HOME_BTN.width / float(self._home_img.width) if self._home_img.width > 0 else 1.0
    self._settings_img = gui_app.texture("images/button_settings.png", SETTINGS_BTN.width, SETTINGS_BTN.height)
    self._mic_img = gui_app.texture("icons/microphone.png", 30, 30)
    self._mic_indicator_rect = rl.Rectangle(0, 0, 0, 0)
    self._font_regular = gui_app.font(FontWeight.NORMAL)
    self._font_bold = gui_app.font(FontWeight.SEMI_BOLD)

    # Callbacks
    self._on_settings_click: Callable | None = None
    self._on_flag_click: Callable | None = None
    self._open_settings_callback: Callable | None = None

  def set_callbacks(self, on_settings: Callable | None = None, on_flag: Callable | None = None,
                    open_settings: Callable | None = None):
    self._on_settings_click = on_settings
    self._on_flag_click = on_flag
    self._open_settings_callback = open_settings

  def _render(self, rect: rl.Rectangle):
    # Background
    rl.draw_rectangle_rec(rect, rl.BLACK)

    self._draw_buttons(rect)
    self._draw_network_indicator(rect)
    self._draw_metrics(rect)

  def _update_state(self):
    sm = ui_state.sm
    self._update_ip()
    self._recording_audio = ui_state.recording_audio
    if not (sm.valid["deviceState"] and sm.alive["deviceState"]):
      self._update_hardware_metrics(None, fresh=False)
      self._net_type = NETWORK_TYPES[NetworkType.none]
      self._net_strength = 0
      return
    if not sm.updated['deviceState']:
      return

    device_state = sm['deviceState']

    self._recording_audio = ui_state.recording_audio
    self._update_hardware_metrics(device_state, fresh=True)
    self._update_network_status(device_state)
    self._update_temperature_status(device_state)
    self._update_panda_status()

  def _update_ip(self):
    gate = getattr(self, "_ip_gate", None)
    self._ip_text = ""
    if gate is not None and gate.get():
      self._ip_text = self._ip_reader.get() or "--"

  def _update_hardware_metrics(self, device_state, *, fresh: bool):
    self._hw_args = (device_state, fresh)
    show_cpu, show_memory, numerical_temp, fahrenheit = metric_visibility_from_params(self._params)
    self._show_cpu = show_cpu
    self._show_memory = show_memory
    self._numerical_temp = numerical_temp
    self._temp_mode = temp_mode(numerical_temp, fahrenheit)
    readings = device_readings(device_state, fresh=fresh, fahrenheit=fahrenheit)
    colors = {"good": Colors.GOOD, "warning": Colors.WARNING, "danger": Colors.DANGER, "unknown": Colors.GRAY}
    for metric, reading in zip((self._offroad_temp_status, self._cpu_status, self._ram_status), readings, strict=True):
      metric.update(metric.label, reading.value, colors[reading.level])
    # chip slot: CPU or GPU; memory slot: RAM, storage left or storage used (0.9.7). CPU and RAM keep their slots by default.
    flags = slot_flags_from_params(self._params) | {"ShowCPU": show_cpu, "ShowMemoryUsage": show_memory}
    self._slot_chip, self._slot_memory = slot_choices(flags)
    self._slot_vehicle = read_vehicle_slot()   # onroad middle box (file choice), read with the other slots, not every frame
    if not hasattr(self, "_extra_status"):
      self._extra_status = {"gpu": MetricData(tr_noop("GPU"), "--", Colors.GRAY),
                            "storage_left": MetricData(tr_noop("LEFT"), "--", Colors.GRAY),
                            "storage_used": MetricData(tr_noop("USED"), "--", Colors.GRAY)}
    extra = {"gpu": chip_reading(device_state, "gpu", fresh=fresh)}
    usage = data_usage_gb() if self._slot_memory in ("storage_left", "storage_used") else None
    for which in ("storage_left", "storage_used"):
      extra[which] = storage_reading(device_state, which, usage, fresh=fresh)
    for which, metric in self._extra_status.items():
      metric.update(metric.label, extra[which].value, colors[extra[which].level])

  def _update_network_status(self, device_state):
    self._net_type = NETWORK_TYPES.get(device_state.networkType.raw, tr_noop("Unknown"))
    strength = device_state.networkStrength
    self._net_strength = max(0, min(5, strength.raw + 1)) if strength.raw > 0 else 0

  def _update_temperature_status(self, device_state):
    thermal_status = device_state.thermalStatus

    if thermal_status == ThermalStatus.ok:
      self._temp_status.update(tr_noop("TEMP"), tr_noop("GOOD"), Colors.GOOD)
    else:
      self._temp_status.update(tr_noop("TEMP"), tr_noop("HIGH"), Colors.DANGER)


  def _update_panda_status(self):
    if ui_state.panda_type == log.PandaState.PandaType.unknown:
      self._panda_seen = False
      self._panda_status.update(tr_noop("NO"), tr_noop("PANDA"), Colors.DANGER)
    else:
      self._panda_seen = True
      self._panda_status.update(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN):
      if self._on_settings_click:
        self._on_settings_click()
    elif rl.check_collision_point_rec(mouse_pos, HOME_BTN) and ui_state.started:
      if self._on_flag_click:
        self._on_flag_click()
    elif self._recording_audio and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect):
      if self._open_settings_callback:
        self._open_settings_callback()
    else:
      for box, kind in self._metric_hits:
        if rl.check_collision_point_rec(mouse_pos, box):
          self._cycle(kind)
          break

  def _store_flags(self, writes: dict) -> None:
    try:
      for key, value in writes.items():
        self._params.put_bool(key, bool(value))
    except Exception:
      pass   # an unwritable preference must never take the UI down; the box simply keeps its contents

  def _cycle(self, kind: str) -> None:
    """A tap inside a metric box moves that box to its next content and saves it (0.9.7 sidebar.cc:75-120). The index
    starts from what is stored, so the first tap after a restart advances what is on screen."""
    if kind == "chip":
      writes = cycle_chip(getattr(self, "_slot_chip", "cpu"))
    elif kind == "memory":
      writes = cycle_memory(getattr(self, "_slot_memory", "memory"))
    elif kind == "temp":
      writes = cycle_temp(getattr(self, "_temp_mode", "celsius"))
    elif kind == "vehicle":
      # onroad middle box: vehicle status <-> CPU, saved as a file choice (SidebarVehicleSlot)
      choice = cycle_vehicle_slot(getattr(self, "_slot_vehicle", "vehicle"))
      if write_vehicle_slot(choice):
        self._slot_vehicle = choice
      return
    else:
      return
    self._store_flags(writes)
    self._update_hardware_metrics(self._hw_args[0], fresh=self._hw_args[1])

  def _draw_buttons(self, rect: rl.Rectangle):
    mouse_pos = rl.get_mouse_position()
    mouse_down = self.is_pressed and rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)

    # Settings button
    settings_down = mouse_down and rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN)
    tint = Colors.BUTTON_PRESSED if settings_down else Colors.BUTTON_NORMAL
    rl.draw_texture_ex(self._settings_img, rl.Vector2(SETTINGS_BTN.x, SETTINGS_BTN.y), 0.0, 1.0, tint)

    # Home/Flag button
    flag_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, HOME_BTN)
    # The BogPilot mark is shown both offroad and onroad (the stock comma flag image is never drawn). Onroad the button
    # still acts as the flag/bookmark tap; only its pressed tint differs.
    button_img = self._home_img

    tint = Colors.BUTTON_PRESSED if (ui_state.started and flag_pressed) else Colors.BUTTON_NORMAL
    # Native-size texture + explicit scale so only one filter step runs (same as the offroad home mark).
    draw_scale = self._home_draw_scale
    if self._home_valid:
      rl.draw_texture_ex(button_img, rl.Vector2(HOME_BTN.x, HOME_BTN.y), 0.0, draw_scale, tint)

    # Microphone button
    if self._recording_audio:
      self._mic_indicator_rect = rl.Rectangle(rect.x + rect.width - 130, rect.y + 245, 75, 40)

      mic_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect)
      bg_color = rl.Color(Colors.DANGER.r, Colors.DANGER.g, Colors.DANGER.b, int(255 * 0.65)) if mic_pressed else Colors.DANGER

      rl.draw_rectangle_rounded(self._mic_indicator_rect, 1, 10, bg_color)
      rl.draw_texture_ex(self._mic_img, rl.Vector2(self._mic_indicator_rect.x + (self._mic_indicator_rect.width - self._mic_img.width) / 2,
                         self._mic_indicator_rect.y + (self._mic_indicator_rect.height - self._mic_img.height) / 2), 0.0, 1.0, Colors.WHITE)

  def _draw_network_indicator(self, rect: rl.Rectangle):
    ip_text = getattr(self, "_ip_text", "")
    if ip_text:
      self._draw_ip(rect, ip_text)
      return
    # Signal strength dots
    x_start = rect.x + 58
    y_pos = rect.y + 196
    dot_size = 27
    dot_spacing = 37

    for i in range(5):
      color = Colors.WHITE if i < self._net_strength else Colors.GRAY
      x = int(x_start + i * dot_spacing + dot_size // 2)
      y = int(y_pos + dot_size // 2)
      rl.draw_circle(x, y, dot_size // 2, color)

    self._draw_network_type(rect)

  def _draw_network_type(self, rect: rl.Rectangle):
    text_y = rect.y + 247
    text_pos = rl.Vector2(rect.x + 58, text_y)
    rl.draw_text_ex(self._font_regular, tr(self._net_type), text_pos, FONT_SIZE, 0, Colors.WHITE)

  def _draw_ip(self, rect: rl.Rectangle, text: str):
    """ShowIP (0.9.7): the Wi-Fi address where the signal dots are, left aligned in the 27 px dot row; the type stays below."""
    size = 30
    width = measure_text_cached(self._font_regular, text, size).x
    max_width = SIDEBAR_WIDTH - 50 - 10
    if width > max_width:
      size = max(18, int(size * max_width / width))
    height = measure_text_cached(self._font_regular, text, size).y
    rl.draw_text_ex(self._font_regular, text, rl.Vector2(rect.x + 50, rect.y + 196 + (27 - height) / 2), size, 0, Colors.WHITE)
    self._draw_network_type(rect)

  def _draw_metrics(self, rect: rl.Rectangle):
    # Keep thermal and vehicle readiness onroad; show genuine RAM instead of removed cloud status.
    # visualsTheme: gate CPU/RAM/numeric temp from preserved ShowCPU / ShowMemoryUsage / NumericalTemp.
    numerical_temp = getattr(self, "_numerical_temp", True)
    chip = getattr(self, "_slot_chip", "cpu" if getattr(self, "_show_cpu", True) else None)
    memory = getattr(self, "_slot_memory", "memory" if getattr(self, "_show_memory", True) else None)
    extra = getattr(self, "_extra_status", {})
    chip_metric = {"cpu": self._cpu_status, "gpu": extra.get("gpu")}.get(chip)
    memory_metric = {"memory": self._ram_status, "storage_left": extra.get("storage_left"),
                     "storage_used": extra.get("storage_used")}.get(memory)
    slots = (338, 496, 654)
    # The temperature box shows GOOD / HIGH or the number in C or F, onroad as well as offroad, as saved by tapping it.
    temp_metric = self._offroad_temp_status if numerical_temp else self._temp_status
    if ui_state.started:
      # The middle box is the vehicle status, or CPU when the driver tapped it to CPU (SidebarVehicleSlot). "NO PANDA"
      # always takes it back, so a missing panda is never hidden.
      shown = vehicle_slot_shown(getattr(self, "_slot_vehicle", "vehicle"), getattr(self, "_panda_seen", True))
      chosen = [(temp_metric, "temp"), (self._cpu_status if shown == "cpu" else self._panda_status, "vehicle")]
      if memory_metric is not None:
        chosen.append((memory_metric, "memory"))
    else:
      chosen = [(temp_metric, "temp")]
      if chip_metric is not None:
        chosen.append((chip_metric, "chip"))
      if memory_metric is not None:
        chosen.append((memory_metric, "memory"))
    self._metric_hits = []
    for (metric, kind), y_offset in zip(chosen, slots[:len(chosen)], strict=True):
      self._draw_metric(rect, metric, rect.y + y_offset)
      if kind is not None:
        self._metric_hits.append((rl.Rectangle(rect.x + METRIC_MARGIN, rect.y + y_offset, METRIC_WIDTH, METRIC_HEIGHT), kind))

  def _draw_metric(self, rect: rl.Rectangle, metric: MetricData, y: float):
    metric_rect = rl.Rectangle(rect.x + METRIC_MARGIN, y, METRIC_WIDTH, METRIC_HEIGHT)
    # Draw colored left edge (clipped rounded rectangle)
    edge_rect = rl.Rectangle(metric_rect.x + 4, metric_rect.y + 4, 100, 118)
    rl.begin_scissor_mode(int(metric_rect.x + 4), int(metric_rect.y), 18, int(metric_rect.height))
    rl.draw_rectangle_rounded(edge_rect, 0.3, 10, metric.color)
    rl.end_scissor_mode()

    # Draw border
    rl.draw_rectangle_rounded_lines_ex(metric_rect, 0.3, 10, 2, Colors.METRIC_BORDER)

    # Draw label and value
    labels = [tr(metric.label), tr(metric.value)]
    text_y = metric_rect.y + (metric_rect.height / 2 - len(labels) * FONT_SIZE * FONT_SCALE)
    for text in labels:
      text_size = measure_text_cached(self._font_bold, text, FONT_SIZE)
      text_y += text_size.y
      text_pos = rl.Vector2(
        metric_rect.x + 22 + (metric_rect.width - 22 - text_size.x) / 2,
        text_y
      )
      rl.draw_text_ex(self._font_bold, text, text_pos, FONT_SIZE, 0, Colors.WHITE)
