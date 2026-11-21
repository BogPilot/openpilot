"""AP1 fingerprint / FW tables.

Sourcing order when fingerprint data conflicts (BogPilot rule):
  1. Ours (BogPilot chassis signature + CarModel / ForceFingerprint)
  2. Tinkla / earlytesla (CAN maps; they never published AP1 FW_VERSIONS rows)
  3. NotAutopilot (contrast / fill gaps only)

Pre-AP: every Pre-AP CAN ID, length and signal layout matches BogPilot 0.9.7
(opendbc/tesla_can.dbc @ 026cfb3), Tinkla / BogGyver or NotAutopilot; the Comma Pedal
frames follow Tinkla. Tinkla Autosteer lockout is not ported. AP2/Raven FW live outside
this brand (see bogpilot-tesla 026cfb3 selfdrive/car/tesla/fingerprints.py).

AP1 Model S and Model X have no FW_VERSIONS rows (Tinkla published no Model X FW).
This brand sends no UDS request of its own, so a row here could never match: the live
responses carry the upstream tesla brand. The one Model X EPS part number seen on a real
car (modelx_observed_data.MODELX_EPS_FW) is read from the live carFw by
modelx_fingerprint.fw_says_x instead.
Selection is detect_ap1_candidate in car_helpers.get_car, not FW:
  - CarModel / ForceFingerprint fallback in get_car, or
  - Model X marker or EPS firmware match, or the Model S chassis signature when neither is present.
"""
from opendbc.car.structs import CarParams
from opendbc.car.tesla_ap1.values import CAR  # noqa: F401

Ecu = CarParams.Ecu

FW_VERSIONS: dict = {}
