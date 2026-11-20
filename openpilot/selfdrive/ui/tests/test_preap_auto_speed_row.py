"""Vehicle screen: Pre AP Auto Speed row is Pre-AP + pedal longitudinal only, offroad only, and writes the file key."""
from types import SimpleNamespace as NS

from openpilot.selfdrive.ui.bogpilot import phase2_vehicle as pv

PREAP = NS(carFingerprint="TESLA_PREAP_MODELS", dashcamOnly=False, openpilotLongitudinalControl=True, alphaLongitudinalAvailable=False)
PREAP_TACC = NS(carFingerprint="TESLA_PREAP_MODELS", dashcamOnly=False, openpilotLongitudinalControl=False, alphaLongitudinalAvailable=False)
AP1 = NS(carFingerprint="TESLA_AP1_MODELS", dashcamOnly=False, openpilotLongitudinalControl=True, alphaLongitudinalAvailable=False)


def _vs(cp, offroad=True, tmp="/tmp"):
  return pv.VehicleSettings(params=None, cp=lambda: cp, offroad=lambda: offroad, file_dir=tmp, params_file=tmp + "/x")


def test_visible_only_on_preap_pedal_long():
  assert _vs(PREAP).visible(pv.AUTO_SPEED)
  assert not _vs(PREAP_TACC).visible(pv.AUTO_SPEED)
  assert not _vs(AP1).visible(pv.AUTO_SPEED)
  assert not _vs(None).visible(pv.AUTO_SPEED)


def test_offroad_only():
  assert not _vs(PREAP, offroad=False).enabled(pv.AUTO_SPEED)


def test_help_reminds_to_review_slc():
  assert "Speed Limit Controller settings" in pv.DESCRIPTIONS[pv.AUTO_SPEED]
