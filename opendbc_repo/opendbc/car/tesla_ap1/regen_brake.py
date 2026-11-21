"""Legacy Tesla comfort regen braking setting (RegenComfortBrake).

v2 (current): the setting turns on the add-only comfort layer in
openpilot/selfdrive/controls/lib/comfort_regen.py for AP1 Model S and Pre-AP.
That layer runs after the stock planner and can only ask for more braking
(final = min(stock, comfort)), gently (at most about 0.9 m/s^2), for a
radar-confirmed closing lead. Stock COMFORT_BRAKE (2.5 m/s^2), the stock lead
gap and MPC constraints are unchanged in both states.

v1 (retired): the setting used to lower the lead MPC comfort brake to
1.0 m/s^2, which widened the desired gap and produced hard braking at long
range when a lead braked briefly. ap1_comfort_brake() now always returns the
stock value; an existing on/off file keeps its meaning (on = comfort layer,
off = stock).

File-backed under /data/params_bogpilot/RegenComfortBrake (the July prebuilt
params_pyx.so cannot store new Tesla* keys). Absent file on AP1 Model S or
Pre-AP => on. Explicit 0/false/off => off. Other cars => always off.

Change on device:
  echo 0 > /data/params_bogpilot/RegenComfortBrake   # off (stock)
  echo 1 > /data/params_bogpilot/RegenComfortBrake   # on
then restart openpilot.

Not applied to CarParams, panda safety, or the ACCEL_MIN braking floor.
"""

from pathlib import Path

# Must match long_mpc.COMFORT_BRAKE. Kept here to avoid importing the MPC module
# (acados) from this lightweight toggle helper.
STOCK_COMFORT_BRAKE = 2.5


REGEN_COMFORT_DIR = Path("/data/params_bogpilot")
REGEN_COMFORT_PATH = REGEN_COMFORT_DIR / "RegenComfortBrake"
# Tests may override the path via this module attribute.
_regen_comfort_path = REGEN_COMFORT_PATH


def regen_comfort_brake_enabled(fingerprint: str | None, stored: str | bytes | None = None) -> bool:
  """Whether comfort regen braking (v2 comfort layer) is on.

  AP1 Model S and Pre-AP: default on when the file is absent. Other fingerprints are always off.
  `stored` overrides the file when not None (tests).
  """
  from opendbc.car.tesla_ap1.values import CAR
  if fingerprint not in (CAR.TESLA_AP1_MODELS, CAR.TESLA_PREAP_MODELS):
    return False
  if stored is not None:
    text = _as_text(stored)
  else:
    text = _read_regen_comfort_file()
  if text == "":
    return True
  if text in ("1", "true", "on"):
    return True
  if text in ("0", "false", "off"):
    return False
  return True


def ap1_comfort_brake(fingerprint: str | None, stored: str | bytes | None = None) -> float:
  """Comfort brake (m/s²) for the lead MPC. Always stock: the v1 gap widening is retired (see module doc)."""
  return STOCK_COMFORT_BRAKE


def set_regen_comfort_brake(enabled: bool, path: Path | None = None) -> None:
  """Write the file-backed RegenComfortBrake preference."""
  target = path if path is not None else _regen_comfort_path
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text("1" if enabled else "0")


def _read_regen_comfort_file() -> str:
  try:
    if _regen_comfort_path.is_file():
      return _regen_comfort_path.read_text(encoding="utf-8", errors="replace").strip()
  except OSError:
    pass
  return ""


def _as_text(stored: str | bytes | None) -> str:
  if stored is None:
    return ""
  if isinstance(stored, bytes):
    stored = stored.decode()
  return stored.strip()
