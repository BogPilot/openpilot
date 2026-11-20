"""PreAPEngagement (NAP-style double pull): first pull steering only, second pull < 400 ms = speed control, brake / re-pull demote,
cancel / gear / door / stale / EPAS drop reset, openpilot-follow resets. The full transition table is in test_preap_nap_fsm.py."""
from opendbc.car.tesla_ap1.preap import engagement as eng
from opendbc.car.tesla_ap1.preap.engagement import ENABLE_TIMEOUT_MS, WINDOW_MS, Mode, PreAPEngagement, preap_steer_drop


def step(e, t, pull=False, cancel=False, brake=False, op=False, pedal=True, gear_d=True, door_open=False, epas_drop=False,
         stale=False, di=False, v_ego=10.0, long_allowed=True, speed_block=False, cancel_tx_ms=0, gas=False, pedal_bus_ok=True):
  return e.update(t, pull_edge=pull, cancel_edge=cancel, brake_pressed=brake, op_enabled=op, pedal=pedal, gear_d=gear_d,
                  door_open=door_open, epas_drop=epas_drop, stale=stale, di_engaged=di, v_ego=v_ego, long_allowed=long_allowed,
                  speed_block=speed_block, cancel_tx_ms=cancel_tx_ms, gas_pressed=gas, pedal_bus_ok=pedal_bus_ok)


def full(e, t=0, **kw):
  step(e, t, pull=True, **kw)
  step(e, t + 10, op=True, **kw)
  return step(e, t + 250, pull=True, op=True, **kw)


def test_window_is_the_400ms_cap():
  assert WINDOW_MS == 400


def test_first_pull_engages_steering_only():
  e = PreAPEngagement()
  d = step(e, 0, pull=True)
  assert d.enable_request and d.engaged and d.lat_only and not d.long_wanted and d.mode == Mode.LAT_PENDING
  d = step(e, 10, op=True)
  assert d.engaged and d.lat_only and not d.enable_request


def test_second_pull_inside_window_is_full():
  e = PreAPEngagement()
  d = full(e)
  assert d.mode == Mode.FULL and d.long_wanted and not d.lat_only and d.full_edge and not d.enable_request


def test_window_expiry_stays_steering_only():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  d = step(e, WINDOW_MS, op=True)
  assert d.mode == Mode.LAT_ONLY and d.lat_only


def test_repull_in_full_demotes_then_second_pull_reenters():
  e = PreAPEngagement()
  full(e)
  d = step(e, 2000, pull=True, op=True)
  assert d.mode == Mode.LAT_PENDING and d.lat_only
  d = step(e, 2300, pull=True, op=True)
  assert d.mode == Mode.FULL and d.full_edge


def test_brake_in_full_drops_speed_keeps_steering_and_one_pull_does_not_restore():
  e = PreAPEngagement()
  full(e)
  d = step(e, 1000, brake=True, op=True)
  assert d.mode == Mode.LAT_ONLY and d.engaged and d.lat_only
  d = step(e, 2000, pull=True, op=True)
  assert d.mode == Mode.LAT_PENDING and not d.long_wanted
  d = step(e, 3000, op=True)
  assert d.mode == Mode.LAT_ONLY


def test_double_pull_while_brake_held_stays_steering_only():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  d = step(e, 200, pull=True, op=True, brake=True)
  assert d.mode == Mode.LAT_ONLY and not d.long_wanted


def test_cancel_gear_door_stale_reset():
  for kw in ({"cancel": True}, {"gear_d": False}, {"door_open": True}, {"stale": True}):
    e = PreAPEngagement()
    full(e)
    d = step(e, 1000, op=True, **kw)
    assert d.mode == Mode.OFF and not d.engaged, kw


def test_epas_drop_locks_out_until_a_new_pull():
  e = PreAPEngagement()
  full(e)
  d = step(e, 1000, op=True, epas_drop=True)
  assert d.mode == Mode.LOCKOUT and not d.engaged
  d = step(e, 1010, pull=True, epas_drop=True)    # drop and pull in one step: the drop wins
  assert d.mode == Mode.LOCKOUT
  d = step(e, 1100, pull=True)
  assert d.mode == Mode.LAT_PENDING and d.enable_request


def test_follows_openpilot_down_after_it_was_enabled():
  e = PreAPEngagement()
  full(e)
  d = step(e, 1000, op=False)
  assert d.mode == Mode.OFF


def test_enable_request_that_never_takes_resets():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  assert step(e, ENABLE_TIMEOUT_MS, op=False).engaged
  assert not step(e, ENABLE_TIMEOUT_MS + 1, op=False).engaged


def test_unknown_inputs_fail_closed():
  e = PreAPEngagement()
  assert step(e, 0, pull=True, gear_d=None).mode == Mode.OFF
  assert step(e, 100, pull=True, door_open=None).mode == Mode.OFF
  step(e, 200, pull=True)
  d = step(e, 300, pull=True, op=True, long_allowed=None)
  assert d.mode == Mode.LAT_ONLY


def test_standstill_option_a_refuses_full(monkeypatch):
  monkeypatch.setattr(eng, "PREAP_FULL_AT_STANDSTILL", False)
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0)
  d = step(e, 200, pull=True, op=True, v_ego=0.0)
  assert d.mode == Mode.LAT_ONLY and d.standstill_refused and not d.standstill_hold


def test_standstill_default_b_holds_until_the_accelerator_release_while_moving():
  assert eng.PREAP_FULL_AT_STANDSTILL is True
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0)
  d = step(e, 200, pull=True, op=True, v_ego=0.0)
  assert d.mode == Mode.FULL and d.standstill_hold and d.full_edge and d.capture_edge and d.capture_from_stop, "t1401: from-stop set on the pull"
  assert step(e, 300, op=True, v_ego=0.0).standstill_hold
  assert step(e, 400, op=True, v_ego=0.0, gas=True).standstill_hold, "still holding while the accelerator is pressed"
  d = step(e, 500, op=True, v_ego=0.0)
  assert d.standstill_hold and not d.capture_edge, "released while still stopped: keep holding, capture nothing"
  step(e, 600, op=True, v_ego=0.5, gas=True)
  d = step(e, 700, op=True, v_ego=1.0)
  assert d.mode == Mode.FULL and not d.standstill_hold and not d.capture_edge, "t1401: released while moving ends the hold, set kept"
  assert not step(e, 800, op=True, v_ego=1.0).capture_edge


def test_moving_double_pull_captures_on_the_full_edge():
  e = PreAPEngagement()
  step(e, 0, pull=True)
  d = step(e, 200, pull=True, op=True)
  assert d.mode == Mode.FULL and d.capture_edge and not d.standstill_hold


def test_standstill_unknown_speed_is_refused_not_held():
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=None)
  d = step(e, 200, pull=True, op=True, v_ego=None)
  assert d.mode == Mode.LAT_ONLY and not d.standstill_hold


def test_brake_during_standstill_hold_drops_to_steering_only():
  e = PreAPEngagement()
  step(e, 0, pull=True, v_ego=0.0)
  step(e, 200, pull=True, op=True, v_ego=0.0)
  d = step(e, 300, op=True, v_ego=0.0, brake=True)
  assert d.mode == Mode.LAT_ONLY and d.lat_only and not d.standstill_hold


def test_speed_block_in_full_demotes_with_flag():
  e = PreAPEngagement()
  full(e)
  d = step(e, 1000, op=True, speed_block=True)
  assert d.mode == Mode.LAT_ONLY and d.speed_blocked
  step(e, 2000, pull=True, op=True)
  d = step(e, 2200, pull=True, op=True)
  assert d.mode == Mode.FULL and not d.speed_blocked


def test_aol_lat_is_retired():
  e = PreAPEngagement()
  assert not step(e, 0, pull=True).aol_lat
  assert not step(e, 100, op=True).aol_lat


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


def test_second_pull_without_a_latched_bus_stays_steering_only():
  e = PreAPEngagement()
  d = full(e, pedal_bus_ok=False)
  assert d.mode == Mode.LAT_ONLY and d.lat_only and not d.long_wanted


def test_bus_not_ok_in_full_demotes_and_stays_steering_only():
  e = PreAPEngagement()
  assert full(e).mode == Mode.FULL
  d = step(e, 300, op=True, pedal_bus_ok=False)
  assert d.mode == Mode.LAT_ONLY and d.lat_only and d.speed_blocked
