"""Pre-AP pedal cruise available + stalk engage mapping (NAP-aligned)."""
from __future__ import annotations

from pathlib import Path

from cereal import car
from openpilot.selfdrive.car.tesla.preap.cruise import (
  SPD_CTRL_CANCEL,
  SPD_CTRL_MAIN,
  pedal_cruise_available,
  remap_preap_pedal_button_type,
)

ROOT = Path(__file__).resolve().parents[4]
ButtonType = car.CarState.ButtonEvent.Type


def test_pedal_cruise_available_requires_ready_pedal():
  assert pedal_cruise_available(detected=True, calibrated=True, faulted=False) is True
  assert pedal_cruise_available(detected=False, calibrated=True) is False
  assert pedal_cruise_available(detected=True, calibrated=False) is False
  assert pedal_cruise_available(detected=True, calibrated=True, faulted=True) is False


def test_stalk_main_rwd_remaps_to_set_cruise():
  assert SPD_CTRL_MAIN == 2
  assert SPD_CTRL_CANCEL == 1
  assert remap_preap_pedal_button_type(ButtonType.resumeCruise) == ButtonType.setCruise
  assert remap_preap_pedal_button_type(ButtonType.cancel) == ButtonType.cancel
  assert remap_preap_pedal_button_type(ButtonType.accelCruise) == ButtonType.accelCruise


def test_carstate_source_gates_available_on_pedal_not_di():
  src = (ROOT / "selfdrive/car/tesla/carstate.py").read_text()
  assert "pedal_cruise_available" in src
  assert "preap_pedal_long" in src
  assert "remap_preap_pedal_button_type" in src
  # Pedal path must not be the only available= DI STANDBY line for preap long
  assert "openpilotLongitudinalControl" in src


def test_interface_source_pcm_enable_false_and_set_cruise():
  src = (ROOT / "selfdrive/car/tesla/interface.py").read_text()
  assert "pcm_enable=False" in src
  assert "ButtonType.setCruise" in src
  assert "TESLA_PREAP_MODELS" in src


def test_panda_preap_arms_on_stalk_rwd_not_di_cruise():
  """controls_allowed via pcm_cruise_check on SpdCtrl lever==2; DI_cruise unused."""
  h = (ROOT / "panda/board/safety/safety_tesla_preap.h").read_text()
  assert "msg->addr == 0x45U" in h or "msg->addr == 0x45U" in h.replace(" ", "")
  assert "lever == 2" in h
  assert "pcm_cruise_check(true)" in h
  assert "lever == 1" in h
  # No DI_cruiseState / 0x368 gate for controls_allowed arming
  assert "DI_cruise" not in h
