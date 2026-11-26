"""AP1 platforms with no public route in this tree.

The public car route list is kept byte-identical to openpilot v0.11.2.
These platforms are registered by BogPilot, so the public route test would
fail without a local skip list. Importing this module, or calling
extend_non_tested_cars(), appends them to the public non_tested_cars list.
"""
from opendbc.car.tesla_ap1.values import CAR

# No public route exists here for any AP1 / Pre-AP platform.
NON_TESTED_CARS = (
  CAR.TESLA_AP1_MODELS,
  CAR.TESLA_PREAP_MODELS,
  CAR.TESLA_AP1_MODELX,
)


def extend_non_tested_cars():
  from opendbc.car.tests.routes import non_tested_cars
  for car in NON_TESTED_CARS:
    if car not in non_tested_cars:
      non_tested_cars.append(car)


extend_non_tested_cars()
