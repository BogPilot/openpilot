"""Structure: hardwared's deviceState loop takes the temperatures and whether they are a real reading from ONE snapshot
(bg_reads.BackgroundReads.snapshot), never from separate get / has_value calls that can straddle a reader update.
Reads the source only (no messaging import), so it runs anywhere."""
import ast
import pathlib

HARDWARED = pathlib.Path(__file__).resolve().parents[1] / "hardwared.py"


def thermal_calls_in_loop(src: str) -> list[tuple[str, str]]:
  tree = ast.parse(src)
  fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "hardware_thread")
  calls = []
  # the deviceState loop: the longest while loop (the startup first-read wait before it may use has_value)
  loop = max((n for n in ast.walk(fn) if isinstance(n, ast.While)), key=lambda n: n.end_lineno - n.lineno)
  for n in ast.walk(loop):
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "thermal_reads"):
      key = n.args[0].value if n.args and isinstance(n.args[0], ast.Constant) else None
      calls.append((n.func.attr, key))
  return calls


def check(src: str) -> None:
  calls = thermal_calls_in_loop(src)
  snaps = [c for c in calls if c == ("snapshot", "temps")]
  assert len(snaps) == 1, f"the loop must take the temperatures from exactly one snapshot: {calls}"
  assert not [c for c in calls if c[0] in ("get", "has_value")], f"separate (non-atomic) temperature reads in the loop: {calls}"
  assert set(c[0] for c in calls) <= {"snapshot", "age_s"}, calls


def test_hardwared_loop_reads_temperatures_from_one_snapshot():
  check(HARDWARED.read_text())


def test_check_catches_the_separate_read_mutation():
  src = HARDWARED.read_text()
  line = '    temps, have_temps = thermal_reads.snapshot("temps", {})\n'
  assert src.count(line) == 1
  mutated = src.replace(line, '    temps = thermal_reads.get("temps", {})\n    have_temps = thermal_reads.has_value("temps")\n')
  try:
    check(mutated)
  except AssertionError:
    return
  raise AssertionError("the separate get / has_value mutation was not caught")
