"""rc_settings_gate tests. The real-tree test reads this checkout's sources (static, no imports);
mutation tests run on a synthetic temp copy and must each FAIL closed."""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "bogpilot"))
import rc_settings_gate as gate  # noqa: E402


def _copy(tmp_path):
  for rel in gate.FILES.values():
    src, dst = ROOT / rel, tmp_path / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
      shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
      shutil.copy2(src, dst)
  return tmp_path


def _edit(root, key, old, new, count=1):
  p = root / gate.FILES[key]
  s = p.read_text()
  assert old in s, old
  p.write_text(s.replace(old, new, count))


def _failed(rep):
  return {r["check"] for r in rep.results if r["status"] == "FAIL"}


def test_real_tree_passes():
  rep = gate.run(ROOT)
  assert rep.ok, [r for r in rep.results if r["status"] != "PASS"]
  assert len(rep.results) >= 20


def test_synthetic_copy_passes(tmp_path):
  assert gate.run(_copy(tmp_path)).ok


@pytest.mark.parametrize("key,old,new,check", [
  ("header", '{"AlwaysOnLateral", {PERSISTENT, BOOL, "0"}}', '{"AlwaysOnLateral", {PERSISTENT, BOOL, "1"}}', "header.matches_registry"),
  ("header", '{"TuningLevel", {PERSISTENT, INT, "0"}}', '{"TuningLevel", {PERSISTENT, WIDGET, "0"}}', "header.known_schema"),
  ("params_py", '"NudgelessLaneChange": ("PERSISTENT", "BOOL", "0"', '"NudgelessLaneChange": ("PERSISTENT", "BOOL", "1"', "defaults.approved_policy"),
  ("shipping", "'AlwaysOnLateral': ('0', 0)", "'AlwaysOnLateral': ('1', 0)", "defaults.approved_policy"),
  ("shipping", "'OffroadScreensaver': False", "'OffroadScreensaver': True", "screensaver.default_off"),
  ("toggles", '"OffroadScreensaver": (False,', '"OffroadScreensaver": (True,', "screensaver.default_off"),
  ("toggles", '"RedesignUI", "BSMFlameTracks"', '"BSMFlameTracks"', "fileonly.required_set"),
  ("ap1_profile", 'AP1_PARAM_PROFILE: dict[str, str] = {', 'AP1_PARAM_PROFILE: dict[str, str] = {\n  "TuningLevel": "1",', "defaults.ap1_profile_respects_policy"),
  ("ap1_profile", '"AlwaysOnLateral": "0",', '"AlwaysOnLateral": "1",', "defaults.ap1_profile_respects_policy"),
  ("reset", 'UNSET_KEYS = frozenset({"TuningLevel", "TuningLevelConfirmed"})', 'UNSET_KEYS = frozenset({"TuningLevel"})', "defaults.tuning_unset_on_reset"),
  ("manager", "params.get(k) is None", "True", "manager.defaults_fill_unset_only"),
])
def test_mutations_fail(tmp_path, key, old, new, check):
  root = _copy(tmp_path)
  _edit(root, key, old, new)
  rep = gate.run(root)
  assert not rep.ok and check in _failed(rep)


def test_file_only_key_registered_as_typed_param_fails(tmp_path):
  root = _copy(tmp_path)
  p = root / gate.FILES["header"]
  p.write_text(p.read_text() + '    {"RedesignUI", {PERSISTENT, BOOL, "1"}},\n')
  assert {"fileonly.not_typed_params", "header.matches_registry"} <= _failed(gate.run(root))


def test_screensaver_settings_row_fails(tmp_path):
  root = _copy(tmp_path)
  p = root / gate.FILES["metadata"]
  p.write_text(p.read_text() + '\n# ToggleDefinition(param="OffroadScreensaver")\n')
  assert "screensaver.no_settings_row" in _failed(gate.run(root))


def test_unregistered_ui_param_is_blocker(tmp_path):
  root = _copy(tmp_path)
  p = root / gate.FILES["metadata"]
  p.write_text(p.read_text() + '\n_X = [\n  ToggleDefinition(\n    title=("Synthetic"),\n    param="SyntheticUnregisteredKey",\n    tuning_level=0,\n  ),\n]\n')
  rep = gate.run(root)
  assert "ui.metadata_params_registered" in _failed(rep)


def test_known_unregistered_fails_once_metadata_is_rendered(tmp_path):
  root = _copy(tmp_path)
  ui = root / "openpilot" / "selfdrive" / "ui" / "synthetic_panel.py"
  ui.parent.mkdir(parents=True, exist_ok=True)
  ui.write_text("from openpilot.selfdrive.ui.bogpilot import toggle_metadata\n")
  assert "ui.metadata_unrendered" in _failed(gate.run(root))


def test_controls_reading_csc_widget_fails(tmp_path):
  root = _copy(tmp_path)
  (root / gate.FILES["controls_dir"] / "synthetic_reader.py").write_text('KEY = "ShowCSCStatus"\n')
  assert "csc.status_display_only" in _failed(gate.run(root))


def test_missing_file_fails_closed(tmp_path):
  root = _copy(tmp_path)
  (root / gate.FILES["header"]).unlink()
  rep = gate.run(root)
  assert not rep.ok and "inputs" in _failed(rep)


def test_empty_tree_fails_closed(tmp_path):
  assert not gate.run(tmp_path).ok


def test_cli_exit_codes(tmp_path, capsys):
  assert gate.main(["--root", str(ROOT)]) == 0
  assert gate.main(["--root", str(tmp_path)]) == 1
  assert "GATE FAIL" in capsys.readouterr().out
