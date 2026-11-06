"""Offroad UI view of the shared BogPilot param store (openpilot/common/bogpilot_store.py).

Every process reads and writes the same Params + /data/params_bogpilot files through one ParamStore.
"""
from openpilot.common.bogpilot_store import ParamStore as _CommonParamStore, store as _common_store


class ParamStore(_CommonParamStore):
  """UI subclass; behaviour is the shared store's (file-only UI keys never touch Params)."""


def store():
  return _common_store()
