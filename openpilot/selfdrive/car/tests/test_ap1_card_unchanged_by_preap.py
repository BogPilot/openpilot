"""AP1 card is unchanged by the Pre-AP card changes (0x560 host gate, refusal gating, fresh pandaStates gate). They are only built
for TESLA_PREAP_MODELS (card.py:190) and every call site is behind `self.preap_refusals is not None` (card.py:258, :283, :476)."""
import pathlib

from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.radar_interface import RadarInterface
from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import ap1_cp
from openpilot.selfdrive.car import card


def test_ap1_card_builds_none_of_the_preap_gates():
  CP = ap1_cp()
  c = card.Car(CarInterface(CP), RadarInterface(CP))
  assert c.preap_refusals is None and c.preap_vin_read is None and c.preap_safety_expects == []
  assert c.preap_560_dropped == 0 and c.preap_ps_seen_at is None


def test_every_preap_gate_call_is_behind_the_preap_check():
  src = (pathlib.Path(card.__file__)).read_text().splitlines()
  for name in ("self.preap_link_update(", "self.preap_gate_560("):
    calls = [i for i, line in enumerate(src) if name in line and "def " not in line]
    assert calls, name
    for i in calls:
      assert "if self.preap_refusals is not None:" in src[i - 1], (name, i + 1)
