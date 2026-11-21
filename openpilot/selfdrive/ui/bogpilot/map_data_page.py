"""BogPilot > Navigation > Maps: FrogPilot's offline OpenStreetMap downloader page (0.9.7 frogpilot/ui/qt/offroad/maps_settings.cc,
same rows in current FrogPilot upstream) on the raylib UI, shared by the comma 3X list and the comma 4 cards.

Rows, in the FrogPilot order: Automatically Update Maps (Manually / Weekly / Monthly), Download Maps (DOWNLOAD / CANCEL, with
Progress, Time Elapsed and Time Remaining while it runs), Last Updated, Map Sources (Countries / U.S. States), Remove Maps,
Repair Map Downloads, Storage Used and the OpenStreetMap credit.

Map Sources: FrogPilot draws one row with COUNTRIES / STATES buttons that open a three-column grid. Here every screen is
made of plain list rows so the comma 4 shows each one as a card (tests/test_comma4_menu_parity.py): Countries and U.S.
States are OPEN rows, each opens its regions (Africa, Asia ... / Midwest, Northeast ...) as OPEN rows, and each region
lists its countries / states as switches. A switch saves the selection right away, as FrogPilot's grid did.

When things may change (selfdrive/ui/bogpilot/onroad_policy.py): the schedule, the region switches and Download work while
driving (ONROAD; a download started at a charger keeps going on the road, at low priority and resumable, see
system/bogpilot/osm/resume.py and priority.py). Scheduled updates still wait for the car to be off. Remove and Repair
(repair reboots) are PARKED: only with the car off or in Park.

comma 4: the PageHost turns on `grid_picker` (enable_grid_picker): Countries and U.S. States then open ONE grid of every region by
name, 2 columns x 3 rows per card page (region_grid.py), instead of the group lists; `grid_cells()` and
`grid_tap()` feed it. The 3X is unchanged.

Every control drives the store or the downloader through `MapDataController` (system/bogpilot/osm/map_data_controller.py);
this module only builds rows and routes taps. Importing it needs raylib; the page logic is tested without it.
"""
from __future__ import annotations

from openpilot.selfdrive.ui.bogpilot import onroad_policy, region_grid
from openpilot.selfdrive.ui.bogpilot.gated_actions import gated_multiple_button_item
from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
from openpilot.system.bogpilot.osm import regions
from openpilot.system.bogpilot.osm.downloads import SCHEDULE_LABELS
from openpilot.system.bogpilot.osm.map_data_controller import SLC_OFF_TEXT, MapDataController
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.list_view import button_item, text_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller

PAGE_KEY = "maps"
PAGE_TITLE = tr_noop("Maps")
# Row ids for the Tuning Level check and the page registry (PreferredSchedule is a registered setting; the rest are actions / readouts).
CONTROLS = ("PreferredSchedule", "MapsSelected", "LastMapsUpdate", "MapdV2")
# onroad_policy.ROW_CLASS keys of the rows that are stricter than the page
ROW_DOWNLOAD, ROW_REMOVE, ROW_REPAIR = "maps:download", "maps:remove", "maps:repair"

# FrogPilot strings (maps_settings.cc), unchanged except for the plain-text help that the BogPilot help pattern shows on tap.
SCHEDULE_DESC = tr_noop("How often maps update from \"OpenStreetMap (OSM)\" with the latest speed limit information. "
                        "Weekly updates run every Sunday; monthly updates run on the 1st, with the car off and on unmetered Wi-Fi.")
DOWNLOAD_DESC = tr_noop("Manually update your selected map sources so \"Speed Limit Controller\" has the latest speed limit information. "
                        "Works on any connection, also while driving. Needs \"Speed Limit Controller\" on.")
COUNTRIES_DESC = tr_noop("Select the countries to use with \"Speed Limit Controller\".")
STATES_DESC = tr_noop("Select the U.S. states to use with \"Speed Limit Controller\".")
REMOVE_DESC = tr_noop("Delete downloaded map data to free up storage space.")
REPAIR_DESC = tr_noop("Fixes stuck or failing map downloads. Clears all map data and the downloader, then reboots.")

CANCEL_Q = tr_noop("Cancel the download?")
REMOVE_Q = tr_noop("Delete all downloaded maps?")
REPAIR_Q = tr_noop("Repair map downloads? This clears all downloaded maps and the downloader, then reboots. Your regions and schedule are kept.")

ATTRIBUTION = "\u00a9 OpenStreetMap contributors"     # U+00A9 is in the font atlas (system/ui/lib/application.py EXTRA_FONT_CHARS)
LICENSE_LINE = tr_noop("Map data is available under the Open Database License (ODbL).")

MAIN_ROWS = ("schedule", "download", "last_updated", "countries", "states", "progress", "elapsed", "eta", "remove", "repair",
             "engine", "storage", "credit")
HELP_KEYS = ("PreferredSchedule", "map_data.download", "map_data.last_updated", "map_data.sources", "map_data.sources",
             "map_data.progress", "map_data.elapsed", "map_data.eta", "map_data.remove", "map_data.repair", "MapdV2", "map_data.storage",
             "map_data.credit")
KIND_TITLES = {"nations": tr_noop("Countries"), "states": tr_noop("U.S. States")}
OPEN = tr_noop("OPEN")


def short_group(kind: str, label: str) -> str:
  """'United States - Midwest' -> 'Midwest' inside U.S. States (the screen title already says U.S. States)."""
  prefix = "United States - "
  return label[len(prefix):] if kind == "states" and label.startswith(prefix) else label


def selected_text(count: int) -> str:
  return tr("None") if count <= 0 else f"{count} " + tr("selected")


# --------------------------------------------------------------------------------------------------------------------- device state
def device_online() -> bool:
  try:
    from openpilot.cereal import log
    from openpilot.selfdrive.ui.ui_state import ui_state
    return ui_state.sm["deviceState"].networkType != log.DeviceState.NetworkType.none
  except Exception:
    return False


def device_parked() -> bool:
  """Car off, or on and in Park (Remove / Repair). Unknown -> not parked."""
  s = onroad_policy.state()
  started = s.started()
  return onroad_policy.downloads_allowed(started, s.parked() if started else True)


def device_keep_awake(on: bool) -> None:
  """FrogPilot `parent->keepScreenOn`: the screen stays on while a download or repair runs."""
  try:
    from openpilot.selfdrive.ui.ui_state import device
    device.set_override_interactive_timeout(3600 if on else None)
  except Exception:
    pass


def push_confirm(message, confirm_label, on_confirm, cancel_label=None):
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog

  def done(result):
    if result == DialogResult.CONFIRM:
      on_confirm()
  gui_app.push_widget(ConfirmDialog(tr(message), tr(confirm_label), cancel_text=tr(cancel_label) if cancel_label else None, callback=done))


# --------------------------------------------------------------------------------------------------------------------- page
class MapDataLayout(Widget):
  """Screens: () main, (kind,) the region groups of Countries / U.S. States, (kind, group) the switches of one group."""

  def __init__(self, store=None, controller: MapDataController | None = None, online=device_online, parked=device_parked,
               confirm=push_confirm, keep_awake=device_keep_awake, can_edit=onroad_policy.can_edit):
    super().__init__()
    if controller is None:
      if store is None:
        from openpilot.common.bogpilot_store import ParamStore
        store = ParamStore()
      controller = MapDataController(store, keep_awake=keep_awake)
    self.ctl = controller
    self._online, self._parked, self._confirm, self._keep_awake = online, parked, confirm, keep_awake
    self._can_edit = can_edit
    self._awake = False
    self._path: tuple = ()
    self._view = self.ctl.view(False, False)
    self._sel = self.ctl.selection()
    self.rows: dict[str, object] = {}
    self._main = Scroller(self._main_items(), line_separator=True, spacing=0)
    self._screen: Scroller | None = None          # the open region screen (built when opened, so only it holds rows)
    self.region_rows: dict[str, object] = {}      # code -> switch row of the open group screen
    self.grid_picker = False                      # comma 4: one 2-column grid per kind instead of the group screens

  # ---- gates
  def _row_ok(self, row_key):
    return lambda: bool(self._can_edit(onroad_policy.row_class(row_key, PAGE_KEY)))

  def _current_view(self):
    return self._view

  def _schedule_description(self):
    text = tr(SCHEDULE_DESC)
    return text if self._view.slc_on else f"{text} {tr(SLC_OFF_TEXT)}."

  def _count(self, kind, codes=None):
    picked = getattr(self._sel, kind)
    return len(picked) if codes is None else len(set(picked) & set(codes))

  # ---- the FrogPilot main page
  def _main_items(self):
    r = self.rows
    v = self._current_view

    r["schedule"] = gated_multiple_button_item(lambda: tr("Automatically Update Maps"), self._schedule_description,
                                               [lambda i=i: tr(SCHEDULE_LABELS[i]) for i in range(len(SCHEDULE_LABELS))],
                                               self.ctl.schedule(), button_width=250, callback=self._on_schedule,
                                               enabled=lambda: v().slc_on)     # no downloads (so no schedule) while the SLC is off
    download_ok = self._row_ok(ROW_DOWNLOAD)
    r["download"] = button_item(lambda: tr("Download Maps"), lambda: tr(v().download_text), lambda: tr(DOWNLOAD_DESC),
                                callback=self._on_download,
                                enabled=lambda: v().download_enabled and (v().download_text == "CANCEL" or download_ok()))
    r["download"].action_item.set_value(lambda: tr(v().download_value))
    r["last_updated"] = text_item(lambda: tr("Last Updated"), lambda: tr(v().last_updated))
    for kind, desc in (("nations", COUNTRIES_DESC), ("states", STATES_DESC)):
      key = "countries" if kind == "nations" else "states"
      r[key] = button_item(lambda k=kind: tr(KIND_TITLES[k]), lambda: tr(OPEN), lambda d=desc: tr(d),
                           callback=lambda k=kind: self.open_screen((k,)))
      r[key].action_item.set_value(lambda k=kind: selected_text(self._count(k)))
    r["progress"] = text_item(lambda: tr("Progress"), lambda: tr(v().progress))
    r["elapsed"] = text_item(lambda: tr("Time Elapsed"), lambda: tr(v().elapsed))
    r["eta"] = text_item(lambda: tr("Time Remaining"), lambda: tr(v().eta))
    remove_ok, repair_ok = self._row_ok(ROW_REMOVE), self._row_ok(ROW_REPAIR)
    r["remove"] = button_item(lambda: tr("Remove Maps"), lambda: tr("REMOVE"), lambda: tr(REMOVE_DESC),
                              callback=lambda: self._confirm(REMOVE_Q, "Remove", self.ctl.remove_maps, "Cancel"),
                              enabled=lambda: v().remove_enabled and remove_ok())
    r["repair"] = button_item(lambda: tr("Repair Map Downloads"), lambda: tr("REPAIR"), lambda: tr(REPAIR_DESC),
                              callback=lambda: self._confirm(REPAIR_Q, "Repair", self.ctl.reset_downloader, "Cancel"),
                              enabled=lambda: v().reset_enabled and repair_ok())
    r["repair"].action_item.set_value(lambda: tr(v().reset_value))
    # mapd v1 (default) or v2: same tiles; the bogpilot_mapd supervisor switches engines within a few seconds
    store = self.ctl.store
    def _engine_state():
      try:
        return bool(store.get_bool("MapdV2"))
      except Exception:
        return False
    r["engine"] = toggle_item(lambda: tr("Use mapd v2"), None, _engine_state(), callback=lambda on: store.put_bool("MapdV2", bool(on)))
    r["storage"] = text_item(lambda: tr("Storage Used"), lambda: v().storage)
    r["credit"] = text_item(ATTRIBUTION, "", description=lambda: tr(LICENSE_LINE))

    r["last_updated"].set_visible(lambda: v().show_last_updated)
    for key in ("progress", "elapsed", "eta"):
      r[key].set_visible(lambda: v().downloading)
    r["remove"].set_visible(lambda: v().show_remove)
    r["repair"].set_visible(lambda: v().show_reset)

    for row, help_key in zip(MAIN_ROWS, HELP_KEYS, strict=True):
      attach_help(r[row], help_key)
    # The Speed Limit Controller notice (FrogPilot has none: there the downloader always runs) as the first row.
    self.notice = text_item(lambda: tr(SLC_OFF_TEXT), "")
    self.notice.set_visible(lambda: not v().slc_on)
    return [self.notice] + [r[k] for k in MAIN_ROWS]

  # ---- Countries / U.S. States screens
  def _groups(self, kind):
    return [(label, sorted(regs, key=lambda r: r[1])) for label, regs in regions.groups()[kind] if regs]

  def enable_grid_picker(self, on: bool = True) -> None:
    """comma 4 PageHost: show Countries / U.S. States as one grid (the open screen is rebuilt)."""
    self.grid_picker = bool(on)
    if self._path:
      self.open_screen(self._path[:1])

  def grid_kind(self):
    """'nations' / 'states' while the grid picker shows that kind's grid, else None."""
    return self._path[0] if self.grid_picker and len(self._path) == 1 else None

  def grid_cells(self):
    """[(code, full name)] of the open grid (A-Z), or None when no grid is open."""
    kind = self.grid_kind()
    return None if kind is None else region_grid.sorted_cells(self._groups(kind))

  def grid_selected(self, code: str) -> bool:
    kind = self.grid_kind()
    return kind is not None and code in getattr(self._sel, kind)

  def grid_tap(self, code: str) -> None:
    """A tap on a grid cell: flip that region (saved at once, like the 3X switch; a refused change leaves it as it was)."""
    kind = self.grid_kind()
    if kind is not None and any(code == c for c, _n in self.grid_cells()):
      self._on_region(kind, code, not self.grid_selected(code))

  def _build_screen(self, path):
    kind = path[0]
    items = []
    self.region_rows = {}
    if self.grid_picker and len(path) == 1:
      pass                                # the comma 4 draws the grid itself; only the credit row follows it
    elif len(path) == 1:
      for label, regs in self._groups(kind):
        codes = [c for c, _n in regs]
        row = button_item(lambda lb=label, k=kind: tr(short_group(k, lb)), lambda: tr(OPEN),
                          callback=lambda lb=label, k=kind: self.open_screen((k, lb)))
        row.action_item.set_value(lambda k=kind, cs=codes: selected_text(self._count(k, cs)))
        items.append(row)
    else:
      regs = dict(self._groups(kind)).get(path[1], [])
      for code, name in regs:
        row = toggle_item(name, initial_state=code in getattr(self._sel, kind),
                          callback=lambda on, k=kind, c=code: self._on_region(k, c, on))
        self.region_rows[code] = row
        items.append(row)
    credit = text_item(ATTRIBUTION, "", description=lambda: tr(LICENSE_LINE))
    attach_help(credit, "map_data.credit")
    items.append(credit)
    return Scroller(items, line_separator=True, spacing=0)

  def open_screen(self, path: tuple) -> None:
    if not path or path[0] not in KIND_TITLES:
      return
    if len(path) == 2 and (self.grid_picker or path[1] not in dict(self._groups(path[0]))):
      return
    self._path = tuple(path)
    self._screen = self._build_screen(self._path)
    self._screen.show_event()

  def _sync_switches(self):
    if len(self._path) != 2:
      return
    picked = set(getattr(self._sel, self._path[0]))
    for code, row in self.region_rows.items():
      if row.action_item.get_state() != (code in picked):
        row.action_item.set_state(code in picked)

  # ---- actions
  def _on_schedule(self, index):
    if not self._view.slc_on:
      self.rows["schedule"].action_item.set_selected_button(self.ctl.schedule())
      return
    self.ctl.set_schedule(index)

  def _on_download(self):
    if self._view.download_text == "CANCEL":
      self._confirm(CANCEL_Q, "Yes", self.ctl.cancel_download, "No")
    else:
      self.ctl.start_download(self._online(), self._parked())

  def _on_region(self, kind, code, on):
    self.ctl.set_region(kind, code, bool(on))
    self._sel = self.ctl.selection()
    self._sync_switches()               # a refused change (too many regions) flips the switch back

  # ---- menu navigation hooks (menu_097.MenuNavigation and the comma 4 PageHost)
  @property
  def navigation_title(self):
    if not self._path:
      return tr(PAGE_TITLE)
    if len(self._path) == 1:
      return tr(KIND_TITLES[self._path[0]])
    return tr(short_group(self._path[0], self._path[1]))

  def navigation_back(self) -> bool:
    if not self._path:
      return False
    parent = self._path[:-1]
    if parent:
      self.open_screen(parent)
    else:
      self._path, self._screen, self.region_rows = (), None, {}
      self._main.show_event()
    return True

  # ---- lifecycle
  def show_event(self):
    super().show_event()
    self._path, self._screen, self.region_rows = (), None, {}
    self._sel = self.ctl.selection()
    self.ctl.refresh_storage()
    self.rows["schedule"].action_item.set_selected_button(self.ctl.schedule())
    self._main.show_event()

  def hide_event(self):
    self._path, self._screen, self.region_rows = (), None, {}
    if self._awake:
      self._awake = False
      self._keep_awake(False)
    super().hide_event()

  def _update_state(self):
    self.ctl.update()
    self._view = self.ctl.view(self._online(), self._parked())
    self._sel = self.ctl.selection()
    self._sync_switches()
    awake = self._view.downloading or self.ctl.phase in ("resetting", "installing")
    if awake != self._awake:
      self._awake = awake
      self._keep_awake(awake)

  def _render(self, rect):
    (self._screen if self._screen is not None else self._main).render(rect)


def create_maps_layout():
  return MapDataLayout()
