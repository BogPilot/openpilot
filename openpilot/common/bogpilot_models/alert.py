"""Offroad alert for a driving-model fallback (text only; the home screen renders it)."""
from __future__ import annotations

from openpilot.common.bogpilot_models import selection

ALERT_KEY = "BogPilot_ModelFallback"


def current_alert(store=None) -> dict | None:
  """{"text", "severity"} while a fallback is unresolved, else None. Never raises."""
  try:
    store = selection.default_store() if store is None else store
    fb = selection.read_state(store).get("fallback")
    if not fb:
      return None
    sel, corrupt = selection.read_selection(store)
    if not corrupt and (sel is None or sel.id != fb.get("requested_id")):
      return None  # the user already moved on
    name = fb.get("requested_name") or "The selected driving model"
    return {"text": f'Driving model "{name}" was not used: {fb.get("reason", "it failed")}. '
                    "The Default (stock) model is driving instead. Review it in Settings > BogPilot > Driving Controls > Driving Model.",
            "severity": 1}
  except Exception:
    return None
