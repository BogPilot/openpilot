"""Docs match the code for the AP1 Model S and Model X longitudinal defaults.

The code is the source of truth: the DisableOpenpilotLongitudinal default in both params tables, and what the car
interface does for each car with the setting off and on. The docs (DIVERGENCES section and the release note) must
state exactly that, so a code change without a doc change (or the other way) fails here."""
import re
from pathlib import Path

import pytest

from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.tests.test_release_interface import fingerprint as s_fingerprint
from opendbc.car.tesla_ap1.tests.tinkla_modelx_data import TINKLA_AP1_MODELX
from opendbc.car.tesla_ap1.values import CAR

ROOT = Path(__file__).resolve().parents[5]
KEY = "DisableOpenpilotLongitudinal"
S, X = CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX
MOBILEYE = {0x399: 8, 0x2B9: 8, 0x488: 4}
DIVERGENCES = ROOT / "docs/tesla/DIVERGENCES.md"
RELEASES = ROOT / "RELEASES.md"
SECTION = "## AP1 Model X openpilot longitudinal"


@pytest.fixture(autouse=True)
def _files(tmp_path, monkeypatch):
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / "AP1XOpenpilotLong")
  monkeypatch.setattr(toggles, "_ap1_standstill_path", tmp_path / "AP1StandstillEngage")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (tmp_path / "Disable1", tmp_path / "Disable2"))
  return tmp_path


def _params(car):
  fp = s_fingerprint() if car == S else {0: dict(TINKLA_AP1_MODELX), 2: dict(MOBILEYE)}
  return CarInterface.get_params(car, fp, [], False, False, False)


def _code_default_off():
  """The DisableOpenpilotLongitudinal default in both params tables (Python and the generated C++ header)."""
  py = (ROOT / "openpilot/common/bogpilot_params.py").read_text()
  h = (ROOT / "openpilot/common/params_keys_bogpilot.h").read_text()
  m_py = re.search(r'"%s":\s*\("PERSISTENT",\s*"BOOL",\s*"([01])"' % KEY, py)
  m_h = re.search(r'\{"%s",\s*\{PERSISTENT,\s*BOOL,\s*"([01])"\}\}' % KEY, h)
  assert m_py and m_h, "DisableOpenpilotLongitudinal missing from a params table"
  assert m_py.group(1) == m_h.group(1), "params tables disagree on the default"
  return m_py.group(1) == "0"


def _section():
  text = DIVERGENCES.read_text()
  start = text.index(SECTION)
  end = text.find("\n## ", start + 1)
  return " ".join(text[start:end if end != -1 else None].split())


def _release_line():
  lines = [l for l in RELEASES.read_text().splitlines() if "share the same defaults" in l and "Model X" in l]
  assert len(lines) == 1, "release note line about the shared AP1 Model S and Model X defaults"
  return lines[0]


def test_code_default_is_off_on_both_tables():
  assert _code_default_off()


def test_both_cars_same_long_default_in_code(_files):
  s, x = _params(S), _params(X)
  assert s.openpilotLongitudinalControl is True and x.openpilotLongitudinalControl is True
  for where in ("Disable1", "Disable2"):
    (_files / where).write_text("1")
    s, x = _params(S), _params(X)
    assert s.openpilotLongitudinalControl is False and x.openpilotLongitudinalControl is False
    assert s.safetyConfigs[0].safetyParam == x.safetyConfigs[0].safetyParam == 8
    (_files / where).unlink()


def test_divergences_states_the_code_defaults(_files):
  sec = _section()
  default_off = _code_default_off()
  long_default = _params(S).openpilotLongitudinalControl and _params(X).openpilotLongitudinalControl
  assert default_off and long_default
  assert SECTION + " (default on, one Disable row)" in sec
  assert f"(`{KEY}`), the same single row and the same default as the Model S" in sec
  assert "Off (default) is openpilot longitudinal" in sec
  (_files / "Disable1").write_text("1")
  param = _params(S).safetyConfigs[0].safetyParam
  assert param == _params(X).safetyConfigs[0].safetyParam
  assert f"AP1 safety param {param} on both the Model S and the Model X" in sec


def test_release_note_states_the_code_defaults():
  line = _release_line()
  assert _code_default_off()
  assert "Disable openpilot Longitudinal Control setting, off by default" in line
  assert "openpilot Longitudinal with engage from a stop is on for both" in line
