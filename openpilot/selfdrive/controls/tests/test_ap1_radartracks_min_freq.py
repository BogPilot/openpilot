"""AP1 Bosch radarTracks 6.69 Hz floor: fingerprints, rate, gaps, and error invalidation."""
import inspect

import pytest

from opendbc.car.structs import car as car_structs
from opendbc.car.tesla.values import CAR as TESLA_CAR
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.radar_interface import PREAP_MISSING_RADAR_FRAMES, RadarInterface
from opendbc.car.tesla_ap1.values import AP1_RADARTRACKS_MIN_FREQ_HZ, CAR, is_ap1_family
from opendbc.car.tesla_ap1 import toggles
from openpilot.cereal import messaging, log
from openpilot.cereal.services import SERVICE_LIST
from openpilot.selfdrive.controls.radard import RadarD, radar_tracks_min_freq
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD
from openpilot.selfdrive.selfdrived.events import Events, EventName


DT = 1.0 / 20.0  # radard polls modelV2 at 20 Hz
WARMUP_S = 60.0
HOLD_S = 120.0
RADAR_ALIVE_S = 10. / SERVICE_LIST['radarTracks'].frequency
STOCK_MIN = 8.0
STOCK_MAX = 24.0


def _msg(service, valid=True):
  msg = messaging.new_message(service)
  msg.valid = valid
  return msg


def make_sm(fingerprint):
  return messaging.SubMaster(['modelV2', 'carState', 'radarTracks'], poll='modelV2',
                             min_freq=radar_tracks_min_freq(fingerprint))


def drive(sm, t0, duration, radar_hz, *, radar_valid=True, dt=DT):
  """Feed modelV2+carState every 20 Hz tick; radarTracks quantized to those ticks."""
  next_radar = t0
  t = t0
  first_invalid_after = None
  last_ok = None
  seen_valid = False
  while t < t0 + duration - 1e-12:
    msgs = [_msg('modelV2'), _msg('carState')]
    if t + 1e-12 >= next_radar:
      msgs.append(_msg('radarTracks', valid=radar_valid))
      next_radar += 1.0 / radar_hz
    sm.update_msgs(t, msgs)
    last_ok = sm.all_checks()
    if last_ok:
      seen_valid = True
    elif seen_valid and first_invalid_after is None:
      first_invalid_after = t - t0
    t += dt
  return t, last_ok, first_invalid_after


def warmup(sm, t0=0.0, hz=12.0, duration=WARMUP_S):
  t, ok, inv = drive(sm, t0, duration, hz)
  assert ok, f"warmup at {hz} Hz ended invalid (ok={ok}, first_invalid={inv})"
  return t


# ---- fingerprints and tracker constants ----

AP1_FPS = (CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX, "TESLA_AP1_MODELS", "TESLA_AP1_MODELX")
OTHER_FPS = (
  CAR.TESLA_PREAP_MODELS,
  "TESLA_PREAP_MODELS",
  TESLA_CAR.TESLA_MODEL_3,
  TESLA_CAR.TESLA_MODEL_Y,
  TESLA_CAR.TESLA_MODEL_X,  # upstream Model X, not AP1
  "HONDA_CIVIC_2022",
)


@pytest.mark.parametrize("fp", AP1_FPS)
def test_ap1_family_gets_6_69hz_floor(fp):
  assert AP1_RADARTRACKS_MIN_FREQ_HZ == 6.69
  assert is_ap1_family(fp)
  assert radar_tracks_min_freq(fp) == {"radarTracks": AP1_RADARTRACKS_MIN_FREQ_HZ}
  sm = make_sm(fp)
  assert sm.freq_tracker['radarTracks'].min_freq == 6.69
  assert sm.freq_tracker['radarTracks'].max_freq == STOCK_MAX
  assert RADAR_ALIVE_S == 0.5


@pytest.mark.parametrize("fp", OTHER_FPS)
def test_preap_and_other_cars_stay_at_8hz(fp):
  assert not is_ap1_family(fp)
  assert radar_tracks_min_freq(fp) is None
  sm = make_sm(fp)
  assert sm.freq_tracker['radarTracks'].min_freq == STOCK_MIN
  assert sm.freq_tracker['radarTracks'].max_freq == STOCK_MAX
  assert RADAR_ALIVE_S == 0.5


# ---- sustained rates on AP1 (6.69 Hz floor) ----

@pytest.mark.parametrize("hz", [7.0, 7.5])
def test_ap1_7_and_75_hz_stay_valid(hz):
  sm = make_sm(CAR.TESLA_AP1_MODELS)
  t = warmup(sm)
  t, ok, inv = drive(sm, t, HOLD_S, hz)
  assert ok and inv is None, f"{hz} Hz should stay valid for {HOLD_S}s; first_invalid={inv}"


@pytest.mark.parametrize("hz", [6.0, 4.0, 2.0])
def test_ap1_6_4_and_2_hz_go_invalid_within_40s(hz):
  sm = make_sm(CAR.TESLA_AP1_MODELS)
  t = warmup(sm)
  t, ok, inv = drive(sm, t, 40.0, hz)
  assert inv is not None and inv <= 40.0, f"{hz} Hz should go invalid within 40s; first_invalid={inv}"
  assert not ok


# ---- gaps and dropouts; alive stays 0.5 s ----

def test_ap1_0_6s_gap_is_invalid_at_0_5s():
  sm = make_sm(CAR.TESLA_AP1_MODELS)
  t = warmup(sm)
  last = sm.recv_time['radarTracks']
  inv_at = None
  gap_t = t
  while gap_t < last + 0.6 - 1e-12:
    gap_t += DT
    sm.update_msgs(gap_t, [_msg('modelV2'), _msg('carState')])
    if not sm.all_checks() and inv_at is None:
      inv_at = gap_t - last
  # Alive is (cur_time - recv_time) < 0.5, sampled on 20 Hz ticks, so the first
  # fail is the first tick at or past 0.5 s (in [0.5, 0.5+DT]).
  assert inv_at is not None and 0.5 <= inv_at <= 0.5 + DT + 1e-9
  assert not sm.alive['radarTracks']
  assert not sm.all_checks()


def test_ap1_0_4s_gap_stays_valid():
  sm = make_sm(CAR.TESLA_AP1_MODELS)
  t = warmup(sm)
  last = sm.recv_time['radarTracks']
  gap_t = t
  while gap_t < last + 0.4 - 1e-12:
    gap_t += DT
    sm.update_msgs(gap_t, [_msg('modelV2'), _msg('carState')])
    assert sm.all_checks(), f"0.4s gap went invalid at {gap_t - last:.3f}s"
  assert sm.alive['radarTracks']


def test_ap1_stop_is_invalid_at_0_5s():
  sm = make_sm(CAR.TESLA_AP1_MODELS)
  t = warmup(sm)
  last = sm.recv_time['radarTracks']
  inv_at = None
  gap_t = t
  while gap_t < last + 1.0 - 1e-12:
    gap_t += DT
    sm.update_msgs(gap_t, [_msg('modelV2'), _msg('carState')])
    if not sm.all_checks() and inv_at is None:
      inv_at = gap_t - last
  assert inv_at is not None and 0.5 <= inv_at <= 0.5 + DT + 1e-9


# ---- canError / radarFault still invalidate, including through RadarD ----

def _radar_data(**errs):
  rr = car_structs.RadarData()
  for k, v in errs.items():
    setattr(rr.errors, k, v)
  return rr


def _healthy_then_invalid_tracks(sm, valid=False):
  t = warmup(sm)
  t, ok, _ = drive(sm, t, 1.0, 12.0, radar_valid=valid)
  return t, ok


@pytest.mark.parametrize("err_field", ["canError", "radarFault"])
def test_radartracks_invalid_fails_all_checks(err_field):
  sm = make_sm(CAR.TESLA_AP1_MODELS)
  t, ok = _healthy_then_invalid_tracks(sm, valid=False)
  assert ok is False
  assert sm.valid['radarTracks'] is False
  assert sm.all_checks() is False


@pytest.mark.parametrize("err_field", ["canError", "radarFault"])
def test_radard_copies_errors_and_clears_valid(err_field):
  sm = make_sm(CAR.TESLA_AP1_MODELS)
  t = warmup(sm)
  rr = _radar_data(**{err_field: True})
  # card publishes radarTracks.valid = not any(errors)
  t, ok, _ = drive(sm, t, 0.5, 12.0, radar_valid=False)
  rd = RadarD(0.05)
  rd.update(sm, rr)
  assert rd.radar_state_valid is False
  assert not ok
  assert getattr(rd.radar_state.radarErrors, err_field) is True


def test_selfdrived_still_maps_canerror_and_radarfault():
  src = inspect.getsource(SelfdriveD.update_events)
  assert "if self.sm['radarState'].radarErrors.canError:" in src
  assert "self.events.add(EventName.canError)" in src
  assert "self.events.add(EventName.radarFault)" in src
  # The canError branch is checked before the catch-all radarFault branch.
  assert src.index("radarErrors.canError") < src.index("EventName.radarFault")


@pytest.mark.parametrize("err_field,event", [("canError", EventName.canError),
                                             ("radarFault", EventName.radarFault)])
def test_selfdrived_event_mapping_for_radar_errors(err_field, event):
  # Mirror the update_events branch on a constructed radarState (the method itself
  # needs a full SelfdriveD). Mapping must stay: canError -> canError, other -> radarFault.
  events = Events()
  rs = log.RadarState.new_message()
  setattr(rs.radarErrors, err_field, True)
  if rs.radarErrors.canError:
    events.add(EventName.canError)
  elif rs.radarErrors.radarUnavailableTemporary:
    events.add(EventName.radarTempUnavailable)
  elif any(rs.radarErrors.to_dict().values()):
    events.add(EventName.radarFault)
  assert event in events.names


# ---- Pre-AP: 8.0 Hz unchanged; a silent radar is harmless, canError only once it has spoken (NAP radar_interface.py:176-177) ----

@pytest.fixture
def preap_radar_on(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path / "params_bogpilot")
  long_on = tmp_path / "long_on"
  long_on.write_text("0")
  monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (long_on,))
  params.set_bool(K.RADAR_ENABLED, True)
  return RadarInterface(CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False))


def test_preap_missing_radar_canerror_only_after_it_spoke(preap_radar_on):
  from opendbc.car.tesla_ap1.tests.test_preap_bosch_radar import frames
  sm = make_sm(CAR.TESLA_PREAP_MODELS)
  assert sm.freq_tracker['radarTracks'].min_freq == STOCK_MIN
  ri = preap_radar_on
  silent = [o for o in (ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES * 4)) if o is not None]
  assert len(silent) == PREAP_MISSING_RADAR_FRAMES * 4 // 5 and not any(any(o.errors.to_dict().values()) for o in silent)
  assert ri.update([(1_000_000_000, frames({}))]) is not None          # the radar speaks once
  outs = [ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES - 1)]
  assert all(o is None for o in outs)
  out = ri.update([])
  assert out is not None and out.errors.canError and not out.points
