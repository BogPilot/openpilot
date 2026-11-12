"""Set-speed tip rounding (AP1TipRoundSet) is ON for new installs, saved values kept. No live car, sockets or real params."""
from types import SimpleNamespace as NS

import pytest

from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.tesla_ap1 import toggles as T
from opendbc.car.tesla_ap1.phase3_stalk_controls import AP1, Settings, Store
from opendbc.car.tesla_ap1.slc_raise import Ap1RaiseHoldoff, next_5_ms, prev_5_ms, step_1_ms
from openpilot.selfdrive.controls.tests.test_phase3_speed_control import DT, MPH, Sm, make
from openpilot.selfdrive.ui.bogpilot.phase3_stalk_controls import DESCRIPTIONS, TITLES, StalkMenu

KMH = CV.KPH_TO_MS


# ---- pure helpers (BogPilot bogpilot-tesla-ic-discovery f0be1ee66 semantics) ----
def test_next_prev_5_round_whole_mph():
  assert next_5_ms(14.8 * MPH, round_whole=True) == pytest.approx(20 * MPH)   # 14.8 -> 15 -> 20
  assert prev_5_ms(15.2 * MPH, round_whole=True) == pytest.approx(10 * MPH)   # 15.2 -> 15 -> 10
  assert next_5_ms(50 * MPH, round_whole=True) == pytest.approx(55 * MPH)
  assert prev_5_ms(50 * MPH, round_whole=True) == pytest.approx(45 * MPH)
  assert next_5_ms(49.6 * MPH, round_whole=True) == pytest.approx(55 * MPH)   # 49.6 -> 50 -> 55
  assert step_1_ms(14.8 * MPH, +1, round_whole=True) == pytest.approx(16 * MPH)
  assert step_1_ms(14.8 * MPH, -1, round_whole=True) == pytest.approx(14 * MPH)


def test_rounding_off_keeps_the_legacy_steps():
  assert next_5_ms(14.8 * MPH) == pytest.approx(15 * MPH)
  assert prev_5_ms(15.2 * MPH) == pytest.approx(15 * MPH)
  assert step_1_ms(14.8 * MPH, +1) == pytest.approx(15.8 * MPH)


def test_metric_steps_in_whole_kmh():
  assert next_5_ms(81.4 * KMH, round_whole=True, is_metric=True) == pytest.approx(85 * KMH)
  assert prev_5_ms(80.6 * KMH, round_whole=True, is_metric=True) == pytest.approx(80 * KMH)   # 81 -> 80
  assert step_1_ms(81.4 * KMH, +1, round_whole=True, is_metric=True) == pytest.approx(82 * KMH)


def tip(h, v, up=True, full=True, base_ms=None):
  h.update(True, False, False, False, 0.0, v, current_set_ms=v, dt=0.05)
  args = dict(current_set_ms=base_ms if base_ms is not None else v, dt=0.05, tip_full=full)
  h.update(True, not up, up, False, 0.0, v, **args)
  return h.tip_ms


def test_holdoff_class_default_off_and_attributes_drive_it():
  assert Ap1RaiseHoldoff().round_whole is False       # the helper class itself is legacy; the planner sets it from the pref
  h = Ap1RaiseHoldoff(); h.round_whole = True
  assert tip(h, 14.8 * MPH) == pytest.approx(20 * MPH)
  h = Ap1RaiseHoldoff()
  assert tip(h, 14.8 * MPH) == pytest.approx(15 * MPH)


# ---- toggle: default ON, saved value kept ----
def test_default_on_missing_empty_unreadable_or_garbage(tmp_path, monkeypatch):
  monkeypatch.setattr(T, "_ap1_tip_round_path", tmp_path / "AP1TipRoundSet")
  assert T.ap1_tip_round_set(AP1) is True                                   # no file = fresh install
  for text in ("", "  \n", "1", "true", "on", "garbage"):
    assert T.ap1_tip_round_set(AP1, text) is True, text
  (tmp_path / "AP1TipRoundSet").write_text("")
  assert T.ap1_tip_round_set(AP1) is True


def test_explicit_off_saved_value_is_preserved(tmp_path, monkeypatch):
  monkeypatch.setattr(T, "_ap1_tip_round_path", tmp_path / "AP1TipRoundSet")
  for text in ("0", "false", "off", " OFF \n", "False"):
    (tmp_path / "AP1TipRoundSet").write_text(text)
    assert T.ap1_tip_round_set(AP1) is False, text
  assert T.ap1_tip_round_set(AP1, "0") is False


def test_non_ap1_never_rounds(tmp_path, monkeypatch):
  monkeypatch.setattr(T, "_ap1_tip_round_path", tmp_path / "AP1TipRoundSet")
  assert T.ap1_tip_round_set("TESLA_MODEL_3") is False
  assert T.ap1_tip_round_set(None) is False


def test_setter_roundtrip(tmp_path):
  p = tmp_path / "d" / "AP1TipRoundSet"
  T.set_ap1_tip_round(False, p)
  assert p.read_text() == "0" and T.ap1_tip_round_set(AP1, p.read_text()) is False
  T.set_ap1_tip_round(True, p)
  assert p.read_text() == "1" and T.ap1_tip_round_set(AP1, p.read_text()) is True


# ---- Stalk Controls store / menu / help ----
def test_store_default_on_and_write_touches_only_the_pref_file(tmp_path):
  store = Store(tmp_path / "StalkControls.json")
  assert Settings().tip_round is True and store.read().tip_round is True
  store.write("pull_hold_s", 1.5)
  json_before = store.path.read_text()
  store.write("tip_round", False)
  assert store.read().tip_round is False and (tmp_path / "AP1TipRoundSet").read_text() == "0"
  assert store.path.read_text() == json_before                 # JSON untouched
  assert "tip_round" not in json_before
  store.write("tip_round", True)
  assert store.read().tip_round is True
  with pytest.raises(ValueError):
    store.write("tip_round", 1)


def test_store_saved_off_survives_json_changes_and_damage(tmp_path):
  store = Store(tmp_path / "StalkControls.json")
  (tmp_path / "AP1TipRoundSet").write_text("off")
  store.write("experimental_pull", False)                      # unrelated write must not flip it
  assert store.read().tip_round is False
  store.path.write_text("{broken")
  s = store.read()
  assert s.tip_round is False and not s.experimental_pull       # damaged JSON: gestures off, saved rounding kept


def test_menu_row_is_offroad_and_long_gated(tmp_path):
  car, offroad = NS(carFingerprint=AP1, dashcamOnly=False, passive=False, openpilotLongitudinalControl=True), True
  menu = StalkMenu(lambda: car, lambda: offroad, Store(tmp_path / "s.json"))
  assert menu.visible("tip_round") and menu.write("tip_round", False)
  assert menu.store.read().tip_round is False
  offroad = False
  assert not menu.write("tip_round", True) and menu.store.read().tip_round is False
  offroad = True
  car.openpilotLongitudinalControl = False
  assert not menu.visible("tip_round")                           # tips only matter with openpilot longitudinal
  car.carFingerprint = "TESLA_MODEL_3"
  assert not menu.visible("tip_round")


def test_row_title_description_and_help_text():
  assert TITLES["tip_round"] == "Round Set Speed Tips"
  assert "whole mph" in DESCRIPTIONS["tip_round"]
  HELP = pytest.importorskip("openpilot.selfdrive.ui.bogpilot.toggle_help").HELP   # needs zmq (VM); skipped without native deps
  e = HELP["tip_round"]
  assert e.default == "On" and "20 instead of 15" in e.what and "saved earlier is kept" in e.note.lower().replace("a value", "A value").lower()


# ---- planner wiring ----
def engage_with_up_tip(ctl, sm, v_ego, limit):
  for _ in range(4):
    sm.set(v_ego=v_ego, limit=limit, cruise=False, long_active=False, up=True)
    ctl.update(sm, 10.0, v_ego, DT)
  sm.set(v_ego=v_ego, limit=limit, cruise=True, long_active=True)
  ctl.update(sm, 10.0, v_ego, DT)                                 # tip-engage: sticky latch at the exact vEgo
  sm.set(v_ego=v_ego, limit=limit, cruise=True, long_active=True, up=True, spd=4)
  return ctl.update(sm, 10.0, v_ego, DT)


@pytest.mark.parametrize("pref,expected", [(True, 20 * MPH), (False, 15 * MPH)])
def test_planner_full_tip_up_from_fractional_latch(pref, expected):
  ctl, sm = make(), Sm()
  ctl._tip_round_fixed, ctl._tip_round = pref, pref
  out = engage_with_up_tip(ctl, sm, 14.8 * MPH, 14.0 * MPH)
  assert out == pytest.approx(expected)
  assert ctl.holdoff.round_whole is pref


def test_planner_reads_the_pref_default_on_and_saved_off(tmp_path, monkeypatch):
  monkeypatch.setattr(T, "_ap1_tip_round_path", tmp_path / "AP1TipRoundSet")
  t = make().toggles()
  ctl = make()
  ctl._tip_round_fixed = None
  ctl._toggles = None
  ctl.toggles()
  assert ctl._tip_round is True                                    # fresh install
  (tmp_path / "AP1TipRoundSet").write_text("0")
  ctl._toggles = None
  ctl.toggles()
  assert ctl._tip_round is False                                   # saved value kept
  assert t is not None


def test_tip_round_does_not_change_pull_or_whole_number_tips():
  for pref in (True, False):
    ctl, sm = make(), Sm()
    ctl._tip_round_fixed, ctl._tip_round = pref, pref
    for _ in range(3):
      sm.set(v_ego=20.0, limit=50 * MPH, cruise=False, long_active=False, rwd=True)
      ctl.update(sm, 10.0, 20.0, DT)
    sm.set(v_ego=20.0, limit=50 * MPH, cruise=True, long_active=True)
    out = ctl.update(sm, 10.0, 20.0, DT)
    assert out == pytest.approx(55 * MPH)                           # pull hand-over unchanged
    sm.set(v_ego=20.0, limit=50 * MPH, cruise=True, long_active=True, dn=True, spd=8)
    assert ctl.update(sm, 10.0, 20.0, DT) == pytest.approx(50 * MPH)   # whole-number set: same 5 step either way
