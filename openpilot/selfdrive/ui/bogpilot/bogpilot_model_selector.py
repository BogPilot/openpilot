"""BogPilot > Driving Controls > Driving Model.

The controller is pure Python (no raylib). The layout factory imports raylib only when the page is built.
"""
from __future__ import annotations

from dataclasses import dataclass

from openpilot.common.bogpilot_models import STOCK_ID, STOCK_NAME, TARGET_OPENPILOT, alert, installer, registry, selection, source
from openpilot.common.bogpilot_models.stock import STOCK_HASHES

PAGE_KEY = "driving_model"
PAGE_TITLE = "Driving Model"
CONTROLS = ("driving_model",)

ONLY_DEFAULT_TEXT = "Only the Default (stock) driving model is installed. Models you install later appear here."
SELECT_LABEL = "SELECT"
SELECTED_LABEL = "SELECTED"
DOWNLOAD_LABEL = "DOWNLOAD"
INLINE_TITLE = "Driving Model"
INLINE_DESC = ("Step through the usable models with - and +. A change is confirmed first, can only be made while the car "
               "is off, and applies from the next drive.")
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
  choices: tuple[tuple[str, str], ...] = ()  # (id, name) of every usable model, Default first: the inline row's values
  pick: str = STOCK_ID                       # id the inline row shows (the saved choice, Default when blocked)
  downloads: tuple[tuple[str, str, str], ...] = ()  # (id, name, detail) of hosted models not installed yet
  can_download: bool = False                 # the strict offroad gate (download_gate) is open


def row_description(snapshot: Snapshot, row: Row) -> str:
  """Text under a model row. The active model is marked only on the interactive page."""
  if snapshot.only_default or not row.active:
    return row.detail
  return f"{row.detail} | Active"


def inline_text(snapshot: Snapshot) -> list[str]:
  """The inline Driving Model row ([-] name [+], Alert Volume style), or nothing when only Default is installed."""
  if snapshot.only_default:
    return []
  name = next((n for i, n in snapshot.choices if i == snapshot.pick), STOCK_NAME)
  return [INLINE_TITLE, f"- {name} +"]


def step_target(snapshot: Snapshot, direction: int) -> str | None:
  """Neighbour of the shown pick among the usable models (no wrap). None at either end or when nothing else is usable."""
  ids = [i for i, _ in snapshot.choices]
  if len(ids) < 2 or direction not in (-1, 1):
    return None
  cur = ids.index(snapshot.pick) if snapshot.pick in ids else 0
  nxt = cur + direction
  return ids[nxt] if 0 <= nxt < len(ids) else None


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
  """Driving-model choice. Never raises; backend failures become status text.

  `is_offroad` is the edit gate. The page passes onroad_policy.editor("driving_model") (0.9.7 Model: reboot-prompt
  class), so a choice can be recorded while driving; it never switches the running model: it applies from the next
  drive start (selection.select + the per-drive latch in resolve), and `started` says whether to tell the user.
  `on_change` runs after a successful choice (the reboot prompt).

  `download_gate` is stricter: a download (network + disk writes) runs only while the car is off. The page passes
  offroad_gate(); tests pass their own."""

  def __init__(self, is_offroad, store=None, root=None, cache=None, started=None, on_change=None, catalog=None,
               transport=None, download_gate=None):
    self.is_offroad = is_offroad
    self.download_gate = download_gate or (lambda: False)  # no gate given: downloads are refused
    self.catalog = catalog        # None: source.CATALOG (empty until we publish a model on our GitHub releases)
    self.transport = transport    # None: installer.https_transport
    self.started = started or (lambda: False)
    self.on_change = on_change or (lambda: None)
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
      # Block param writes here as well as in selection.select: the page must not start a write while onroad.
      try:
        offroad = self.is_offroad() is True
      except Exception:
        result = selection.SelectResult(False, "Cannot confirm the car is off, so the driving model was not changed.")
      else:
        if not offroad:
          result = selection.SelectResult(False, "Driving model can only be changed while the car is off (offroad).")
        else:
          # select() re-validates the files itself and does not reuse cached Validation objects.
          result = selection.select(model_id, self.is_offroad, self.store, self.root, self.cache)
    except Exception as exc:
      result = selection.SelectResult(False, f"Driving model was not changed ({type(exc).__name__}).")
    self.message = result.message
    self.refresh()
    if getattr(result, "ok", False):
      try:
        self.on_change()
      except Exception:
        pass
    return result

  def step(self, direction: int) -> str | None:
    """Model id the inline row's - (-1) or + (+1) would pick, or None. Does not select anything."""
    try:
      return step_target(self.refresh(), direction)
    except Exception:
      return None

  def download(self, model_id) -> installer.InstallResult:
    """Fetch, verify and install one hosted model (offroad only). The saved choice is not changed."""
    try:
      item = next((i for i in self._catalog() if isinstance(i, dict) and i.get("id") == model_id), None)
      if item is None:
        result = installer.InstallResult(False, "That model is not offered for download.", str(model_id))
      else:
        result = installer.install(item, self.download_gate, self.transport, self.root, self.cache)
    except Exception as exc:
      result = installer.InstallResult(False, f"Driving model was not downloaded ({type(exc).__name__}).", str(model_id))
    self.message = result.message
    self.refresh()
    return result

  def _catalog(self) -> tuple:
    items = source.CATALOG if self.catalog is None else self.catalog
    return tuple(i for i in items if installer.screen(i) == "")

  def _offroad(self) -> bool:
    try:
      return self.is_offroad() is True
    except Exception:
      return False

  def _started(self) -> bool:
    try:
      return bool(self.started())
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
    onnx = f" | ONNX {entry.onnx_sha256[:12]}" if entry.onnx_sha256 else ""
    return f"Version {entry.version} | License {entry.license} | model {short}{onnx} | {compat}"

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
    elif self._started():
      status += " | Takes effect after a reboot"
    only_default = len(entries) == 1 and entries[0].id == STOCK_ID
    choices = tuple((r.id, r.title) for r in rows if not r.problem)
    pick = selected_id if selected_id is not None and selected_id in {i for i, _ in choices} else STOCK_ID
    downloads = []
    for item in self._catalog():
      if item.get("id") not in known:
        downloads.append((item["id"], item.get("name") or item["id"],
                          f"Version {item.get('version', '')} | License {item.get('license', '')} | Download, then select"))
    try:
      can_download = self.download_gate() is True
    except Exception:
      can_download = False
    return Snapshot(tuple(rows), status, only_default, notice, offroad, choices, pick, tuple(downloads), can_download)


def offroad_gate():
  """True only while the car is off. Any error reading the state counts as on (no write)."""
  from openpilot.selfdrive.ui.bogpilot import onroad_policy

  def gate():
    try:
      return onroad_policy.is_started() is False
    except Exception:
      return False
  return gate


def create_driving_model_layout(controller=None):
  import time

  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import DialogResult, Widget
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.list_view import button_item, text_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  from openpilot.selfdrive.ui.bogpilot.gated_actions import MINUS, PLUS, gated_value_step_item

  if controller is None:
    from openpilot.selfdrive.ui.bogpilot import onroad_policy
    controller = ModelSelectorController(onroad_policy.editor("driving_model"), started=onroad_policy.is_started,
                                         on_change=lambda: onroad_policy.changed("driving_model"), download_gate=offroad_gate())

  class DrivingModelLayout(Widget):
    def __init__(self):
      super().__init__()
      self.controller = controller
      self.scroller = None
      self._snapshot = None
      self._open_desc = []
      self._refreshed_at = 0.0
      self._visible = False
      self._busy = False   # a download is running in the background

    def _inline_row(self):
      """[-] [model name] [+], the Alert Volume value-row style. Taps ask first; nothing is saved without a yes."""
      def value():
        lines = inline_text(self._snapshot) if self._snapshot else []
        return lines[1][2:-2] if lines else STOCK_NAME

      def stepped(direction):
        target = step_target(self._snapshot, direction) if self._snapshot else None
        if target is not None:
          name = next((n for i, n in self._snapshot.choices if i == target), target)
          self._confirm(target, name)

      def enabled():
        snap = self._snapshot
        return bool(snap and snap.offroad and len(snap.choices) > 1 and not self._busy)

      row = gated_value_step_item(lambda: tr(INLINE_TITLE), lambda: tr(INLINE_DESC), value,
                                  on_minus=lambda: stepped(-1), on_plus=lambda: stepped(1), minus=MINUS, plus=PLUS,
                                  selected_index=1, button_width=150, enabled=enabled,
                                  default_text=lambda: STOCK_NAME,
                                  is_default=lambda: bool(self._snapshot is None or self._snapshot.pick == STOCK_ID),
                                  translate=tr)
      attach_help(row, "driving_model.inline")
      return row

    def _download_rows(self):
      out = []
      for mid, name, detail in (self._snapshot.downloads if self._snapshot else ()):
        item = button_item(name, tr(DOWNLOAD_LABEL), detail, callback=lambda m=mid, n=name: self._confirm_download(m, n),
                           enabled=lambda: bool(self._snapshot and self._snapshot.can_download and not self._busy))
        attach_help(item, "driving_model.download", extra=lambda d=detail: d)
        out.append(item)
      return out

    def _confirm_download(self, model_id, name):
      if self._busy or not (self._snapshot and self._snapshot.can_download):
        return
      prompt = (f"Download {name}? Every file is checked against its pinned hash and the model must pass the 0.11.2 "
                "compatibility check before it is installed. It is not selected until you pick it.")

      def on_result(result):
        if result != DialogResult.CONFIRM:
          return
        import threading
        self._busy = True

        def work():
          try:
            self.controller.download(model_id)
          finally:
            self._busy = False
            self._refreshed_at = 0.0   # the next frame rebuilds from the new snapshot

        threading.Thread(target=work, name="bogpilot-model-download", daemon=True).start()

      gui_app.push_widget(ConfirmDialog(tr(prompt), tr("Download"), callback=on_result))

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
        # Status with the one explanation under it (a description wraps; a title would be cut off), and the Default row.
        # No buttons and no empty sections.
        status = text_item(snap.status, "", ONLY_DEFAULT_TEXT)
        attach_help(status, "driving_model.status", extra=lambda: ONLY_DEFAULT_TEXT)
        items.append(status)
        self._open_desc.append(status)
        for row in snap.rows:
          item = text_item(row.title, "", row.detail or None)
          attach_help(item, "driving_model.default" if row.id == STOCK_ID else "driving_model.entry",
                      extra=lambda r=row: r.detail)
          items.append(item)
        items += self._download_rows()
      else:
        status = text_item(snap.status, "", snap.notice or None)
        attach_help(status, "driving_model.status", extra=lambda: snap.notice)
        items.append(status)
        if snap.notice:
          self._open_desc.append(status)
        items.append(self._inline_row())
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
        items += self._download_rows()
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
