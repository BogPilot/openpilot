"""Lane 2: UI model -> file store -> actual soundd consumer. No audio device."""
import importlib.util, os, sys
from pathlib import Path
import pytest

if os.environ.get("PHASE2_SOUNDS"):  # overlay run against a read-only staging tree
  _spec = importlib.util.spec_from_file_location("phase2_sounds", os.environ["PHASE2_SOUNDS"])
  ps = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ps)
else:
  from openpilot.selfdrive.ui.bogpilot import phase2_sounds as ps


@pytest.fixture
def store(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path))
  from openpilot.selfdrive.ui import soundd
  monkeypatch.setattr(soundd, "_bogpilot_params_dir", lambda: tmp_path)
  # isolate from any real Params value
  import openpilot.common.params as p
  monkeypatch.setattr(p, "Params", lambda: type("P", (), {"get": lambda s, k: None})())
  return tmp_path


def test_every_row_has_soundd_consumer():
  from openpilot.selfdrive.ui import soundd
  assert set(ps.VOLUME_KEYS) == set(soundd._VOLUME_ALERT_KEYS.values()) == set(soundd.VOLUME_PARAM_KEYS)


def test_fresh_defaults_owner_audible(store):
  r = ps.rows()
  assert r[0]["value"] is False and all(not x["visible"] for x in r[1:])
  assert all(x["value"] == 101 and x["label"] == "Auto" for x in r[1:])
  assert list(store.iterdir()) == []  # reading never writes


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
  (store / "WarningImmediateVolume").write_text("0")  # hand-edited value: soundd clamp still applies
  assert ps.effective_gain("WarningImmediateVolume", 0.1) == pytest.approx(0.25)


def test_rejects_unowned_keys(store):
  with pytest.raises(KeyError):
    ps.set_volume("GreenLightAlert", 1)


def test_corrupt_and_out_of_range(store):
  (store / "PromptVolume").write_text("abc")
  assert ps.read_volume("PromptVolume") == 101
  (store / "PromptVolume").write_text("999")
  assert ps.read_volume("PromptVolume") == 101 and ps.raw_out_of_range("PromptVolume")
  assert (store / "PromptVolume").read_text() == "999"  # not rewritten
  ps.set_controller(True)
  # documents current consumer limitation: soundd would apply 9.99 gain (patch clamps)
  assert ps.effective_gain("PromptVolume", 0.3) == pytest.approx(9.99)
