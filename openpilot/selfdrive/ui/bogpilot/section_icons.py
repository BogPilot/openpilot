"""Section icons on the Gas / Brake and Steering pages, as in BogPilot 0.9.7.

The PNGs are the 0.9.7 frogpilot/assets/toggle_icons files, copied unchanged (same bytes, same names) into
selfdrive/assets/icons/bogpilot/. Only section rows (MANAGE / OPEN rows and the section switches) get an icon; the rows
inside a section do not. The mapping is the one 0.9.7 uses (longitudinal_settings.cc, lateral_settings.cc)."""
from pathlib import Path

ICON_SUBDIR = "bogpilot"          # under selfdrive/assets/icons
ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons" / ICON_SUBDIR
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

SECTION_ICONS = {
  # GAS / BRAKE (0.9.7 longitudinal_settings.cc)
  "AdvancedLongitudinalTune": "icon_advanced_longitudinal_tune.png",
  "ConditionalExperimental": "icon_conditional.png",
  "CurveSpeedController": "icon_speed_map.png",
  "CustomPersonalities": "icon_personality.png",
  "LongitudinalTune": "icon_longitudinal_tune.png",
  "QOLLongitudinal": "icon_quality_of_life.png",
  "SpeedLimitController": "icon_speed_limit.png",
  # STEERING (0.9.7 lateral_settings.cc)
  "AdvancedLateralTune": "icon_advanced_lateral_tune.png",
  "AlwaysOnLateral": "icon_always_on_lateral.png",
  "LaneChanges": "icon_lane.png",
  "LateralTune": "icon_lateral_tune.png",
  "QOLLateral": "icon_quality_of_life.png",
}


# Menu pages that stand for a 0.9.7 section row (the STEERING list opens Lane Changes as its own page).
PAGE_SECTIONS = {"lane_changes": "LaneChanges"}

# Gas / Brake top rows (phase3_gas_brake.root_entries keys) and the 0.9.7 section each one is.
GAS_BRAKE_SECTIONS = {
  "advanced": "AdvancedLongitudinalTune",
  "conditional": "ConditionalExperimental",
  "personalities": "CustomPersonalities",
  "profiles": "LongitudinalTune",
  "qol": "QOLLongitudinal",
  "slc": "SpeedLimitController",
}

# The section switches on the Steering Tuning page (no MANAGE row in this tree: the switch is the section row).
STEERING_SECTIONS = ("AdvancedLateralTune", "QOLLateral")


def resolve_icon(key: str) -> str | None:
  """The icon of section `key` as a path under selfdrive/assets/icons (what ListItem(icon=...) takes), or None when
  the section has no icon or its file is missing or unreadable. Never raises."""
  try:
    name = SECTION_ICONS.get(key)
    if not name:
      return None
    path = ICON_DIR / name
    with open(path, "rb") as f:
      if f.read(len(PNG_MAGIC)) != PNG_MAGIC:
        return None
    return f"{ICON_SUBDIR}/{name}"
  except Exception:
    return None


__all__ = ["GAS_BRAKE_SECTIONS", "ICON_DIR", "ICON_SUBDIR", "PAGE_SECTIONS", "SECTION_ICONS", "STEERING_SECTIONS",
           "resolve_icon"]
