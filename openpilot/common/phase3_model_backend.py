"""Lane3 ModelBackend adapter over the phase 3 model runtime (lane2).

Only capabilities the runtime really implements are advertised: select (and stock rollback) when at
least one installed alternate passes the exact-ABI check, delete for installed non-protected alternates.
Download / automatic / randomizer / blacklist / ratings are NOT advertised: no compatible catalog source
or real consumer exists, and lane3 then renders the concrete unavailable reason.
"""
from __future__ import annotations
from openpilot.common.phase3_model_catalog import STOCK_NAME
from openpilot.common.phase3_model_runtime import STOCK_ID, Runtime


def _ui_types():
  from openpilot.selfdrive.ui.bogpilot import phase3_model_selector as ui
  return ui


def default_is_offroad():
  from openpilot.common.params import Params
  return Params().get_bool("IsOffroad")


class RuntimeModelBackend:
  def __init__(self, runtime: Runtime | None = None, is_offroad=default_is_offroad, ui_types=None):
    self.rt = runtime or Runtime()
    self.is_offroad = is_offroad
    self.ui = ui_types or _ui_types()

  def snapshot(self):
    ui, st = self.ui, self.rt.status()
    models = [ui.Model(id=STOCK_ID, name=STOCK_NAME, available=True, downloaded=st.stock_verified,
                       compatible=True if st.stock_verified else None, reason=st.stock_reason, protected=True)]
    for i in st.installed:
      reason, comp, verified = st.failed.get(i.id) or i.reason, i.compatible, i.verified
      if i.id in st.failed:  # rolled back: re-hash now so a corrupt/missing bundle is not offered for selection
        c2, r2 = self.rt.verify_bundle_deep(i.id)
        if c2 is not True:
          comp, verified, reason = c2, False, f"{reason}; now: {r2}"
      models.append(ui.Model(id=i.id, name=i.name, available=True, downloaded=verified, compatible=comp,
                             reason=("Rolled back: " + reason) if i.id in st.failed else reason))
    caps = set()
    if any(i.compatible is True for i in st.installed) and st.stock_verified:
      caps.add("select")
    if any(i.id not in (st.active_id, st.pending_id, st.selected_id) for i in st.installed):
      caps.add("delete")
    return ui.Snapshot(revision=st.revision, models=tuple(models), capabilities=frozenset(caps),
                       active_id=st.active_id, pending_id=st.pending_id, error=st.error, limitation=st.limitation)

  def request(self, action, model_id, revision):
    ui = self.ui
    try:
      if action == "select" and model_id is not None:
        ok, msg = self.rt.select(model_id, revision, self.is_offroad)
      elif action == "delete" and model_id is not None:
        ok, msg = self.rt.delete(model_id, revision, self.is_offroad)
      else:
        ok, msg = False, f"{action} is not supported by the 0.11.2 model runtime."
    except Exception as e:
      ok, msg = False, f"Model runtime error: {type(e).__name__}"
    return ui.Result(accepted=ok, message=msg)
