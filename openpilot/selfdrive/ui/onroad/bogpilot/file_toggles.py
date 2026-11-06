"""Small file-backed onroad contract; no unregistered Params lookups.

These keys belong to /data/params_bogpilot, as on the existing BogPilot UI.
Missing settings preserve shipping defaults; explicit user OFF values survive.
BlindSpotPath is a registered FrogPilot setting when the params stream is present.
"""
from pathlib import Path
import time

DEFAULTS = {"RedesignUI": True, "BSMFlameTracks": True, "SwapSpeedGraph": True,
            "BlindSpotPath": True}


def registered_value(key):
  # Only BlindSpotPath is a typed setting. Legacy redesign/flame/swap keys are
  # file-backed and must not consult a second, potentially divergent store.
  if key != "BlindSpotPath":
    return None
  from openpilot.common.params import Params
  params = Params()
  if key.encode() not in params.all_keys():
    return None
  return params.get(key)


class FileToggles:
  def __init__(self, path="/data/params_bogpilot", clock=time.monotonic, read_param=registered_value):
    self.path = Path(path)
    self.clock = clock
    self.read_param = read_param
    self._next = -1.0
    self._values = DEFAULTS.copy()

  def get(self, key):
    now = self.clock()
    if now >= self._next:
      self._next = now + 2.0
      for name, default in DEFAULTS.items():
        try:
          raw = (self.path / name).read_text().strip().lower()
        except (OSError, UnicodeError):
          raw = ""
        typed = self.read_param(name)
        if typed is not None:
          raw = str(typed).strip().lower()
        self._values[name] = raw in ("1", "true", "yes", "on") if raw else default
    return self._values[key]


toggles = FileToggles()
