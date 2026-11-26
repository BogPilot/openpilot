"""Pre-AP double pull rides Always On Lateral. The single seam between Pre-AP and Always On Lateral.

AOL stays fail-closed and out of runtime. This module only ASKS: it calls `selfdrive.car.ap1_runtime.preap_aol_available(CP)` if the AOL
lane has added it, and treats a missing function, an import error, an exception or any answer other than True as "AOL not available".
It never reads the AlwaysOnLateral param and never writes anything. `install(CP)` registers that answer as the provider that
opendbc's `preap.params.aol_available()` consults (card process and UI process each call it once with their CarParams).

Contract for the AOL lane (what `preap_aol_available(CP)` must mean): True only while the whole AOL activation policy passes for this
Pre-AP car AND the AOL core will steer when carState.bogpilot.preapAolLat is True (latActive without enabled, 0.9.7
`... or bogpilotCarState.pedalCruiseLatOnly`).
"""
from __future__ import annotations


def preap_aol_available(CP) -> bool:
  if getattr(CP, "carFingerprint", None) != "TESLA_PREAP_MODELS":
    return False
  try:
    from openpilot.selfdrive.car import ap1_runtime
    fn = getattr(ap1_runtime, "preap_aol_available", None)
    return callable(fn) and fn(CP) is True
  except Exception:
    return False


def install(CP) -> None:
  from opendbc.car.tesla_ap1.preap import params as preap_params
  preap_params.register_aol_provider(lambda: preap_aol_available(CP))
