"""Pre-AP (NotAutopilot-sourced) gates: AP1 unchanged, Pre-AP opt-in only.

Avoids importing CarInterface (pulls hardware/smbus) so M4P48 host pytest works.
Interface wiring is checked via source contracts + a lightweight params call
through safety_flags / cereal only.
"""
from pathlib import Path

from cereal import car
from openpilot.selfdrive.car.tesla.platform import (
  EarlyPlatformFixture, classify_ap1_chassis, classify_tesla_platform, long_control_allowed,
)
from openpilot.selfdrive.car.tesla.safety_flags import (
  dashcam_only_for_candidate, flags_for_candidate, flags_for_preap,
)
from openpilot.selfdrive.car.tesla.values import CANBUS, CAR, TeslaPlatform
from openpilot.selfdrive.car.tesla.preap.pedal_can import PedalCommandCounter, create_pedal_command, GAS_COMMAND_ID
from panda import Panda

ROOT = Path(__file__).resolve().parents[4]


def test_ap1_chassis_never_becomes_preap():
  addrs = {0x45, 0x2B9, 0x488, 0x370}
  assert classify_ap1_chassis(addrs) == TeslaPlatform.ap1_s
  assert classify_tesla_platform({CANBUS.chassis: {a: 1 for a in addrs}}) == TeslaPlatform.ap1_s


def test_preap_from_car_member_and_fixture():
  assert classify_tesla_platform(CAR.TESLA_PREAP_MODELS) == TeslaPlatform.preap
  assert classify_tesla_platform(EarlyPlatformFixture(TeslaPlatform.preap)) == TeslaPlatform.preap


def test_long_control_allowed_only_preap():
  assert long_control_allowed(TeslaPlatform.preap) is True
  assert long_control_allowed(TeslaPlatform.ap1_s) is False
  assert long_control_allowed(None) is False


def test_dashcam_and_ap1_flags_unchanged_for_ap1():
  assert dashcam_only_for_candidate(CAR.TESLA_AP1_MODELS) is False
  assert dashcam_only_for_candidate(CAR.TESLA_PREAP_MODELS) is False
  assert dashcam_only_for_candidate(CAR.TESLA_AP2_MODELS) is True
  flags = flags_for_candidate(CAR.TESLA_AP1_MODELS, {0: {0x45: 1, 0x2b9: 1, 0x488: 1}})
  assert flags == (Panda.FLAG_TESLA_AP1 | Panda.FLAG_TESLA_LONG_CONTROL,)


def test_preap_safety_flags_and_cereal_model():
  assert flags_for_preap(enable_pedal=True) == Panda.FLAG_TESLA_PREAP_ENABLE_PEDAL
  assert int(car.CarParams.SafetyModel.teslaPreap) == 32
  assert int(car.CarParams.SafetyModel.tesla) == 10
  assert Panda.SAFETY_TESLA_PREAP == 32
  assert Panda.SAFETY_TESLA == 10


def test_interface_source_uses_teslaPreap_for_preap_only():
  src = (ROOT / "selfdrive/car/tesla/interface.py").read_text()
  assert "SafetyModel.teslaPreap" in src
  assert "CAR.TESLA_PREAP_MODELS" in src
  # AP1 branch still names SafetyModel.tesla
  assert "SafetyModel.tesla," in src or "SafetyModel.tesla)" in src
  assert "flags_for_preap" in src


def test_ap1_safety_tesla_h_untouched_by_preap_symbols():
  ap1 = (ROOT / "panda/board/safety/safety_tesla.h").read_text()
  assert "0x551" not in ap1
  assert "TESLA_PREAP" not in ap1
  assert "tesla_preap" not in ap1


def test_pedal_command_enable_bit_and_checksum():
  c = PedalCommandCounter()
  addr, dat, bus = create_pedal_command(20.0, 1, c, pedal_can_bus=2)
  assert addr == GAS_COMMAND_ID
  assert bus == 2
  assert len(dat) == 6
  assert dat[4] & 0x80  # ENABLE
  addr2, dat2, _ = create_pedal_command(0.0, 0, c)
  assert (dat2[4] & 0x80) == 0
  assert dat2[0] == 0 and dat2[1] == 0
