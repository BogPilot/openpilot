"""t1003u: Stop Acceleration / Stopping Rate rows with safe floors (<= -0.5 m/s^2, >= 0.1 m/s^3).

Real compiled-Params ParamStore. The floor is enforced in the UI (SettingsController range) AND in the consumer
(read_runtime_stopping / LongControl) so a stale saved value outside the floor is clamped. Defaults equal stock
stopping; a saved 0.9.7 preference stays dormant until THAT row is changed; a reset clears the markers.
Synthetic native tests only - no route replay, no road use.
"""
import json
import math
from pathlib import Path

import pytest
from opendbc.car.structs import car
from openpilot.common.realtime import DT_CTRL
from openpilot.common.bogpilot_store import ParamStore
from openpilot.common.params import Params
from openpilot.selfdrive.controls.lib import phase3_long_stopping as LS
from openpilot.selfdrive.controls.lib.longcontrol import LongControl, LongCtrlState
from openpilot.selfdrive.controls.lib.phase3_long_accel import ADVANCED_ACK, STOP_ACCEL_ACK, STOPPING_RATE_ACK, ROW_ACKS
from openpilot.selfdrive.ui.layouts.settings.phase3_long_accel_settings import SettingsController, BY_KEY, GROUPS
from openpilot.selfdrive.controls.tests.test_t994_gas_brake import (  # noqa: F401  (fixtures)
  make_cp, production_store, prefs, store, window, run_longcontrol_equivalence,
)

ROOT = Path(__file__).resolve().parents[4]


def adopted(store, cp, **rows):
  c = SettingsController("advanced", store, cp=cp)
  assert c.change("AdvancedLongitudinalTune", True)
  for key, value in rows.items():
    assert c.change(key, value)
  return c


def fresh_reader(store):
  return ParamStore(params=Params(store._params.d))


def stop_after(cp, store, frames):
  control = LongControl(cp, stopping_store=fresh_reader(store))
  cs = car.CarState.new_message()
  out = None
  for _ in range(frames):
    out = control.update(True, cs, 0, True, (-4., 2.))
  assert control.long_control_state == LongCtrlState.stopping
  return out


# ---- registration ------------------------------------------------------------------------------------------
def test_rows_registered_in_advanced_group_with_the_0_9_7_ranges():
  assert GROUPS["advanced"][3] == ("LongitudinalActuatorDelay", "MaxDesiredAcceleration", "StopAccel", "StoppingDecelRate")
  accel, rate = BY_KEY["StopAccel"], BY_KEY["StoppingDecelRate"]
  assert (accel.title, accel.low, accel.high, accel.step) == ("Stop Acceleration", -4, -0.5, .01)
  assert (rate.title, rate.low, rate.high, rate.step) == ("Stopping Rate", .1, 1, .01)
  assert (BY_KEY["MaxDesiredAcceleration"].low, BY_KEY["MaxDesiredAcceleration"].high) == (.1, 4)   # other ranges untouched
  assert (BY_KEY["LongitudinalActuatorDelay"].low, BY_KEY["LongitudinalActuatorDelay"].high) == (0, 1)
  assert LS.STOP_TUNING_ENABLED and LS.STOP_ACCEL_CEILING == -0.5 and LS.STOPPING_RATE_FLOOR == 0.1


# ---- UI floor ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("asked,saved", [(0, -0.5), (1.0, -0.5), (-0.49, -0.5), (-0.5, -0.5), (-2.0, -2.0), (-4, -4), (-9, -4)])
def test_ui_clamps_stop_acceleration(store, asked, saved):
  c = adopted(store, make_cp())
  assert c.change("StopAccel", asked)
  assert fresh_reader(store).get_float("StopAccel") == pytest.approx(saved)


@pytest.mark.parametrize("asked,saved", [(0, .1), (.001, .1), (.099, .1), (.1, .1), (.5, .5), (1, 1), (7, 1)])
def test_ui_clamps_stopping_rate(store, asked, saved):
  c = adopted(store, make_cp())
  assert c.change("StoppingDecelRate", asked)
  assert fresh_reader(store).get_float("StoppingDecelRate") == pytest.approx(saved)


def test_ui_refuses_non_finite_and_nudges_stop_at_the_floor(store):
  c = adopted(store, make_cp())
  for bad in (float("nan"), float("inf"), float("-inf")):
    assert c.change("StopAccel", bad) is False and c.change("StoppingDecelRate", bad) is False
  assert store.raw("StopAccel") is None and store.raw(ROW_ACKS["StopAccel"]) is None
  c.change("StopAccel", -0.5)
  assert c.nudge("StopAccel", 1) and c.display_value("StopAccel") == pytest.approx(-0.5)      # cannot rise above the floor
  c.change("StoppingDecelRate", .1)
  assert c.nudge("StoppingDecelRate", -1) and c.display_value("StoppingDecelRate") == pytest.approx(.1)
  assert c.value_text("StopAccel") == "-0.50 m/s^2" and c.value_text("StoppingDecelRate") == "0.10 m/s^3"


def test_ui_shows_clamped_value_for_a_stale_saved_one(store):
  c = adopted(store, make_cp())
  store.put("StopAccel", 0.0, block=True)
  store.put("StoppingDecelRate", .001, block=True)
  assert c.display_value("StopAccel") == pytest.approx(-0.5)
  assert c.display_value("StoppingDecelRate") == pytest.approx(.1)
  store.put("StopAccel", -50, block=True)
  assert c.display_value("StopAccel") == pytest.approx(-4)
  assert c.nudge("StopAccel", 1) and fresh_reader(store).get_float("StopAccel") == pytest.approx(-3.99)


# ---- consumer floor (stale saved values) -------------------------------------------------------------------
@pytest.mark.parametrize("stale,clamped", [("0", -0.5), ("0.3", -0.5), ("-0.1", -0.5), ("-9", -4.0), ("-1.5", -1.5)])
def test_consumer_clamps_stale_stop_acceleration(store, stale, clamped):
  cp = make_cp()
  adopted(store, cp, StopAccel=-1.0)
  store.put("StopAccel", float(stale), block=True)        # stale/out-of-range value saved behind the UI
  assert LS.read_runtime_stopping(fresh_reader(store), cp).stop_accel == pytest.approx(clamped)


@pytest.mark.parametrize("stale,clamped", [("0", .1), ("0.001", .1), ("5", 1.0), ("0.4", .4)])
def test_consumer_clamps_stale_stopping_rate(store, stale, clamped):
  cp = make_cp()
  adopted(store, cp, StoppingDecelRate=.5)
  store.put("StoppingDecelRate", float(stale), block=True)
  assert LS.read_runtime_stopping(fresh_reader(store), cp).stopping_decel_rate == pytest.approx(clamped)


def test_consumer_non_finite_stale_value_falls_back_to_stock(store):
  cp = make_cp()
  adopted(store, cp, StopAccel=-1.0, StoppingDecelRate=.5)
  tune = LS.read_runtime_stopping(_Raw(store, StopAccel="nan", StoppingDecelRate="inf"), cp)
  assert (tune.stop_accel, tune.stopping_decel_rate) == (-2, 1.0)


class _Raw:
  """Store wrapper returning raw junk for chosen keys (ParamStore FLOAT keys refuse to persist non-numbers)."""
  def __init__(self, inner, **raw):
    self.inner, self.raw_values = inner, raw
  def get(self, key):
    return self.raw_values[key] if key in self.raw_values else self.inner.get(key)
  def __getattr__(self, name):
    return getattr(self.inner, name)


def test_longcontrol_output_never_holds_less_than_the_floor_with_stale_values(store):
  cp = make_cp()
  adopted(store, cp, StopAccel=-1.0, StoppingDecelRate=.5)
  store.put("StopAccel", 0.0, block=True)          # a stale 0 would hold no brake command at standstill
  out = stop_after(cp, store, 400)                 # rate 0.5 m/s^3 -> reaches the -0.5 floor after 100 frames
  assert -0.5 - 0.01 <= out <= -0.5 + 1e-9, out
  store.put("StopAccel", -1.0, block=True)
  store.put("StoppingDecelRate", .001, block=True)  # a ~0 rate would ramp ~1000x slower than stock
  out = stop_after(cp, store, 100)
  assert out == pytest.approx(-0.1 * DT_CTRL * 100, abs=1e-6), out


def test_longcontrol_user_values_take_effect_and_actuator_limits_still_win(store):
  cp = make_cp()
  adopted(store, cp, StopAccel=-1.0, StoppingDecelRate=.5)
  out = stop_after(cp, store, 400)
  assert -1.0 - 0.005 <= out <= -1.0 + 1e-9, out
  control = LongControl(cp, stopping_store=fresh_reader(store))
  cs = car.CarState.new_message()
  for _ in range(400):
    out = control.update(True, cs, 0, True, (-0.3, 2.))
  assert out == pytest.approx(-0.3)                # stock actuator limit still clamps


# ---- dormancy / adoption markers ---------------------------------------------------------------------------
def test_saved_0_9_7_values_are_dormant_until_that_row_is_changed(store):
  cp = make_cp()
  for key, value in (("StopAccel", -4), ("StoppingDecelRate", .1)):
    store.put(key, value, block=True)               # as restored from a 0.9.7 backup
  store.put_bool("AdvancedLongitudinalTune", True, block=True)
  stock = LS.native_stopping_tune(cp)
  assert LS.read_runtime_stopping(fresh_reader(store), cp) == stock
  c = SettingsController("advanced", store, cp=cp)
  assert c.change("AdvancedLongitudinalTune", True)                 # group adopted via the parent ...
  assert c.change("MaxDesiredAcceleration", 1.5)                    # ... and another row
  assert fresh_reader(store).get_bool(ADVANCED_ACK, False)
  assert LS.read_runtime_stopping(fresh_reader(store), cp) == stock  # stop rows still dormant
  assert c.change("StopAccel", -3.0)
  tune = LS.read_runtime_stopping(fresh_reader(store), cp)
  assert tune.stop_accel == pytest.approx(-3.0) and tune.stopping_decel_rate == 1.0   # rate row still dormant
  assert c.change("StoppingDecelRate", .4)
  assert LS.read_runtime_stopping(fresh_reader(store), cp).stopping_decel_rate == pytest.approx(.4)


def test_parent_off_or_no_longitudinal_or_disabled_is_stock(store):
  cp = make_cp()
  c = adopted(store, cp, StopAccel=-3.0, StoppingDecelRate=.4)
  assert c.change("AdvancedLongitudinalTune", False)
  assert LS.read_runtime_stopping(fresh_reader(store), cp) == LS.native_stopping_tune(cp)
  c.change("AdvancedLongitudinalTune", True)
  assert LS.read_runtime_stopping(fresh_reader(store), make_cp(long=False)) == LS.native_stopping_tune(make_cp(long=False))


# ---- stock equivalence at defaults -------------------------------------------------------------------------
def test_defaults_equal_stock_when_nothing_written_5000_frames(prefs):
  run_longcontrol_equivalence(make_cp(), production_store(prefs, "t1003_fresh"))


def test_unwritten_rows_display_stock_values_and_write_nothing(store):
  cp = make_cp()
  c = SettingsController("advanced", store, cp=cp)
  assert c.display_value("StopAccel") == pytest.approx(-2.0) and c.display_value("StoppingDecelRate") == pytest.approx(1.0)
  assert store.raw("StopAccel") is None and store.raw("StoppingDecelRate") is None
  assert store.raw(STOP_ACCEL_ACK) is None and store.raw(STOPPING_RATE_ACK) is None


def test_rows_written_at_the_stock_values_equal_stock_5000_frames(store):
  cp = make_cp()
  adopted(store, cp, StopAccel=-2.0, StoppingDecelRate=1.0)
  run_longcontrol_equivalence(cp, fresh_reader(store))


def test_user_can_choose_a_stop_accel_below_a_weak_stock_value_but_unwritten_keeps_stock(store):
  cp = make_cp()
  cp.stopAccel = -0.2                      # a car whose stock value is above the user floor
  adopted(store, cp)
  assert LS.read_runtime_stopping(fresh_reader(store), cp).stop_accel == pytest.approx(-0.2)   # unwritten = stock, not clamped
  SettingsController("advanced", store, cp=cp).change("StopAccel", -0.3)
  assert LS.read_runtime_stopping(fresh_reader(store), cp).stop_accel == pytest.approx(-0.5)


# ---- init guard --------------------------------------------------------------------------------------------
def test_store_failure_still_falls_back_to_stock_stopping():
  class Broken:
    def get_bool(self, *a, **k): raise RuntimeError("settings unavailable")
    def __getattr__(self, name): raise RuntimeError("settings unavailable")
  cp = make_cp()
  control = LongControl(cp, stopping_store=Broken())
  cs = car.CarState.new_message()
  out = control.update(True, cs, 0, True, (-3., 2.))
  assert control.long_control_state == LongCtrlState.stopping
  assert out == pytest.approx(-1.0 * DT_CTRL)


# ---- reset clears markers ----------------------------------------------------------------------------------
def test_reset_and_backup_tables_carry_both_new_markers():
  from openpilot.selfdrive.ui.bogpilot.phase3_system_utilities import ADOPTION_MARKERS as A
  from openpilot.system.bogpilot import toggle_reset
  from openpilot.system.bogpilot.settings_backup import FILE_KEYS
  new = {STOP_ACCEL_ACK, STOPPING_RATE_ACK}
  assert new <= set(A) and new <= set(toggle_reset.ADOPTION_MARKERS) and new <= set(FILE_KEYS)
  assert set(A) == set(toggle_reset.ADOPTION_MARKERS) and len(set(A)) == 15
  for table in (toggle_reset.shipping_defaults(), toggle_reset.reset_defaults()):
    for key in new:
      assert key in table and table[key] is None
  fixture = json.loads((ROOT / "openpilot/system/bogpilot/tests/fixtures/reset_backup_scope.json").read_text())
  assert new <= set(fixture["file_keys"])


def test_reset_removes_the_stop_row_markers_and_the_consumer_returns_to_stock(store, tmp_path):
  from openpilot.system.bogpilot import toggle_reset
  cp = make_cp()
  adopted(store, cp, StopAccel=-3.0, StoppingDecelRate=.4)
  d = tmp_path / "markers"
  d.mkdir()
  for key in (STOP_ACCEL_ACK, STOPPING_RATE_ACK):
    (d / key).write_text("1")

  class P:
    removed = []
    def all_keys(self): return [toggle_reset.REQUEST_KEY]
    def get_bool(self, k): return True
    def remove(self, k): self.removed.append(k)
    def get(self, k): return None
  result = toggle_reset.reset_requested(P(), str(d), backup=lambda: True)
  assert result.status == "completed", result.error
  for key in (STOP_ACCEL_ACK, STOPPING_RATE_ACK):
    assert not (d / key).exists(), key
  # With the markers gone (ParamStore reads the same file-store names) the stale saved values are dormant again.
  for key in (STOP_ACCEL_ACK, STOPPING_RATE_ACK):
    store.put_bool(key, False, block=True)
  assert LS.read_runtime_stopping(fresh_reader(store), cp) == LS.native_stopping_tune(cp)
  assert math.isclose(fresh_reader(store).get_float("StopAccel"), -3.0)   # the saved preference itself is kept


def test_longcontrol_source_guards_unchanged():
  src = (ROOT / "openpilot/selfdrive/controls/lib/longcontrol.py").read_text()
  assert "stock (feae) stopping behaviour" in src and "stopping_store=None" in src


def test_settings_units_and_descriptions_are_ascii():
  """t1019: the font atlas has no superscripts; units read m/s^2 and m/s^3 (rendered rows and their descriptions)."""
  from openpilot.selfdrive.ui.layouts.settings import phase3_long_accel_settings as S
  units = {r.key: r.unit for r in S.ROWS}
  assert units["StopAccel"] == " m/s^2" and units["MaxDesiredAcceleration"] == " m/s^2" and units["StoppingDecelRate"] == " m/s^3"
  src = Path(S.__file__).read_text()
  assert "m/s\u00b2" not in src and "m/s\u00b3" not in src
