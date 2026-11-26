"""The strict stale-thermal rule (bg_reads.py THERMAL_STALE_S, > 10 s) can only see the temperature reader.

A missing or late radar, or any non-thermal reader (free space, memory, cpu, gpu, power, brightness), can never become an
overheat: selfdrived's overheat event comes only from deviceState.thermalStatus (selfdrived.py), deviceState is published only by
hardwared on the device (hardwared.py PubMaster), and in hardwared the staleness that feeds fail_hot_thermal_status is
ThermalStaleness fed by thermal_reads.age_s("temps") alone, where thermal_reads runs read_thermal_zones only. Neither file reads
any radar message. Source checks need no messaging import, so they run anywhere."""
import ast
import pathlib
import re

from openpilot.system.hardware.bg_reads import (ReadStaleness, THERMAL_STALE_S, ThermalStaleness, fail_hot_thermal_status)

ROOT = pathlib.Path(__file__).resolve().parents[4]
HW = ROOT / "openpilot/system/hardware"
OK, OVERHEATED = 1, 3


def code(path):
  return "\n".join(line.split("#", 1)[0] for line in path.read_text().splitlines())


def calls(tree, obj, attr):
  return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
          and isinstance(n.func.value, ast.Name) and n.func.value.id == obj and n.func.attr == attr]


def test_thermal_staleness_is_fed_by_the_temperature_reader_only():
  tree = ast.parse((HW / "hardwared.py").read_text())
  ups = calls(tree, "thermal_age", "update")
  assert len(ups) == 1
  arg = ups[0].args[0]
  assert (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.value.id == "thermal_reads"
          and arg.func.attr == "age_s" and arg.args[0].value == "temps")
  # thermal_reads is the BackgroundReads named "thermal" with the one read "temps" -> read_thermal_zones
  ctor = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "thermal_reads")
  reads = ctor.value.args[1]
  assert [k.value for k in reads.keys] == ["temps"] and "read_thermal_zones" in ast.unparse(reads.values[0])
  # the stale inputs of fail_hot_thermal_status are thermal_age's
  fh = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "fail_hot_thermal_status"]
  assert len(fh) == 1 and ast.unparse(fh[0].args[1]) == "thermal_age.stale" and ast.unparse(fh[0].args[2]) == "thermal_age.stale_s"
  # the device reader's staleness goes to its log and the new-entry gate only, never to thermal_status
  for name in ("dev_age", "entry_gate", "dev_ages"):
    for n in ast.walk(tree):
      if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "thermal_status" for t in n.targets):
        assert name not in ast.unparse(n.value)


def test_no_radar_input_in_the_thermal_path():
  for f in ("hardwared.py", "bg_reads.py"):
    src = code(HW / f).lower()
    for word in ("radar", "livetracks", "radarstate", "radartracks", "can_sock", "'can'"):
      assert word not in src, (f, word)


def test_device_state_published_by_hardwared_only():
  pubs = []
  for p in (ROOT / "openpilot").rglob("*.py"):
    if "/tests/" in str(p) or "/test/" in str(p) or "/tools/" in str(p) or "/ui/tests/" in str(p):
      continue
    if any("deviceState" in m for m in re.findall(r"PubMaster\(([^)]*)\)", code(p))):
      pubs.append(p.relative_to(ROOT).as_posix())
  assert pubs == ["openpilot/system/hardware/hardwared.py"], pubs


def test_overheat_event_from_thermal_status_only():
  sd = code(ROOT / "openpilot/selfdrive/selfdrived/selfdrived.py")
  lines = [line for line in sd.splitlines() if "EventName.overheat" in line]
  assert len(lines) == 1
  i = sd.index(lines[0])
  assert "self.sm['deviceState'].thermalStatus >= ThermalStatus.overheated" in sd[i - 200:i]


class Clock:
  def __init__(self):
    self.t = 100.0

  def __call__(self):
    return self.t


def test_stale_non_thermal_reads_never_make_thermal_status_overheated():
  clk = Clock()
  thermal = ThermalStaleness(clock=clk)
  device = ReadStaleness("device", clock=clk)
  for _ in range(600):                       # 60 s: temps fresh every 0.1 s, every device read hung from the start
    clk.t += 0.1
    device.update({"free_space": None, "memory": None, "cpu": None, "gpu": None, "power_draw": None})
    stale = thermal.update(0.05)
    st = fail_hot_thermal_status(OK, stale, thermal.stale_s, 40.0, 88.0, OK, OVERHEATED, strict=True)
    assert not stale and st == OK
  assert device.stale == {"free_space", "memory", "cpu", "gpu", "power_draw"}


def test_strict_needs_the_temperatures_themselves_stale():
  clk = Clock()
  thermal = ThermalStaleness(clock=clk)
  assert not thermal.update(THERMAL_STALE_S - 0.01)
  assert thermal.update(THERMAL_STALE_S + 0.01)
  assert fail_hot_thermal_status(OK, True, 0.0, 40.0, 88.0, OK, OVERHEATED, strict=True) == OVERHEATED
