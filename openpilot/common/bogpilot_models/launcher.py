"""modeld entry point that applies BogPilot's driving-model selection without editing pinned modeld files.

process_config starts "modeld" here. The choice is resolved ONCE per modeld start (modeld only runs onroad), so
a running modeld never switches model. With Default selected, or on any error at all in the selector, this
calls the untouched stock modeld.main(): no patching, no hashing, no extra file reads beyond one setting read.

A selected model is used only if it passed validation (file hashes + 0.11.2 compatibility) in
bogpilot_models.resolve and then loads and runs one warm-up inference. Any failure records a fallback (the home
screen shows the offroad alert) and constructs the exact stock ModelState instead.
"""
from __future__ import annotations

import re

import numpy as np

_WARP_RE = re.compile(r"^driving_warp_(\d+x\d+)_tinygrad\.pkl$")


def _log(level: str, msg: str) -> None:
  try:
    from openpilot.common.swaglog import cloudlog
    getattr(cloudlog, level)(msg)
  except Exception:
    print(f"bogpilot_models.launcher {level}: {msg}")


class _OverlayDir:
  """Stands in for modeld.MODELS_DIR while the alternate loads: warp programs the model ships come from its
  directory, everything else (including any warp it omits) from the stock models directory."""

  def __init__(self, paths: dict, stock_dir):
    self.paths, self.stock_dir = paths, stock_dir

  def __truediv__(self, name):
    m = _WARP_RE.match(str(name))
    if m and f"driving_warp_{m.group(1)}" in self.paths:
      return self.paths[f"driving_warp_{m.group(1)}"]
    return self.stock_dir / name


def install(m, res, store):
  """Replace m.ModelState with a subclass that loads res's verified model, falling back to stock."""
  from openpilot.common.bogpilot_models import resolve
  base = m.ModelState
  if getattr(base, "_bp_selector", False):
    return base
  stock_path, stock_dir = m.modeld_pkl_path, m.MODELS_DIR
  try:
    chestnut_mode = bool(m.chestnut_compiled() and (m.chestnut_present() or m.cable_connected()))
  except Exception:
    chestnut_mode = True

  class SelectedModelState(base):
    _bp_selector = True

    def __init__(self, cam_w, cam_h, chestnut):
      self._bp_alt = False
      if chestnut or chestnut_mode:
        if not chestnut:  # small fallback model of a Chestnut setup: stock, and say why
          resolve.note_failed(store, res, "alternate driving models are not supported with the Chestnut GPU", "load")
        return base.__init__(self, cam_w, cam_h, chestnut)
      try:
        m.modeld_pkl_path = lambda _chestnut, _p=res.paths["driving_model"]: _p
        m.MODELS_DIR = _OverlayDir(res.paths, stock_dir)
        try:
          base.__init__(self, cam_w, cam_h, chestnut)
        finally:
          m.modeld_pkl_path, m.MODELS_DIR = stock_path, stock_dir
        self._bp_alt = True
        self.warmup()  # one zero-frame inference: load-time failures fall back before anything is published
        resolve.note_started(store, res)
        _log("warning", f"driving model {res.entry.id} ({res.selection.pin_model[:12]}) loaded")
        return None
      except Exception as e:
        _log("error", f"selected driving model {res.entry.id} failed to load, using stock: {type(e).__name__}")
        self._bp_alt = False
        resolve.note_failed(store, res, f"load or first inference failed ({type(e).__name__})", "load")
      m.modeld_pkl_path, m.MODELS_DIR = stock_path, stock_dir
      return base.__init__(self, cam_w, cam_h, chestnut)  # exact stock

    def run(self, *args, **kwargs):
      try:
        out = base.run(self, *args, **kwargs)
        if self._bp_alt and not all(np.all(np.isfinite(v)) for v in out.values() if isinstance(v, np.ndarray)):
          raise RuntimeError("model output not finite")
        return out
      except Exception as e:
        if self._bp_alt:
          resolve.note_failed(store, res, f"inference error ({type(e).__name__})", "run")
        raise  # modeld restarts; the recorded fallback makes the next start stock

  m.ModelState = SelectedModelState
  return SelectedModelState


def run(m, store=None, demo=False):
  """Resolve the model once, install it if it is an alternate, then hand over to modeld.main()."""
  res = None
  try:
    from openpilot.common.bogpilot_models import resolve, selection
    store = selection.default_store() if store is None else store
    res = resolve.resolve_for_modeld(store)
  except Exception as e:
    _log("error", f"driving model selector unavailable, using stock: {type(e).__name__}")
  if res is not None and res.is_alternate:
    try:
      install(m, res, store)
    except Exception as e:
      _log("error", f"driving model selector could not install, using stock: {type(e).__name__}")
  elif res is not None:
    resolve.note_started(store, res)
  return m.main(demo=demo)


def main(demo=False):
  """Called by the manager with no arguments, exactly like stock modeld.main()."""
  from openpilot.selfdrive.modeld import modeld as m
  return run(m, demo=demo)


if __name__ == "__main__":
  import argparse
  parser = argparse.ArgumentParser()
  parser.add_argument("--demo", action="store_true", help="A boolean for demo mode.")
  try:
    main(demo=parser.parse_args().demo)
  except KeyboardInterrupt:
    _log("warning", "got SIGINT")
