"""Gate checks for SAFETY_TESLA_PREAP vs AP1 safety_tesla.h (no firmware build)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREAP = (ROOT / "board/safety/safety_tesla_preap.h").read_text()
AP1 = (ROOT / "board/safety/safety_tesla.h").read_text()
SAFETY_H = (ROOT / "board/safety.h").read_text()


def test_preap_is_separate_file_and_registered():
  assert "tesla_preap_hooks" in PREAP
  assert "SAFETY_TESLA_PREAP" in SAFETY_H
  assert "safety_tesla_preap.h" in SAFETY_H
  assert "{SAFETY_TESLA_PREAP, &tesla_preap_hooks}" in SAFETY_H


def test_ap1_safety_file_has_no_preap_tx():
  assert "0x551" not in AP1
  assert "TESLA_PREAP" not in AP1
  assert "TESLA_FLAG_AP1" in AP1


def test_preap_tx_has_pedal_not_ibooster():
  assert "0x551" in PREAP
  assert "0x553" not in PREAP  # iBooster not in NA cut
  assert "0x488" in PREAP


def test_radar_tx_whitelist_behind_flag_default_off():
  assert "PREAP_FLAG_RADAR_EMULATION = 2" in PREAP
  assert "TESLA_PREAP_TX_MSGS_WITH_RADAR" in PREAP
  assert "0x560" in PREAP
  assert "preap_radar_emulation" in PREAP
  # default TX table (no radar) must not be the only table — with-radar is separate
  assert "if (preap_radar_emulation)" in PREAP
