"""BogPilot Visuals: the one settings entry for BogPilot onroad visuals that are already implemented.

Only existing registered keys; nothing new is registered and no default changes. Each row reads and writes the
key through ParamStore, so a typed (registered) key goes to Params and a file-only key to /data/params_bogpilot,
the same owner every onroad consumer already reads:
  AdjacentLeadsUI  -> hud_compose.PolicyToggles (adjacent lead boxes)
  BlindSpotPath    -> file_toggles + bogpilot_model BsmPolicy (BSM lane fill; AP1 cars only)
  BlindSpotMetrics -> hud_compose.bsm_border (BSM border half, with the existing BorderMetrics parent)
  OnroadDistanceButton -> hud_compose PolicyToggles (personality button; DM moves beside it)
  PedalsOnUI       -> hud_renderer pedals
  ScreenRecorder   -> onroad record button
Consumers re-read within their 2 s caches. No controls, safety, tuning or reset options live here.
"""
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.lib.multilang import tr, tr_noop

# key, title, description
VISUAL_TOGGLES = (
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
)
VISUAL_KEYS = tuple(k for k, _, _ in VISUAL_TOGGLES)


def _store():
  from openpilot.common.bogpilot_store import ParamStore
  return ParamStore()


class BogPilotVisualsLayout(Widget):
  def __init__(self, store=None):
    super().__init__()
    self._store = store if store is not None else _store()
    self._toggles = {}
    items = []
    for key, title, desc in VISUAL_TOGGLES:
      item = toggle_item(lambda t=title: tr(t), lambda d=desc: tr(d), self._read(key),
                         callback=lambda state, k=key: self._write(k, state))
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
