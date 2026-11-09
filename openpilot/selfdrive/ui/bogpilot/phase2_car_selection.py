"""BogPilot > Vehicle Settings > Car Selection.

Manual selection writes CarModel / ForceFingerprint so a bench or bring-up can
pick Tesla AP1 Model S when automatic detection returned None (unmatched CAN /
no signature). Auto (default) clears the override.

SAFETY: the saved model is applied ONLY when detection returned None. A
positively detected different car always wins — ForceFingerprint must never
replace a recognised non-AP1 (or any other) identity. See REVIEW.md blocker.

Aligned with CAR_DETECTION.md (t993): only TESLA_AP1_MODELS is a real Platforms
entry. AP1 Model X (ap1_x) stays fixture-only — listed but not writable. Do not
invent FW_VERSIONS rows.

Consumer wiring (get_car fingerprint_override + card.py) is NOT applied here;
see PROPOSED_shared.patch for the integrator. This is a NEW safety-relevant
consumer on feae (env FINGERPRINT was the only fixed path).
"""
from __future__ import annotations

MAKE_KEY, MODEL_KEY, MODEL_NAME_KEY, FORCE_KEY = "CarMake", "CarModel", "CarModelName", "ForceFingerprint"

AUTO = "auto"
AP1_S = "ap1_s"
AP1_X = "ap1_x"

AP1_S_PLATFORM = "TESLA_AP1_MODELS"
AP1_S_MAKE = "Tesla"
AP1_S_DOC = "Tesla Model S (Autopilot 1) 2014-16"

# UI labels: Auto first (default). Model X is shown but not selectable for force.
CHOICE_ORDER = (AUTO, AP1_S, AP1_X)
CHOICE_LABELS = {
  AUTO: "Auto",
  AP1_S: "Tesla AP1 Model S",
  AP1_X: "Tesla AP1 Model X (unavailable)",
}
CHOICE_DESCRIPTIONS = {
  AUTO: "Automatic detection (chassis + Mobileye when present). Default. Clears any saved CarModel / ForceFingerprint. Takes effect the next time the car starts.",
  AP1_S: "Use Tesla AP1 Model S (TESLA_AP1_MODELS) via CarModel + ForceFingerprint only when automatic detection returns no car. A positively detected different car always wins. Takes effect the next time the car starts.",
  AP1_X: "AP1 Model X is not a registered platform in this tip (fixture-only). Cannot be forced without inventing a Platforms / FW entry — not offered.",
}


def _text(value) -> str:
  if value is None:
    return ""
  if isinstance(value, (bytes, bytearray)):
    value = value.decode(errors="replace")
  return str(value).strip()


def valid_platform(name: str, platforms=None) -> bool:
  if platforms is None:
    from opendbc.car.values import PLATFORMS
    platforms = PLATFORMS
  return bool(name) and name in platforms and name != "MOCK"


def selected_fingerprint(params, detected: str | None, platforms=None) -> tuple[str | None, bool]:
  """get_car override: (candidate, used_saved).

  Saved CarModel is used ONLY when automatic detection returned None, and only
  if it is a real platform in this tree. A positively detected car always wins
  (including when it equals the saved model — detected wins, used_saved=False).
  ForceFingerprint never overrides a different recognised identity.
  Never invents platforms.
  """
  saved = _text(params.get(MODEL_KEY))
  if not valid_platform(saved, platforms):
    return detected, False
  if detected is None:
    return saved, True
  # detected is a real identity (same or different): detection wins
  return detected, False


def current_choice(params) -> str:
  """Map stored Params to a UI choice id. Fresh/empty -> Auto."""
  saved = _text(params.get(MODEL_KEY))
  if not saved:
    return AUTO
  if saved == AP1_S_PLATFORM:
    return AP1_S
  # Unknown / other saved model: surface as Auto for this AP1-only picker, but
  # do not clear it here (owner may have set it elsewhere).
  return AUTO


def choice_label(params) -> str:
  choice = current_choice(params)
  if choice == AP1_S and _text(params.get(MODEL_KEY)) == AP1_S_PLATFORM:
    force = bool(params.get_bool(FORCE_KEY))
    base = CHOICE_LABELS[AP1_S]
    return f"{base} (forced)" if force else f"{base} (fallback)"
  return CHOICE_LABELS[choice]


def available_choices():
  """Writable choices only (Auto + Model S). Model X excluded from apply list."""
  return (AUTO, AP1_S)


def apply_choice(params, choice: str, *, offroad: bool) -> bool:
  """Write CarModel/ForceFingerprint for a writable choice. Offroad-only.

  Returns True when Params were updated. Model X and unknown ids refuse.
  """
  if not offroad:
    return False
  if choice == AUTO:
    clear_selection(params)
    return True
  if choice == AP1_S:
    if not valid_platform(AP1_S_PLATFORM):
      return False
    params.put(MAKE_KEY, AP1_S_MAKE, block=True)
    params.put(MODEL_KEY, AP1_S_PLATFORM, block=True)
    params.put(MODEL_NAME_KEY, AP1_S_DOC, block=True)
    params.put_bool(FORCE_KEY, True, block=True)
    return True
  # AP1_X and anything else: refuse (no Platforms entry / do not invent)
  return False


def clear_selection(params) -> None:
  """Back to Auto: forget the saved model and turn ForceFingerprint off."""
  for key in (MAKE_KEY, MODEL_KEY, MODEL_NAME_KEY):
    try:
      params.remove(key)
    except Exception:
      pass
  # Ensure Auto even if remove() is a no-op on some Params backends
  for key in (MAKE_KEY, MODEL_KEY, MODEL_NAME_KEY):
    if _text(params.get(key)):
      try:
        params.put(key, "", block=True)
      except Exception:
        pass
  params.put_bool(FORCE_KEY, False, block=True)


def create_car_selection_layout(params=None):
  """Lazy UI factory: Auto / Tesla AP1 Model S (+ unavailable Model X note)."""
  from openpilot.common.params import Params
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.lib.multilang import tr
  from openpilot.system.ui.widgets import DialogResult, Widget
  from openpilot.system.ui.widgets.list_view import button_item, text_item
  from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
  from openpilot.system.ui.widgets.scroller_tici import Scroller

  class CarSelectionLayout(Widget):
    def __init__(self):
      super().__init__()
      self.params = params if params is not None else Params()
      self._dialog = None
      self._select = button_item(
        lambda: tr("Car Selection"),
        lambda: tr("SELECT"),
        lambda: tr("Choose Auto (default) or force Tesla AP1 Model S when detection fails. Takes effect the next time the car starts."),
        callback=self._open_picker,
        enabled=ui_state.is_offroad,
      )
      self._current = text_item(lambda: tr("Current selection"), "")
      self._note = text_item(
        lambda: tr("AP1 Model X"),
        lambda: tr(CHOICE_DESCRIPTIONS[AP1_X]),
      )
      self.scroller = Scroller([self._select, self._current, self._note], line_separator=True, spacing=0)

    def _open_picker(self):
      if not ui_state.is_offroad():
        self.refresh()
        return
      labels = [CHOICE_LABELS[c] for c in available_choices()]
      current = CHOICE_LABELS[current_choice(self.params)]
      if current not in labels:
        current = CHOICE_LABELS[AUTO]

      def done(result):
        sel = self._dialog.selection if self._dialog is not None else None
        self._dialog = None
        if result == DialogResult.CONFIRM and sel in labels:
          choice = available_choices()[labels.index(sel)]
          apply_choice(self.params, choice, offroad=ui_state.is_offroad())
        self.refresh()

      self._dialog = MultiOptionDialog(tr("Car Selection"), labels, current, callback=done)
      gui_app.push_widget(self._dialog)

    def refresh(self):
      self._current.action_item.set_text(tr(choice_label(self.params)))
      self._select.action_item.set_value(tr(CHOICE_LABELS[current_choice(self.params)]))

    def show_event(self):
      super().show_event()
      self.scroller.show_event()
      self.refresh()

    def _render(self, rect):
      self.refresh()
      self.scroller.render(rect)

  return CarSelectionLayout()
