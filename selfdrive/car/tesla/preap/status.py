"""Human status strings for Pre-AP pedal (UI + tests). BogPilot wording."""
from __future__ import annotations

from openpilot.selfdrive.car.tesla.preap.calib import (
  STATUS_NEEDS_CALIBRATION,
  STATUS_NOT_DETECTED,
  STATUS_READY,
  pedal_status,
)

# Short BogPilot menu / status line copy (Pre-AP only).
STATUS_LABELS = {
  STATUS_NOT_DETECTED: "Not detected",
  STATUS_NEEDS_CALIBRATION: "Needs calibration",
  STATUS_READY: "Ready",
}

STATUS_HELP = {
  STATUS_NOT_DETECTED: "No comma pedal reply on the selected CAN bus.",
  STATUS_NEEDS_CALIBRATION: "Pedal seen. Run Calibrate before longitudinal.",
  STATUS_READY: "Pedal detected and calibrated. Longitudinal can use it.",
}


def status_label(code: str | None = None) -> str:
  if code is None:
    code = pedal_status()
  return STATUS_LABELS.get(code, "Unknown")


def status_help(code: str | None = None) -> str:
  if code is None:
    code = pedal_status()
  return STATUS_HELP.get(code, "")
