"""t997/Bardo: Stalk Controls experimental pull/push hold default is exactly 1.23 s (UI text, engine default, fresh settings)."""
from opendbc.car.tesla_ap1 import phase3_stalk_controls as engine


def test_engine_default_is_1_23_seconds():
  assert engine.DEFAULT_HOLD_S == 1.23
  s = engine.Settings()
  assert s.pull_hold_s == 1.23
  assert s.push_hold_s == 1.23


def test_ui_text_states_default_1_23():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[1] / "bogpilot" / "phase3_stalk_controls.py").read_text()
  assert "Default 1.23 seconds" in src
