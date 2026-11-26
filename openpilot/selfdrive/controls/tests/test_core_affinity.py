"""Core layout guard.

On the c3x the UI is pinned FIFO-54 to core 5 and averaged 83% of that core on the road.
plannerd (13%) and radard (4%) were also pinned to core 5 at FIFO-52, so radarState was
published late and its 1 s average frequency fell below 16 Hz (commIssueAvgFreq). The
latency-critical control services must not share a core with the UI.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # openpilot/selfdrive


def _core(path: str):
  src = (ROOT / path).read_text()
  m = re.search(r"^\s*config_realtime_process\(([^,]+),", src, re.M)
  assert m, f"no config_realtime_process in {path}"
  return ast.literal_eval(m.group(1).strip())


def _cores(v):
  return set(v) if isinstance(v, (list, tuple)) else {v}


def test_ui_core_is_not_shared_with_planner_or_radar():
  ui = _cores(5)  # ui.py: cores = {5, }
  assert re.search(r"cores = \{5, \}", (ROOT / "ui/ui.py").read_text())
  for p in ("controls/plannerd.py", "controls/radard.py"):
    assert not (_cores(_core(p)) & ui), p


def test_planner_and_radar_not_on_controls_core():
  ctrl = _cores(_core("controls/controlsd.py"))  # core 4: controlsd/selfdrived/card
  for p in ("controls/plannerd.py", "controls/radard.py"):
    assert not (_cores(_core(p)) & ctrl), p


def test_planner_and_radar_stay_on_online_big_core_and_below_ui_priority():
  for p in ("controls/plannerd.py", "controls/radard.py"):
    assert _cores(_core(p)) <= {4, 5, 6, 7}
    assert "Priority.CTRL_LOW" in (ROOT / p).read_text()


def test_planner_and_radar_are_not_on_the_camerad_core():
  """camerad (system/camerad/main.cc set_core_affinity({6})) is SCHED_OTHER on an isolated core: any FIFO task
  pinned there preempts it. plannerd/radard (FIFO 51) go to core 7 where modeld (FIFO 54) outranks them."""
  cam = _cores(int(re.search(r"set_core_affinity\(\{(\d+)\}\)", (ROOT.parent / "system/camerad/main.cc").read_text()).group(1)))
  assert cam == {6}
  for p in ("controls/plannerd.py", "controls/radard.py"):
    assert not (_cores(_core(p)) & cam), p
    assert _cores(_core(p)) == {7}, p
  modeld = re.search(r"config_realtime_process\((\d+), (\d+)\)", (ROOT / "modeld/modeld.py").read_text())
  assert int(modeld.group(1)) == 7 and int(modeld.group(2)) > 51   # modeld outranks plannerd/radard (51) on that core
