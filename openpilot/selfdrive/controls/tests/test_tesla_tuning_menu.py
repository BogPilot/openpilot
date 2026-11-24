"""Tesla Tuning (Settings > Vehicle Settings > Tesla Tuning): table, store, consumers, untouched replay, menu wiring.

Consumers read their values once, at import, so every consumer check runs in a fresh interpreter (tesla_tuning_probe.py).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from opendbc.car.tesla_ap1 import tesla_tuning as tt
from openpilot.selfdrive.ui.bogpilot import tesla_tuning_menu as menu
from openpilot.selfdrive.ui.bogpilot import tesla_start_values as sv

PROBE = str(Path(__file__).with_name("tesla_tuning_probe.py"))
S, X, P = tt.S, tt.X, tt.P
PANDA_ACCEL_MIN, PANDA_ACCEL_MAX = -3.52, 2.0
FORBIDDEN = re.compile(r"mass|wheelbase|steerlimit|timer|steer|panda|safety|flag", re.I)


@pytest.fixture
def pdir(tmp_path, monkeypatch):
  d = tmp_path / "bogpilot"
  d.mkdir()
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(d))
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "params"))
  tt.reload()
  yield d
  monkeypatch.undo()
  tt.reload()


def run_probe(mode, params_dir=None, params_root=None):
  env = dict(os.environ)
  env.pop("BOGPILOT_PARAMS_DIR", None)
  env["BOGPILOT_PARAMS_DIR"] = str(params_dir) if params_dir else "/nonexistent_bogpilot_dir"
  env["PARAMS_ROOT"] = str(params_root) if params_root else "/nonexistent_params_root"
  out = subprocess.run([sys.executable, PROBE, mode], env=env, capture_output=True, text=True, timeout=300)
  assert out.returncode == 0, out.stderr[-2000:]
  return json.loads(out.stdout.strip().splitlines()[-1])


def set_level(root, level, confirmed=True):
  d = Path(root) / "d"
  d.mkdir(parents=True, exist_ok=True)
  (d / "TuningLevelConfirmed").write_text("1" if confirmed else "0")
  (d / "TuningLevel").write_text(str(level))


# ---------------------------------------------------------------- table
def test_table_shape():
  assert len(tt.KEYS) == len(set(tt.KEYS)) == 23
  for r in tt.ROWS:
    assert r.lo <= r.shipped <= r.hi, r.key
    assert r.step > 0 and r.cars and set(r.cars) <= set(tt.ALL)
    assert r.clamp(r.lo - 100) == r.lo and r.clamp(r.hi + 100) == r.hi
    assert not FORBIDDEN.search(r.key + " " + r.title), r.key


def test_bounds_stay_inside_panda_limits():
  standby = tt.BY_KEY["AP1StandbyAccelMin"]
  assert PANDA_ACCEL_MIN < standby.lo and standby.hi <= 0.0   # standby window is -3.52 .. 0.0 (top fixed at 0.0)
  for k in ("AP1BrakeHardAccel", "CurveMaxDecel", "PreApPedalRegenMax"):
    assert tt.BY_KEY[k].lo >= -2.0 and tt.BY_KEY[k].hi < 0
  assert tt.BY_KEY["PreApPedalAccelMax"].hi <= 2.5 <= PANDA_ACCEL_MAX + 0.5 and tt.BY_KEY["PreApPedalAccelMax"].lo >= 1.1
  assert tt.BY_KEY["AP1BrakeHardAccel"].hi < -1.0                     # stays below AP1_BRAKE_URGENT_ACCEL
  for k in ("AP1RiseJerk", "AP1DriveReleaseJerk", "AP1DriveReleaseBrakeJerk", "AP1BrakeOnsetJerk", "AP1ComfortJerkLimit"):
    assert tt.BY_KEY[k].hi <= 8.0                                      # never above the full jerk limit sent for deep braking


def test_shipped_values_equal_the_live_constants():
  """With nothing saved every consumer holds exactly the table's shipped value (the constant the car code has always used)."""
  v = run_probe("values")
  for r in tt.ROWS:
    assert v[r.key] == pytest.approx(r.shipped, abs=1e-9), r.key
  assert v["_preap_modules"] == [2.5, -1.5, 2.5, -1.5]
  assert v["_standby_engage_hold"] == -1.4


# ---------------------------------------------------------------- store
def test_get_defaults_and_bad_files(pdir):
  assert tt.reload() == {}
  for text in ("", "abc", "nan", "inf", "-inf", "1e999"):
    (pdir / tt.file_key("AP1RiseJerk")).write_text(text)
    assert tt.reload() == {}, text
    assert tt.get("AP1RiseJerk", 2.5) == 2.5


def test_get_clamps_and_returns_shipped_object(pdir):
  (pdir / tt.file_key("AP1RiseJerk")).write_text("99")
  (pdir / tt.file_key("AP1BrakeHardAccel")).write_text("-9")
  tt.reload()
  assert tt.get("AP1RiseJerk", 2.5) == 5.0 and tt.get("AP1BrakeHardAccel", -2.0) == -2.0
  assert tt.get("AP1LaunchJerkMax", 1.5) == 1.5


def test_tuning_level_gate(pdir, tmp_path):
  (pdir / tt.file_key("AP1RiseJerk")).write_text("3.0")
  for level, applies in ((0, False), (1, False), (2, True), (3, True)):
    set_level(tmp_path / "params", level)
    assert tt.reload().get("AP1RiseJerk") == (3.0 if applies else None), level
  set_level(tmp_path / "params", 0, confirmed=False)      # never confirmed reads as Developer
  assert tt.reload().get("AP1RiseJerk") == 3.0


def test_set_value_clamps_and_removes_default_file(pdir):
  assert menu.set_value("AP1RiseJerk", 3.0) == 3.0 and (pdir / "TeslaTuningAP1RiseJerk").read_text() == "3"
  assert menu.read_value("AP1RiseJerk") == 3.0 and not menu.is_default("AP1RiseJerk")
  assert menu.set_value("AP1RiseJerk", 100) == 5.0
  assert menu.set_value("AP1RiseJerk", -100) == 0.5
  assert menu.set_value("AP1RiseJerk", 2.5) == 2.5 and not (pdir / "TeslaTuningAP1RiseJerk").exists()
  assert menu.is_default("AP1RiseJerk")


def test_nudge_steps_from_the_shipped_value_and_clamps(pdir):
  assert menu.nudge("AP1StandbyJerkMax", 1) == 0.496 and menu.nudge("AP1StandbyJerkMax", -1) == 0.476
  assert menu.is_default("AP1StandbyJerkMax")
  for _ in range(100):
    menu.nudge("CurveMaxDecel", -1)
  assert menu.read_value("CurveMaxDecel") == -1.2
  assert menu.value_text("CurveMaxDecel") == "-1.2" and "\u2212" not in menu.value_text("CurveMaxDecel")


def test_reset_table_restores_everything(pdir):
  for r in tt.ROWS:
    menu.set_value(r.key, r.hi if r.hi != r.shipped else r.lo)
  assert all(not menu.is_default(r.key) for r in tt.ROWS)
  for key, value in menu.reset_table().items():
    menu.set_value(key, value)
  assert all(menu.is_default(r.key) for r in tt.ROWS) and list(pdir.glob("TeslaTuning*")) == []


# ---------------------------------------------------------------- consumers use the edited values
def edited_values():
  out = {}
  for r in tt.ROWS:
    out[r.key] = round(r.shipped + r.step * (2 if r.shipped + 2 * r.step <= r.hi else -2), 4)
    assert r.lo <= out[r.key] <= r.hi and out[r.key] != r.shipped
  return out


def test_consumers_use_every_edited_value_written_by_the_menu(pdir, tmp_path):
  edits = edited_values()
  for key, value in edits.items():
    assert menu.set_value(key, value) == value          # the UI store
  v = run_probe("values", pdir, tmp_path / "params")      # the consumers, in a fresh process
  for key, value in edits.items():
    assert v[key] == pytest.approx(value, abs=1e-6), (key, v[key], value)
  assert v["_preap_modules"] == [edits["PreApPedalAccelMax"], edits["PreApPedalRegenMax"]] * 2
  assert v["_standby_engage_hold"] == edits["AP1StandbyAccelMin"]


def test_out_of_range_files_are_clamped_by_the_consumers(pdir, tmp_path):
  for r in tt.ROWS:
    (pdir / tt.file_key(r.key)).write_text(str(r.hi + 50 if r.shipped >= 0 else r.lo - 50))
  v = run_probe("values", pdir, tmp_path / "params")
  for r in tt.ROWS:
    assert r.lo - 1e-9 <= v[r.key] <= r.hi + 1e-9, r.key


def test_edits_below_advanced_are_ignored_by_the_consumers(pdir, tmp_path):
  for key, value in edited_values().items():
    menu.set_value(key, value)
  set_level(tmp_path / "params", 1)
  v = run_probe("values", pdir, tmp_path / "params")
  assert all(v[r.key] == pytest.approx(r.shipped, abs=1e-9) for r in tt.ROWS)


# ---------------------------------------------------------------- untouched replay is identical
def test_untouched_replay_identical(pdir, tmp_path):
  baseline = run_probe("replay")
  assert run_probe("replay", pdir, tmp_path / "params") == baseline               # empty store
  for r in tt.ROWS:                                                                # saved values equal to the shipped ones, plus junk
    (pdir / tt.file_key(r.key)).write_text(f"{r.shipped:g}")
  (pdir / "TeslaTuningNotARow").write_text("9")
  assert run_probe("replay", pdir, tmp_path / "params") == baseline
  for key, value in edited_values().items():                                       # real edits, but Tuning Level below Advanced
    (pdir / tt.file_key(key)).write_text(f"{value:g}")
  set_level(tmp_path / "params", 1)
  assert run_probe("replay", pdir, tmp_path / "params") == baseline
  set_level(tmp_path / "params", 2)                                                # sanity: the replay does react to edits
  assert run_probe("replay", pdir, tmp_path / "params") != baseline


# ---------------------------------------------------------------- menu wiring
def test_car_gating_and_pill():
  assert all(menu.pill_visible(lambda c=c: c) for c in menu.LEGACY_TESLAS)
  assert not menu.pill_visible(lambda: "TOYOTA_COROLLA") and not menu.pill_visible(lambda: "")
  assert {r.key for r in tt.rows_for(P)} >= {"PreApPedalAccelMax", "PreApPedalRegenMax"}
  x_keys = {r.key for r in tt.rows_for(X)}
  assert "AP1RiseJerk" in x_keys and not {"PreApPedalAccelMax", "PreApPedalRegenMax", "AP1StandbyAccelMin"} & x_keys
  assert "AP1StandbyAccelMin" in {r.key for r in tt.rows_for(S)} and "AP1StandbyAccelMin" not in {r.key for r in tt.rows_for(P)}


def test_tuning_level_page_class_and_help():
  from openpilot.selfdrive.ui.bogpilot import onroad_policy, toggle_help, tuning_level
  assert onroad_policy.page_class(menu.PAGE_KEY) == onroad_policy.LOCKED
  for r in tt.ROWS:
    assert tuning_level.row_level(r.key) == tuning_level.ADVANCED
    assert tuning_level.row_visible(r.key, 2) and not tuning_level.row_visible(r.key, 1)
    entry = toggle_help.resolve(r.key)
    assert entry is not None and entry.default and entry.range
    text = toggle_help.help_plain(entry) + sv.tuning_start_text(r.key) + sv.tuning_start_text(r.key, S)
    assert text.isascii() and "<" not in text and ">" not in text and "\u2212" not in text, r.key
    assert "Advanced" in entry.note and "panda" in entry.note and "next time the car starts" in entry.note
  assert tuning_level.page_level(menu.controls()) == tuning_level.ADVANCED


def test_start_values_per_car():
  for r in tt.ROWS:
    for fp in tt.ALL:
      text = sv.tuning_value_text(r.key, fp)
      assert (text is not None) == (fp in r.cars)
      if text:
        assert text.startswith(f"{r.shipped:.{r.decimals}f}")
  assert "Pre-AP Model S not used" in sv.tuning_start_text("AP1RiseJerk")
  assert sv.tuning_start_text("PreApPedalAccelMax", P) == "Starting value on this car (Pre-AP Model S): 2.5 m/s^2."
  assert sv.tuning_start_text("PreApPedalAccelMax", S) == "Not used on this car (AP1 Model S)."


def test_menu_registration():
  pytest.importorskip("pyray")
  from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections, working_pages
  vehicle = next(s for s in menu_sections() if s.key == "vehicle")
  pill = next(p for p in vehicle.pills if p.key == "tesla_tuning")
  assert pill.title == "Tesla Tuning" and [pg.key for pg in pill.pages] == ["tesla_tuning"] and pill.visible is menu.pill_visible
  page = next(pg for pg in working_pages()["vehicle"] if pg.key == "tesla_tuning")
  assert page.controls == menu.controls() and len(page.controls) == 23


@pytest.fixture
def fonts():
  """Font-resource stand-in only (no display on the build VM): the real raylib widgets and their callbacks stay real."""
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  original = gui_app.font
  gui_app.font = lambda *a, **kw: rl.Font()
  yield
  gui_app.font = original


def test_layout_rows_follow_the_car_and_write_through_the_store(pdir, fonts):
  pytest.importorskip("pyray")
  state = {"car": S, "edit": True}
  layout = menu.create_tesla_tuning_layout(car_fn=lambda: state["car"], editable=lambda: state["edit"])
  row = layout.rows["AP1RiseJerk"]
  assert row.is_visible and not layout.rows["PreApPedalAccelMax"].is_visible and layout.rows["AP1StandbyAccelMin"].is_visible
  state["car"] = P
  assert layout.rows["PreApPedalAccelMax"].is_visible and not row.is_visible
  state["car"] = S
  action = row.action_item
  assert [str(b) for b in action.buttons][:3] == ["-", "2.5", "+"] or action.buttons[0] == "-"
  action.callback(2)                     # +
  assert menu.read_value("AP1RiseJerk") == 2.6
  action.callback(0)                     # -
  assert menu.read_value("AP1RiseJerk") == 2.5 and not (pdir / "TeslaTuningAP1RiseJerk").exists()
  state["edit"] = False
  action.callback(2)
  assert menu.read_value("AP1RiseJerk") == 2.5            # locked: no write
  assert layout.reset.title and "Reset to Tesla defaults" in str(layout.reset.title() if callable(layout.reset.title) else layout.reset.title)
  assert dict(layout.reset.section_defaults()) == menu.reset_table()


def test_pill_follows_car_and_tuning_level(monkeypatch, pdir):
  pytest.importorskip("pyray")
  from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections
  from openpilot.selfdrive.ui.layouts.settings.menu_097 import MenuNavigation
  nav = MenuNavigation(menu_sections(), lambda: None, lambda *_: None)
  vehicle = next(s for s in nav.sections if s.key == "vehicle")

  def pills(level):
    return [p.key for p in nav.pills_of(vehicle, level)]
  for car, shows in ((S, True), (X, True), (P, True), ("TOYOTA_COROLLA", False), ("", False)):
    monkeypatch.setattr(menu, "current_car", lambda car=car: car)
    assert ("tesla_tuning" in pills(3)) == shows, car          # Developer
    assert ("tesla_tuning" in pills(2)) == shows, car          # Advanced
    assert "tesla_tuning" not in pills(1) and "tesla_tuning" not in pills(0), car   # Standard / Minimal
