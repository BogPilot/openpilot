"""The Pre-AP radar donor VIN never reaches uploaded logs, crash reports, backups or the settings dump.

TeslaRadarDonorVin lives in the /data/params_bogpilot file store (opendbc tesla_ap1/preap/params.py PARAMS_DIR), not in the
openpilot Params store. loggerd's initData params snapshot (system/loggerd/logger.cc) only reads the Params store
(params.readAll() of PARAMS_ROOT), so the donor VIN can never land in initData / rlog params; it is in no Params key table
(the equivalent of DONT_LOG, and stronger: not even the key name is logged). Settings backups list their file keys explicitly
and leave it out. Synthetic VIN only.
"""
import pathlib
import re

from opendbc.car.tesla_ap1.preap import params as preap_params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys

ROOT = pathlib.Path(__file__).resolve().parents[3]          # openpilot/
VIN_KEYS = (PreApParamKeys.RADAR_DONOR_VIN, PreApParamKeys.RADAR_VIN_READ_STATUS, PreApParamKeys.RADAR_READ_VIN)


def test_donor_vin_is_a_file_store_key_not_a_params_key():
  assert str(preap_params.PARAMS_DIR) == "/data/params_bogpilot"
  for header in ("common/params_keys.h", "common/params_keys_bogpilot.h"):
    text = (ROOT / header).read_text()
    for key in VIN_KEYS:
      assert f'"{key}"' not in text, (header, key)
  from openpilot.common import bogpilot_params
  flat = repr(bogpilot_params.BOGPILOT_PARAMS) + repr(bogpilot_params.BOGPILOT_STOCK_KEY_DEFAULTS)
  for key in VIN_KEYS:
    assert key not in flat


def test_initdata_snapshot_reads_only_the_params_store():
  logger = (ROOT / "system/loggerd/logger.cc").read_text()
  assert "params.readAll()" in logger
  assert "params_bogpilot" not in logger


def test_donor_vin_not_backed_up_or_dumped():
  from openpilot.system.bogpilot import settings_backup
  for key in VIN_KEYS:
    assert key not in settings_backup.FILE_KEYS
    assert key not in settings_backup.SETTING_KEYS
  dump = (ROOT.parent / "tools/bogpilot/settings_row_dump.py").read_text()
  assert "TeslaRadarDonorVin" not in dump


def test_no_logging_of_the_vin_in_runtime_paths():
  card = (ROOT / "selfdrive/car/card.py").read_text()
  block = card[card.index("preap_vin_read"):]
  assert not re.search(r"(cloudlog|carlog|print)\([^)]*(vin|VIN)", block)
  ui = (ROOT / "selfdrive/ui/bogpilot/phase2_vehicle.py").read_text()
  assert not re.search(r"(cloudlog|carlog|print)\([^)]*(vin|VIN)", ui)
