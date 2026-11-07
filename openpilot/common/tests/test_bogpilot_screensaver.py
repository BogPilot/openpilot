"""OffroadScreensaver default-OFF policy and one-shot migration (synthetic file-dir tests)."""
from openpilot.common import bogpilot_toggles as bt
from openpilot.common.bogpilot_shipping_defaults import FILE_TOGGLE_DEFAULTS


def _boot(d):
  return bt.migrate_screensaver_default_off(d)


def test_fresh_install_defaults_off(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  assert bt.FILE_TOGGLES["OffroadScreensaver"][0] is False
  assert FILE_TOGGLE_DEFAULTS["OffroadScreensaver"] is False
  assert bt.read_toggle("OffroadScreensaver") is False
  assert _boot(tmp_path) is False
  assert bt.read_toggle("OffroadScreensaver") is False
  assert (tmp_path / bt.SCREENSAVER_MIGRATION_MARKER).exists()
  assert not (tmp_path / "OffroadScreensaver").exists()  # nothing invented


def test_inherited_on_migrates_off_once(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  for legacy in ("1", "true", " ON\n"):
    for f in tmp_path.iterdir():
      f.unlink()
    (tmp_path / "OffroadScreensaver").write_text(legacy)
    assert _boot(tmp_path) is True
    assert bt.read_toggle("OffroadScreensaver") is False


def test_repeated_boots_and_deliberate_opt_in_survive(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  bt.write_toggle("OffroadScreensaver", True)
  assert _boot(tmp_path) is True
  for _ in range(5):
    assert _boot(tmp_path) is False
  bt.write_toggle("OffroadScreensaver", True)  # deliberate opt-in after migration
  for _ in range(5):
    assert _boot(tmp_path) is False
    assert bt.read_toggle("OffroadScreensaver") is True


def test_explicit_off_and_unrelated_files_untouched(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  (tmp_path / "OffroadScreensaver").write_text("0")
  (tmp_path / "ScreenTimeout").write_text("30")  # stand-in for a user timer value: must survive
  (tmp_path / "BSMFlameTracks").write_text("1")
  assert _boot(tmp_path) is False
  assert (tmp_path / "OffroadScreensaver").read_text() == "0"
  assert (tmp_path / "ScreenTimeout").read_text() == "30"
  assert (tmp_path / "BSMFlameTracks").read_text() == "1"


def test_unwritable_dir_never_raises(tmp_path):
  blocker = tmp_path / "file"
  blocker.write_text("x")
  assert _boot(blocker / "sub") is False
