"""PreAPEngagement: single pull, double pull (400 ms window), demote on re-pull, brake, cancel, openpilot-follow resets."""
from opendbc.car.tesla_ap1.preap.engagement import ENABLE_TIMEOUT_MS, WINDOW_MS, PreAPEngagement, preap_steer_drop


def step(e, t, pull=False, cancel=False, brake=False, op=False, double=False):
  return e.update(t, pull_edge=pull, cancel_edge=cancel, brake_pressed=brake, op_enabled=op, double_pull=double)


def test_window_is_the_400ms_cap():
  assert WINDOW_MS == 400


def test_single_pull_engages_lateral_and_long_together():
  e = PreAPEngagement()
  d = step(e, 0, pull=True)
  assert d.enable_request and d.engaged and d.long_wanted and not d.lat_only
  d = step(e, 10, op=True)
  assert d.engaged and d.long_wanted and not d.enable_request


def test_double_pull_first_pull_is_an_aol_lateral_intent_not_an_engagement():
  e = PreAPEngagement()
  d = step(e, 0, pull=True, double=True)
  assert d.aol_lat and not d.engaged and not d.enable_request and not d.long_wanted and not d.lat_only
  # never engages or goes long on its own, however long we wait
  for t in range(10, 3000, 10):
    d = step(e, t, op=False, double=True)
    assert d.aol_lat and not d.engaged and not d.long_wanted and not d.enable_request


def test_double_pull_second_pull_inside_window_engages_lateral_and_long():
  for gap in (50, 250, 399, 400):
    e = PreAPEngagement()
    step(e, 0, pull=True, double=True)
    d = step(e, gap, pull=True, double=True)
    assert d.engaged and d.long_wanted and d.enable_request and not d.lat_only and not d.aol_lat, gap
    d = step(e, gap + 10, op=True, double=True)
    assert d.engaged and d.long_wanted and not d.enable_request


def test_double_pull_second_pull_outside_window_stays_aol_lateral():
  e = PreAPEngagement()
  step(e, 0, pull=True, double=True)
  d = step(e, 401, pull=True, double=True)
  assert d.aol_lat and not d.engaged and not d.enable_request
  # but that pull opened a window: a third pull inside it engages
  d = step(e, 401 + 300, pull=True, double=True)
  assert d.engaged and d.long_wanted and d.enable_request


def test_repull_while_engaged_demotes_to_aol_lateral_then_second_pull_reengages():
  e = PreAPEngagement()
  step(e, 0, pull=True, double=True)
  step(e, 200, pull=True, double=True)
  step(e, 210, op=True, double=True)                          # engaged, openpilot enabled
  d = step(e, 2000, pull=True, op=True, double=True)          # re-pull: demote
  assert d.aol_lat and not d.engaged and not d.long_wanted
  d = step(e, 2010, op=False, double=True)                    # openpilot disengages; the lateral intent survives that
  assert d.aol_lat and not d.engaged
  d = step(e, 2250, pull=True, double=True)                   # second pull inside the window: engage again
  assert d.engaged and d.long_wanted and d.enable_request
  step(e, 2260, op=True, double=True)
  step(e, 5000, pull=True, op=True, double=True)              # demote again; a late pull does not re-engage
  d = step(e, 5500, pull=True, double=True)
  assert d.aol_lat and not d.engaged and not d.enable_request


def test_double_pull_brake_while_engaged_hands_lateral_to_aol():
  e = PreAPEngagement()
  step(e, 0, pull=True, double=True)
  step(e, 100, pull=True, double=True)
  step(e, 110, op=True, double=True)
  d = step(e, 200, brake=True, op=True, double=True)
  assert d.aol_lat and not d.engaged and not d.long_wanted and not d.lat_only


def test_aol_going_away_drops_the_lateral_intent_and_never_promotes_it():
  e = PreAPEngagement()
  step(e, 0, pull=True, double=True)
  d = step(e, 10, double=False)
  assert not d.aol_lat and not d.engaged and not d.enable_request
  # a pull afterwards is a normal single pull
  d = step(e, 20, pull=True, double=False)
  assert d.engaged and d.long_wanted and d.enable_request


def test_cancel_resets_both_modes():
  for dbl in (False, True):
    e = PreAPEngagement()
    step(e, 0, pull=True, double=dbl)
    d = step(e, 100, cancel=True, op=True, double=dbl)
    assert not d.engaged and not d.long_wanted and not d.lat_only and not d.aol_lat
    d = step(e, 200, pull=True, double=dbl)
    assert d.enable_request or d.aol_lat


def test_brake_drops_long_keeps_lateral():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  step(e, 10, op=True)
  d = step(e, 20, brake=True, op=True)
  assert d.engaged and d.lat_only and not d.long_wanted
  # a single-mode pull afterwards brings long back
  d = step(e, 1000, pull=True, op=True)
  assert d.long_wanted


def test_single_pull_while_the_brake_is_still_held_does_not_offer_long_back():
  # the panda blocks the pedal while the brake is pressed, so a pull with the foot still on the brake changes nothing
  e = PreAPEngagement()
  step(e, 0, pull=True)
  step(e, 10, op=True)
  d = step(e, 20, brake=True, op=True)
  assert d.engaged and d.lat_only and not d.long_wanted
  d = step(e, 500, pull=True, brake=True, op=True)             # pull, brake still held
  assert d.engaged and d.lat_only and not d.long_wanted and not d.enable_request
  d = step(e, 520, brake=False, op=True)                       # released: still lateral only until a pull
  assert d.engaged and d.lat_only and not d.long_wanted
  d = step(e, 900, pull=True, brake=False, op=True)            # pull with the brake free: long is back
  assert d.engaged and d.long_wanted and not d.lat_only and not d.enable_request


def test_follows_openpilot_down_after_it_was_enabled():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  step(e, 10, op=True)
  d = step(e, 20, op=False)
  assert not d.engaged
  # a fresh pull is a fresh engage (enable request again)
  assert step(e, 30, pull=True).enable_request


def test_enable_request_that_never_takes_resets():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  assert step(e, ENABLE_TIMEOUT_MS - 1, op=False).engaged
  assert not step(e, ENABLE_TIMEOUT_MS + 1, op=False).engaged


def test_double_mode_second_pull_can_land_before_openpilot_state_changes():
  # the second pull arrives while openpilot is still disabled (the first pull never enabled it): exactly one enable request
  e = PreAPEngagement()
  step(e, 0, pull=True, double=True)
  d = step(e, 30, pull=True, op=False, double=True)
  assert d.long_wanted and d.enable_request
  d = step(e, 40, op=False, double=True)
  assert d.engaged and not d.enable_request


def test_steer_drop_matches_the_panda_condition():
  # G1 (tesla_preap.h tesla_preap_epas_state): EAC_FAULT, hands on at level 3 or INHIBITED + error 6..9 drop controls
  assert preap_steer_drop(3)
  for status in (0, 1, 2, 4):
    assert not preap_steer_drop(status)
  for status in range(8):
    for hands in range(4):
      for err in range(16):
        want = status == 3 or hands >= 3 or (status == 0 and 6 <= err <= 9)
        assert preap_steer_drop(status, hands, err) == want, (status, hands, err)
