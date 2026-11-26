"""The engage-set helpers are warmed at card start, so the first engage frame imports nothing new."""
import sys
from pathlib import Path

from opendbc.car import structs
from openpilot.selfdrive.controls.lib.phase3_speed_control import EngageLimitOffset, EngageTapFromZero, warm_engage_helpers

CARD = Path(__file__).resolve().parents[2] / "car" / "card.py"


def _cp():
  CP = structs.CarParams()
  CP.brand = "tesla_ap1"
  CP.carFingerprint = "TESLA_AP1_MODELS"
  return CP


def test_first_engage_call_imports_nothing_after_warmup():
  offset, tap = EngageLimitOffset(_cp()), EngageTapFromZero()
  warm_engage_helpers(offset, tap)
  before = set(sys.modules)
  offset._toggles_t = -1e9  # cache expired, as on an engage long after boot
  offset(24.6)
  tap._t = -1e9
  tap()
  assert set(sys.modules) - before == set()


def test_warmup_is_failure_tolerant():
  class Boom:
    def _toggles(self):
      raise OSError("param read failed")

  def boom():
    raise RuntimeError("tap read failed")

  warm_engage_helpers(Boom(), boom)
  warm_engage_helpers(None, None)


def test_card_warms_helpers_right_after_creating_them():
  src = CARD.read_text()
  i = src.index("self.CI.CS.op_long_tap_from_zero = EngageTapFromZero()")
  assert "warm_engage_helpers(self.CI.CS.op_long_offset, self.CI.CS.op_long_tap_from_zero)" in src[i:i + 300]
