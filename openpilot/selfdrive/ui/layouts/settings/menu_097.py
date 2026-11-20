"""BogPilot settings home in the 0.9.7 layout: Tuning Level, then six sections, each a row with an icon, a title on
the left, pill buttons on the right and thin dividers between rows.

`Section` / `Pill` are plain data (what the menu shows and which existing raylib page each pill opens). `MenuNavigation`
is pure state (no raylib): home -> pill -> optional page list -> page, with Back. `MenuLayout` is the raylib widget.

Nothing here writes a setting except the Tuning Level control (only when it is tapped) and, through
onroad_policy.install, the reboot-class changes staged while the car was on (applied when it turns off). Importing this
module has no UI or Params side effects.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from openpilot.selfdrive.ui.bogpilot import onroad_policy
from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import Page, content_bounds
from openpilot.system.ui.lib.multilang import tr_noop

ICON_DIR = "bogpilot"
HOME_TITLE = tr_noop("BogPilot")
LOCKED_WHILE_DRIVING = tr_noop("Locked while the car is on")
DEVELOPER_WARNING = tr_noop(
  "WARNING: Developer shows every setting, including ones that change how the car drives and that are not for everyday use. "
  "Use them at your own risk, and only if you know what a setting does.")


@dataclass(frozen=True)
class Pill:
  key: str
  label: str            # pill text, upper case as in 0.9.7
  title: str            # header of the page or page list it opens
  pages: tuple[Page, ...]
  visible: Callable[[], bool] | None = None   # None: always (subject to the Tuning Level); else the pill follows the car


@dataclass(frozen=True)
class Section:
  key: str
  title: str
  icon: str             # file under assets/icons/bogpilot
  pills: tuple[Pill, ...]
  help_key: str = ""


def _all_pages(sections):
  return [(s, p, pg) for s in sections for p in s.pills for pg in p.pages]


def _pill_shown(pill: Pill) -> bool:
  try:
    return bool(pill.visible())
  except Exception:
    return True


def validate(sections) -> None:
  keys, page_keys = set(), set()
  for section, pill, page in _all_pages(sections):
    if not callable(page.factory) or not page.controls:
      raise ValueError(f"inert page: {page.key}")
    if page.key in page_keys:
      raise ValueError(f"page opened twice: {page.key}")
    page_keys.add(page.key)
  for section in sections:
    for pill in section.pills:
      if pill.key in keys:
        raise ValueError(f"duplicate pill: {pill.key}")
      if not pill.pages:
        raise ValueError(f"pill without a page: {pill.key}")
      keys.add(pill.key)


class MenuNavigation:
  """Home -> (pill) -> (pill, page). A pill with one visible page opens it directly."""

  def __init__(self, sections, home_factory: Callable, menu_factory: Callable, level: Callable[[], int] | None = None,
               on_move: Callable[[], None] | None = None):
    validate(sections)
    self.sections = tuple(sections)
    self._home_factory = home_factory
    self._menu_factory = menu_factory
    self._level = level or tl.effective_level
    self._on_move = on_move
    self._cache: dict = {}
    self.path: tuple = ()
    self.visible = False

  # ---- what the chosen Tuning Level shows
  def pages_of(self, pill: Pill, level: int | None = None):
    lvl = self._level() if level is None else level
    if pill.visible is not None and not _pill_shown(pill):
      return ()
    return tuple(p for p in pill.pages if tl.page_level(p.controls) <= lvl)

  def pills_of(self, section: Section, level: int | None = None):
    return tuple(p for p in section.pills if self.pages_of(p, level))

  def visible_sections(self, level: int | None = None):
    return tuple(s for s in self.sections if self.pills_of(s, level))

  def pill(self, key: str) -> Pill:
    for s in self.sections:
      for p in s.pills:
        if p.key == key:
          return p
    raise KeyError(key)

  # ---- navigation
  @property
  def title(self) -> str:
    if not self.path:
      return HOME_TITLE
    pill = self.pill(self.path[0])
    if len(self.path) == 1:
      return pill.title
    inner = getattr(self._cache.get(self.path), "navigation_title", None)
    if isinstance(inner, str) and inner:
      return inner
    return next(p.title for p in pill.pages if p.key == self.path[1])

  def entries(self):
    if len(self.path) == 1:
      return tuple((p.key, p.title) for p in self.pages_of(self.pill(self.path[0])))
    return ()

  @property
  def current(self):
    if self.path not in self._cache:
      if not self.path:
        # One home instance for the whole session: it re-reads the level while rendering.
        self._cache[()] = self._home_factory()
      elif len(self.path) == 2:
        page = next(p for p in self.pill(self.path[0]).pages if p.key == self.path[1])
        widget = page.factory()
        # A page that wants to send the user to another page (a "go to the setting" button) is handed this navigation.
        hook = getattr(widget, "set_navigator", None)
        if callable(hook):
          hook(self)
        self._cache[self.path] = widget
      else:
        self._cache[self.path] = self._menu_factory(self.entries(), lambda k, pill=self.path[0]: self.open_page(pill, k))
    return self._cache[self.path]

  def _move(self, path: tuple) -> None:
    old = self.path
    self.path = path
    try:
      if len(path) == 1:
        self._cache.pop(path, None)     # the page list depends on the level: rebuild
      target = self.current
    except Exception:
      self.path = old
      raise
    self.path = old
    if self.visible:
      self.current.hide_event()
    self.path = path
    if self._on_move is not None:
      self._on_move()
    if self.visible:
      target.show_event()

  def open_pill(self, key: str) -> None:
    pages = self.pages_of(self.pill(key))
    if not pages:
      raise KeyError(key)
    self._move((key, pages[0].key) if len(pages) == 1 else (key,))

  def can_open(self, pill_key: str, page_key: str) -> bool:
    try:
      return page_key in {p.key for p in self.pages_of(self.pill(pill_key))}
    except KeyError:
      return False

  def open_page(self, pill_key: str, page_key: str) -> None:
    if page_key not in {p.key for p in self.pages_of(self.pill(pill_key))}:
      raise KeyError(page_key)
    self._move((pill_key, page_key))

  def back(self) -> bool:
    if not self.path:
      return False
    inner_back = getattr(self._cache.get(self.path), "navigation_back", None)
    if len(self.path) == 2 and callable(inner_back) and inner_back():
      return True
    if len(self.path) == 2 and len(self.pages_of(self.pill(self.path[0]))) > 1:
      self._move(self.path[:1])
    else:
      self._move(())
    return True

  @property
  def at_top(self) -> bool:
    return not self.path

  def reset(self) -> None:
    """Return to the top level from anywhere (0.9.7: tapping the BogPilot tab, or leaving the panel, closes every open
    sub-panel). Pages with their own inner pages are walked back to their first page so they reopen there too."""
    for path, widget in list(self._cache.items()):
      inner_back = getattr(widget, "navigation_back", None)
      if len(path) == 2 and callable(inner_back):
        for _ in range(8):
          if not inner_back():
            break
    if self.path:
      self._move(())

  def show_event(self) -> None:
    if not self.visible:
      self.current.show_event()
      self.visible = True

  def hide_event(self) -> None:
    if self.visible:
      self.current.hide_event()
      self.visible = False


def choose_tuning_level(level, *, can_edit: Callable[[], bool], show_warning: Callable[[str], None], store=None) -> bool:
  """A tap on a Tuning Level (3X segmented control and comma 4 level list alike). Offroad only (`can_edit`, the
  onroad_policy MENU_CLASS gate). Writes TuningLevel and TuningLevelConfirmed; choosing Developer shows the 0.9.7
  warning once."""
  level = tl.clamp(level)
  if not can_edit():
    return False
  before = tl.effective_level(store)
  if not tl.set_level(level, store):
    return False
  if level == tl.DEVELOPER and before != tl.DEVELOPER:
    show_warning(DEVELOPER_WARNING)
  return True


def page_class_of(navigation: MenuNavigation) -> str | None:
  """Onroad class of what is open: the page, or on a page list the class its visible pages share (None when they differ
  or at home)."""
  path = navigation.path
  if len(path) == 2:
    return onroad_policy.page_class(path[1])
  if len(path) == 1:
    classes = {onroad_policy.page_class(p.key) for p in navigation.pages_of(navigation.pill(path[0]))}
    return classes.pop() if len(classes) == 1 else None
  return None


def page_note(navigation: MenuNavigation, drive=None) -> str:
  drive = drive or onroad_policy.state()
  cls = page_class_of(navigation)
  if cls is None:
    return ""
  started = drive.started()
  return onroad_policy.note(cls, started, drive.parked() if started else True)


# ---------------------------------------------------------------------------------------------------------------------
# raylib widgets (imported lazily so the data and navigation above stay testable without a window)
# ---------------------------------------------------------------------------------------------------------------------
def build_menu(sections, store=None, can_edit: Callable[[], bool] | None = None, show_warning: Callable[[str], None] | None = None):
  import pyray as rl
  from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
  from openpilot.system.ui.lib.application import FontWeight, gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.lib.text_measure import measure_text_cached
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
  from openpilot.system.ui.widgets.list_view import (BUTTON_HEIGHT, ICON_SIZE, ITEM_PADDING, ITEM_TEXT_COLOR, ITEM_TEXT_FONT_SIZE,
                                                     ITEM_TEXT_VALUE_COLOR, RIGHT_ITEM_PADDING, ItemAction, ListItem, button_item,
                                                     text_item)
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  ROW_HEIGHT = 140
  PILL_FONT = 40
  PILL_PAD = 38
  PILL_MIN = 170
  SUBTITLE_FONT = 36
  SUBTITLE_GAP = 4
  SUBTITLE_MIN = 26
  SUBTITLE_ROOM_GAP = 24
  GREEN = rl.Color(51, 171, 76, 255)
  GRAY = rl.Color(57, 57, 57, 255)
  PRESSED = rl.Color(74, 74, 74, 255)

  class PillsAction(ItemAction):
    """Pill buttons on the right of a row. `entries()` gives the live (key, label) list; a press calls `on_press(key)`.
    `selected()` (optional) is the key drawn green: the segmented Tuning Level control uses it, plain pills do not."""

    def __init__(self, entries, on_press, selected=None, enabled=True):
      super().__init__(0, enabled)
      self._entries, self._on_press, self._selected = entries, on_press, selected
      self._font = gui_app.font(FontWeight.MEDIUM)

    def _labels(self):
      return [(k, tr(label)) for k, label in self._entries()]

    def _widths(self):
      return [max(PILL_MIN, int(measure_text_cached(self._font, text, PILL_FONT).x) + 2 * PILL_PAD + 1)
              for _, text in self._labels()]

    def get_width_hint(self) -> float:
      widths = self._widths()
      return sum(widths) + RIGHT_ITEM_PADDING * max(0, len(widths) - 1)

    def pill_rects(self, rect: rl.Rectangle):
      y = rect.y + (rect.height - BUTTON_HEIGHT) / 2
      out, x = [], rect.x
      for (key, text), w in zip(self._labels(), self._widths(), strict=True):
        out.append((key, text, rl.Rectangle(x, y, w, BUTTON_HEIGHT)))
        x += w + RIGHT_ITEM_PADDING
      return out

    def _render(self, rect):
      selected = self._selected() if self._selected else None
      for key, text, r in self.pill_rects(rect):
        down = self.enabled and self.is_pressed and rl.check_collision_point_rec(rl.get_mouse_position(), r)
        color = GREEN if key == selected else (PRESSED if down else GRAY)
        if not self.enabled:
          color = rl.Color(color.r, color.g, color.b, 150)
        rl.draw_rectangle_rounded(r, 1.0, 20, color)
        size = measure_text_cached(self._font, text, PILL_FONT)
        tc = rl.Color(228, 228, 228, 255) if self.enabled else rl.Color(150, 150, 150, 255)
        rl.draw_text_ex(self._font, text, rl.Vector2(r.x + (r.width - size.x) / 2, r.y + (r.height - size.y) / 2), PILL_FONT, 0, tc)

    def _handle_mouse_release(self, mouse_pos):
      if not self.enabled:
        return
      for key, _, r in self.pill_rects(self._rect):
        if rl.check_collision_point_rec(mouse_pos, r):
          self._on_press(key)
          return

  class MenuRow(ListItem):
    """A 0.9.7 menu row: icon, title on the left, pills on the right. 140 px high so the seven rows fit the 2160x1080 panel."""

    def get_right_item_rect(self, item_rect):
      r = super().get_right_item_rect(item_rect)
      return rl.Rectangle(r.x, r.y, r.width, ROW_HEIGHT)

    subtitle: Callable[[], str] | None = None   # small grey line under the title; empty text draws nothing

    def get_item_height(self, font, max_width):
      if not self.is_visible:
        return 0
      height = float(ROW_HEIGHT)
      if self.description_visible:
        height += self._html_renderer.get_total_height(max_width) + ITEM_PADDING
      return height

    def _render(self, _):
      if not self.is_visible:
        return
      if self._rect.y + self._rect.height <= self._parent_rect.y or self._rect.y >= self._parent_rect.y + self._parent_rect.height:
        return
      x = self._rect.x + ITEM_PADDING
      if self.icon:
        texture = self._get_icon_texture()   # loaded on first draw; none if the file will not load
        if texture is not None:
          rl.draw_texture_ex(texture, rl.Vector2(x, self._rect.y + (ROW_HEIGHT - texture.height) / 2), 0.0, 1.0, rl.WHITE)
        x += ICON_SIZE + ITEM_PADDING
      size = measure_text_cached(self._font, self.title, ITEM_TEXT_FONT_SIZE)
      note = self.subtitle() if self.subtitle is not None else ""
      if note:
        # Fit the note between the title and the pills on the right (it shrinks a little rather than run under them).
        room = self.get_right_item_rect(self._rect).x - x - SUBTITLE_ROOM_GAP
        font_size = SUBTITLE_FONT
        while font_size > SUBTITLE_MIN and measure_text_cached(self._font, note, font_size).x > room:
          font_size -= 2
        note_size = measure_text_cached(self._font, note, font_size)
        top = self._rect.y + (ROW_HEIGHT - (size.y + SUBTITLE_GAP + note_size.y)) // 2
        rl.draw_text_ex(self._font, self.title, rl.Vector2(x, top), ITEM_TEXT_FONT_SIZE, 0, ITEM_TEXT_COLOR)
        rl.draw_text_ex(self._font, note, rl.Vector2(x, top + size.y + SUBTITLE_GAP), font_size, 0, ITEM_TEXT_VALUE_COLOR)
      else:
        rl.draw_text_ex(self._font, self.title, rl.Vector2(x, self._rect.y + (ROW_HEIGHT - size.y) // 2), ITEM_TEXT_FONT_SIZE, 0, ITEM_TEXT_COLOR)
      if self.description_visible:
        content_width = int(self._rect.width - ITEM_PADDING * 2)
        self._html_renderer.render(rl.Rectangle(self._rect.x + ITEM_PADDING, self._rect.y + ROW_HEIGHT, content_width,
                                                self._html_renderer.get_total_height(content_width)))
      if self.action_item:
        right = self.get_right_item_rect(self._rect)
        right.y = self._rect.y
        self.action_item.render(right)

  def icon_path(name: str) -> str:
    return f"{ICON_DIR}/{name}"

  class MenuLayout(Widget):
    def __init__(self):
      super().__init__()
      from openpilot.selfdrive.ui.ui_state import ui_state
      self._ui_state = ui_state
      # Onroad policy (bogpilot/onroad_policy.py, 0.9.7 parity): there is no global lock any more. Each page has a class
      # (editable / reboot prompt / parked / locked) and guards its own rows; this widget only gates the Tuning Level
      # control (offroad only) and shows the open page's note next to the title.
      self._can_edit = can_edit or onroad_policy.editor("", "tuning_level")
      self._store = store
      self._show_warning = show_warning or (lambda text: gui_app.push_widget(alert_dialog(tr(text))))
      self.navigation = MenuNavigation(sections, self._build_home, self._build_page_list, level=self.level,
                                       on_move=onroad_policy.new_visit)
      onroad_policy.install(ui_state)   # staged reboot-class changes are applied when the car turns off
      # Title only: Back is the top-left item of the settings sidebar (see SettingsLayout), as in 0.9.7.
      self._header = text_item(lambda: tr(self.navigation.title), lambda: tr(self._page_note()))

    def _page_note(self) -> str:
      """Note next to the title while the car is on: the open page's class (or, on a page list, the class all its
      pages share)."""
      return page_note(self.navigation)

    # ---- Tuning Level control
    def level(self) -> int:
      return tl.effective_level(self._store)

    def choose_level(self, level) -> bool:
      """Tap on a level. Writes TuningLevel and TuningLevelConfirmed; Developer shows the 0.9.7 warning."""
      return choose_tuning_level(level, can_edit=self._can_edit, show_warning=self._show_warning, store=self._store)

    # ---- views
    def _build_home(self):
      nav = self.navigation
      segmented = PillsAction(lambda: [(i, n) for i, n in enumerate(tl.LEVEL_NAMES)], self.choose_level,
                              selected=self.level, enabled=self._can_edit)
      tuning = attach_help(MenuRow(lambda: tr("Tuning Level"), icon_path("menu_tuning.png"), action_item=segmented),
                           "menu.tuning_level")
      # The home page has no header: the Tuning Level stays offroad only, so say so under its row while the car is on.
      tuning.subtitle = lambda: "" if self._can_edit() else tr(LOCKED_WHILE_DRIVING)
      items = [tuning]
      for section in nav.sections:
        pills = PillsAction(lambda s=section: [(p.key, p.label) for p in nav.pills_of(s)], self._open_pill)
        row = MenuRow(lambda s=section: tr(s.title), icon_path(section.icon), action_item=pills)
        row.set_visible(lambda s=section: bool(nav.pills_of(s)))
        attach_help(row, section.help_key or f"menu.{section.key}")
        items.append(row)
      for item in items:
        item.set_rect(rl.Rectangle(0, 0, 600, ROW_HEIGHT))
      return Scroller(items, line_separator=True, spacing=0, pad_end=False)

    def _open_pill(self, key):
      self.navigation.open_pill(key)

    def _build_page_list(self, entries, open_page):
      from openpilot.selfdrive.ui.bogpilot.section_icons import PAGE_SECTIONS, resolve_icon
      # A page that stands for a 0.9.7 section row (Lane Changes under STEERING) gets that section's icon.
      items = [button_item(lambda title=title: tr(title), lambda: tr("OPEN"), callback=lambda key=key: open_page(key),
                           icon=resolve_icon(PAGE_SECTIONS.get(key, "")))
               for key, title in entries]
      if not items:
        items = [text_item(lambda: tr("No active features available"), "")]
      return Scroller(items, line_separator=True, spacing=0)

    # ---- Back / top level (driven by the settings sidebar)
    def can_go_back(self) -> bool:
      return not self.navigation.at_top

    def go_back(self) -> bool:
      return self.navigation.back()

    def reset_to_top(self) -> None:
      self.navigation.reset()

    # ---- lifecycle
    def show_event(self):
      super().show_event()
      self._header.show_event()
      self.navigation.show_event()

    def hide_event(self):
      self.navigation.hide_event()
      self._header.hide_event()
      super().hide_event()
      # 0.9.7 closes every open sub-panel when the BogPilot panel is left: it always reopens at the top level.
      self.navigation.reset()

    def _render(self, rect):
      if not self.navigation.path:
        # Home: no header, so all seven rows fit the panel at once.
        self.navigation.current.render(rect)
        return
      header, body = content_bounds(rect.x, rect.y, rect.width, rect.height)
      self._header.set_parent_rect(rect)
      self._header.render(rl.Rectangle(*header))
      if body[2] > 0 and body[3] > 0:
        self.navigation.current.render(rl.Rectangle(*body))

  return MenuLayout()
