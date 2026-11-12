"""ShowAccelGraph / LowerSpeedLimitsBox default-OFF policy and one-shot migration."""
from openpilot.common import bogpilot_toggles as bt
from openpilot.common.bogpilot_shipping_defaults import FILE_TOGGLE_DEFAULTS


def _boot(d):
  return bt.migrate_ui_layout_defaults(d)


def test_fresh_install_writes_nothing(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  assert bt.FILE_TOGGLES["ShowAccelGraph"][0] is False
  assert bt.FILE_TOGGLES["LowerSpeedLimitsBox"][0] is False
  assert FILE_TOGGLE_DEFAULTS["ShowAccelGraph"] is False
  assert FILE_TOGGLE_DEFAULTS["LowerSpeedLimitsBox"] is False
  assert bt.read_toggle("ShowAccelGraph") is False
  assert bt.read_toggle("LowerSpeedLimitsBox") is False
  assert _boot(tmp_path) is False
  assert bt.read_toggle("ShowAccelGraph") is False
  assert bt.read_toggle("LowerSpeedLimitsBox") is False
  assert (tmp_path / bt.ACCEL_GRAPH_MIGRATION_MARKER).exists()
  assert not (tmp_path / "ShowAccelGraph").exists()
  assert not (tmp_path / "LowerSpeedLimitsBox").exists()


def test_old_default_hide_off_is_not_rewritten(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  (tmp_path / "HideAccelGraph").write_text("0")
  (tmp_path / "SwapSpeedGraph").write_text("1")
  assert _boot(tmp_path) is False
  assert (tmp_path / "HideAccelGraph").read_text() == "0"
  assert (tmp_path / "SwapSpeedGraph").read_text() == "1"
  assert not (tmp_path / "ShowAccelGraph").exists()
  assert not (tmp_path / "LowerSpeedLimitsBox").exists()
  assert bt.read_toggle("ShowAccelGraph") is False
  assert bt.read_toggle("LowerSpeedLimitsBox") is False


def test_custom_hide_on_preserves_lower_slot(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  (tmp_path / "HideAccelGraph").write_text("1")
  assert _boot(tmp_path) is True
  assert (tmp_path / "ShowAccelGraph").read_text() == "0"
  assert (tmp_path / "LowerSpeedLimitsBox").read_text() == "1"
  assert bt.read_toggle("ShowAccelGraph") is False
  assert bt.read_toggle("LowerSpeedLimitsBox") is True
  # one-shot: later boots leave a deliberate Show Accel Graph opt-in alone
  for _ in range(3):
    assert _boot(tmp_path) is False
  bt.write_toggle("ShowAccelGraph", True)
  assert _boot(tmp_path) is False
  assert bt.read_toggle("ShowAccelGraph") is True
  assert bt.read_toggle("LowerSpeedLimitsBox") is True


def test_existing_new_keys_are_never_overwritten(monkeypatch, tmp_path):
  monkeypatch.setattr(bt, "BOGPILOT_DIR", tmp_path)
  (tmp_path / "HideAccelGraph").write_text("1")
  (tmp_path / "ShowAccelGraph").write_text("1")
  (tmp_path / "LowerSpeedLimitsBox").write_text("0")
  assert _boot(tmp_path) is False
  assert (tmp_path / "ShowAccelGraph").read_text() == "1"
  assert (tmp_path / "LowerSpeedLimitsBox").read_text() == "0"


def test_unwritable_dir_never_raises(tmp_path):
  blocker = tmp_path / "file"
  blocker.write_text("x")
  assert _boot(blocker / "sub") is False
