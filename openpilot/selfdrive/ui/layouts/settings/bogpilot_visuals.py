"""BogPilot Visuals: settings entry for BogPilot onroad visuals with real consumers.

Leaf rows already on feae:
  AdjacentLeadsUI, BlindSpotPath, BlindSpotMetrics, OnroadDistanceButton,
  PedalsOnUI, DriverCamera. (The Screen Recorder button is under System Settings > Device Controls > Screen Settings.)

visualsTheme adds parent / peer gates that earlier builds had ON but were unregistered:
  QOLVisuals, CustomUI, LowerSpeedLimitsBox, NavigationUI, ShowSpeedLimits.

Developer overlays: DeveloperHUD (onroad Developer HUD panel), FPSCounter, DeveloperSidebar (with its seven metric pickers,
shown while it is on) and ShowIP. The sidebar's CPU / GPU, RAM / storage and temperature contents are not rows: a tap on
each sidebar box cycles them (layouts/sidebar.py).

Each row reads/writes through ParamStore (typed Params or /data/params_bogpilot for
file-only keys like LowerSpeedLimitsBox). Consumers re-read within their caches.
Omitted theme keys (AccelerationPath, ModelUI, …) stay documented in
phase2_visuals_theme.OMITTED — no inert rows.
"""
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import button_item, multiple_button_item, toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.selfdrive.ui.bogpilot.phase2_visuals_theme import NEW_VISUAL_TOGGLES, SIDEBAR_TAP_KEYS
from openpilot.selfdrive.ui.bogpilot import developer_sidebar_logic as DSL
from openpilot.selfdrive.ui.bogpilot.nesting import place
from openpilot.selfdrive.ui.bogpilot.toggle_help import attach_help
from openpilot.selfdrive.ui.onroad.bogpilot.overlay_gate import read_overlay
from openpilot.selfdrive.ui.bogpilot import camera_view as CV

# key, title, description — existing leaf rows first (stable order for tests/screenshots)
_EXISTING = (
  ("AdjacentLeadsUI", tr_noop("Adjacent Lead Speed Boxes"),
   tr_noop("Show boxes with the speed of radar-tracked cars in the lanes beside you while openpilot is engaged.")),
  ("BlindSpotPath", tr_noop("Blind Spot Lane Fill"),
   tr_noop("Tint the lane beside you red while the car's blind spot monitor reports a vehicle there. "
           "Shown only on cars that report blind spot data.")),
  ("BlindSpotMetrics", tr_noop("Blind Spot Border"),
   tr_noop("Turn the matching half of the screen border red while the blind spot monitor reports a vehicle. "
           "Shown only on cars that report blind spot data.")),
  ("OnroadDistanceButton", tr_noop("Driving Personality Button"),
   tr_noop("Show a button in the driver-side corner that shows and changes the driving personality.")),
  ("PedalsOnUI", tr_noop("Pedals on Screen"),
   tr_noop("Shows the brake pedal on the left bar, regen power in the middle and acceleration on the right.")),
  ("DriverCamera", tr_noop("Show Driver Camera When In Reverse"),
   tr_noop("Show the driver camera feed when the vehicle is in reverse.")),
)

# New theme/parent rows (tr_noop wrappers)
# The sidebar rows (Show CPU, Show Memory, temperature units) are not menu rows: tapping a sidebar box cycles its contents.
_NEW = tuple((k, tr_noop(title), tr_noop(desc)) for k, title, desc in NEW_VISUAL_TOGGLES if k not in SIDEBAR_TAP_KEYS)

# "Bog to the Future" flame tire tracks (onroad flame_tracks.py). File-only key: read and written through the store's
# legacy file path, /data/params_bogpilot/BSMFlameTracks, the same file the renderer reads. Default on.
_FLAME = (("BSMFlameTracks", tr_noop("Bog to the Future"),
           tr_noop("Draw burning tire tracks down the lane beside you behind a car that passes faster than 88 mph. "
                   "Display only; needs the blind spot lane fill.")),)

# Custom Log Upload Stats (selfdrive/ui/bogpilot/upload_stats.py). File-only key, default off. It reads the status line a
# manually installed rsync or Nextcloud uploader writes; with no uploader reporting, nothing is drawn.
_UPLOAD = (("CustomLogUploadStats", tr_noop("Custom Log Upload Stats"),
            tr_noop("Show the upload rate and segments left on screen for an rsync or Nextcloud uploader you installed "
                    "yourself to copy realdata and screen recordings to your own storage. Hidden while no uploader is "
                    "reporting. Display only.")),)

# Developer overlays (0.9.7). DeveloperHUD is file-backed like the other onroad UI toggles and is read by the onroad HUD
# (developer_hud.py); ShowIP is read by layouts/sidebar.py.
_DEVELOPER = (
  ("ShowAccelGraph", tr_noop("Show Accel Graph"),
   tr_noop("Show the acceleration request graph on the driving screen. It can slow UI draw time, so it is off by "
           "default. Display only; takes effect within 2 seconds.")),
  ("DeveloperHUD", tr_noop("Developer HUD"),
   tr_noop("Show a live data panel at the top right of the driving screen: acceleration, lead distance and speed, "
           "steering angle (real and desired), lateral acceleration, altitude and memory. Display only.")),
  ("FPSCounter", tr_noop("FPS Display"),
   tr_noop("Show the frames per second the screen is drawing, with the minimum and maximum for this drive and the "
           "average over the last minute, along the bottom of the driving screen. Display only.")),
  ("DeveloperSidebar", tr_noop("Developer Sidebar"),
   tr_noop("Show a 300 pixel panel on the right of the driving screen with up to seven live metrics you choose below. "
           "Display only.")),
  ("ShowIP", tr_noop("Show IP in Sidebar"),
   tr_noop("Show the Wi-Fi address in place of the signal dots in the sidebar.")),
)

# BogPilot 0.9.7 confidence ball (onroad/bogpilot/confidence_ball.py). File-only key like Bog to the Future: the row and the renderer
# share /data/params_bogpilot/ConfidenceBall. Default on (0.9.7: no file = shown); top of the page, every tuning level.
_BALL = (("ConfidenceBall", tr_noop("Confidence Ball"),
          tr_noop("Show a small ball on the edge of the driving screen whose height follows how confident the driving model "
                  "is. While openpilot is engaged it is green, orange or red. While you override it is white with a grey shade. "
                  "While openpilot is off it is slate grey when the model is sure and fades to white when it is not. "
                  "Display only.")),)
# 0.9.7 had Off / Left / Right in one control: the on/off row above plus this Left / Right row (ConfidenceBallSide, default Left).
SIDE_KEY = "ConfidenceBallSide"
SIDE_CHOICES = ("left", "right")
SIDE_DESCRIPTION = tr_noop("Which edge of the driving screen the confidence ball rides on.")
SIDE_BUTTON_WIDTH = 200
# Camera View (QOL child): Auto / Standard / Wide; stored codes 0 / 2 / 3 (bogpilot/camera_view.py). No Driver.
CAMERA_KEY = "CameraView"
CAMERA_DESCRIPTION = tr_noop("Which road camera the driving screen shows. Auto switches to the wide camera at low speed in "
                             "Experimental Mode, as stock openpilot does. Display only.")
CAMERA_BUTTON_WIDTH = 230
# Rows hidden on a Pre-AP Model S. It reports no blind spot data, so these never draw there; 0.9.7 hid them on a car
# without blind spot data (visual_settings.cc:548-553 and :616 @04d560f3). Saved values are kept and nothing is written.
# Same rule as the Speed Limit Controller rows (phase3_speed_control_settings.car_row_allowed).
PREAP = "TESLA_PREAP_MODELS"
PREAP_HIDDEN = ("BlindSpotPath", "BlindSpotMetrics", "BSMFlameTracks")
CAR_GATED = frozenset(PREAP_HIDDEN)


def car_row_allowed(key, CP) -> bool:
  """CAR_GATED rows: hidden on a Pre-AP Model S only; shown on every other car and with no CarParams."""
  if key not in CAR_GATED:
    return True
  return not (CP is not None and str(getattr(CP, "carFingerprint", "") or "") == PREAP)


VISUAL_TOGGLES = _BALL + _EXISTING[:3] + _FLAME + _EXISTING[3:] + _NEW + _UPLOAD + _DEVELOPER
VISUAL_KEYS = tuple(k for k, _, _ in VISUAL_TOGGLES)
DEVELOPER_KEYS = tuple(k for k, _, _ in _DEVELOPER)
# FPS Display registers OFF. Counted only when stored, so a device whose compiled key table still carries the old default (on)
# stays off until the user turns it on: row and overlay read the same thing.
STORED_ONLY_KEYS = ("FPSCounter",)
EXISTING_VISUAL_KEYS = tuple(k for k, _, _ in _EXISTING)
# the two navigation widgets live under Navigation in the 0.9.7 menu; the rest is Appearance.
NAVIGATION_KEYS = ("NavigationUI", "ShowSpeedLimits")
APPEARANCE_KEYS = tuple(k for k in VISUAL_KEYS if k not in NAVIGATION_KEYS)


# The page tree: (row, (children...)). A child is indented under its parent and shown only while the parent is on (nesting.py).
# Each pairing is the one the consumer already enforces (QOL: reverse_camera / hud_compose, CustomUI: bogpilot_onroad_toggles /
# pedals.py). Bog to the Future and Adjacent Lead Speed Boxes stay peers: their renderers read no
# parent, so hiding them would leave them applying unseen.
_SIDEBAR_PICKERS = tuple((k, ()) for k in DSL.metric_keys())
TREE = (
  ("ConfidenceBall", ()),
  (SIDE_KEY, ()),
  ("QOLVisuals", (("DriverCamera", ()), (CAMERA_KEY, ()), ("OnroadDistanceButton", ()))),
  ("CustomUI", (("BlindSpotPath", ()), ("PedalsOnUI", ()))),
  ("BSMFlameTracks", ()),
  ("AdjacentLeadsUI", ()),
  ("BlindSpotMetrics", ()),
  ("LowerSpeedLimitsBox", ()),
  ("CustomLogUploadStats", ()),
  ("ShowAccelGraph", ()),
  ("DeveloperHUD", ()),
  ("FPSCounter", ()),
  ("DeveloperSidebar", _SIDEBAR_PICKERS),
  ("ShowIP", ()),
  ("NavigationUI", (("ShowSpeedLimits", ()),)),
)


def _store():
  from openpilot.common.bogpilot_store import ParamStore
  return ParamStore()


class BogPilotVisualsLayout(Widget):
  def __init__(self, store=None, keys=None, cp_source=None):
    super().__init__()
    self._store = store if store is not None else _store()
    self._cp_source = cp_source
    self._toggles = {}
    self._pickers = {}
    by_key = {}
    for key, title, desc in VISUAL_TOGGLES:
      if keys is not None and key not in keys:
        continue
      item = toggle_item(lambda t=title: tr(t), lambda d=desc: tr(d), self._read(key),
                         callback=lambda state, k=key: self._write(k, state))
      attach_help(item, key)
      if key in CAR_GATED and hasattr(item, "set_visible"):
        item.set_visible(lambda k=key: car_row_allowed(k, self._cp()))
      self._toggles[key] = item
      by_key[key] = item
      if key == "DeveloperSidebar":
        for n, metric_key in enumerate(DSL.metric_keys(), start=1):
          self._pickers[metric_key] = by_key[metric_key] = self._make_picker(metric_key, n)
    self._side = None
    if "ConfidenceBall" in self._toggles:
      self._side = by_key[SIDE_KEY] = multiple_button_item(lambda: tr("Confidence Ball Side"), lambda: tr(SIDE_DESCRIPTION),
                                                           [lambda: tr("Left"), lambda: tr("Right")], self._read_side(),
                                                           button_width=SIDE_BUTTON_WIDTH, callback=self._write_side)
      attach_help(self._side, SIDE_KEY)
    self._camera = None
    if "QOLVisuals" in self._toggles:
      self._camera = by_key[CAMERA_KEY] = multiple_button_item(
        lambda: tr("Camera View"), lambda: tr(CAMERA_DESCRIPTION), [lambda n=n: tr(n) for n in CV.OPTIONS.values()],
        self._read_camera(), button_width=CAMERA_BUTTON_WIDTH, callback=self._write_camera)
      attach_help(self._camera, CAMERA_KEY)
    items = place(by_key, TREE)
    # a row the tree does not name is still offered (never silently lost), after the tree
    items += [item for key, item in by_key.items() if item not in items]
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _cp(self):
    """The car's CarParams (offroad, from the last drive), or None."""
    try:
      if self._cp_source is not None:
        return self._cp_source()
      from openpilot.selfdrive.ui.ui_state import ui_state
      return ui_state.CP
    except Exception:
      return None

  # ---- Developer Sidebar metric pickers (0.9.7: Metric #1 to #7) ----
  def _torque_steering(self):
    """True / False when the car's steering type is known (offroad it comes from the last drive), else None."""
    try:
      from openpilot.selfdrive.ui.ui_state import ui_state
      return DSL.torque_steering(ui_state.CP)
    except Exception:
      return None

  def _metric_name(self, key: str) -> str:
    try:
      number = self._store.get_int(key)
    except Exception:
      number = 0
    return DSL.METRICS[number][1] if number in DSL.METRICS else "None"

  def _make_picker(self, key: str, n: int):
    item = button_item(lambda n=n: tr("Metric #{}").format(n), lambda k=key: tr(self._metric_name(k)),
                       lambda n=n: tr("Choose the metric shown in tile {} of the Developer Sidebar.").format(n),
                       callback=lambda k=key: self._open_picker(k))
    attach_help(item, key)
    return item

  def _open_picker(self, key: str):
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.system.ui.widgets import DialogResult
    from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
    offered = DSL.available_metrics(self._torque_steering())
    by_label = {tr("None"): 0} | {tr(name): number for number, (_, name, _) in offered.items()}
    current = tr(self._metric_name(key))
    dialog = MultiOptionDialog(tr("Select a metric to display"), list(by_label), current if current in by_label else tr("None"))

    def done(result):
      if result == DialogResult.CONFIRM and dialog.selection in by_label:
        self._store.put(key, by_label[dialog.selection])
        self._store.invalidate(key)

    dialog._callback = done
    gui_app.push_widget(dialog)
    return dialog

  def _read(self, key: str) -> bool:
    try:
      if key in STORED_ONLY_KEYS:
        return read_overlay(self._store, key, stored_only=True)
      return bool(self._store.get_bool(key))
    except Exception:
      return False

  def _write(self, key: str, state: bool) -> None:
    self._store.put_bool(key, bool(state))
    self._store.invalidate(key)

  def _read_side(self) -> int:
    try:
      return 1 if str(self._store.get(SIDE_KEY)).strip().lower() == "right" else 0
    except Exception:
      return 0

  def _write_side(self, index: int) -> None:
    self._store.put(SIDE_KEY, SIDE_CHOICES[1 if index == 1 else 0])
    self._store.invalidate(SIDE_KEY)

  def _read_camera(self) -> int:
    try:
      return CV.button_index(CV.normalize(self._store.get(CAMERA_KEY)))   # a saved Driver shows (and acts) as Auto
    except Exception:
      return 0

  def _write_camera(self, index: int) -> None:
    self._store.put(CAMERA_KEY, CV.CODES[index] if 0 <= index < len(CV.CODES) else CV.AUTO)
    self._store.invalidate(CAMERA_KEY)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self.refresh()

  def refresh(self):
    for key, item in self._toggles.items():
      item.action_item.set_state(self._read(key))
    if self._side is not None:
      self._side.action_item.set_selected_button(self._read_side())
    if self._camera is not None:
      self._camera.action_item.set_selected_button(self._read_camera())

  def _render(self, rect):
    self._scroller.render(rect)
