"""Tesla AP1 treats qcomgpsd as optional for processNotRunning (selfdrived); every other car keeps it essential."""
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.selfdrived.selfdrived import AP1_OPTIONAL_PROCESSES, NON_ESSENTIAL_PROCESSES, ignored_processes


def cp(brand):
  return SimpleNamespace(brand=brand)


def test_ap1_family_ignores_qcomgpsd_in_addition_to_the_bogpilot_helpers():
  assert AP1_OPTIONAL_PROCESSES == frozenset({"qcomgpsd"})
  assert ignored_processes(cp("tesla_ap1")) == NON_ESSENTIAL_PROCESSES | {"qcomgpsd"}


@pytest.mark.parametrize("brand", ["tesla", "toyota", "honda", "hyundai", "mock"])
def test_other_brands_keep_qcomgpsd_essential(brand):
  assert ignored_processes(cp(brand)) == NON_ESSENTIAL_PROCESSES
  assert "qcomgpsd" not in ignored_processes(cp(brand))


def test_only_gps_is_added_for_ap1():
  # camera, model, controls and safety processes must still raise processNotRunning on AP1
  extra = ignored_processes(cp("tesla_ap1")) - NON_ESSENTIAL_PROCESSES
  assert extra == {"qcomgpsd"}


def test_selfdrived_filters_the_not_running_set_through_the_brand_gate():
  from pathlib import Path
  import openpilot.selfdrive.selfdrived.selfdrived as sd
  src = Path(sd.__file__).read_text()
  assert "p.name not in ignored_processes(self.CP)" in src
