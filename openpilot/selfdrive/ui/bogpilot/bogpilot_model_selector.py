"""BogPilot > Driving Controls > Driving Model.

The controller is pure Python (no raylib). The layout factory imports raylib only when the page is built.
"""
from __future__ import annotations

from dataclasses import dataclass

from openpilot.common.bogpilot_models import STOCK_ID, STOCK_NAME, TARGET_OPENPILOT, alert, registry, selection
from openpilot.common.bogpilot_models.stock import STOCK_HASHES

PAGE_KEY = "driving_model"
PAGE_TITLE = "Driving Model"
CONTROLS = ("driving_model",)

ONLY_DEFAULT_TEXT = "Only the Default (stock) driving model is installed. Models you install later appear here."
SELECT_LABEL = "SELECT"
SELECTED_LABEL = "SELECTED"
_REFRESH_S = 1.0


@dataclass(frozen=True)
class Row:
  id: str
  title: str
  detail: str
  selected: bool
  active: bool
  selectable: bool
  problem: str


@dataclass(frozen=True)
class Snapshot:
  rows: tuple[Row, ...]
  status: str
  only_default: bool
  notice: str
  offroad: bool


def row_description(snapshot: Snapshot, row: Row) -> str:
  """Text under a model row. The active model is marked only on the interactive page."""
  if snapshot.only_default or not row.active:
    return row.detail
  return f"{row.detail} | Active"


def ui_text(snapshot: Snapshot) -> list[str]:
  """Exact strings the page shows, in order. No raylib."""
  lines = [snapshot.status]
  if snapshot.only_default:
    lines.append(ONLY_DEFAULT_TEXT)
    for row in snapshot.rows:
      lines.append(row.title)
      lines.append(row.detail)
    return lines
  if snapshot.notice:
    lines.append(snapshot.notice)
  for row in snapshot.rows:
    lines.append(row.title)
    lines.append(row_description(snapshot, row))
    lines.append(SELECTED_LABEL if row.selected else SELECT_LABEL)
  return lines


class ModelSelectorController:
  """Offroad driving-model choice. Never raises; backend failures become status text."""

  def __init__(self, is_offroad, store=None, root=None, cache=None):
    self.is_offroad = is_offroad
    self.store = store
    self.root = root
    # Shared with validate_entry, which stores hashes and Validation objects here.
    self.cache = {} if cache is None else cache
    self.message = ""
    self.snapshot = Snapshot((), "", False, "", False)

  def refresh(self) -> Snapshot:
    try:
      snap = self._build()
    except Exception as exc:
      snap = Snapshot((), f"Driving model list failed ({type(exc).__name__}).", False, "", self._offroad())
    self.snapshot = snap
    return snap

  def select(self, model_id) -> selection.SelectResult:
    try:
      # select() re-validates the files itself and does not reuse cached Validation objects.
      result = selection.select(model_id, self.is_offroad, self.store, self.root, self.cache)
    except Exception as exc:
      result = selection.SelectResult(False, f"Driving model was not changed ({type(exc).__name__}).")
    self.message = result.message
    self.refresh()
    return result

  def _offroad(self) -> bool:
    try:
      return self.is_offroad() is True
    except Exception:
      return False

  def _compat(self, entry: registry.Entry) -> tuple[bool, str, str]:
    """(valid, problem, compat status). The built-in Default is valid without hashing."""
    if entry.builtin:
      return True, "", f"Ships with openpilot {TARGET_OPENPILOT}"
    result = registry.validate_entry(entry, self.cache)
    if result.ok:
      return True, "", f"Compatible with {TARGET_OPENPILOT}"
    problem = result.reason or entry.problem or "invalid"
    return False, problem, f"Not usable: {problem}"

  def _name(self, entries, model_id: str, fallback: str) -> str:
    for entry in entries:
      if entry.id == model_id and entry.name:
        return entry.name
    if model_id == STOCK_ID:
      return STOCK_NAME
    return fallback or model_id

  def _detail(self, entry: registry.Entry, compat: str) -> str:
    if entry.builtin:
      short = STOCK_HASHES["driving_tinygrad.pkl"][:12]
      return f"Built in | License {entry.license} | model {short} | {compat}"
    if entry.manifest is None:
      return compat  # invalid manifest: there is no version/license/hash to show, only why it is unusable
    short = (entry.model_sha256 or "")[:12]
    return f"Version {entry.version} | License {entry.license} | model {short} | {compat}"

  def _build(self) -> Snapshot:
    offroad = self._offroad()
    entries = registry.list_entries(self.root)
    state = selection.read_state(self.store)
    chosen, corrupt = selection.read_selection(self.store)
    known = {entry.id for entry in entries}
    selected_id = STOCK_ID
    if not corrupt and chosen is not None and chosen.id in known:
      selected_id = chosen.id
    found = alert.current_alert(self.store)
    notice = found["text"] if isinstance(found, dict) and isinstance(found.get("text"), str) else ""
    blocked = bool(notice)  # the saved choice failed at its last start: Default is in use until the user chooses again
    if blocked:
      selected_id = None
    active_raw = state.get("active") if isinstance(state.get("active"), dict) else {}
    active_id = active_raw.get("id") if isinstance(active_raw.get("id"), str) and active_raw.get("id") else STOCK_ID
    active_fallback = active_raw.get("name") if isinstance(active_raw.get("name"), str) else ""
    active_name = self._name(entries, active_id, active_fallback)
    selected_name = self._name(entries, selected_id if selected_id is not None else STOCK_ID, "")

    rows = []
    for entry in entries:
      valid, problem, compat = self._compat(entry)
      rows.append(Row(
        id=entry.id,
        title=entry.name,
        detail=self._detail(entry, compat),
        selected=entry.id == selected_id,
        active=entry.id == active_id,
        selectable=bool(offroad and valid and entry.id != selected_id),  # blocked: every valid row, so the user can retry or dismiss
        problem=problem,
      ))

    status = f"Active: {active_name}"
    if (selected_id if selected_id is not None else STOCK_ID) != active_id:
      status += f" | Next drive: {selected_name}"
    if not offroad:
      status += " | Changes apply offroad only"
    only_default = len(entries) == 1 and entries[0].id == STOCK_ID
    return Snapshot(tuple(rows), status, only_default, notice, offroad)


def create_driving_model_layout(controller=None):
  import time

  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import DialogResult, Widget
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.list_view import button_item, text_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

  if controller is None:
    from openpilot.selfdrive.ui.ui_state import ui_state
    controller = ModelSelectorController(ui_state.is_offroad)

  class DrivingModelLayout(Widget):
    def __init__(self):
      super().__init__()
      self.controller = controller
      self.scroller = None
      self._snapshot = None
      self._open_desc = []
      self._refreshed_at = 0.0
      self._visible = False

    def _refresh_ui(self, force):
      now = time.monotonic()
      if not force and (now - self._refreshed_at) < _REFRESH_S:
        return
      self._refreshed_at = now
      snap = self.controller.refresh()
      if snap != self._snapshot:
        self._snapshot = snap
        self._rebuild()
        self._reveal()

    def _rebuild(self):
      snap = self._snapshot
      items = []
      self._open_desc = []
      if snap.only_default:
        # Status, one explanation, and the Default row. No buttons and no empty sections.
        items.append(attach_help(text_item(snap.status, ""), "driving_model.status"))
        items.append(attach_help(text_item(ONLY_DEFAULT_TEXT, ""), "driving_model.status"))
        for row in snap.rows:
          item = text_item(row.title, "", row.detail or None)
          attach_help(item, "driving_model.default" if row.id == STOCK_ID else "driving_model.entry",
                      extra=lambda r=row: r.detail)
          items.append(item)
          if row.detail:
            self._open_desc.append(item)
      else:
        status = text_item(snap.status, "", snap.notice or None)
        attach_help(status, "driving_model.status", extra=lambda: snap.notice)
        items.append(status)
        if snap.notice:
          self._open_desc.append(status)
        for row in snap.rows:
          desc = row_description(snap, row)
          if row.selected:
            item = text_item(row.title, tr(SELECTED_LABEL), desc or None)
          else:
            item = button_item(
              row.title,
              tr(SELECT_LABEL),
              desc or None,
              callback=lambda mid=row.id, name=row.title: self._confirm(mid, name),
              enabled=row.selectable,
            )
          attach_help(item, "driving_model.default" if row.id == STOCK_ID else "driving_model.entry",
                      extra=lambda r=row: r.detail)
          items.append(item)
          if row.active and desc:
            self._open_desc.append(item)
      self.scroller = Scroller(items, line_separator=True, spacing=0)

    def _reveal(self):
      for item in self._open_desc:
        try:
          item._set_description_visible(True)
        except Exception:
          item.description_visible = True

    def _confirm(self, model_id, name):
      row = next((r for r in (self._snapshot.rows if self._snapshot else ()) if r.id == model_id), None)
      if row is None or not row.selectable:
        return
      prompt = (f"Use {name} from the next drive? It is checked again at start and "
                "the Default (stock) model is used if it fails.")

      def on_result(result):
        if result != DialogResult.CONFIRM:
          return
        self.controller.select(model_id)
        self._refreshed_at = time.monotonic()
        snap = self.controller.snapshot
        if snap != self._snapshot:
          self._snapshot = snap
          self._rebuild()
          self._reveal()

      gui_app.push_widget(ConfirmDialog(tr(prompt), tr("Confirm"), callback=on_result))

    def show_event(self):
      super().show_event()
      # Opening the page refreshes once. Later show_event calls share the one-second cap.
      self._refresh_ui(force=not self._visible)
      self._visible = True
      if self.scroller is not None:
        self.scroller.show_event()
      self._reveal()

    def hide_event(self):
      if self._visible and self.scroller is not None:
        self.scroller.hide_event()
      self._visible = False
      super().hide_event()

    def _render(self, rect):
      self._refresh_ui(force=False)
      if self.scroller is not None:
        self.scroller.render(rect)

  return DrivingModelLayout()
