"""Cached on/off gate for the Developer overlays (display only; reads a key through the store, never writes).

The three overlays that share it (FPS counter, Developer Sidebar, sidebar IP address) are off unless the owner turned them on
and the Tuning Level allows the row. A read failure means off.
"""
from __future__ import annotations

import time


class OverlayGate:
  """`stored_only`: count the key only when it was explicitly stored. Used for FPSCounter, which registers OFF; devices still
  running a key table compiled with the old ON default must not light the overlay while the key is unset."""

  def __init__(self, key: str, *, stored_only: bool = False, store=None, clock=time.monotonic, ttl: float = 2.0):
    self.key, self.stored_only = key, stored_only
    self._store, self.clock, self.ttl = store, clock, ttl
    self._next = -1.0
    self._value = False

  def get(self) -> bool:
    now = self.clock()
    if now >= self._next:
      self._next = now + self.ttl
      try:
        self._value = bool(read_overlay(self._get_store(), self.key, self.stored_only))
      except Exception:
        self._value = False
    return self._value

  def _get_store(self):
    if self._store is None:
      from openpilot.common.bogpilot_store import ParamStore
      self._store = ParamStore()
    return self._store


def read_overlay(store, key: str, stored_only: bool = False) -> bool:
  """Effective state of an overlay key: the Tuning Level rule, and the stored value when `stored_only`."""
  if not store.honoured(key):
    return False
  if stored_only:
    from openpilot.common.bogpilot_store import parse_bool
    return parse_bool(store.raw(key), False)
  return bool(store.get_bool(key))
