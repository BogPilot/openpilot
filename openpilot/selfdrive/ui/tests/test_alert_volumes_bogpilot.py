"""Stream 7: FrogPilot alert volumes — engage/disengage must not ship muted."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# Allow running from either nested (C3X) or flat (C3) trees without install.
_HERE = Path(__file__).resolve()
for parent in _HERE.parents:
  if (parent / "selfdrive").is_dir() or (parent / "openpilot" / "selfdrive").is_dir():
    sys.path.insert(0, str(parent))
    break

try:
  from openpilot.selfdrive.ui.bogpilot.alert_volumes import (  # type: ignore
    AP1_VOLUME_PROFILE,
    FROGPILOT_VOLUME_DEFAULTS,
    is_muted_engage_disengage,
    resolve_alert_gain,
    values_equal,
    volume_fraction,
  )
except ImportError:
  from selfdrive.ui.bogpilot.alert_volumes import (  # type: ignore
    AP1_VOLUME_PROFILE,
    FROGPILOT_VOLUME_DEFAULTS,
    is_muted_engage_disengage,
    resolve_alert_gain,
    values_equal,
    volume_fraction,
  )


def test_frogpilot_defaults_audible():
  assert FROGPILOT_VOLUME_DEFAULTS["AlertVolumeControl"] == "0"
  assert FROGPILOT_VOLUME_DEFAULTS["EngageVolume"] == "101"
  assert FROGPILOT_VOLUME_DEFAULTS["DisengageVolume"] == "101"
  assert not is_muted_engage_disengage(FROGPILOT_VOLUME_DEFAULTS)


def test_ap1_profile_matches_frogpilot_not_legacy_mute():
  assert AP1_VOLUME_PROFILE == FROGPILOT_VOLUME_DEFAULTS
  assert not is_muted_engage_disengage(AP1_VOLUME_PROFILE)
  # Explicitly reject the old AP1 mute shape
  legacy_mute = {
    "AlertVolumeControl": "1",
    "EngageVolume": "0.000000",
    "DisengageVolume": "0.000000",
  }
  assert is_muted_engage_disengage(legacy_mute)
  assert AP1_VOLUME_PROFILE != legacy_mute
  assert not values_equal(AP1_VOLUME_PROFILE["EngageVolume"], 0)
  assert not values_equal(AP1_VOLUME_PROFILE["DisengageVolume"], 0)


def test_resolve_gain_controller_off_uses_ambient():
  ambient = 0.42
  assert resolve_alert_gain(alert_volume_control=False, percent=0, ambient=ambient) == ambient
  assert resolve_alert_gain(alert_volume_control=False, percent=101, ambient=ambient) == ambient


def test_resolve_gain_auto_and_fixed():
  ambient = 0.55
  assert resolve_alert_gain(alert_volume_control=True, percent=101, ambient=ambient) == ambient
  assert resolve_alert_gain(alert_volume_control=True, percent=0, ambient=ambient) == 0.0
  assert resolve_alert_gain(alert_volume_control=True, percent=50, ambient=ambient) == pytest.approx(0.5)


def test_warning_immediate_floor():
  assert volume_fraction(5, key="WarningImmediateVolume") == pytest.approx(0.25)
  assert volume_fraction(80, key="WarningImmediateVolume") == pytest.approx(0.80)
