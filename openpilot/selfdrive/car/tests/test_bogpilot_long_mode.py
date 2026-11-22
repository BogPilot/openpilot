"""The longitudinal mode the car started in is logged once per drive (cloudlog event bogpilot_long_mode)."""
from types import SimpleNamespace

from opendbc.car.tesla_ap1 import toggles
from openpilot.selfdrive.car import bogpilot_long_mode as LM


def cp(fp, long, brand="tesla_ap1", param=8):
  return SimpleNamespace(brand=brand, carFingerprint=fp, openpilotLongitudinalControl=long, dashcamOnly=False,
                         safetyConfigs=[SimpleNamespace(safetyParam=param)])


def test_x_long_on_and_off(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  events = []
  f = LM.log_long_mode(cp("TESLA_AP1_MODELX", True, param=9), event=lambda name, **kw: events.append((name, kw)))
  assert events == [("bogpilot_long_mode", f)]
  assert f["mode"] == "openpilot" and f["xLong"] == "on" and f["xLongSetting"] is True and f["safetyParam"] == 9
  (tmp_path / "AP1XOpenpilotLong").write_text("0")
  f = LM.long_mode_fields(cp("TESLA_AP1_MODELX", False))
  assert f["mode"] == "stock" and f["xLong"] == "off" and f["xLongSetting"] is False


def test_s_and_preap_logged_without_x_fields():
  for fp in ("TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"):
    f = LM.long_mode_fields(cp(fp, True))
    assert f["mode"] == "openpilot" and "xLong" not in f


def test_other_brands_and_errors_log_nothing():
  events = []
  assert LM.log_long_mode(cp("TOYOTA_RAV4", True, brand="toyota"), event=lambda *a, **k: events.append(a)) is None
  assert events == []
  assert LM.long_mode_fields(None) is None
  assert LM.log_long_mode(cp("TESLA_AP1_MODELS", False), event=lambda *a, **k: 1 / 0) is None


def test_card_logs_it_once_at_init():
  from pathlib import Path
  src = (Path(LM.__file__).parent / "card.py").read_text()   # read, not imported (no msgq needed)
  assert src.count("log_long_mode(self.CP)") == 1
  init_at, call_at = src.index("  def __init__(self, CI=None, RI=None)"), src.index("log_long_mode(self.CP)")
  assert init_at < call_at < src.index("    self.trim_persist = ") + 400                 # in __init__, next to trim_persist
