"""Active-only phase two navigation. Importing this module has no UI/Params side effects.

The integrator supplies Page descriptors from working feature lanes. No discovery,
optional-module imports or guessed controls: an absent/empty page has no entry.
"""
from dataclasses import dataclass
from collections.abc import Callable, Iterable

GROUPS = (("alerts_sounds", "Alerts and Sounds"),
          ("driving", "Driving Controls"), ("vehicle", "Vehicle Settings"))


@dataclass(frozen=True)
class Page:
  key: str
  title: str
  factory: Callable[[], object]
  # Actual active consumer-backed control IDs, supplied by the feature owner.
  controls: tuple[str, ...] = ()


def active_groups(supplied):
  """Return canonical requested groups only, omitting empty pages/groups.

  supplied maps canonical group key to an iterable of Page instances. Unknown
  groups and duplicate page keys are errors, rather than accidentally porting
  historical Navigation/System/Theme categories.
  """
  unknown = set(supplied) - {key for key, _ in GROUPS}
  if unknown:
    raise ValueError(f"Unsupported groups: {sorted(unknown)}")
  seen, result = set(), []
  for key, title in GROUPS:
    pages = []
    for page in supplied.get(key, ()):
      if not page.controls:
        continue
      if not page.key or not page.title or not callable(page.factory):
        raise ValueError("Active pages need key, title and callable factory")
      if page.key in seen:
        raise ValueError(f"Duplicate page: {page.key}")
      seen.add(page.key)
      pages.append(page)
    if pages:
      result.append((key, title, tuple(pages)))
  return tuple(result)


class Navigation:
  """Inline view lifecycle/backstack, independent of raylib and vehicle state."""
  def __init__(self, supplied, menu_factory):
    self.groups = active_groups(supplied)
    self._menu_factory = menu_factory
    self._cache = {}
    self.path = ()
    self.visible = False

  @property
  def title(self):
    if not self.path:
      return "BogPilot"
    group = next(g for g in self.groups if g[0] == self.path[0])
    return group[1] if len(self.path) == 1 else next(p.title for p in group[2] if p.key == self.path[1])

  def entries(self):
    if not self.path:
      return tuple((key, title) for key, title, _ in self.groups)
    if len(self.path) == 1:
      return tuple((p.key, p.title) for key, _, pages in self.groups if key == self.path[0] for p in pages)
    return ()

  @property
  def current(self):
    if self.path not in self._cache:
      if len(self.path) == 2:
        page = next(p for key, _, pages in self.groups if key == self.path[0] for p in pages if p.key == self.path[1])
        self._cache[self.path] = page.factory()
      else:
        self._cache[self.path] = self._menu_factory(self.entries(), self.open)
    return self._cache[self.path]

  def _move(self, path):
    old = self.path
    # Construct first: a failed factory must leave the visible view intact.
    self.path = path
    try:
      target = self.current
    except Exception:
      self.path = old
      raise
    self.path = old
    if self.visible:
      self.current.hide_event()
    self.path = path
    if self.visible:
      target.show_event()

  def open(self, key):
    if key not in dict(self.entries()):
      raise KeyError(key)
    self._move((*self.path, key))

  def back(self):
    if not self.path:
      return False
    self._move(self.path[:-1])
    return True

  def show_event(self):
    if not self.visible:
      self.current.show_event()
      self.visible = True

  def hide_event(self):
    if self.visible:
      self.current.hide_event()
      self.visible = False


def content_bounds(x, y, width, height):
  """Bound header/content to the caller's settings panel (no sidebar overlap)."""
  width, height = max(0, width), max(0, height)
  header = min(170, height)
  return (x, y, width, header), (x, y + header, width, height - header)


def build_layout(supplied=None):
  """Construct the raylib Widget only when settings initializes it.

  No leaf is instantiated until opened. Navigation never reads/writes Params.
  Existing settings owns show/hide and close; internal Back is inline, not a
  gui_app stack push, so sidebar changes and dialogs retain their lifecycle.
  """
  import pyray as rl
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import Widget
  from openpilot.system.ui.widgets.list_view import button_item, text_item
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  def menu(entries, open_page):
    items = [button_item(lambda title=title: tr(title), lambda: tr("OPEN"),
                         callback=lambda key=key: open_page(key)) for key, title in entries]
    if not items:
      items = [text_item(lambda: tr("No active features available"), "")]
    return Scroller(items, line_separator=True, spacing=0)

  class Phase2Layout(Widget):
    def __init__(self):
      super().__init__()
      self.navigation = Navigation(supplied or {}, menu)
      self._header = button_item(lambda: tr(self.navigation.title), lambda: tr("BACK"),
                                  callback=self.navigation.back, enabled=lambda: bool(self.navigation.path))

    def show_event(self):
      super().show_event()
      self._header.show_event()
      self.navigation.show_event()

    def hide_event(self):
      self.navigation.hide_event()
      self._header.hide_event()
      super().hide_event()

    def _render(self, rect):
      header, body = content_bounds(rect.x, rect.y, rect.width, rect.height)
      self._header.render(rl.Rectangle(*header))
      if body[2] > 0 and body[3] > 0:
        self.navigation.current.render(rl.Rectangle(*body))

  return Phase2Layout()
