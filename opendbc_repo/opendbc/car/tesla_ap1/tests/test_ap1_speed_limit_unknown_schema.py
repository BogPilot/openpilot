"""ap1SpeedLimitUnknown schema lines stay byte-identical to the AP1 set-speed change.

car.capnp @36 and log.capnp @109 must match the AP1 set-speed change (014bb965d).
Pre-AP fields stay at car.capnp @37 and log.capnp @110.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Byte-identical copies of the two lines at the AP1 set-speed change (014bb965d).
RC8_CAR_LINE = "  ap1SpeedLimitUnknown @36 :Bool;  # AP1 openpilot long: standstill, no dashboard speed limit and no stalk tap set, so no engage set (NO_ENTRY)"
RC8_LOG_LINE = "    ap1SpeedLimitUnknown @109;  # AP1 openpilot long: standstill engage with no known speed limit and no stalk tap set"
RC8_REV = "014bb965d"
CAR_REL = "opendbc_repo/opendbc/car/car.capnp"
LOG_REL = "openpilot/cereal/log.capnp"


def _worktree() -> Path:
  # tests / tesla_ap1 / car / opendbc / opendbc_repo / worktree
  return Path(__file__).resolve().parents[5]


def _field_lines(text: str, field: str) -> list[str]:
  return [ln for ln in text.splitlines() if field in ln]


def _git_show(wt: Path, rev: str, rel: str) -> str | None:
  if shutil.which("git") is None:
    return None
  try:
    r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=wt, capture_output=True, text=True, timeout=15)
  except (OSError, subprocess.TimeoutExpired):
    return None
  return r.stdout if r.returncode == 0 else None


def test_ap1_speed_limit_unknown_lines_match_the_set_speed_change():
  wt = _worktree()
  car_text = (wt / CAR_REL).read_text()
  log_text = (wt / LOG_REL).read_text()
  car_lines = _field_lines(car_text, "ap1SpeedLimitUnknown")
  log_lines = _field_lines(log_text, "ap1SpeedLimitUnknown")
  assert car_lines == [RC8_CAR_LINE]
  assert log_lines == [RC8_LOG_LINE]
  # rc9 Pre-AP fields stay in the next ordinals
  assert _field_lines(car_text, "preapFsmMode @37")
  assert _field_lines(log_text, "preapSteerOnly @110")

  for rel, expected in ((CAR_REL, RC8_CAR_LINE), (LOG_REL, RC8_LOG_LINE)):
    shown = _git_show(wt, RC8_REV, rel)
    if shown is None:
      continue
    got = _field_lines(shown, "ap1SpeedLimitUnknown")
    assert got == [expected], f"{RC8_REV}:{rel} drifted from the pinned line"
