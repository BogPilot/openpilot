"""Stalk Controls experimental pull/push hold default is exactly 1.23 s (UI text, engine default, fresh settings)."""
from opendbc.car.tesla_ap1 import phase3_stalk_controls as engine


def test_engine_default_is_1_23_seconds():
  assert engine.DEFAULT_HOLD_S == 1.23
  s = engine.Settings()
  assert s.pull_hold_s == 1.23
  assert s.push_hold_s == 1.23


def test_ui_uses_engine_default_for_the_hint():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[1] / "bogpilot" / "phase3_stalk_controls.py").read_text()
  # The 1.23 s figure lives on DEFAULT_HOLD_S; the row shows it as the shared "default: X" hint.
  assert "DEFAULT_HOLD_S" in src
  assert "default_text" in src
  assert "Default 1.23 seconds" not in src
