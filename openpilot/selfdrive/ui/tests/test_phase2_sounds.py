"""soundsUI: UI model/Mute/ASCII minus -> file store -> soundd gain. No audio device."""
import importlib.util
import os

import pytest

if os.environ.get("PHASE2_SOUNDS"):
  _spec = importlib.util.spec_from_file_location("phase2_sounds", os.environ["PHASE2_SOUNDS"])
  ps = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ps)
else:
  from openpilot.selfdrive.ui.bogpilot import phase2_sounds as ps


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  from openpilot.selfdrive.ui import soundd
  monkeypatch.setattr(soundd, "_bogpilot_params_dir", lambda: tmp_path)
  import openpilot.common.params as p
  monkeypatch.setattr(p, "Params", lambda: type("P", (), {"get": lambda s, k: None})())
  return tmp_path


def test_every_row_has_soundd_consumer():
  from openpilot.selfdrive.ui import soundd
  assert set(ps.VOLUME_KEYS) == set(soundd._VOLUME_ALERT_KEYS.values()) == set(soundd.VOLUME_PARAM_KEYS)


def test_fresh_defaults_owner_audible(store):
  r = ps.rows()
  assert r[0]["value"] is False and all(not x["visible"] for x in r[1:])
  assert all(x["value"] == 101 and x["label"] == "Auto" and x["type"] == "slider" for x in r[1:])
  assert list(store.iterdir()) == []


def test_saved_prefs_preserved(store):
  (store / "EngageVolume").write_text("40")
  (store / "AlertVolumeControl").write_text("1")
  assert ps.read_volume("EngageVolume") == 40 and ps.read_controller()


def test_ui_write_reaches_soundd_instance(store):
  from openpilot.selfdrive.ui import soundd
  ps.set_controller(True)
  assert ps.set_volume("EngageVolume", 0) == 0
  ps.set_volume("PromptVolume", 55)
  ctl = soundd._bogpilot_bool(soundd._bogpilot_read_param("AlertVolumeControl"), False)
  pct = {k: soundd._bogpilot_int(soundd._bogpilot_read_param(k), 101) for k in soundd.VOLUME_PARAM_KEYS}
  assert ctl and pct["EngageVolume"] == 0 and pct["PromptVolume"] == 55
  assert ps.effective_gain("PromptVolume", 0.3) == pytest.approx(0.55)
  assert ps.effective_gain("EngageVolume", 0.3) == 0.0


def test_controller_off_is_ambient(store):
  ps.set_volume("EngageVolume", 0)
  assert ps.effective_gain("EngageVolume", 0.3) == 0.3


def test_warning_floors_kept(store):
  assert ps.set_volume("WarningImmediateVolume", 0) == 25
  assert ps.set_volume("WarningSoftVolume", 3) == 25
  ps.set_controller(True)
  (store / "WarningImmediateVolume").write_text("0")
  assert ps.effective_gain("WarningImmediateVolume", 0.1) == pytest.approx(0.25)


def test_rejects_unowned_keys(store):
  with pytest.raises(KeyError):
    ps.set_volume("GreenLightAlert", 1)


def test_corrupt_and_out_of_range(store):
  (store / "PromptVolume").write_text("abc")
  assert ps.read_volume("PromptVolume") == 101
  (store / "PromptVolume").write_text("999")
  assert ps.read_volume("PromptVolume") == 101 and ps.raw_out_of_range("PromptVolume")
  assert (store / "PromptVolume").read_text() == "999"
  ps.set_controller(True)
  assert ps.effective_gain("PromptVolume", 0.3) == pytest.approx(9.99)


def test_file_store_precedes_params(store, monkeypatch):
  from openpilot.selfdrive.ui import soundd
  class FakeParams:
    def get(self, k):
      return b"10"
  import openpilot.common.params as p
  monkeypatch.setattr(p, "Params", FakeParams)
  (store / "EngageVolume").write_text("77")
  assert soundd._bogpilot_read_param("EngageVolume") == "77"
  assert ps.read_volume("EngageVolume") == 77


def test_slider_math_clamp_and_mapping():
  assert ps.slider_fraction(0, 0, 101) == 0.0
  assert ps.slider_value_from_x(50, 0, 100, 0, 100) == 50
  assert ps.clamp("WarningSoftVolume", 0) == 25


def test_idle_refresh_constant():
  assert ps.IDLE_REFRESH_S == pytest.approx(1.0)


def test_ascii_minus_glyph_not_u2212():
  assert ps.MINUS_GLYPH == "-"
  assert ps.MINUS_GLYPH == "\u002d"
  assert ps.MINUS_GLYPH != "\u2212"
  assert ord(ps.MINUS_GLYPH) == 0x2D


def test_rows_buttons_use_ascii_minus(store):
  ps.set_controller(True)
  for row in ps.rows()[1:]:
    assert row["buttons"][1] == "-"
    assert "\u2212" not in "".join(row["buttons"])


def test_mute_sets_minimum_and_unmute_restores(store):
  ps.set_controller(True)
  ps.set_volume("EngageVolume", 55)
  assert ps.toggle_mute("EngageVolume") == 0
  assert ps.read_volume("EngageVolume") == 0
  assert ps.is_muted("EngageVolume")
  assert (store / "EngageVolumePreMute").read_text() == "55"
  assert ps.effective_gain("EngageVolume", 0.3) == 0.0
  assert ps.toggle_mute("EngageVolume") == 55
  assert ps.read_volume("EngageVolume") == 55
  assert not ps.is_muted("EngageVolume")
  assert not (store / "EngageVolumePreMute").exists()


def test_mute_warning_clamps_to_floor_not_silence(store):
  ps.set_controller(True)
  ps.set_volume("WarningImmediateVolume", 80)
  assert ps.mute_button_title("WarningImmediateVolume") == "Min"
  assert ps.toggle_mute("WarningImmediateVolume") == 25
  assert ps.read_volume("WarningImmediateVolume") == 25
  assert ps.is_muted("WarningImmediateVolume")
  assert ps.effective_gain("WarningImmediateVolume", 0.1) == pytest.approx(0.25)
  assert ps.toggle_mute("WarningImmediateVolume") == 80


def test_mute_soft_warning_floor(store):
  ps.set_controller(True)
  ps.set_volume("WarningSoftVolume", 60)
  assert ps.toggle_mute("WarningSoftVolume") == 25
  assert ps.label(ps.read_volume("WarningSoftVolume")) == "25%"
  assert ps.toggle_mute("WarningSoftVolume") == 60


def test_mute_persistence_across_restart(store, monkeypatch):
  """PreMute file survives a fresh module read (simulates process restart)."""
  ps.set_controller(True)
  ps.set_volume("DisengageVolume", 42)
  assert ps.toggle_mute("DisengageVolume") == 0
  assert (store / "DisengageVolumePreMute").read_text() == "42"
  # Re-bind readers as a new import would: same store path via env already set.
  assert ps.is_muted("DisengageVolume")
  assert ps.read_premute("DisengageVolume") == 42
  assert ps.toggle_mute("DisengageVolume") == 42
  assert ps.read_volume("DisengageVolume") == 42


def test_manual_adjust_clears_premute(store):
  ps.set_controller(True)
  ps.set_volume("RefuseVolume", 70)
  ps.toggle_mute("RefuseVolume")
  assert ps.is_muted("RefuseVolume")
  ps.set_volume("RefuseVolume", 33)  # user moves slider/buttons
  assert not (store / "RefuseVolumePreMute").exists()
  assert not ps.is_muted("RefuseVolume")


def test_ui_store_soundd_gain_matrix(store):
  from openpilot.selfdrive.ui import soundd
  ps.set_controller(True)
  cases = [
    ("EngageVolume", 0, 0.0),
    ("DisengageVolume", 40, 0.40),
    ("PromptVolume", 101, 0.25),
    ("RefuseVolume", 80, 0.80),
    ("WarningSoftVolume", 25, 0.25),
    ("WarningImmediateVolume", 50, 0.50),
  ]
  ambient = 0.25
  for key, pct, expect in cases:
    assert ps.set_volume(key, pct) == pct
    raw = soundd._bogpilot_int(soundd._bogpilot_read_param(key), 101)
    assert raw == ps.raw_volume(key)
    assert ps.effective_gain(key, ambient) == pytest.approx(expect)


def test_rows_expose_slider_and_mute_metadata(store):
  ps.set_controller(True)
  r = ps.rows()
  assert r[0]["type"] == "toggle"
  for row in r[1:]:
    assert row["type"] == "slider"
    assert row["mute_title"] in ("Mute", "Min")
    assert row["can_silence"] == (row["min"] == 0)
    assert row["buttons"][0] == row["mute_title"]
    assert row["buttons"][1] == "-"
    assert row["buttons"][3] == "+"


SAFETY_KEYS = ("PromptVolume", "PromptDistractedVolume", "WarningSoftVolume", "WarningImmediateVolume")


def test_every_safety_category_has_audible_floor_in_ui_and_consumer(store):
  """t994 INT: UI row bounds, Mute->Min, saved 0 and the soundd gain all stay >= 25% for safety alerts."""
  from openpilot.selfdrive.ui import soundd
  ps.set_controller(True)
  for key in SAFETY_KEYS:
    assert ps.row_bounds(key)[0] == 25, key
    assert ps.mute_button_title(key) == "Min", key
    assert ps.set_volume(key, 0) == 25, key
    ps.set_volume(key, 80)
    assert ps.toggle_mute(key) == 25, key
    assert ps.read_volume(key) >= 25
    assert ps.effective_gain(key, 0.1) == pytest.approx(0.25), key
    # a stale/hand-edited saved 0 (e.g. from an older build) is floored by the consumer too
    (store / key).write_text("0")
    assert ps.effective_gain(key, 0.1) == pytest.approx(0.25), key
    assert soundd.resolve_alert_gain(alert_volume_control=True, percent=0, ambient=0.1, key=key) == pytest.approx(0.25), key
    ps.set_volume(key, 101)
  row = {r["key"]: r for r in ps.rows()[1:]}
  for key in SAFETY_KEYS:
    assert row[key]["can_silence"] is False, key
  assert row["EngageVolume"]["can_silence"] is True  # informational chimes stay mutable


def test_prompt_distracted_reaches_soundd_with_floor(store):
  from openpilot.selfdrive.ui import soundd
  assert soundd._VOLUME_ALERT_KEYS[soundd.AudibleAlert.promptDistracted] == "PromptDistractedVolume"
  assert soundd._VOLUME_ALERT_KEYS[soundd.AudibleAlert.promptRepeat] == "PromptVolume"
  ps.set_controller(True)
  (store / "PromptDistractedVolume").write_text("0")
  assert ps.effective_gain("PromptDistractedVolume", 0.3) >= 0.25
