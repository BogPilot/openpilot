"""Pre-AP regen-limit alert (selfdrived/preap_regen.py), alert only. G1: a plan asking aTarget -2.5 for 0.5 s while longActive
alerts within 0.3 s; -1.0 does not. The -1.5 floor is a commanded NAP constant, UNPROVEN as the car's real regen, so the same is
checked for a -0.9 floor."""
import math
import pathlib
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.selfdrived import preap_regen as pr

PREAP = SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=True)


def first_alert_s(w, a, long_active=True, seconds=0.5):
  for i in range(int(seconds * 100)):
    if w.update(long_active, a):
      return i * 0.01
  return None


def test_floor_is_the_pedal_clip():
  assert pr.REGEN_MAX == -1.5


@pytest.mark.parametrize("floor,hard,soft", [(-1.5, -2.5, -1.0), (-0.9, -2.5, -0.6), (-0.9, -1.2, -0.6)])
def test_g1_alerts_within_0_3_s_and_not_on_a_soft_plan(floor, hard, soft):
  t = first_alert_s(pr.PreapRegenWatch(PREAP, floor), hard)
  assert t is not None and t <= 0.31
  assert first_alert_s(pr.PreapRegenWatch(PREAP, floor), soft) is None


def test_default_floor_threshold_edges():
  w = pr.PreapRegenWatch(PREAP)
  assert first_alert_s(w, -1.29, seconds=2.0) is None          # above floor + margin
  assert first_alert_s(pr.PreapRegenWatch(PREAP), -1.31) is not None


def test_minus_0_9_floor_alerts_where_minus_1_5_does_not():
  assert first_alert_s(pr.PreapRegenWatch(PREAP, -0.9), -1.0) is not None
  assert first_alert_s(pr.PreapRegenWatch(PREAP, -1.5), -1.0) is None


def test_short_dips_and_inactive_long_never_alert():
  w = pr.PreapRegenWatch(PREAP)
  for _ in range(20):
    for _ in range(25):
      assert not w.update(True, -2.5)
    assert not w.update(True, 0.0)
  assert first_alert_s(pr.PreapRegenWatch(PREAP), -3.0, long_active=False, seconds=2.0) is None
  assert first_alert_s(pr.PreapRegenWatch(PREAP), math.nan, seconds=2.0) is None


@pytest.mark.parametrize("cp", [SimpleNamespace(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True),
                                SimpleNamespace(carFingerprint="TESLA_PREAP_MODELS", openpilotLongitudinalControl=False)])
def test_only_pre_ap_with_openpilot_long(cp):
  assert first_alert_s(pr.PreapRegenWatch(cp), -3.0, seconds=2.0) is None


def test_alert_only_wiring():
  root = pathlib.Path(pr.__file__).resolve().parents[2]
  ev = (root / "selfdrive/selfdrived/events.py").read_text()
  block = ev.split("EventName.preapRegenLimit: {", 1)[1].split("},", 1)[0]
  assert "ET.WARNING" in block and "DISABLE" not in block and "NO_ENTRY" not in block
  sd = (root / "selfdrive/selfdrived/selfdrived.py").read_text()
  assert "self.preap_regen.update(self.sm['carControl'].longActive, self.sm['longitudinalPlan'].aTarget)" in sd
  assert "preapRegenLimit @113;" in (root / "cereal/log.capnp").read_text()
