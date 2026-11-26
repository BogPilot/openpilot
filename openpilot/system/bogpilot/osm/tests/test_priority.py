"""mapd CPU / IO priority (priority.py): every thread, best effort, never raises."""
from openpilot.system.bogpilot.osm import priority as PR


def test_apply_sets_every_thread():
  niced, io = [], []
  n = PR.apply(42, PR.DOWNLOAD_NICE, set_nice_fn=lambda t, v: niced.append((t, v)) or True,
               set_io_fn=lambda t, c, l: io.append((t, c, l)), threads_fn=lambda pid: [42, 43, 44])
  assert n == 3 and niced == [(42, 19), (43, 19), (44, 19)]
  assert io == [(t, PR.IOPRIO_CLASS_BE, PR.IO_LEVEL_LOWEST) for t in (42, 43, 44)]


def test_levels_never_compete_with_openpilot():
  assert PR.BASE_NICE >= 10 and PR.DOWNLOAD_NICE == 19
  assert PR.IOPRIO_CLASS_BE == 2 and PR.IO_LEVEL_LOWEST == 7      # best effort lowest, not idle (loggerd would starve it)
  assert PR.ioprio_value(2, 7) == (2 << 13) | 7


def test_failures_are_quiet():
  assert PR.set_nice(-12345, 19) is False
  assert PR.threads(-12345) == [-12345]
  assert isinstance(PR.set_ioprio(-12345), bool)
