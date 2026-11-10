"""System Settings > Device Controls submenu (active consumers only).

sysData owns the System Settings parent page. This module delivers the Device
Controls nested pages (Device Settings / Screen Settings) plus preference writes
with readback. Runtime hooks for ui_state Device and power_monitoring are proposed
separately in PROPOSED_shared.patch — do not claim working until INT applies them.
"""
from __future__ import annotations

from openpilot.selfdrive.ui.bogpilot.phase3_device_controls_runtime import (
  DEVICE_MASTER, SCREEN_MASTER, shutdown_label,
  screen_timeout, screen_brightness, screen_awake, shutdown_time, voltage_cutoff,
)

# Active keys with real consumers once PROPOSED hooks land (or recorder for start/stop).
DEVICE_KEYS = frozenset({
  DEVICE_MASTER, "DeviceShutdown", "LowVoltageShutdown",
  SCREEN_MASTER, "ScreenBrightness", "ScreenBrightnessOnroad",
  "ScreenTimeout", "ScreenTimeoutOnroad", "StandbyMode",
})

RANGES = {
  "DeviceShutdown": (0, 33, 1),
  "LowVoltageShutdown": (11.8, 12.5, 0.1),
  "ScreenBrightness": (1, 101, 1),
  "ScreenBrightnessOnroad": (0, 101, 1),
  "ScreenTimeout": (5, 60, 5),
  "ScreenTimeoutOnroad": (5, 60, 5),
}

BOOL_KEYS = frozenset({DEVICE_MASTER, SCREEN_MASTER, "StandbyMode"})

# Honest non-toggle rows — not shipped as fake working controls.
UNAVAILABLE = {
  "Raise Temperature Limits": "Pending approved thermal envelope; stock thermal protections remain unchanged.",
  "Disable Logging": "Not wired here: needs process_config/manager consent hooks owned by INT; local recording unchanged.",
  "High-Quality Recording": "Not wired: no current encoder consumer for historical HD bitrate on this build.",
  "Offroad Screensaver": "Not wired: no raylib screensaver renderer/root hook on this lane; normal screen sleep remains.",
}

DEFAULTS = {
  DEVICE_MASTER: False,
  "DeviceShutdown": 33,  # stock: 30 h (MAX_TIME_OFFROAD_S)
  "LowVoltageShutdown": 11.8,
  SCREEN_MASTER: False,
  "ScreenBrightness": 101,
  "ScreenBrightnessOnroad": 101,
  "ScreenTimeout": 30,
  "ScreenTimeoutOnroad": 10,  # stock onroad timeout
  "StandbyMode": False,
}


class MemoryStore:
  """Test/fixture store with the ParamStore-like surface the consumers need."""

  def __init__(self, values=None):
    self.values = {k: str(v) if not isinstance(v, str) else v for k, v in (values or {}).items()}
    self.writes = []

  def raw(self, key):
    return self.values.get(key)

  def get(self, key, default=""):
    return self.values.get(key, default)

  def get_bool(self, key, default=False):
    raw = self.values.get(key)
    if raw is None:
      return default
    return raw in ("1", "true", "True", "on")

  def put(self, key, value):
    text = str(value)
    self.values[key] = text
    self.writes.append((key, text))

  def put_bool(self, key, value):
    self.put(key, "1" if value else "0")


class DevicePreferences:
  """Offroad/capability-guarded preference writer with mandatory readback."""

  def __init__(self, store, offroad, capable):
    self.store, self.offroad, self.capable = store, offroad, capable

  def guard(self):
    if not self.offroad() or not self.capable():
      raise PermissionError("Offroad supported device required")

  def set(self, key, value):
    self.guard()
    if key not in DEVICE_KEYS:
      raise ValueError("Preference outside Device Controls scope")
    if key in RANGES:
      lo, hi, step = RANGES[key]
      value = float(value)
      if not lo <= value <= hi or abs((value - lo) / step - round((value - lo) / step)) > 1e-6:
        raise ValueError("Preference outside historical range/step")
      text = str(round(value, 1)) if step < 1 else str(int(value))
      self.store.put(key, text)
      actual = self.store.raw(key)
      if actual is None or abs(float(actual) - float(value)) > 1e-6:
        raise OSError("Preference write verification failed")
      return float(actual) if step < 1 else int(float(actual))
    if key not in BOOL_KEYS or type(value) is not bool:
      raise ValueError("Boolean required")
    self.store.put_bool(key, value)
    actual = self.store.raw(key)
    if actual != ("1" if value else "0"):
      raise OSError("Preference write verification failed")
    return value


class DeviceControlsMenu:
  """Testable Device Controls model: pages, rows, UI -> store -> consumer."""

  STOCK_TIMEOUT_OFFROAD = 30
  STOCK_TIMEOUT_ONROAD = 10
  STOCK_BRIGHTNESS = 50.0
  STOCK_SHUTDOWN_S = 30 * 3600
  STOCK_VOLTAGE = 11.8

  def __init__(self, store=None, offroad=None, capable=None, recorder_start=None, recorder_stop=None):
    self.store = store if store is not None else MemoryStore()
    self.offroad = offroad or (lambda: True)
    self.capable = capable or (lambda: True)
    self.prefs = DevicePreferences(self.store, self.offroad, self.capable)
    self.recorder_start = recorder_start or (lambda: "recorder.start not injected")
    self.recorder_stop = recorder_stop or (lambda: "recorder.stop not injected")
    self.path = ()  # () | ("Device Settings",) | ("Screen Settings",)
    self.status = ""

  @property
  def title(self):
    return self.path[-1] if self.path else "Device Controls"

  def allowed(self):
    return bool(self.offroad() and self.capable())

  def go(self, title):
    if title in ("Device Settings", "Screen Settings"):
      self.path = (title,)
      return True
    return False

  def back(self):
    if self.path:
      self.path = ()
      return True
    return False

  def set(self, key, value):
    if not self.allowed():
      self.status = "Offroad supported device required; no changes made."
      return False
    try:
      self.prefs.set(key, value)
      self.status = "Saved."
      return True
    except Exception as exc:
      self.status = f"Refused ({type(exc).__name__}); no success claimed."
      return False

  def rows(self):
    """Logical menu rows for the current page (for tests and thin UI adapters)."""
    if not self.path:
      return [
        {"kind": "manage", "title": "Device Settings"},
        {"kind": "manage", "title": "Screen Settings"},
      ]
    if self.path[-1] == "Device Settings":
      rows = [
        {"kind": "toggle", "key": DEVICE_MASTER, "title": "Device Settings",
         "value": self.store.get_bool(DEVICE_MASTER, False)},
        {"kind": "number", "key": "DeviceShutdown", "title": "Device Shutdown Timer",
         "value": int(float(self.store.raw("DeviceShutdown") or DEFAULTS["DeviceShutdown"])),
         "label": shutdown_label(int(float(self.store.raw("DeviceShutdown") or DEFAULTS["DeviceShutdown"]))),
         "requires": DEVICE_MASTER},
        {"kind": "number", "key": "LowVoltageShutdown", "title": "Low-Voltage Cutoff",
         "value": float(self.store.raw("LowVoltageShutdown") or DEFAULTS["LowVoltageShutdown"]),
         "requires": DEVICE_MASTER},
        {"kind": "unavailable", "title": "Disable Logging", "reason": UNAVAILABLE["Disable Logging"]},
        {"kind": "unavailable", "title": "High-Quality Recording", "reason": UNAVAILABLE["High-Quality Recording"]},
        {"kind": "unavailable", "title": "Raise Temperature Limits", "reason": UNAVAILABLE["Raise Temperature Limits"]},
      ]
      return rows
    if self.path[-1] == "Screen Settings":
      return [
        {"kind": "toggle", "key": SCREEN_MASTER, "title": "Screen Settings",
         "value": self.store.get_bool(SCREEN_MASTER, False)},
        {"kind": "number", "key": "ScreenBrightness", "title": "Screen Brightness (Offroad)",
         "value": int(float(self.store.raw("ScreenBrightness") or DEFAULTS["ScreenBrightness"])),
         "requires": SCREEN_MASTER},
        {"kind": "number", "key": "ScreenBrightnessOnroad", "title": "Screen Brightness (Onroad)",
         "value": int(float(self.store.raw("ScreenBrightnessOnroad") or DEFAULTS["ScreenBrightnessOnroad"])),
         "requires": SCREEN_MASTER},
        {"kind": "number", "key": "ScreenTimeout", "title": "Screen Timeout (Offroad)",
         "value": int(float(self.store.raw("ScreenTimeout") or DEFAULTS["ScreenTimeout"])),
         "requires": SCREEN_MASTER},
        {"kind": "number", "key": "ScreenTimeoutOnroad", "title": "Screen Timeout (Onroad)",
         "value": int(float(self.store.raw("ScreenTimeoutOnroad") or DEFAULTS["ScreenTimeoutOnroad"])),
         "requires": SCREEN_MASTER},
        {"kind": "toggle", "key": "StandbyMode", "title": "Standby Mode",
         "value": self.store.get_bool("StandbyMode", False), "requires": SCREEN_MASTER},
        {"kind": "action", "title": "Screen Recorder", "label": "Start Recording", "action": "start_recording"},
        {"kind": "action", "title": "Screen Recorder", "label": "Stop Recording", "action": "stop_recording"},
        {"kind": "unavailable", "title": "Offroad Screensaver", "reason": UNAVAILABLE["Offroad Screensaver"]},
      ]
    raise ValueError("Unknown Device Controls page")

  def active_keys(self):
    return [r["key"] for r in self.rows() if r.get("kind") in ("toggle", "number")]

  def consume_timeout(self, onroad=False):
    stock = self.STOCK_TIMEOUT_ONROAD if onroad else self.STOCK_TIMEOUT_OFFROAD
    return screen_timeout(self.store, onroad, stock)

  def consume_brightness(self, onroad=False, stock=None, attention=False):
    return screen_brightness(self.store, onroad, self.STOCK_BRIGHTNESS if stock is None else stock, attention)

  def consume_awake(self, ignition=False, timed_out=True, pc=False, attention=False):
    return screen_awake(self.store, ignition, timed_out, pc, attention)

  def consume_shutdown(self, stock=None):
    return shutdown_time(self.store, self.STOCK_SHUTDOWN_S if stock is None else stock)

  def consume_voltage(self, stock=None):
    return voltage_cutoff(self.store, self.STOCK_VOLTAGE if stock is None else stock)

  def run_action(self, action):
    if not self.allowed():
      self.status = "Offroad supported device required; no changes made."
      return False
    if action == "start_recording":
      outcome = self.recorder_start()
      self.status = outcome if isinstance(outcome, str) else "Start requested."
      return True
    if action == "stop_recording":
      outcome = self.recorder_stop()
      self.status = outcome if isinstance(outcome, str) else "Stop requested."
      return True
    raise ValueError("Unknown action")


def create_device_controls_layout(store=None, runtime_hooks=True, show_header=False):
  """Raylib Device Controls page for nesting under System Settings (sysData parent).

  runtime_hooks=True shows numeric/screen toggles as editable only when INT has
  applied PROPOSED_shared.patch. When False, masters still save but numeric rows
  explain that runtime integration is pending (no fake working claim).
  """
  import pyray as rl
  from openpilot.common.hardware import HARDWARE, PC
  from openpilot.common.params import Params
  from openpilot.common.bogpilot_store import ParamStore
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.selfdrive.ui.onroad.bogpilot.screen_recorder import recorder
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import button_item, text_item, toggle_item
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
  from openpilot.system.ui.widgets import DialogResult
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  params = Params()
  base = store if store is not None else ParamStore(params)
  offroad = ui_state.is_offroad
  capable = lambda: (not PC) and HARDWARE.get_device_type() in {"tici", "tizi", "mici"}
  menu = DeviceControlsMenu(
    store=base, offroad=offroad, capable=capable,
    recorder_start=lambda: ("Recording started." if recorder().engine.start() else "Recorder refused to start."),
    recorder_stop=lambda: (recorder().stop() or "Recording stopped."),
  )

  class DeviceControlsLayout(Widget):
    def __init__(self):
      super().__init__()
      self._visible = False
      self._dirty = False
      self._header = button_item(lambda: tr(menu.title), lambda: tr("BACK"),
                                 callback=self.back, enabled=lambda: bool(menu.path))
      self._scroller = self.make_scroller()

    @property
    def navigation_title(self):
      return menu.title

    def navigation_back(self):
      if menu.path:
        menu.back()
        self.rebuild()
        return True
      return False

    def allowed(self):
      return menu.allowed()

    def back(self):
      menu.back()
      self.rebuild()

    def go(self, title):
      menu.go(title)
      self.rebuild()

    def rebuild(self):
      if self._visible:
        self._scroller.hide_event()
      self._scroller = self.make_scroller()
      if self._visible:
        self._scroller.show_event()
      self._dirty = False

    def put(self, key, value):
      menu.set(key, value)
      self._dirty = True

    def number(self, key, title):
      lo, hi, step = RANGES[key]
      values = [round(lo + i * step, 1) for i in range(round((hi - lo) / step) + 1)]

      def label(value):
        n = int(value) if float(value).is_integer() else float(value)
        if key == "DeviceShutdown":
          return shutdown_label(n)
        if "Brightness" in key:
          return "Auto" if int(n) == 101 else f"{int(n)}%"
        if "Timeout" in key:
          return f"{int(n)} s"
        if key == "LowVoltageShutdown":
          return f"{float(n):.1f} V"
        return str(n)

      current = menu.store.raw(key)
      current_f = float(current) if current is not None else float(DEFAULTS[key])

      def open_dialog():
        if not self.allowed():
          menu.status = "Offroad supported device required; no changes made."
          self._dirty = True
          return
        choices = [label(v) for v in values]
        dialog = MultiOptionDialog(tr(title), choices)
        # preselect nearest
        try:
          idx = min(range(len(values)), key=lambda i: abs(values[i] - current_f))
          dialog.selection = choices[idx]
        except Exception:
          pass

        def done(result):
          if result == DialogResult.CONFIRM and dialog.selection in choices:
            self.put(key, values[choices.index(dialog.selection)])
            self.rebuild()

        dialog._callback = done
        gui_app.push_widget(dialog)

      desc = "Requires parent setting enabled. Brightness: next UI frame (filtered). Timeout: next interaction/alert reset. Power: next hardwared check; existing shutdown guards remain."
      if not runtime_hooks:
        return text_item(lambda: tr(title), lambda: tr("Runtime integration pending"),
                         lambda: tr("Preference not advertised as working until PROPOSED ui_state/power hooks land."))
      return attach_help(button_item(lambda: tr(title), lambda: tr(label(current_f)), lambda: tr(desc),
                                     callback=open_dialog, enabled=self.allowed), key)

    def make_scroller(self):
      items = []
      if not menu.path:
        for title in ("Device Settings", "Screen Settings"):
          items.append(attach_help(button_item(lambda t=title: tr(t), lambda: tr("MANAGE"),
                                               callback=lambda t=title: self.go(t)), "system:" + title))
      elif menu.path[-1] == "Device Settings":
        items.append(attach_help(toggle_item(lambda: tr("Device Settings"),
                                             lambda: tr("Master for shutdown timer and low-voltage cutoff. Off keeps stock power protection."),
                                             menu.store.get_bool(DEVICE_MASTER, False),
                                             callback=lambda v: self.put(DEVICE_MASTER, v), enabled=self.allowed),
                                 "system:Device Settings"))
        if runtime_hooks:
          items += [self.number("DeviceShutdown", "Device Shutdown Timer"),
                    self.number("LowVoltageShutdown", "Low-Voltage Cutoff")]
        else:
          items += [text_item("Device Shutdown Timer", "Runtime integration pending"),
                    text_item("Low-Voltage Cutoff", "Runtime integration pending")]
        for title in ("Disable Logging", "High-Quality Recording", "Raise Temperature Limits"):
          items.append(text_item(lambda t=title: tr(t), lambda: tr("Unavailable"),
                                 lambda t=title: tr(UNAVAILABLE[t])))
      elif menu.path[-1] == "Screen Settings":
        items.append(attach_help(toggle_item(lambda: tr("Screen Settings"),
                                             lambda: tr("Master for brightness, timeout and standby. Off keeps stock display behavior."),
                                             menu.store.get_bool(SCREEN_MASTER, False),
                                             callback=lambda v: self.put(SCREEN_MASTER, v), enabled=self.allowed),
                                 "system:Screen Settings"))
        if runtime_hooks:
          items += [
            self.number("ScreenBrightness", "Screen Brightness (Offroad)"),
            self.number("ScreenBrightnessOnroad", "Screen Brightness (Onroad)"),
            self.number("ScreenTimeout", "Screen Timeout (Offroad)"),
            self.number("ScreenTimeoutOnroad", "Screen Timeout (Onroad)"),
            attach_help(toggle_item(lambda: tr("Standby Mode"),
                                    lambda: tr("Allow display sleep while ignition is on after timeout. Alerts and engagement changes wake."),
                                    menu.store.get_bool("StandbyMode", False),
                                    callback=lambda v: self.put("StandbyMode", v), enabled=self.allowed), "StandbyMode"),
          ]
        else:
          for title in ("Screen Brightness (Offroad)", "Screen Brightness (Onroad)",
                        "Screen Timeout (Offroad)", "Screen Timeout (Onroad)", "Standby Mode"):
            items.append(text_item(title, "Runtime integration pending"))
        items += [
          attach_help(button_item(lambda: tr("Screen Recorder"), lambda: tr("Start Recording"),
                                  callback=lambda: menu.run_action("start_recording"), enabled=self.allowed),
                      "ScreenRecorderControl"),
          attach_help(button_item(lambda: tr("Screen Recorder"), lambda: tr("Stop Recording"),
                                  callback=lambda: menu.run_action("stop_recording"), enabled=self.allowed),
                      "ScreenRecorderControl"),
          text_item(lambda: tr("Offroad Screensaver"), lambda: tr("Unavailable"),
                    lambda: tr(UNAVAILABLE["Offroad Screensaver"])),
        ]
      items.append(text_item(lambda: tr("Status"), lambda: tr(menu.status or "Ready; no changes made")))
      return Scroller(items, line_separator=True, spacing=0)

    def show_event(self):
      super().show_event()
      if not self._visible:
        self.rebuild()
        self._visible = True
        if show_header:
          self._header.show_event()
        self._scroller.show_event()

    def hide_event(self):
      if self._visible:
        self._scroller.hide_event()
        if show_header:
          self._header.hide_event()
        self._visible = False
      super().hide_event()

    def _render(self, rect):
      if self._dirty:
        self.rebuild()
      header_h = min(170, max(0, rect.height)) if show_header else 0
      if show_header:
        self._header.render(rl.Rectangle(rect.x, rect.y, max(0, rect.width), header_h))
      if rect.height > header_h and rect.width > 0:
        self._scroller.render(rl.Rectangle(rect.x, rect.y + header_h, rect.width, rect.height - header_h))

  return DeviceControlsLayout()


# Registration helper for sysData / INT (do not edit shared settings.py here).
REGISTRATION_HINT = '''
# sysData owns System Settings parent. Nest Device Controls like:
from openpilot.selfdrive.ui.bogpilot.phase3_device_controls import create_device_controls_layout
# inside System Settings page factory, after Data / before Utilities:
#   "Device Controls" -> create_device_controls_layout(runtime_hooks=True, show_header=False)
# Set runtime_hooks=True ONLY after applying PROPOSED_shared.patch (ui_state + power_monitoring).
'''
