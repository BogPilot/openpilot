"""AP1 fingerprint / FW tables.

Sourcing order when fingerprint data conflicts (BogPilot rule):
  1. Ours (BogPilot chassis signature + CarModel / ForceFingerprint)
  2. Tinkla / earlytesla (CAN maps; they never published AP1 FW_VERSIONS rows)
  3. NotAutopilot (contrast / fill gaps only)

Pre-AP: data values may be taken from the third-party legacy port; never its
code. Tinkla Autosteer lockout is not ported. AP2/Raven FW live outside this
brand (see bogpilot-tesla 026cfb3 selfdrive/car/tesla/fingerprints.py).

AP1 Model S has no FW_VERSIONS row yet. Selection is:
  - CarModel / ForceFingerprint fallback in get_car, or
  - chassis CAN signature (values.match_ap1_chassis) when no FW match exists
    (wired in opendbc.car.car_helpers.fingerprint).
"""
from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.values import CAR  # noqa: F401

Ecu = CarParams.Ecu

FW_VERSIONS: dict = {}
