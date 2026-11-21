"""BogPilot settings on the comma 4 (mici): the 3X BogPilot menu, page for page.

Same data as the 3X (layouts/settings/bogpilot.py menu_sections(): sections, pills, pages and their factories), same
navigation state (menu_097.MenuNavigation: Tuning Level filtering, one-page pills open directly, Back, inner pages,
"go to the setting" jumps), same onroad policy (onroad_policy: page classes, reboot prompt once per page visit through
new_visit on every move, staged Disable Longitudinal applied by install(), the Tuning Level LOCKED gate), same pages.
Only the presentation is comma 4: horizontal BigButton cards, swipe down for Back, option lists and the value adjuster
(widgets.py), and comma 4 dialogs (dialogs.py).

  settings > bogpilot          Tuning Level card, one card per section (3X row icons)
    section with several pills  one card per pill
      pill with several pages   one card per page (MenuNavigation path (pill,))
        page                    the 3X page drawn off screen, its rows as cards (MenuNavigation path (pill, page))
"""
from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui.bogpilot import onroad_policy
from openpilot.selfdrive.ui.bogpilot import row_model as rm
from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot import dialogs
from openpilot.selfdrive.ui.mici.layouts.settings.bogpilot.widgets import (ChoicePage, InfoCard, LiveCard, RegionGridPage,
                                                                           StepperPage, cards_for)
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller

# Where a 3X page is drawn: far left of the screen (nothing visible, no touch lands there) and tall enough that the 3X
# scroller lays out and draws every row, so every row it shows is recorded each frame.
HOST_RECT = (-40000.0, 0.0, 1660.0, 20000.0)
LOGO = "icons/bogpilot/icon_bogpilot.png"


def _icon(path, w=64, h=64):
  try:
    return gui_app.texture(path, w, h)
  except Exception:
    return None


class _NoView:
  """MenuNavigation wants a widget for home and page lists; on the comma 4 those are this module's own pages."""

  def show_event(self):
    pass

  def hide_event(self):
    pass


class PageHost(NavScroller):
  """One 3X page as comma 4 cards. The page is drawn off screen every frame (its own refresh, visibility, Tuning
  Level and onroad gates run as on the 3X); the rows it drew become cards, rebuilt only when that list changes."""

  def __init__(self, layout: BogPilotLayoutMici, path: tuple, widget, title):
    super().__init__()
    # not self._layout: that name is Widget._layout(), called by every render (an attribute there made render() raise)
    self._menu, self.path, self.widget = layout, path, widget
    self._title = title
    self._header = InfoCard(self._title_text, lambda: tr(layout.page_note()))
    self._cards: dict[int, tuple] = {}
    self._ids: tuple = ()
    self.rows: list = []
    self.grid_pages: list = []             # comma 4 region grid (Maps > Countries / U.S. States), see region_grid.py
    self._grid_sig: tuple | None = None
    enable = getattr(widget, "enable_grid_picker", None)
    if callable(enable):
      enable(True)
    self._scroller.add_widget(self._header)

  def _title_text(self):
    inner = getattr(self.widget, "navigation_title", None)
    return tr(inner) if isinstance(inner, str) and inner else tr(self._title)

  def refresh_rows(self) -> list:
    rows = rm.record(self.widget, rl.Rectangle(*HOST_RECT))
    self._sync_cards(rows)
    return rows

  def _grid(self):
    """(signature, cells) of the open region grid, or (None, None) when the page has no grid open."""
    grid = getattr(self.widget, "grid_cells", None)
    cells = grid() if callable(grid) else None
    if cells is None:
      return None, None
    return (self.widget.grid_kind(), tuple(code for code, _n in cells)), cells

  def _sync_cards(self, items):
    ids = tuple(id(i) for i in items)
    sig, cells = self._grid()
    if ids == self._ids and sig == self._grid_sig:
      return
    self._ids, self._grid_sig = ids, sig
    cards = [self._header]
    self.grid_pages = []
    if cells is not None:
      from openpilot.selfdrive.ui.bogpilot import region_grid
      self.grid_pages = [RegionGridPage(page, self.widget.grid_selected, self.widget.grid_tap) for page in region_grid.paginate(cells)]
      cards.extend(self.grid_pages)
    rows = []
    for item in items:
      cached = self._cards.get(id(item))
      if cached is None or cached[0] is not item:
        row = rm.Row(item)
        cached = (item, row, cards_for(row, self._menu.open_choice, self._menu.open_stepper))
        self._cards[id(item)] = cached
      rows.append(cached[1])
      cards.extend(cached[2])
    self.rows = rows
    for card in cards:
      card._touch_valid_callback = None   # add_widget wraps it again
    self._scroller._items = []
    self._scroller.add_widgets(cards)

  def _render(self, rect):
    self.refresh_rows()
    super()._render(rect)

  def _handle_mouse_event(self, mouse_event):
    # Swipe down inside a page with inner pages (Gas / Brake sections, Data, Device Controls ...) goes up one inner
    # level first, as the 3X Back does (MenuNavigation.back -> navigation_back); only at its first view does it close.
    was = self._playing_dismiss_animation
    super()._handle_mouse_event(mouse_event)
    if not was and self._playing_dismiss_animation and self._dismiss_callback is None:
      inner_back = getattr(self.widget, "navigation_back", None)
      if callable(inner_back) and inner_back():
        self._playing_dismiss_animation = False


class PageList(NavScroller):
  """A pill with several pages (MenuNavigation path (pill,)): one card per page."""

  def __init__(self, layout: BogPilotLayoutMici, pill):
    super().__init__()
    self.path = (pill.key,)
    nav = layout.navigation
    cards = [InfoCard(lambda: tr(pill.title), lambda: tr(layout.page_note()))]
    for page in pill.pages:
      card = LiveCard(lambda p=page: tr(p.title), lambda: tr("OPEN"), on_tap=lambda p=page: layout.open_page(pill.key, p.key))
      card.set_visible(lambda p=page: nav.can_open(pill.key, p.key))
      cards.append(card)
    self._scroller.add_widgets(cards)


class SectionPage(NavScroller):
  """A 3X menu row with several pills (Driving Controls, System Settings, Vehicle Settings): one card per pill."""

  def __init__(self, layout: BogPilotLayoutMici, section):
    super().__init__()
    nav = layout.navigation
    cards = [InfoCard(lambda: tr(section.title), lambda: "")]
    for pill in section.pills:
      card = LiveCard(lambda p=pill: tr(p.title), lambda p=pill: tr(p.label), on_tap=lambda p=pill: layout.open_pill(p.key))
      card.set_visible(lambda p=pill: p in nav.pills_of(section))
      cards.append(card)
    self._scroller.add_widgets(cards)


class TuningLevelChoice:
  """Option-list adapter over the Tuning Level (menu_097.choose_tuning_level, the 3X control's own function)."""

  def __init__(self, layout: BogPilotLayoutMici):
    self._layout = layout

  def title(self):
    return tr("Tuning Level")

  def description(self):
    from openpilot.selfdrive.ui.bogpilot.toggle_help import HELP, help_plain
    entry = HELP.get("menu.tuning_level")
    return help_plain(entry, tr) if entry is not None else ""

  def options(self):
    return [tr(n) for n in tl.LEVEL_NAMES]

  def selected(self):
    return tl.effective_level()

  def enabled(self):
    return bool(self._layout.can_edit_level())

  def choose(self, i):
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import choose_tuning_level
    from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
    return choose_tuning_level(i, can_edit=self._layout.can_edit_level,
                               show_warning=lambda text: gui_app.push_widget(alert_dialog(tr(text))))


class BogPilotLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import LOCKED_WHILE_DRIVING, MenuNavigation
    from openpilot.selfdrive.ui.ui_state import ui_state
    dialogs.install()
    self.can_edit_level = onroad_policy.editor("", "tuning_level")
    self.sections = menu_sections()
    self.navigation = MenuNavigation(self.sections, _NoView, lambda entries, open_page: _NoView(), on_move=self._on_move)
    onroad_policy.install(ui_state)   # staged reboot-class changes are applied when the car turns off
    self._views: list = []            # pushed PageList / PageHost views, bottom to top, mirroring navigation.path
    self._hosts: dict = {}
    self._syncing = False

    level_card = LiveCard(lambda: tr("Tuning Level"),
                          lambda: tr(tl.LEVEL_NAMES[tl.effective_level()]) + ("" if self.can_edit_level() else " - " + tr(LOCKED_WHILE_DRIVING)),
                          on_tap=lambda: self.open_choice(TuningLevelChoice(self)), icon=_icon("icons/bogpilot/menu_tuning.png"))
    cards = [level_card]
    for section in self.sections:
      card = LiveCard(lambda s=section: tr(s.title), lambda s=section: ", ".join(tr(p.title) for p in self.navigation.pills_of(s)),
                      on_tap=lambda s=section: self.open_section(s), icon=_icon(f"icons/bogpilot/{section.icon}"))
      card.set_visible(lambda s=section: bool(self.navigation.pills_of(s)))
      cards.append(card)
    self._scroller.add_widgets(cards)

  # ---- what the pages ask for
  def page_note(self) -> str:
    from openpilot.selfdrive.ui.layouts.settings.menu_097 import page_note
    return page_note(self.navigation)

  def open_choice(self, source):
    gui_app.push_widget(ChoicePage(source))

  def open_stepper(self, row):
    gui_app.push_widget(StepperPage(row, note=lambda: tr(self.page_note())))

  # ---- navigation (all moves go through MenuNavigation, then the pushed views follow its path)
  def open_section(self, section):
    pills = self.navigation.pills_of(section)
    if len(pills) == 1:
      self.open_pill(pills[0].key)
    elif pills:
      gui_app.push_widget(SectionPage(self, section))

  def open_pill(self, key):
    self.navigation.open_pill(key)

  def open_page(self, pill_key, page_key):
    self.navigation.open_page(pill_key, page_key)

  def _view_for(self, path):
    if len(path) == 1:
      key = path
      view = self._hosts.get(key)
      if view is None:
        view = PageList(self, self.navigation.pill(path[0]))
        self._hosts[key] = view
      return view
    widget = self.navigation.current if self.navigation.path == path else self.navigation._cache.get(path)
    view = self._hosts.get(path)
    if view is None or view.widget is not widget:
      page = next(p for p in self.navigation.pill(path[0]).pages if p.key == path[1])
      view = PageHost(self, path, widget, page.title)
      view.set_back_callback(lambda v=view: self._view_closed(v))
      self._hosts[path] = view
    return view

  def desired_paths(self) -> list[tuple]:
    path = self.navigation.path
    if not path:
      return []
    out = []
    if len(self.navigation.pages_of(self.navigation.pill(path[0]))) > 1:
      out.append(path[:1])
    if len(path) == 2:
      out.append(path)
    return out

  def _on_move(self):
    onroad_policy.new_visit()
    self._sync()

  def _sync(self):
    if self._syncing:
      return
    self._syncing = True
    try:
      want = [self._view_for(p) for p in self.desired_paths()]
      keep = 0
      while keep < len(self._views) and keep < len(want) and self._views[keep] is want[keep]:
        keep += 1
      for view in reversed(self._views[keep:]):
        self._pop(view)
      self._views = self._views[:keep]
      for view in want[keep:]:
        if len(view.path) == 1:
          view.set_back_callback(lambda v=view: self._view_closed(v))
        gui_app.push_widget(view)
        self._views.append(view)
    finally:
      self._syncing = False

  @staticmethod
  def _pop(view):
    stack = getattr(gui_app, "_nav_stack", [])
    if view in stack:
      gui_app.pop_widget(stack.index(view))

  def _view_closed(self, view):
    """A view was swiped away (NavWidget already popped it): step the navigation back to match."""
    if view not in self._views:
      return
    self._views = self._views[:self._views.index(view)]
    target = view.path[:-1] if len(view.path) == 2 and len(self.navigation.pages_of(self.navigation.pill(view.path[0]))) > 1 else ()
    while self.navigation.path and self.navigation.path != target and len(self.navigation.path) >= len(target):
      if not self.navigation.back():
        break
    self._sync()

  # ---- lifecycle
  def show_event(self):
    super().show_event()
    self.navigation.show_event()

  def hide_event(self):
    super().hide_event()
    # 0.9.7: leaving the BogPilot settings closes every open sub-panel; it always reopens at the top level.
    self.navigation.reset()
    self.navigation.hide_event()


__all__ = ["BogPilotLayoutMici", "PageHost", "PageList", "SectionPage", "TuningLevelChoice", "HOST_RECT", "LOGO"]
