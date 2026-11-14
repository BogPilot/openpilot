"""Conditional Experimental Mode is removed (docs/tesla/DIVERGENCES.md "Conditional Experimental Mode removed").
Saved CE* values must stay harmless, nothing may drive from them, and regular Experimental Mode is untouched."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from opendbc.car.tesla_ap1.phase3_stalk_controls import AP1, CEM_REMOVED as STALK_CEM_REMOVED, apply_experimental_toggle, cem_is_on
from openpilot.common.bogpilot_params import BOGPILOT_PARAMS
from openpilot.selfdrive.controls.lib.phase3_long_accel import (
  CEM_ACK, CEM_KEYS, CEM_REMOVED, Conditions, ConditionalMode, LongAccelPort,
)
from openpilot.selfdrive.ui.bogpilot import phase3_gas_brake as GB
from openpilot.selfdrive.ui.layouts.settings import phase3_long_accel_settings as LS
from openpilot.selfdrive.ui.onroad.bogpilot.phase3_cem_status import HIDDEN, read_status

REPO = Path(__file__).resolve().parents[4]
ALL_ON = {CEM_ACK: 1, "ConditionalExperimental": 1, "ShowCEMStatus": 1, "CEStatus": 4, "CESpeed": 99, "CECurves": 1,
          "CELead": 1, "CEStopLights": 1, "CEModelStopTime": 8, "CESignalSpeed": 55}


class Store:
  def __init__(self, **values):
    self.values, self.puts = dict(values), []
  def default(self, key):
    return BOGPILOT_PARAMS.get(key, (None, None, "0"))[2] or "0"
  def raw(self, key):
    return self.values.get(key)
  def get(self, key, default=None):
    return self.values.get(key, self.default(key) if default is None else default)
  def get_bool(self, key, default=None):
    return str(self.get(key, default)).lower() in ("1", "true")
  def get_float(self, key):
    return float(self.get(key))
  def get_int(self, key, default=None):
    return int(self.get_float(key))
  def honoured(self, key, level=None):
    return True
  def toggle_bool(self, key, level=None):
    return self.get_bool(key)
  def put(self, key, value, block=False):
    self.values[key] = value
    self.puts.append((key, value))
  def put_bool(self, key, value, block=False):
    self.put(key, bool(value))
  def invalidate(self, *a):
    pass


def test_removed_flags_are_set():
  assert CEM_REMOVED is True and STALK_CEM_REMOVED is True


def test_every_cem_key_stays_registered_so_saved_values_and_resets_are_harmless():
  header = (REPO / "openpilot/common/params_keys_bogpilot.h").read_text()
  for key in (*CEM_KEYS, "CEStatus"):
    assert key in BOGPILOT_PARAMS, key
    assert '"%s"' % key in header, key
  # the adoption marker is a file key: still known to backup and reset, so an old marker is cleared as before
  for path in ("openpilot/system/bogpilot/settings_backup.py", "openpilot/system/bogpilot/toggle_reset.py"):
    assert CEM_ACK in (REPO / path).read_text(), path


@pytest.mark.parametrize("saved", [{}, ALL_ON, {"ConditionalExperimental": 0}, {"ConditionalExperimental": "junk", CEM_ACK: 1}])
def test_saved_cem_params_never_produce_conditions(saved):
  assert Conditions.read(Store(**saved)) is None


def test_status_is_never_published():
  store = Store(**ALL_ON)
  port = LongAccelPort.__new__(LongAccelPort)
  port.store, port.cem, port._published_status = store, ConditionalMode(), None
  for status, experimental in ((4, True), (2, True), (1, False), (0, False)):
    port.cem.status, port.cem.experimental = status, experimental
    port.publish_status()
  assert store.puts == [] and store.values["CEStatus"] == 4


def test_hud_badge_is_hidden_with_every_cem_setting_saved_on():
  sm = NS(recv_time={"bogpilotPlan": 100.0}, alive={"bogpilotPlan": True}, valid={"bogpilotPlan": True})
  assert read_status(Store(**ALL_ON), sm, 100.0, 90.0, True) is HIDDEN


class Params:
  def __init__(self, **data):
    self.data, self.puts = dict(data), []
  def get_bool(self, key, block=False):
    return bool(self.data.get(key, False))
  def get(self, key, block=False, return_default=False):
    return self.data.get(key)
  def put(self, key, value, block=False):
    self.data[key] = value
    self.puts.append((key, value))
  def put_bool(self, key, value, block=False):
    self.put(key, bool(value))


def test_stalk_hold_flips_regular_experimental_mode_with_cem_saved_on():
  p = Params(ExperimentalMode=False, ExperimentalModeConfirmed=True, ConditionalExperimental=True,
             Phase3CEMEnabled=True, CEStatus=0)
  assert not cem_is_on(p)
  car = NS(carFingerprint=AP1, dashcamOnly=False, passive=False, openpilotLongitudinalControl=True)
  state = NS(canValid=True, bogpilot=NS(ap1StalkPullToggle=True, ap1StalkFwdToggle=False))
  assert apply_experimental_toggle(p, car, state, True) is True and p.data["ExperimentalMode"] is True
  assert apply_experimental_toggle(p, car, state, True) is False and p.data["ExperimentalMode"] is False
  assert p.puts == [("ExperimentalMode", True), ("ExperimentalMode", False)]


def test_no_conditional_entry_in_the_settings_menus(monkeypatch):
  from openpilot.system.ui.widgets import list_view
  monkeypatch.setattr(list_view, "button_item", lambda title, *a, **k: NS(title=title))   # no window or fonts here
  store = Store(**ALL_ON)
  assert "conditional" not in [k for k, _, _ in GB.root_entries(store, None)]
  assert "ConditionalExperimental" not in GB.CONTROLS
  titles = [i.title for i in LS.gas_accel_entries(lambda *a: None, store)]
  assert "Conditional Experimental Mode" not in titles and "Advanced Longitudinal Tuning" in titles


def test_regular_experimental_mode_keys_are_untouched():
  header = (REPO / "openpilot/common/params_keys.h").read_text()
  for key in ("ExperimentalMode", "ExperimentalModeConfirmed"):
    assert '"%s"' % key in header, key
