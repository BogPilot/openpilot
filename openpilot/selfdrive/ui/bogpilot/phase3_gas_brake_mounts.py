"""BogPilot > Driving Controls > Gas / Brake: the Driving Personalities, Speed Limit Controller and Longitudinal Tuning
(Human-Like Following, Human Lane Changes, Lead Detection Confidence Threshold) pages, mounted in the 0.9.7 hierarchy.

The page contents are the existing panel models (phase3_following, phase3_speed_control_settings); this module only
mounts them under the Gas / Brake page:

  Gas / Brake
    Driving Personalities      switch + MANAGE on Gas / Brake (MANAGE only while the switch is on); then one inline
                               page: Aggressive / Standard / Relaxed, each switch followed (indented, while it is on) by
                               Following Distance, five smoothness rows, Reset to Defaults
    Longitudinal Tuning        Acceleration / Deceleration profile, Human-Like Acceleration, Human-Like Following,
                               Human Lane Changes, Lead Detection Confidence Threshold
    Speed Limit Controller     toggle, Fallback Speed, Override Speed, Speed Limit Offsets / Quality of Life /
                               Visual Settings sub pages

Every write still goes through the panel model's own guard (offroad, row visible for the tuning level and parent, openpilot
longitudinal control) and its own consumer helper; nothing here writes. Importing the module needs no raylib.
"""
from __future__ import annotations

PERSONALITIES_TITLE = "Driving Personalities"
SLC_TITLE = "Speed Limit Controller"
PERSONALITIES_KEY = "CustomPersonalities"
SLC_KEY = "SpeedLimitController"


def personalities_description() -> str:
  from openpilot.selfdrive.ui.bogpilot.phase3_following import BY_KEY
  return BY_KEY[PERSONALITIES_KEY].desc


def slc_description() -> str:
  from openpilot.selfdrive.ui.layouts.settings.phase3_speed_control_settings import BY_KEY
  return BY_KEY[SLC_KEY][3]


def slc_supported(cp) -> bool | None:
  """True: a CarParams for a car the Speed Limit Controller consumer drives (Tesla AP1); False: any other car;
  None: no CarParams yet (the row shows, greyed, like the other longitudinal entries)."""
  from openpilot.selfdrive.controls.lib.phase3_speed_control import AP1
  try:
    fingerprint = getattr(cp, "carFingerprint", None)
  except Exception:
    return None
  if fingerprint is None:
    return None
  return str(fingerprint) == AP1


def _request_confirm(text, on_yes):
  """Ask through the dialog stack; the reset runs from the callback only, after a yes."""
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import DialogResult
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog

  def on_result(result):
    if result == DialogResult.CONFIRM:
      on_yes()

  gui_app.push_widget(ConfirmDialog(tr(text), tr("Reset"), callback=on_result))


def make_nested_panel(build, titles):
  """Panel with inner pages. build(section, open_section) -> widget (section None = first page); titles[section] names the
  inner page. Implements the navigation protocol the Gas / Brake page and the settings sidebar use: navigation_back()
  steps up one inner page and returns True, or returns False at the first page so the caller steps up itself."""
  from openpilot.system.ui.widgets import Widget

  class NestedPanel(Widget):
    def __init__(self):
      super().__init__()
      self._path = []
      self._shown = False
      self._current = build(None, self._open)

    @property
    def navigation_title(self):
      return titles.get(self._path[-1], "") if self._path else ""

    def _switch(self):
      if self._shown:
        self._current.hide_event()
      self._current = build(self._path[-1] if self._path else None, self._open)
      if self._shown:
        self._current.show_event()

    def _open(self, section):
      self._path.append(section)
      self._switch()

    def navigation_back(self):
      if not self._path:
        return False
      self._path.pop()
      self._switch()
      return True

    def show_event(self):
      super().show_event()
      self._shown = True
      self._current.show_event()

    def hide_event(self):
      self._shown = False
      self._current.hide_event()
      super().hide_event()

    def _render(self, rect):
      if rect.width > 0 and rect.height > 0:
        self._current.render(rect)

  return NestedPanel()


def make_personalities_panel(store, cp, can_edit):
  """One inline page: Aggressive / Standard / Relaxed, each switch followed by its own rows while it is on."""
  from openpilot.selfdrive.ui.bogpilot.phase3_following import make_layout
  return make_layout(cp, store, can_edit, section="personalities", request_confirm=_request_confirm)


def make_slc_panel(store, cp, can_edit):
  from openpilot.selfdrive.ui.layouts.settings.phase3_speed_control_settings import SUB_PANELS, make_layout

  def build(section, open_section):
    return make_layout(cp, store, can_edit, section=section, open_section=open_section)

  return make_nested_panel(build, dict(SUB_PANELS))


def longitudinal_tuning_items(store, cp, can_edit):
  """Returns a callable that builds the Human-Like Following / Human Lane Changes / Lead Detection Confidence Threshold rows for
  the Longitudinal Tuning page (appended after Human-Like Acceleration, 0.9.7 order). Built fresh on every page build."""
  from openpilot.selfdrive.ui.bogpilot.phase3_following import FollowingEditor, build_items

  def items():
    editor = FollowingEditor(cp, store, can_edit)
    return build_items(editor, store, cp, "longitudinal_tuning", runtime_integrated=True)[0]

  return items
