"""pandad records the panda firmware version for the Pre-AP Vehicle screen. No panda needed."""
from pathlib import Path

from opendbc.car.tesla_ap1.preap import params as pp
from openpilot.selfdrive.pandad import pandad


def test_text_names_the_version_and_flags_a_panda_that_is_not_on_the_shipped_app():
  assert pandad.panda_firmware_text(b"DEV-328a9d92-DEBUG\x00".rstrip(b"\x00")) == "DEV-328a9d92-DEBUG"
  assert pandad.panda_firmware_text("v1.2") == "v1.2"
  assert pandad.panda_firmware_text("v1.2", up_to_date=False) == "v1.2 (out of date)"
  assert pandad.panda_firmware_text("v1.2", bootstub=True) == "v1.2 (bootloader only)"
  assert pandad.panda_firmware_text("  ") == "unknown"


def test_record_writes_the_file_backed_param_and_never_raises(tmp_path, monkeypatch):
  monkeypatch.setattr(pp, "_params_dir", Path(tmp_path))
  pandad.record_panda_firmware("DEV-1234abcd-RELEASE")
  assert pp.get_str(pp.PreApParamKeys.PANDA_FIRMWARE) == "DEV-1234abcd-RELEASE"
  pandad.record_panda_firmware("Not found")
  assert pp.get_str(pp.PreApParamKeys.PANDA_FIRMWARE) == "Not found"
  monkeypatch.setattr(pp, "_params_dir", Path(tmp_path) / "file" / "x")     # unwritable: must be swallowed
  (Path(tmp_path) / "file").write_text("not a directory")
  pandad.record_panda_firmware("anything")


def test_panda_ready_records_what_it_found(tmp_path, monkeypatch):
  monkeypatch.setattr(pp, "_params_dir", Path(tmp_path))

  class FakePanda:
    bootstub = False
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_version(self): return "DEV-cafe0001-DEBUG"
    def up_to_date(self): return False
    @staticmethod
    def wait_for_panda(*a, **k): return True

  monkeypatch.setattr(pandad, "Panda", FakePanda)
  assert pandad.panda_ready() is False                       # out of date: not ready ...
  assert pp.get_str(pp.PreApParamKeys.PANDA_FIRMWARE) == "DEV-cafe0001-DEBUG (out of date)"      # ... and the screen says why
  FakePanda.up_to_date = lambda self: True
  assert pandad.panda_ready() is True
  assert pp.get_str(pp.PreApParamKeys.PANDA_FIRMWARE) == "DEV-cafe0001-DEBUG"
  monkeypatch.setattr(FakePanda, "wait_for_panda", staticmethod(lambda *a, **k: False))
  assert pandad.panda_ready() is False
  assert pp.get_str(pp.PreApParamKeys.PANDA_FIRMWARE) == "Not found"
