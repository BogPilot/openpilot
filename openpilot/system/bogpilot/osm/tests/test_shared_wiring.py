"""Shared-file wiring contract (process_config / selfdrived). Nothing starts by default; a crash is never user-visible."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]


def test_process_registered_with_gate_not_always_run():
  pc = (ROOT / "openpilot/system/manager/process_config.py").read_text()
  m = re.search(r'PythonProcess\("bogpilot_mapd",\s*"openpilot\.system\.bogpilot\.osm\.supervisor",\s*(\w+)', pc)
  assert m, "bogpilot_mapd not registered"
  assert m.group(1) == "bogpilot_mapd_wanted"          # never always_run / only_onroad
  assert "from openpilot.system.bogpilot.osm.supervisor import manager_condition as bogpilot_mapd_wanted" in pc


def test_mapd_failure_never_raises_process_not_running():
  src = (ROOT / "openpilot/selfdrive/selfdrived/selfdrived.py").read_text()
  m = re.search(r"NON_ESSENTIAL_PROCESSES = frozenset\(\{([^}]*)\}\)", src)
  assert m and "bogpilot_mapd" in m.group(1) and "bogpilot_trackd" in m.group(1)


def test_fresh_install_does_not_start_mapd_without_a_region(tmp_path):
  from types import SimpleNamespace
  from openpilot.system.bogpilot.osm.supervisor import manager_condition
  # SLC is default ON (0.9.7) but nothing starts, downloads or touches the network until the user selects a region
  params = SimpleNamespace(get=lambda k: None, get_bool=lambda k: True)
  assert manager_condition(True, params, None) is False
  assert manager_condition(False, params, None) is False


def test_default_on_runs_with_a_saved_region_and_slc_on(tmp_path):
  from types import SimpleNamespace
  from openpilot.system.bogpilot.osm import supervisor as S
  assert S.ACTIVATION_POLICY == "default_on"
  sel = b'{"states":["WY"]}'

  def fake(slc):
    vals = {"MapsSelected": sel, "SpeedLimitController": slc}
    return SimpleNamespace(get=lambda k: vals.get(k), all_keys=lambda: list(vals))
  on, off = fake(b"1"), fake(b"0")
  assert S.manager_condition(True, on, None) is True     # supervisor installs/verifies the pinned binary itself
  assert S.manager_condition(True, off, None) is False   # user switched the Speed Limit Controller off


def test_adoption_policy_still_requires_marker_and_binary(tmp_path, monkeypatch):
  from types import SimpleNamespace
  from openpilot.system.bogpilot.osm import supervisor as S
  monkeypatch.setattr(S, "ACTIVATION_POLICY", "adoption")
  params = SimpleNamespace(get=lambda k: b'{"states":["WY"]}', get_bool=lambda k: True)
  assert S.manager_condition(True, params, None) is False


def test_only_the_slc_consumer_imports_osm_and_lazily():
  # planner/ui/car must not import the osm package; phase3_speed_control does it inside _wire_map_sources (try/except)
  hits = []
  for sub in ("openpilot/selfdrive/controls", "openpilot/selfdrive/ui", "openpilot/selfdrive/car"):
    for p in (ROOT / sub).rglob("*.py"):
      if "/tests/" in str(p):
        continue
      if "bogpilot.osm" in p.read_text(errors="ignore"):
        hits.append(str(p.relative_to(ROOT)))
  assert hits == ["openpilot/selfdrive/controls/lib/phase3_speed_control.py"]
  src = (ROOT / "openpilot/selfdrive/controls/lib/phase3_speed_control.py").read_text()
  head = src.split("def _wire_map_sources")[0]
  assert not re.search(r"^\s*(from|import)\s+\S*bogpilot\.osm", head, re.M)   # no module-level import: a broken osm package cannot break the planner
