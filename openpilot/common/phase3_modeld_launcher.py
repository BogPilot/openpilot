"""modeld entry point that applies the phase 3 model runtime without editing pinned modeld files.

process_config points "modeld" here. Model choice is resolved exactly once per modeld process
start (modeld is only_onroad), so a running modeld never switches model. Any alternate load or
run failure records a rollback to stock; load failures fall back to stock in the same process.
"""
from __future__ import annotations
import numpy as np

from openpilot.common.phase3_model_runtime import STOCK_ID, Runtime


def install(modeld_module, runtime: Runtime | None = None):
  m = modeld_module
  rt = runtime or Runtime()
  base = m.ModelState
  if getattr(base, "_bp_phase3", False):
    return base
  original_path = m.modeld_pkl_path
  # Same expression modeld.main() uses. When the Chestnut big model can run, the small model is only a
  # fallback that may never run, so it stays stock (an unrun alternate would falsely count as unconfirmed).
  try:
    chestnut_mode = m.chestnut_compiled() and (m.chestnut_present() or m.cable_connected())
  except Exception:
    chestnut_mode = True

  class Phase3ModelState(base):
    _bp_phase3 = True

    def __init__(self, cam_w, cam_h, chestnut):
      sel = rt.resolve_for_modeld(chestnut or chestnut_mode)
      self._bp_id, self._bp_sha, self._bp_confirmed, self._bp_warmup = STOCK_ID, "", False, False
      if sel.id != STOCK_ID:
        m.modeld_pkl_path = lambda _chestnut, _p=sel.path: _p
        try:
          super().__init__(cam_w, cam_h, chestnut)
          self._bp_id, self._bp_sha = sel.id, sel.sha256
          return
        except Exception as e:
          m.cloudlog.exception("phase3 alternate model load failed, using stock")
          rt.record_failure(sel.id, f"load failed: {type(e).__name__}")
        finally:
          m.modeld_pkl_path = original_path
      super().__init__(cam_w, cam_h, chestnut)

    def warmup(self):
      self._bp_warmup = True
      try:
        return super().warmup()
      finally:
        self._bp_warmup = False

    def run(self, *args, **kwargs):
      try:
        out = super().run(*args, **kwargs)
        if self._bp_id != STOCK_ID and not all(np.all(np.isfinite(v)) for v in out.values() if isinstance(v, np.ndarray)):
          raise RuntimeError("alternate model output not finite")
      except Exception as e:
        if self._bp_id != STOCK_ID:
          rt.record_failure(self._bp_id, f"run failed: {type(e).__name__}")
        raise
      if not self._bp_confirmed and not self._bp_warmup:
        self._bp_confirmed = True
        try:
          rt.confirm(self._bp_id, self._bp_sha, self.chestnut)
        except Exception:
          m.cloudlog.exception("phase3 model ack failed")
      return out

  m.ModelState = Phase3ModelState
  return Phase3ModelState


def main(demo=False):
  # manager's launcher calls mod.main() with no arguments, exactly like stock modeld.main()
  from openpilot.selfdrive.modeld import modeld as m
  install(m)
  m.main(demo=demo)


if __name__ == "__main__":
  import argparse
  parser = argparse.ArgumentParser()
  parser.add_argument('--demo', action='store_true', help='A boolean for demo mode.')
  try:
    main(demo=parser.parse_args().demo)
  except KeyboardInterrupt:
    print("got SIGINT")
