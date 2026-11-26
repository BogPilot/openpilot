"""Pre-AP "Read radar VIN" button runtime: one manual, read-only F190 read of the VIN stored in a Bosch radar.

Starts ONLY when the driver presses Read Radar VIN in BogPilot > Vehicle Settings (request file TeslaRadarReadVin); there is
no automatic start (NAP's RadarDonorVinCommissioner start-on-0x501-vinValidity is not ported). Runs only with the panda radar
gateway on (flag 256) and only while disengaged; engaging (or the panda reporting controls allowed) stops it at once and
nothing more is sent. The panda independently allows only NAP's read-only 0x641 frames on bus 1 while disengaged.

The VIN read is stored ONLY in TeslaRadarDonorVin (a /data/params_bogpilot file, not an openpilot Params key, so it is never
in initData / rlog params, and it is excluded from settings backups and the settings dump). It is never written to log text
(carlog / cloudlog / print) and never put into the status text; the device UI may show it from the param. It is used as the donor VIN
from the next car start.

NAP reference: openpilot/selfdrive/car/card.py:207-220,338-362 and radar_donor_vin.py @ naponsp-alpha-prebuilt 7eb09d2a7.
NAP card.py:216 (status text "saved <VIN>") is deliberately not ported.
"""
from __future__ import annotations

from opendbc.car.can_definitions import CanData
from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys
from opendbc.car.tesla_ap1.preap.radar_donor_vin import (
  RADAR_UDS_BUS,
  RADAR_UDS_RX,
  RadarDonorVinReader,
  RadarDonorVinState,
)

STATUS_READING = "reading"
STATUS_SAVED = "saved, restart the car"
STATUS_ENGAGED = "disengage first"
STATUS_RADAR_OFF = "radar off"
STATUS_STOPPED = "stopped: engaged"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "read error"

# Backstop over the reader's own bounds (20 s for the read, then at most 3 s of cleanup): the button is free again after this.
MAX_READ_S = 30.0

_DONE = (RadarDonorVinState.COMPLETE, RadarDonorVinState.FAILED)


class RadarVinReadRunner:
  def __init__(self, radar_emulation: bool, params=preap_params):
    self.radar_emulation = bool(radar_emulation)
    self.params = params
    self.reader: RadarDonorVinReader | None = None
    self.stored = False
    self.started_at = 0.0

  def _status(self, text: str) -> None:
    self.params.set_str(PreApParamKeys.RADAR_VIN_READ_STATUS, text)

  def _finish(self, text: str) -> None:
    self.reader = None
    self._status(text)
    self.params.set_bool(PreApParamKeys.RADAR_READ_VIN, False)

  def fail_safe(self) -> None:
    """End the read after an internal error (called by card). Never raises; the error text is never stored or logged."""
    self.reader = None
    try:
      self._status(STATUS_ERROR)
      self.params.set_bool(PreApParamKeys.RADAR_READ_VIN, False)
    except Exception:
      pass

  def update(self, can_packets, now: float, engaged: bool) -> list:
    """can_packets: CanData-like items (address, dat, src) from this step. Returns 0x641 frames to send (bus 1)."""
    requested = self.params.get_bool(PreApParamKeys.RADAR_READ_VIN)
    if self.reader is None:
      if not requested:
        return []
      if not self.radar_emulation:
        self._finish(STATUS_RADAR_OFF)
        return []
      if engaged:
        self._finish(STATUS_ENGAGED)
        return []
      self.reader = RadarDonorVinReader()
      self.reader.start(now)
      self.stored = False
      self.started_at = now
      self._status(STATUS_READING)

    if engaged or not requested:
      # Engaged (or the request was cleared): stop at once, send nothing more. The panda refuses 0x641 while engaged anyway.
      self._finish(STATUS_STOPPED if engaged else "")
      return []

    if now - self.started_at > MAX_READ_S:
      self._finish(STATUS_TIMEOUT)
      return []

    # CanData or plain (address, dat, src) tuples, as can_capnp_to_list gives them.
    rx = [CanData(p[0], p[1], p[2]) for p in can_packets if p[0] == RADAR_UDS_RX and p[2] == RADAR_UDS_BUS]
    out = self.reader.update(rx, now)
    if out.vin and not self.stored:
      # Stored as soon as F190 decodes (NAP test_commissioner_stores_vin_as_soon_as_f190_decodes); kept out of log text.
      self.params.set_str(PreApParamKeys.RADAR_DONOR_VIN, out.vin)
      self.stored = True
    if out.state in _DONE:
      if self.stored:
        self._finish(STATUS_SAVED)
      else:
        self._finish(out.failure.name.lower().replace("_", " ") if out.failure else "failed")
    return [s for s in out.can_sends if s.src == RADAR_UDS_BUS]
