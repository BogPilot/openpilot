"""BogPilot save cadence helper: stock 10 to 60 s cadence, dirty only, stable stagger, no IO."""
import pytest

from openpilot.common import bogpilot_checkpoint as cp


class Clock:
  def __init__(self, t=1000.0):
    self.t = t

  def __call__(self):
    return self.t


def test_intervals_match_stock_analogs():
  assert cp.LEARNED_INTERVAL_S == 60.0       # paramsd / lagd
  assert cp.COUNTER_INTERVAL_S == 60.0       # hardwared UptimeOnroad
  assert cp.RATE_LIMITED_INTERVAL_S == 10.0  # CarBatteryCapacity
  assert cp.MIN_INTERVAL_S == 10.0


@pytest.mark.parametrize("bad", [0.0, 1.0, 9.99, float("nan"), float("-inf")])
def test_faster_than_stock_is_refused(bad):
  with pytest.raises(ValueError):
    cp.Checkpoint("x", bad)


def test_nothing_is_due_until_marked():
  c = Clock()
  k = cp.Checkpoint("CurvatureData", 60.0, clock=c)
  c.t += 10_000
  assert not k.due()
  k.mark()
  assert k.due()


def test_at_most_once_per_interval_and_latest_wins():
  c = Clock()
  k = cp.Checkpoint("a", 60.0, clock=c)
  saves = 0
  for _ in range(36_000):     # one hour at 10 Hz, dirty every tick
    c.t += 0.1
    k.mark()
    if k.due():
      k.saved()
      saves += 1
  assert 59 <= saves <= 61
  assert k.saves == saves


def test_first_save_waits_between_half_and_one_interval():
  for name in ("CurvatureData", "TeslaTrimDetected", "BogPilotStats", "PreviousSpeedLimit"):
    c = Clock()
    k = cp.Checkpoint(name, 60.0, clock=c)
    k.mark()
    first = None
    for i in range(1, 700):
      c.t += 0.1
      if k.due():
        first = i * 0.1
        break
    assert first is not None and 30.0 - 0.11 <= first <= 60.0 + 0.11


def test_phases_differ_between_names_and_are_stable():
  names = ["CurvatureData", "TeslaTrimDetected", "BogPilotStats", "PreviousSpeedLimit"]
  fr = [cp.phase_fraction(n) for n in names]
  assert len(set(fr)) == len(fr)
  assert fr == [cp.phase_fraction(n) for n in names]


def test_first_at_once_saves_the_first_change_then_waits():
  c = Clock()
  k = cp.Checkpoint("PreviousSpeedLimit", 10.0, clock=c, first_at_once=True)
  k.mark()
  assert k.due()
  k.saved()
  k.mark()
  c.t += 9.9
  assert not k.due()
  c.t += 0.2
  assert k.due()


def test_no_io(monkeypatch):
  import builtins
  def boom(*a, **k):
    raise AssertionError("Checkpoint must not open files")
  monkeypatch.setattr(builtins, "open", boom)
  k = cp.Checkpoint("a", 10.0, clock=Clock())
  k.mark()
  k.due()
  k.saved()
