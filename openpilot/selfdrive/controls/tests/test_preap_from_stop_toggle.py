"""Pre-AP From-Stop Speed (TeslaPreApFromStopSpeed, default OFF): registration, the menu row and AP1 isolation."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from opendbc.car.tesla_ap1.preap import params as pp
from openpilot.common.bogpilot_toggles import FILE_TOGGLES
from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv
from openpilot.system.bogpilot import settings_backup as sb
from openpilot.system.bogpilot.toggle_reset import FILE_RESET_KEYS

KEY = "TeslaPreApFromStopSpeed"
PREAP = NS(carFingerprint="TESLA_PREAP_MODELS", dashcamOnly=False, openpilotLongitudinalControl=True, alphaLongitudinalAvailable=False)
PREAP_TACC = NS(carFingerprint="TESLA_PREAP_MODELS", dashcamOnly=False, openpilotLongitudinalControl=False, alphaLongitudinalAvailable=False)
AP1 = NS(carFingerprint="TESLA_AP1_MODELS", dashcamOnly=False, openpilotLongitudinalControl=True, alphaLongitudinalAvailable=False)


@pytest.fixture
def pdir(tmp_path, monkeypatch):
  monkeypatch.setattr(pp, "_params_dir", tmp_path)
  return tmp_path


def _vs(cp, offroad=True, tmp="/tmp"):
  return pv.VehicleSettings(params=None, cp=lambda: cp, offroad=lambda: offroad, file_dir=tmp, params_file=tmp + "/x")


def test_registered_default_off_backed_up_never_reset():
  assert pp.PreApParamKeys.FROM_STOP_SPEED == KEY
  assert pp.DEFAULTS[KEY] is False
  assert FILE_TOGGLES[KEY][0] is False
  assert KEY in sb.FILE_KEYS and KEY not in FILE_RESET_KEYS


def test_reader_default_and_errors(pdir, monkeypatch):
  assert pp.preap_from_stop_speed() is False
  pp.set_bool(KEY, True)
  assert pp.preap_from_stop_speed() is True
  monkeypatch.setattr(pp, "get_bool", lambda *a, **k: (_ for _ in ()).throw(OSError()))
  assert pp.preap_from_stop_speed() is False


def test_feature_spec_and_help():
  from openpilot.selfdrive.ui.bogpilot.phase3_system_settings_feature_specs import FEATURE_SPECS
  from openpilot.selfdrive.ui.bogpilot import toggle_help
  spec = FEATURE_SPECS[KEY]
  assert spec["declared_default"] == "0" and spec["type"] == "BOOL" and spec["title"] == pv.TITLES[pv.FROM_STOP]
  assert KEY in toggle_help.HELP


def test_row_only_on_preap_pedal_long_with_auto_speed_off(pdir):
  assert _vs(PREAP).visible(pv.FROM_STOP)
  assert not _vs(PREAP_TACC).visible(pv.FROM_STOP)
  assert not _vs(AP1).visible(pv.FROM_STOP)
  assert not _vs(None).visible(pv.FROM_STOP)
  pp.set_bool(pp.PreApParamKeys.AUTO_SPEED, True)
  assert not _vs(PREAP).visible(pv.FROM_STOP)       # Auto Speed ON always uses the from-stop speed: the row would be inert


def test_row_offroad_only_and_writes_the_file(pdir):
  assert not _vs(PREAP, offroad=False).enabled(pv.FROM_STOP)
  vs = _vs(PREAP)
  assert vs.read(pv.FROM_STOP) is False
  assert vs.write(pv.FROM_STOP, True) and vs.read(pv.FROM_STOP) is True
  assert pp.get_bool(KEY) is True


def test_auto_speed_help_no_longer_says_only_the_stalk():
  assert "only the stalk" not in pv.DESCRIPTIONS[pv.AUTO_SPEED]
  assert "last set" in pv.DESCRIPTIONS[pv.AUTO_SPEED]


def test_key_is_file_backed_never_in_libparams():
  from pathlib import Path
  lib = Path(__file__).resolve().parents[3] / "common" / "libparams_c.so"
  if lib.is_file():
    assert lib.read_bytes().count(KEY.encode()) == 0   # file-backed (params_bogpilot): no libparams rebuild needed


def test_ap1_never_reads_the_policy_toggles():
  from openpilot.selfdrive.car.cruise import VCruiseHelper
  card = (Path(__file__).resolve().parents[2] / "car" / "card.py").read_text()
  assert card.count("PreapPullPolicy.read()") == 1
  i = card.index("PreapPullPolicy.read()")
  gate = card.rindex('if self.CP.brand == "tesla_ap1" and self.CP.carFingerprint == "TESLA_PREAP_MODELS" and not self.CP.pcmCruise:', 0, i)
  assert "\n    if " not in card[gate + 10:i]                    # read inside the Pre-AP pedal block only
  h = VCruiseHelper(NS(pcmCruise=False, carFingerprint="TESLA_AP1_MODELS"))
  assert h._tesla_rpt is None and h.preap_restore_kph(20.0) is None
