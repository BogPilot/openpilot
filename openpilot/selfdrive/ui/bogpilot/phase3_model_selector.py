"""Driving Models UI boundary. No Params, catalog, downloader or inference claims here.

A backend adapter must provide atomic snapshots and revalidate requests offroad.
The adapter is deliberately injected, never inferred from legacy model parameters.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Model:
  id: str
  name: str
  available: bool
  downloaded: bool  # all artifacts verified, not mere file existence
  compatible: bool | None  # None = not validated; must never be selectable
  reason: str = ""
  protected: bool = False
  blacklisted: bool = False
  rating: str = "Ratings unavailable"


@dataclass(frozen=True)
class Snapshot:
  revision: str  # changes whenever catalog, compatibility or runtime status changes
  models: tuple[Model, ...]
  capabilities: frozenset[str]
  active_id: str | None = None  # acknowledged by running inference, NOT requested Params
  pending_id: str | None = None
  automatic: bool = False
  randomizer: bool = False
  busy: bool = False
  progress: str = ""
  error: str = ""
  limitation: str = ""  # e.g. Only the stock model is currently validated


@dataclass(frozen=True)
class Result:
  accepted: bool
  message: str  # acceptance is not activation; active_id remains authoritative


class ModelBackend(Protocol):
  def snapshot(self) -> Snapshot: ...
  def request(self, action: str, model_id: str | None, revision: str) -> Result:
    """Nonblocking; atomically recheck revision, offroad, capabilities and artifacts.

    select queues activation; report pending until runtime acknowledgement.
    Never return accepted if an alternate cannot actually be loaded by inference.
    """
    ...


# Exact seven rows/order from approved 04d560f3 model_settings.cc.
ITEMS = (
  ("automatic", "Automatically Download New Models"),
  ("delete", "Delete Driving Models"),
  ("download", "Download Driving Models"),
  ("randomizer", "Model Randomizer"),
  ("blacklist", "Manage Model Blacklist"),
  ("ratings", "Manage Model Ratings"),
  ("select", "Select Driving Model"),
)
OPERATIONS = {
  "automatic": ("automatic_on", "automatic_off"),
  "delete": ("delete", "delete_all"),
  "download": ("download", "download_all", "cancel"),
  "randomizer": ("randomizer_on", "randomizer_off"),
  "blacklist": ("blacklist_add", "blacklist_remove", "blacklist_clear"),
  "ratings": ("ratings_reset",),
  "select": ("select",),
}
TARGETED = frozenset(("select", "download", "delete", "blacklist_add", "blacklist_remove"))
ALL_ACTIONS = frozenset(a for actions in OPERATIONS.values() for a in actions)


class ModelSelector:
  def __init__(self, backend: ModelBackend, is_offroad):
    self.backend = backend
    self.is_offroad = is_offroad  # authoritative live predicate, not cached at page entry
    self.message = ""
    self.state = None
    self.refresh()

  def visible_items(self):
    """Only rows with a real consumer: Select always (shows Default (stock)); others only when the
    backend advertises one of their operations. No inert rows, no rating placeholders."""
    caps = self.state.capabilities if self.state else frozenset()
    return tuple((key, title) for key, title in ITEMS
                 if key == "select" or any(a in caps for a in OPERATIONS[key]))

  def refresh(self):
    try:
      state = self.backend.snapshot()
      ids = [m.id for m in state.models]
      if len(ids) != len(set(ids)) or any(not mid for mid in ids):
        raise ValueError("Invalid model IDs from backend")
      if any(mid is not None and mid not in ids for mid in (state.active_id, state.pending_id)):
        raise ValueError("Runtime model is absent from catalog")
      self.state = state
    except Exception as exc:
      self.state = None  # never keep stale actionable data on failure
      self.message = f"Model backend unavailable: {exc}"
    return self.state

  def allowed(self, action, model_id=None):
    s = self.state
    if not s:
      return False, "Model backend unavailable"
    if action not in ALL_ACTIONS or action not in s.capabilities:
      return False, "Not supported by the current model backend"
    try:
      offroad = self.is_offroad()
    except Exception:
      return False, "Offroad state unavailable"
    if offroad is not True:
      return False, "Offroad only"
    if s.busy and action != "cancel":
      return False, "Model operation in progress"
    if action == "cancel" and not s.busy:
      return False, "No operation in progress"
    if action == "randomizer_on" and sum(m.downloaded and m.compatible is True and not m.blacklisted for m in s.models) < 2:
      return False, "Randomizer requires at least two verified compatible models"
    if action in TARGETED:
      m = next((m for m in s.models if m.id == model_id), None)
      if m is None:
        return False, "Model no longer available"
      if action in ("select", "download", "blacklist_add") and m.compatible is not True:
        return False, m.reason or "Compatibility has not been validated"
      if action == "select":
        if not m.downloaded:
          return False, "Download and verify model artifacts first"
        if m.id in (s.active_id, s.pending_id):
          return False, "Already active or pending"
      if action == "download" and (not m.available or m.downloaded):
        return False, "Not available for download"
      if action == "delete" and (not m.downloaded or m.protected or m.id in (s.active_id, s.pending_id)):
        return False, "Active, pending and protected models cannot be deleted"
      if action == "blacklist_add" and m.blacklisted:
        return False, "Already blacklisted"
      if action == "blacklist_remove" and not m.blacklisted:
        return False, "Not blacklisted"
    return True, ""

  def execute(self, action, model_id=None, expected_revision=None):
    self.refresh()  # includes confirmation-to-execution race recheck
    if expected_revision is not None and self.state and self.state.revision != expected_revision:
      self.message = "Model state changed. Review and confirm again."
      return False
    ok, reason = self.allowed(action, model_id)
    if not ok:
      self.message = reason
      return False
    try:
      result = self.backend.request(action, model_id, self.state.revision)
      self.message = result.message
      self.refresh()
      return result.accepted
    except Exception as exc:
      self.message = f"Model operation failed: {exc}"
      self.refresh()
      return False

  def status(self):
    s = self.state
    if not s:
      return self.message
    names = {m.id: m.name for m in s.models}
    return " | ".join(filter(None, (
      f"Active: {names.get(s.active_id, 'Not confirmed')}",
      f"Pending: {names[s.pending_id]}" if s.pending_id else "",
      s.limitation, s.progress, s.error, self.message,
    )))

  def model_status(self, m):
    s = self.state
    flags = ["Available" if m.available else "Unavailable",
             "Downloaded / verified" if m.downloaded else "Not downloaded",
             "Compatible" if m.compatible is True else "Incompatible" if m.compatible is False else "Compatibility unknown"]
    if s and m.id == s.active_id:
      flags.append("Active (runtime confirmed)")
    if s and m.id == s.pending_id:
      flags.append("Pending activation")
    if m.reason:
      flags.append(m.reason)
    return "; ".join(flags)


def create_model_selector_layout(controller: ModelSelector):
  """Create a native raylib Widget; imports deferred so contract tests need no GUI."""
  import time
  from openpilot.system.ui.widgets import Widget, DialogResult
  from openpilot.system.ui.widgets.list_view import button_item, text_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr

  class ModelSelectorLayout(Widget):
    def __init__(self):
      super().__init__()
      self.section = None
      self.last_refresh = 0
      self.signature = None
      self.rebuild()

    def open_section(self, section):
      self.section = section
      self.rebuild()

    def confirm(self, action, model_id=None):
      controller.refresh()
      ok, reason = controller.allowed(action, model_id)
      if not ok:
        controller.message = reason
        return
      revision = controller.state.revision
      model = next((m.name for m in controller.state.models if m.id == model_id), "")
      def confirmed(result):
        if result == DialogResult.CONFIRM:
          controller.execute(action, model_id, revision)
        self.rebuild()
      gui_app.push_widget(ConfirmDialog(tr(f"Confirm {action.replace('_', ' ')} {model}?"), tr("Confirm"), callback=confirmed))

    def rebuild(self):
      controller.refresh()
      s = controller.state
      status = text_item(tr("Driving Models"), "", lambda: controller.status())
      status.description_visible = True
      items = [status]
      if self.section is None:
        for key, title in controller.visible_items():
          items.append(button_item(tr(title), tr("OPEN"), callback=lambda k=key: self.open_section(k)))
      else:
        items.append(button_item(tr("Driving Models"), tr("BACK"), callback=lambda: self.open_section(None)))
        if s:
          key = self.section
          if key == "ratings":
            for m in s.models:
              items.append(text_item(m.name, m.rating))
          if key in ("automatic", "randomizer"):
            value = s.automatic if key == "automatic" else s.randomizer
            items.append(text_item(tr("Current setting"), tr("On") if value else tr("Off")))
          for action in OPERATIONS[key]:
            targets = s.models if action in TARGETED else (None,)
            for m in targets:
              mid = m.id if m else None
              title = m.name if m else action.replace("_", " ").title()
              enabled, reason = controller.allowed(action, mid)
              desc = controller.model_status(m) if m else ""
              if reason:
                desc = f"{desc}; {reason}" if desc else reason
              item = button_item(title, tr(action.split("_")[-1].upper()), desc,
                                 callback=lambda a=action, i=mid: self.confirm(a, i),
                                 enabled=lambda a=action, i=mid: controller.allowed(a, i)[0])
              item.description_visible = True
              items.append(item)
      self.scroller = Scroller(items, line_separator=True, spacing=0)
      self.signature = (s, self.section, controller.message, self.offroad())

    def offroad(self):
      try:
        return controller.is_offroad() is True
      except Exception:
        return False

    def show_event(self):
      super().show_event()
      self.rebuild()
      self.scroller.show_event()

    def _render(self, rect):
      if time.monotonic() - self.last_refresh > 1:
        self.last_refresh = time.monotonic()
        controller.refresh()
        signature = (controller.state, self.section, controller.message, self.offroad())
        if signature != self.signature:
          self.rebuild()
      self.scroller.render(rect)

  return ModelSelectorLayout()
