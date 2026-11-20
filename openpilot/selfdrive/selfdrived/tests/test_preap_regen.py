"""Pre-AP regen-limit alert (selfdrived/preap_regen.py), alert only. t1385: one fixed 1.2 m/s^2 threshold at every speed,
0.3 s wait, shown at least 1 s, cleared by the brake, red border + repeating prompt, Pre-AP pedal long only."""
import math
import pathlib
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.selfdrived import preap_regen as pr

PREAP = SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True)


def first_alert_s(w, a, long_active=True, seconds=0.5, brake=False):
  for i in range(int(seconds * 100)):
    if w.update(long_active, a, brake):
      return i * 0.01
  return None


def test_constants():
  assert pr.ALERT_DECEL == 1.2 and pr.HOLD_S == 0.3 and pr.MIN_SHOW_S == 1.0
  assert pr.REGEN_MAX == -1.5   # pedal clip unchanged


@pytest.mark.parametrize("a", [-1.21, -1.6, -2.5, -3.5])
def test_alerts_within_0_3_s_at_and_above_threshold(a):
  t = first_alert_s(pr.PreapRegenWatch(PREAP), a)
  assert t is not None and t <= 0.31


@pytest.mark.parametrize("a", [-1.2, -1.19, -0.9, 0.0, 1.0])
def test_soft_plans_never_alert(a):
  assert first_alert_s(pr.PreapRegenWatch(PREAP), a, seconds=3.0) is None


def test_threshold_has_no_speed_term():
  import inspect
  assert "v_ego" not in inspect.signature(pr.PreapRegenWatch.update).parameters


def test_shown_at_least_1_s_after_the_demand_ends():
  w = pr.PreapRegenWatch(PREAP)
  assert first_alert_s(w, -2.0) is not None
  on = sum(w.update(True, 0.0) for _ in range(150))
  assert 95 <= on <= 101


def test_brake_and_long_inactive_clear_at_once():
  w = pr.PreapRegenWatch(PREAP)
  assert first_alert_s(w, -2.0) is not None
  assert not w.update(True, -2.0, True)
  w = pr.PreapRegenWatch(PREAP)
  assert first_alert_s(w, -2.0) is not None
  assert not w.update(False, -2.0)
  assert first_alert_s(pr.PreapRegenWatch(PREAP), -3.0, brake=True, seconds=2.0) is None


def test_short_dips_and_nan_never_alert():
  w = pr.PreapRegenWatch(PREAP)
  for _ in range(20):
    for _ in range(25):
      assert not w.update(True, -2.5)
    assert not w.update(True, 0.0)
  assert first_alert_s(pr.PreapRegenWatch(PREAP), math.nan, seconds=2.0) is None
  assert first_alert_s(pr.PreapRegenWatch(PREAP), -math.inf, seconds=2.0) is None


@pytest.mark.parametrize("cp", [SimpleNamespace(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True),
                                SimpleNamespace(carFingerprint="TESLA_AP1_MODELX", openpilotLongitudinalControl=True),
                                SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=False)])
def test_only_pre_ap_with_openpilot_long(cp):
  assert first_alert_s(pr.PreapRegenWatch(cp), -3.0, seconds=2.0) is None


def test_alert_only_wiring_red_border_and_repeat():
  root = pathlib.Path(pr.__file__).resolve().parents[2]
  ev = (root / "selfdrive/selfdrived/events.py").read_text()
  block = ev.split("EventName.preapRegenLimit: {", 1)[1].split("},", 1)[0]
  assert "ET.WARNING" in block and "DISABLE" not in block and "NO_ENTRY" not in block
  assert "AudibleAlert.promptRepeat" in block
  sd = (root / "selfdrive/selfdrived/selfdrived.py").read_text()
  assert ("self.preap_regen.update(self.sm['carControl'].longActive, self.sm['longitudinalPlan'].aTarget, CS.brakePressed)"
          in sd)
  assert "preapRegenLimit @113;" in (root / "cereal/log.capnp").read_text()
  from openpilot.selfdrive.ui.onroad.bogpilot.alert_banner_logic import is_regen_limit_alert
  assert is_regen_limit_alert("preapRegenLimit/warning")
  assert not is_regen_limit_alert("preapRadarNotReady/warning") and not is_regen_limit_alert(None)
  ui = root / "selfdrive/ui/onroad/bogpilot"
  assert "self.regen_red()" in (ui / "hud_compose.py").read_text()
  assert "is_regen_limit_alert(ui_state.sm" in (ui / "bogpilot_hud.py").read_text()
