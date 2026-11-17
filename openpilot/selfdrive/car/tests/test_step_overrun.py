"""card step overrun counter (selfdrive/car/step_overrun.py)."""
from openpilot.selfdrive.car.step_overrun import StepOverrunCounter


def test_counts_only_steps_over_10_ms_and_keeps_the_worst():
  logs = []
  c = StepOverrunCounter(logs.append)
  for i, dt in enumerate((0.002, 0.0099, 0.010, 0.0101, 0.120, 0.004)):
    c.record(dt, 100.0 + i * 0.01)
  assert c.overruns == 2 and abs(c.worst_s - 0.120) < 1e-9


def test_logs_are_rate_limited_and_carry_the_window_count():
  logs = []
  c = StepOverrunCounter(logs.append)
  t = 0.0
  for _ in range(2000):                   # 20 s, an overrun every 10th step
    c.record(0.02, t)
    t += 0.01
    for _ in range(9):
      c.record(0.003, t)
      t += 0.01
  assert c.overruns == 2000
  assert 2 <= len(logs) <= 21
  assert logs[0].startswith("card: 1 step overrun(s) > 10 ms, worst 20 ms (1 total)")


def test_no_overrun_no_log():
  logs = []
  c = StepOverrunCounter(logs.append)
  for i in range(1000):
    c.record(0.004, i * 0.01)
  assert c.overruns == 0 and logs == []
