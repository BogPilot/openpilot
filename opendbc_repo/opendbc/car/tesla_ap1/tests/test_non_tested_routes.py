from opendbc.car.tesla_ap1.tests.non_tested_routes import NON_TESTED_CARS, extend_non_tested_cars
from opendbc.car.tesla_ap1.values import CAR
from opendbc.car.tests.routes import non_tested_cars, routes
from opendbc.car.values import PLATFORMS


def test_ap1_platforms_without_public_routes_are_skipped():
  extend_non_tested_cars()
  tested = {r.car_model for r in routes}
  for car in NON_TESTED_CARS:
    assert car not in tested
    assert car in non_tested_cars
  assert CAR.TESLA_AP1_MODELX in non_tested_cars
  missing = [p for p in PLATFORMS if p not in tested and p not in set(non_tested_cars)]
  assert missing == []
