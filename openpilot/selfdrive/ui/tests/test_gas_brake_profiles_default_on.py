"""The Gas / Brake panel shows the profile group as the planner runs it (live by default on the legacy Tesla platforms)."""
from types import SimpleNamespace as NS
import pytest
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController
from openpilot.selfdrive.controls.lib.phase3_long_accel import PROFILE_ACK, ADVANCED_ACK, CEM_ACK


class Store:
  def __init__(self, **values):
    self.values, self.writes = dict(values), []
  def default(self, key):
    return BOGPILOT_PARAMS.get(key, (None, None, "0"))[2] or "0"
  def get(self, key, default=None):
    return self.values.get(key, self.default(key) if default is None else default)
  def get_bool(self, key, default=None):
    return str(self.get(key, default)).lower() in ("1", "true")
  def get_float(self, key):
    return float(self.get(key))
  def honoured(self, key, level=None):
    return True
  def toggle_bool(self, key, level=None):
    return self.get_bool(key)
  def raw(self, key):
    return self.values.get(key)
  def put(self, key, value, block=False):
    self.values[key] = value; self.writes.append(key)
  def put_bool(self, key, value, block=False):
    self.put(key, value)
  def invalidate(self):
    pass


@pytest.mark.parametrize("platform", ["TESLA_AP1_MODELS", "TESLA_AP1_MODELX", "TESLA_PREAP_MODELS"])
def test_profile_group_is_active_without_an_ack_on_legacy_tesla(platform):
  s = Store(LongitudinalTune="1")
  c = SettingsController("profiles", s, cp=NS(carFingerprint=platform, openpilotLongitudinalControl=True))
  assert c.active() and [r.key for r in c.rows()] == ["AccelerationProfile", "DecelerationProfile", "HumanAcceleration"]
  assert s.writes == []                       # showing the panel writes nothing


def test_other_cars_and_missing_car_params_keep_the_ack_rule():
  for cp in (None, NS(carFingerprint="TOYOTA_COROLLA_TSS2", openpilotLongitudinalControl=True), NS(openpilotLongitudinalControl=True)):
    s = Store(LongitudinalTune="1")
    c = SettingsController("profiles", s, cp=cp)
    assert not c.active() and c.rows() == []
    s.values[PROFILE_ACK] = "1"
    assert c.active()


def test_live_cp_without_car_params_does_not_break_the_panel():
  class Live:
    openpilotLongitudinalControl = False
    def __getattr__(self, name):
      raise AttributeError(name)
  assert not SettingsController("profiles", Store(LongitudinalTune="1"), cp=Live()).active()


def test_tune_off_hides_the_group_and_advanced_and_cem_still_need_their_ack():
  cp = NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True)
  assert not SettingsController("profiles", Store(LongitudinalTune="0"), cp=cp).active()
  assert not SettingsController("advanced", Store(AdvancedLongitudinalTune="1"), cp=cp).active()
  assert not SettingsController("conditional", Store(ConditionalExperimental="1"), cp=cp).active()
  assert SettingsController("advanced", Store(AdvancedLongitudinalTune="1", **{ADVANCED_ACK: "1"}), cp=cp).active()


def test_changing_a_row_still_records_the_owner_adoption():
  s = Store(LongitudinalTune="1")
  c = SettingsController("profiles", s, cp=NS(carFingerprint="TESLA_AP1_MODELS", openpilotLongitudinalControl=True))
  assert c.change("DecelerationProfile", 1)
  assert s.values["DecelerationProfile"] == 1 and s.values[PROFILE_ACK] is True
