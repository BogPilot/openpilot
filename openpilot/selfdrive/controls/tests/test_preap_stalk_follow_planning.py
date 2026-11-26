"""Pre-AP follow-distance dial reaches the planner (AP1 stalk retrofit auto-detect)."""
from types import SimpleNamespace

from openpilot.selfdrive.controls.lib.ap1_planning import Ap1Planning


def test_planner_uses_the_pre_ap_dial_only_with_pedal_long():
  for fp, long, expect in (("TESLA_PREAP_MODELS", True, 1.45), ("TESLA_PREAP_MODELS", False, None), ("TESLA_AP1_MODELS", True, 1.45)):
    plan = Ap1Planning(SimpleNamespace(carFingerprint=fp, openpilotLongitudinalControl=long), 0.05)
    assert plan.t_follow(SimpleNamespace(bogpilot=SimpleNamespace(ap1StalkFollowS=1.45)), True) == expect, (fp, long)
    assert plan.t_follow(SimpleNamespace(bogpilot=SimpleNamespace(ap1StalkFollowS=0.0)), True) is None
    assert plan.t_follow(SimpleNamespace(bogpilot=SimpleNamespace(ap1StalkFollowS=1.45)), False) is None
