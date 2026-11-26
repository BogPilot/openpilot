"""0.9.7 section icons: the copied files and the section mapping (pure, no window).

The rows that carry them, the icon width in the row layout and a missing file are checked natively in
test_bogpilot_menu_097.py (TestMenuNative)."""
import hashlib
from pathlib import Path

from openpilot.selfdrive.ui.bogpilot import section_icons as si

ICONS = Path(__file__).resolve().parents[2] / "assets" / "icons" / "bogpilot"

# sha256 of each file, byte-identical to BogPilot 0.9.7 frogpilot/assets/toggle_icons (same names)
SHA256 = {
  "icon_advanced_lateral_tune.png": "674157a344a3b0efa1b202a8c339b6a40816d980635434e189026fbdc1581bb7",
  "icon_advanced_longitudinal_tune.png": "89c3571538ec1061fb6d9ddf788e0362be54dbb1e6696ef9c724b7b4316c6a0a",
  "icon_always_on_lateral.png": "bc1f083148897dd2e3630c9e1985c4e5beca910711d7b7679f496053acc8d525",
  "icon_conditional.png": "dcf4bcc7b10bda85dcf944ac988460fa4290797ca383ce304f9ecd4916db1f9b",
  "icon_lane.png": "a49e6e7f3152506f69206c969bda3b78526ed1cb86d93876043675e9abff3b63",
  "icon_lateral_tune.png": "e3884aaea6b0370974bdb22713c106e1d116fb1c874ae6c5197ff50e07d4fc90",
  "icon_longitudinal_tune.png": "c3aa510a070595c97549cde1743163b9925a65339fa16ca75671ed220f430085",
  "icon_personality.png": "1504ef7844683999ba04917c04354aef6c635c288b71595cb2acb3e40dfe7828",
  "icon_quality_of_life.png": "ac9df3cdee92ae60efd00490f090151a6ec1ec6b999dbfef7e608ce5b2250c5a",
  "icon_speed_limit.png": "a3275fbdb3a54cf308e5450f3c41dd325b13d44aa10f80c2b38a668be269dd5b",
  "icon_speed_map.png": "69d99a7d7191f5718f2fb733584887aaca5c4e5aab6c06f669bd06521d234352",
}

MAPPING_097 = {
  # GAS / BRAKE (longitudinal_settings.cc)
  "AdvancedLongitudinalTune": "icon_advanced_longitudinal_tune.png", "ConditionalExperimental": "icon_conditional.png",
  "CurveSpeedController": "icon_speed_map.png", "CustomPersonalities": "icon_personality.png",
  "LongitudinalTune": "icon_longitudinal_tune.png", "QOLLongitudinal": "icon_quality_of_life.png",
  "SpeedLimitController": "icon_speed_limit.png",
  # STEERING (lateral_settings.cc)
  "AdvancedLateralTune": "icon_advanced_lateral_tune.png", "AlwaysOnLateral": "icon_always_on_lateral.png",
  "LaneChanges": "icon_lane.png", "LateralTune": "icon_lateral_tune.png", "QOLLateral": "icon_quality_of_life.png",
}


def test_icon_files_exist_byte_identical():
  assert si.ICON_DIR == ICONS
  assert set(SHA256) == set(MAPPING_097.values())
  for name, digest in SHA256.items():
    data = (ICONS / name).read_bytes()
    assert data[:8] == si.PNG_MAGIC and hashlib.sha256(data).hexdigest() == digest, name


def test_existing_menu_icons_are_kept():
  for name in ("menu_alerts.png", "menu_driving.png", "menu_navigation.png", "menu_system.png", "menu_theme.png",
               "menu_vehicle.png"):
    assert (ICONS / name).is_file(), name


def test_mapping_is_the_097_one():
  assert si.SECTION_ICONS == MAPPING_097
  for key in MAPPING_097:
    assert si.resolve_icon(key) == "bogpilot/" + MAPPING_097[key]


def test_rows_wired_to_sections():
  assert si.GAS_BRAKE_SECTIONS == {"advanced": "AdvancedLongitudinalTune", "conditional": "ConditionalExperimental",
                                   "personalities": "CustomPersonalities", "profiles": "LongitudinalTune",
                                   "qol": "QOLLongitudinal", "slc": "SpeedLimitController"}
  assert si.PAGE_SECTIONS == {"lane_changes": "LaneChanges", "steering_tuning": "LateralTune"}
  assert si.STEERING_SECTIONS == ("AdvancedLateralTune", "QOLLateral")


def test_steering_tuning_row_gets_the_lateral_tuning_icon_and_the_file_is_there():
  import hashlib
  assert si.resolve_icon(si.PAGE_SECTIONS["steering_tuning"]) == "bogpilot/icon_lateral_tune.png"
  path = si.ICON_DIR / "icon_lateral_tune.png"
  assert path.is_file() and path.read_bytes()[:8] == si.PNG_MAGIC
  assert hashlib.sha256(path.read_bytes()).hexdigest() == SHA256["icon_lateral_tune.png"]   # same bytes as 0.9.7


def test_no_icon_for_anything_else():
  for key in ("", "SteerRatio", "PauseLateralSpeed", "NudgelessLaneChange", "AggressivePersonalityProfile", None):
    assert si.resolve_icon(key) is None


def test_missing_or_unreadable_file_gives_no_icon(tmp_path, monkeypatch):
  monkeypatch.setattr(si, "ICON_DIR", tmp_path)
  assert si.resolve_icon("LaneChanges") is None
  (tmp_path / "icon_lane.png").write_bytes(b"GIF89a")
  assert si.resolve_icon("LaneChanges") is None
  monkeypatch.setattr(si, "ICON_DIR", tmp_path / "icon_lane.png")   # a file where the directory should be
  assert si.resolve_icon("LaneChanges") is None
