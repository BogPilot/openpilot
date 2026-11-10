"""System Settings > Data submenu — local retention / storage / export only.

Cloud upload/telemetry intentionally absent. Device Controls and Utilities are
owned by sister lanes. Import-safe; no constructor default seeding.
"""
from openpilot.selfdrive.ui.bogpilot.phase3_system_settings_backend import (
  LocalData, SystemPreferences, DurableStore,
)
from openpilot.selfdrive.ui.bogpilot.phase3_system_settings_features import FeatureArchive, native_compatibility
from openpilot.selfdrive.ui.bogpilot.phase3_system_settings_feature_specs import FEATURE_SPECS, PROTECTED_EXCLUSIONS

PENDING = {
  "BogPilot Backups": "Code backup/restore needs a verified executable compatibility and rollback policy. Not implemented.",
}


def build_data_layout(*, params=None, store=None, offroad=None, capable=None, show_header=True,
                      compatibility=None, defaults=None, export_dir=None):
  """Build the Data submenu Widget. Parent System Settings owns outer navigation."""
  import json
  import threading
  import pyray as rl
  from openpilot.common.hardware import HARDWARE, PC
  from openpilot.common.params import Params
  from openpilot.common.bogpilot_store import ParamStore
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.selfdrive.ui.onroad.bogpilot.screen_recorder import recorder
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import Widget, DialogResult
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
  from openpilot.system.ui.widgets.keyboard import Keyboard
  from openpilot.system.ui.widgets.list_view import button_item, text_item
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help_first
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  params = params if params is not None else Params()
  store = store if store is not None else ParamStore(params)
  offroad = offroad or ui_state.is_offroad
  capable = capable or (lambda: not PC and HARDWARE.get_device_type() in {"tici", "tizi", "mici"})
  store = DurableStore(store, set(FEATURE_SPECS) | {"FrogPilotStats", "DebugMode", "LocalLoggingDisableConsent", "HighQualityRecordingConsent"})
  prefs = SystemPreferences(store, offroad, capable, stats_backup_dir="/data/bogpilot_stats_backups")
  data = LocalData(offroad, capable, recording=lambda: recorder().recording)

  def installed_compatibility():
    cp = getattr(ui_state, "CP", None)
    fingerprint = getattr(cp, "carFingerprint", None) if cp is not None else None
    if isinstance(fingerprint, bytes):
      fingerprint = fingerprint.decode("utf-8", "replace")
    return native_compatibility(store, fingerprint, HARDWARE.get_device_type())

  archives = FeatureArchive(prefs, compatibility or installed_compatibility, defaults=defaults)

  def human_bytes(n):
    n = int(n)
    for unit, scale in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
      if n >= scale:
        return f"{n / scale:.1f} {unit}"
    return f"{n} B"

  class DataSettingsLayout(Widget):
    def __init__(self):
      super().__init__()
      self.path = ("Data",)
      self.busy = False
      self.status = ""
      self._visible = False
      self._dirty = False
      self._preview = None
      self._header = button_item(lambda: tr(self.title), lambda: tr("BACK"), callback=self.back,
                                 enabled=lambda: len(self.path) > 1 and not self.busy)
      self._scroller = self.make_scroller()

    @property
    def title(self):
      return self.path[-1]

    @property
    def navigation_title(self):
      return self.title

    def navigation_back(self):
      if len(self.path) > 1 and not self.busy:
        self.back()
        return True
      return bool(self.busy)

    def allowed(self):
      return not self.busy and offroad() and capable()

    def unavailable(self, title):
      return text_item(lambda: tr(title), lambda: tr("Unavailable"), lambda: tr(PENDING[title]))

    def action(self, title, label, callback, description=""):
      return attach_help_first(
        button_item(lambda: tr(title), lambda: tr(label), lambda: tr(description),
                    callback=lambda: self.attempt(callback), enabled=self.allowed),
        f"data:{title}:{label}", f"data:{title}")

    def attempt(self, callback):
      if not self.allowed():
        self.status = "Offroad supported device required; no changes made."
        self._dirty = True
        return
      try:
        callback()
      except Exception as exc:
        self.status = f"Action refused or failed ({type(exc).__name__}); no success claimed."
        self._dirty = True

    def run(self, function):
      if not self.allowed():
        return
      self.busy = True
      self.status = "Working..."
      self._dirty = True

      def worker():
        try:
          prefs.guard()
          outcome = function()
          self.status = outcome if isinstance(outcome, str) else "Completed."
        except Exception as exc:
          self.status = f"Action failed ({type(exc).__name__}); may be partially complete."
        finally:
          self.busy = False
          self._dirty = True

      threading.Thread(target=worker, daemon=True).start()

    def confirm(self, question, function, label="Confirm"):
      if not self.allowed():
        return

      def done(result):
        if result == DialogResult.CONFIRM:
          self.attempt(lambda: self.run(function))

      gui_app.push_widget(ConfirmDialog(tr(question), tr(label), callback=done))

    def select(self, title, choices, callback):
      if not choices:
        self.status = "No matching local files."
        self._dirty = True
        return
      dialog = MultiOptionDialog(tr(title), list(choices))

      def done(result):
        if result == DialogResult.CONFIRM:
          self.attempt(lambda: callback(dialog.selection))

      dialog._callback = done
      gui_app.push_widget(dialog)

    def manage(self, title):
      return attach_help_first(
        button_item(lambda: tr(title), lambda: tr("MANAGE"), callback=lambda: self.go(title), enabled=lambda: not self.busy),
        f"data:{title}")

    def go(self, title):
      if not self.busy:
        self.path += (title,)
        self.rebuild()

    def back(self):
      if len(self.path) > 1 and not self.busy:
        self.path = self.path[:-1]
        self.rebuild()

    def rebuild(self):
      if self._visible:
        self._scroller.hide_event()
      self._scroller = self.make_scroller()
      if self._visible:
        self._scroller.show_event()
      self._dirty = False

    def recording_select(self, action):
      self.select("Screen Recordings", data.list_recordings(), action)

    def rename(self, selected):
      keyboard = Keyboard(max_text_size=150, min_text_size=1)
      keyboard.set_title(tr("Rename Screen Recording"))
      keyboard.set_text(selected[:-4])

      def done(result):
        if result == DialogResult.CONFIRM:
          new = keyboard.text
          self.attempt(lambda: self.confirm(
            "Rename this screen recording? Existing files will never be overwritten.",
            lambda: data.rename_recording(selected, new), "Rename"))

      keyboard.set_callback(done)
      gui_app.push_widget(keyboard)

    def preview_restore(self, selected):
      self._preview = archives.preview(selected)
      self.go("Preview Changes")

    def backup_select(self, callback):
      self.select("Toggle Backups", archives.list(), callback)

    def do_export_stats(self):
      if export_dir is None:
        raise RuntimeError("Export directory not configured by integrator")
      path = prefs.export_stats(export_dir)
      return f"Exported stats to {path}"

    def make_scroller(self):
      title = self.title
      if title == "Data":
        items = [
          self.action("Delete Driving Data", "DELETE", lambda: self.confirm(
            "Delete all unpreserved local driving data and footage? Preserved drives are kept.",
            lambda: data.delete("driving"), "Delete")),
          self.action("Delete Error Logs", "DELETE", lambda: self.confirm(
            "Delete all local error logs?", lambda: data.delete("errors"), "Delete")),
        ]
        items += [self.manage(t) for t in (
          "Screen Recordings", "Storage Use", "BogPilot Backups", "Toggle Backups", "BogPilot Stats")]
      elif title == "Screen Recordings":
        items = [
          self.action("Screen Recordings", "DELETE", lambda: self.recording_select(lambda n: self.confirm(
            "Delete this screen recording?", lambda: data.delete("recordings", n), "Delete"))),
          self.action("Screen Recordings", "DELETE ALL", lambda: self.confirm(
            "Delete all completed local screen recordings?",
            lambda: data.delete("recordings"), "Delete All")),
          self.action("Screen Recordings", "RENAME", lambda: self.recording_select(self.rename),
                      "Recording must be stopped. Active locks/partial files block management."),
        ]
      elif title == "Storage Use":
        try:
          usage = data.storage_use()
          labels = {
            "driving": "Driving Data",
            "errors": "Error Logs",
            "recordings": "Screen Recordings",
          }
          items = [text_item(labels.get(k, k), f"{human_bytes(v['bytes'])} across {v['roots_present']} root(s)")
                   for k, v in usage.items()]
          total = sum(v["bytes"] for v in usage.values())
          items.append(text_item("Total local data", human_bytes(total)))
        except Exception as exc:
          items = [text_item("Storage Use", f"Unavailable ({type(exc).__name__})")]
      elif title == "BogPilot Backups":
        items = [self.unavailable("BogPilot Backups")]
      elif title == "Toggle Backups":
        items = [
          attach_help_first(
            text_item("Scope", f"{len(FEATURE_SPECS)} audited nonsecret feature preferences",
                      "Exact installed-source/schema/platform/vehicle compatibility required. "
                      "Security/calibration/identity/DM/cloud/policy keys excluded. No cloud upload."),
            "data:Toggle Backups.scope"),
          self.action("Toggle Backups", "BACKUP", lambda: self.run(archives.backup)),
          self.action("Toggle Backups", "DELETE", lambda: self.backup_select(lambda n: self.confirm(
            "Delete this compatible feature-toggle backup?", lambda: archives.delete(n), "Delete"))),
          self.action("Toggle Backups", "DELETE ALL", lambda: self.confirm(
            "Delete all validated feature-toggle backups? Old/system/executable archives are kept.",
            archives.delete, "Delete All")),
          self.action("Toggle Backups", "RESTORE", lambda: self.backup_select(self.preview_restore)),
        ]
      elif title == "Preview Changes":
        plan = self._preview
        items = [text_item("Baseline", plan["reason"]), text_item("Affected keys", str(len(plan["changes"])))]
        items += [text_item(f"{FEATURE_SPECS[k]['title']} ({k})",
                            f"{v['from'] if v['from'] is not None else 'Inherited'} -> {v['to'] if v['to'] is not None else 'Inherited'}")
                  for k, v in sorted(plan["changes"].items())]
        items += [text_item("Protected: " + k, reason) for k, reason in sorted(PROTECTED_EXCLUSIONS.items())]
        items.append(self.action("Apply Preview", "CONFIRM", lambda: self.confirm(
          "Apply ONLY the listed compatible preference changes? A durable pre-change backup is mandatory. "
          "Driving behavior preferences may change. Protected security/calibration/car identity/DM/cloud keys are excluded. "
          "No restart or reboot is performed.",
          lambda: archives.apply_preview(plan), "Apply Changes")))
      elif title == "BogPilot Stats":
        items = [
          self.action("BogPilot Stats", "RESET", lambda: self.confirm(
            "Reset collected BogPilot stats? Driving logs and recordings are kept.",
            prefs.reset_stats, "Reset")),
          self.manage("View Stats"),
        ]
        if export_dir is not None:
          items.append(self.action("BogPilot Stats", "EXPORT", lambda: self.confirm(
            "Export a local JSON copy of BogPilot stats? No upload or network action occurs.",
            self.do_export_stats, "Export"),
            "Local file only; overwrite refused; path set by integrator/tests."))
      elif title == "View Stats":
        try:
          stats = prefs.stats()
          items = [text_item(str(k), json.dumps(v, ensure_ascii=False)[:300]) for k, v in list(stats.items())[:500]]
          items = items or [text_item("BogPilot Stats", "No local stats recorded")]
        except (ValueError, TypeError):
          items = [text_item("BogPilot Stats", "Stored stats invalid; not overwritten")]
      else:
        raise ValueError(f"Unknown Data page: {title}")
      items.append(text_item(lambda: tr("Status"), lambda: tr(self.status or "Ready; no changes made")))
      return Scroller(items, line_separator=True, spacing=0)

    def show_event(self):
      super().show_event()
      if not self._visible:
        self.rebuild()
        self._visible = True
        self._header.show_event()
        self._scroller.show_event()

    def hide_event(self):
      if self._visible:
        self._scroller.hide_event()
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

  return DataSettingsLayout()
