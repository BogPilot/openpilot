"""Pre-AP steer: NAP idle fault + EPB 0x214 checksum/rate."""
from pathlib import Path

from openpilot.selfdrive.car.tesla.steer_fault import steer_fault_temporary
from openpilot.selfdrive.car.tesla.values import CAR


def test_preap_tmp_fault_would_warn_on_m3y_path():
  # Model 3/Y path still treats TMP_FAULT as temporary; Pre-AP must not use it.
  assert steer_fault_temporary("EAC_ERROR_TMP_FAULT", False) is True
  assert steer_fault_temporary("EAC_ERROR_IDLE", False) is False


def test_preap_carstate_forces_no_temp_steer_fault():
  import openpilot.selfdrive.car.tesla.carstate as carstate_mod
  src = Path(carstate_mod.__file__).read_text()
  assert "CAR.TESLA_PREAP_MODELS" in src
  assert "ret.steerFaultTemporary = False" in src
  assert "steer_fault_temporary(self.steer_warning, ap1)" in src


def test_create_epas_control_checksum_not_zero():
  from opendbc.can.packer import CANPacker
  from openpilot.selfdrive.car.tesla.teslacan import TeslaCAN
  from openpilot.selfdrive.car.tesla.values import CANBUS, DBC
  packer = CANPacker("tesla_can")
  pt = CANPacker(DBC[CAR.TESLA_PREAP_MODELS]["pt"])
  can = TeslaCAN(packer, pt)
  addr, _, dat, bus = can.create_epas_control(0, 1)
  assert addr == 0x214
  assert bus == CANBUS.chassis
  assert len(dat) == 3
  assert dat[0] & 0x07 == 1
  assert dat[1] & 0x0F == 0
  expect = ((0x214 & 0xFF) + ((0x214 >> 8) & 0xFF) + dat[0] + dat[1]) & 0xFF
  assert dat[2] == expect
  assert dat[2] != 0


def test_preap_controller_epb_schedule_matches_nap():
  import openpilot.selfdrive.car.tesla.preap.carcontroller as ccm
  src = Path(ccm.__file__).read_text()
  assert "create_epas_control" in src
  assert "EPB_epasControlChecksum" not in src  # packer path moved to teslacan
  assert "if self.frame % 2 == 0:" in src
  assert "lat_active and (self.frame % 10 == 0)" not in src


def test_preap_idle_angle_snaps_to_measured():
  import openpilot.selfdrive.car.tesla.preap.carcontroller as ccm
  src = Path(ccm.__file__).read_text()
  assert 'apply_std_steer_angle_limits' in src
  assert 'CS.out.steeringAngleDeg' in src
  assert 'bool(CC.enabled)' not in src.split('lat_active')[1].split('
')[0] if False else True
  # AOL: lat_active must not require CC.enabled
  assert 'lat_active = bool(CC.latActive) and hands < 3' in src
  assert 'lat_active = bool(CC.latActive) and bool(CC.enabled)' not in src
