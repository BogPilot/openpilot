"""BogPilot Visuals: settings entry for BogPilot onroad visuals with real consumers.

Leaf rows already on feae:
  AdjacentLeadsUI, BlindSpotPath, BlindSpotMetrics, OnroadDistanceButton,
  PedalsOnUI, ScreenRecorder, DriverCamera.

t994 visualsTheme adds parent / peer gates that Bardo had ON but were unregistered:
  QOLVisuals, CustomUI, BorderMetrics, DynamicPedalsOnUI, SwapSpeedGraph,
  Fahrenheit, NumericalTemp, ShowCPU, ShowMemoryUsage, NavigationUI, ShowSpeedLimits.

Each row reads/writes through ParamStore (typed Params or /data/params_bogpilot for
file-only keys like SwapSpeedGraph). Consumers re-read within their caches.
Omitted theme keys (AccelerationPath, ModelUI, …) stay documented in
phase2_visuals_theme.OMITTED — no inert rows.
"""
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.selfdrive.ui.bogpilot.phase2_visuals_theme import NEW_VISUAL_TOGGLES
from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help

# key, title, description — existing leaf rows first (stable order for tests/screenshots)
_EXISTING = (
  ("AdjacentLeadsUI", tr_noop("Adjacent Lead Speed Boxes"),
   tr_noop("Show boxes with the speed of radar-tracked cars in the lanes beside you while openpilot is engaged.")),
  ("BlindSpotPath", tr_noop("Blind Spot Lane Fill"),
   tr_noop("Tint the lane beside you red while the car's blind spot monitor reports a vehicle there. "
           "Shown only on cars that report blind spot data.")),
  ("BlindSpotMetrics", tr_noop("Blind Spot Border"),
   tr_noop("Turn the matching half of the screen border red while the blind spot monitor reports a vehicle. "
           "Requires the status border (Border Metrics), which is on by default.")),
  ("OnroadDistanceButton", tr_noop("Driving Personality Button"),
   tr_noop("Show a button in the driver-side corner that shows and changes the driving personality.")),
  ("PedalsOnUI", tr_noop("Pedals on Screen"),
   tr_noop("Show translucent gas and brake pedals that fill with the car's acceleration.")),
  ("ScreenRecorder", tr_noop("Screen Recorder Button"),
   tr_noop("Show a button on the driving screen to record the screen.")),
  ("DriverCamera", tr_noop("Show Driver Camera When In Reverse"),
   tr_noop("Show the driver camera feed when the vehicle is in reverse.")),
)

# New theme/parent rows (tr_noop wrappers)
_NEW = tuple((k, tr_noop(title), tr_noop(desc)) for k, title, desc in NEW_VISUAL_TOGGLES)

# t1025: "Bog to the Future" flame tire tracks (onroad flame_tracks.py). File-only key: read and written through the store's
# legacy file path, /data/params_bogpilot/BSMFlameTracks, the same file the renderer reads. Default on.
_FLAME = (("BSMFlameTracks", tr_noop("Bog to the Future"),
           tr_noop("Draw burning tire tracks down the lane beside you behind a car that passes faster than 88 mph. "
                   "Display only; needs the blind spot lane fill.")),)

VISUAL_TOGGLES = _EXISTING[:3] + _FLAME + _EXISTING[3:] + _NEW
VISUAL_KEYS = tuple(k for k, _, _ in VISUAL_TOGGLES)
EXISTING_VISUAL_KEYS = tuple(k for k, _, _ in _EXISTING)
# t1024: the two navigation widgets live under Navigation in the 0.9.7 menu; the rest is Appearance.
NAVIGATION_KEYS = ("NavigationUI", "ShowSpeedLimits")
APPEARANCE_KEYS = tuple(k for k in VISUAL_KEYS if k not in NAVIGATION_KEYS)


def _store():
  from openpilot.common.bogpilot_store import ParamStore
  return ParamStore()


class BogPilotVisualsLayout(Widget):
  def __init__(self, store=None, keys=None):
    super().__init__()
    self._store = store if store is not None else _store()
    self._toggles = {}
    items = []
    for key, title, desc in VISUAL_TOGGLES:
      if keys is not None and key not in keys:
        continue
      item = toggle_item(lambda t=title: tr(t), lambda d=desc: tr(d), self._read(key),
                         callback=lambda state, k=key: self._write(k, state))
      attach_help(item, key)
      self._toggles[key] = item
      items.append(item)
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _read(self, key: str) -> bool:
    try:
      return bool(self._store.get_bool(key))
    except Exception:
      return False

  def _write(self, key: str, state: bool) -> None:
    self._store.put_bool(key, bool(state))
    self._store.invalidate(key)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self.refresh()

  def refresh(self):
    for key, item in self._toggles.items():
      item.action_item.set_state(self._read(key))

  def _render(self, rect):
    self._scroller.render(rect)
