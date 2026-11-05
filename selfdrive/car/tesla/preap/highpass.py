"""Band-pass helper used by NAP-style VirtualDAS grade estimation.

Credit: NAP-style.
"""
from openpilot.common.filter_simple import FirstOrderFilter


class HighPassFilter:
  # technically a band-pass filter
  def __init__(self, x0, rc1, rc2, dt, initialized=True):
    self.x = x0
    self._f1 = FirstOrderFilter(x0, rc1, dt, initialized)
    self._f2 = FirstOrderFilter(x0, rc2, dt, initialized)
    assert rc2 > rc1, "rc2 must be greater than rc1"

  def update(self, x):
    self.x = self._f1.update(x) - self._f2.update(x)
    return self.x
