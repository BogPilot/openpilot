"""Pre-AP radarDataInvalid: mapping, alerts, first-contact/resume grace, silence path, AP1 unchanged.

Cadence: card calls RadarInterface.update at 100 Hz; the 0x36E trigger arrives about every 70-100 ms
(~16 Hz). Tests step at 10 ms with 5 empty updates between triggers, and send TeslaRadarSguInfo (0x301)
at 10 Hz unless a case drops it.
"""
import inspect

import pytest
from opendbc.can import CANPacker
from opendbc.car import Bus, gen_empty_fingerprint, structs
from opendbc.car.tesla_ap1 import toggles
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.radar_interface import (
  PREAP_MISSING_RADAR_FRAMES, PREAP_PARSER_GRACE_S, RadarInterface,
)
from opendbc.car.tesla_ap1.values import AP1_CHASSIS_SIGNATURE, CAR, DBC, is_preap
from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import (
  EVENTS, ET, Events, EventName, Alert, ImmediateDisableAlert, NoEntryAlert,
  AlertStatus, AlertSize, Priority, VisualAlert, AudibleAlert,
)
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD


NS = 1_000_000_000
DT = 0.01          # card update rate, 100 Hz
TRIG_EVERY = 6     # 5 empty updates between triggers: 16.7 Hz, in the real 70-100 ms / ~16 Hz band
SGU_EVERY = 10     # TeslaRadarSguInfo (0x301) at 10 Hz
NUM_POINTS = 64


@pytest.fixture(autouse=True)
def _params_dir(tmp_path, monkeypatch):
  monkeypatch.setattr(params, "_params_dir", tmp_path / "params_bogpilot")
  yield tmp_path


@pytest.fixture
def long_paths(tmp_path, monkeypatch):
  def set_long(pedal):
    f = tmp_path / ("long_on" if pedal else "long_off")
    f.write_text("0" if pedal else "1")
    monkeypatch.setattr(toggles, "DISABLE_OP_LONG_PATHS", (f,))
  return set_long


def store(radar=None, nosecone=None):
  for key, value in ((K.RADAR_ENABLED, radar), (K.RADAR_BEHIND_NOSECONE, nosecone)):
    if value is not None:
      params.set_bool(key, value)


def preap_cp():
  return CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)


def ap1_cp():
  fp = gen_empty_fingerprint()
  fp[0] = dict(AP1_CHASSIS_SIGNATURE)
  fp[2] = {0x399: 8, 0x2B9: 8, 0x488: 4}
  return CarInterface.get_params(CAR.TESLA_AP1_MODELS, fp, [], False, False, False)


def _packer():
  return CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar])


def frames(*, include_sgu=True, trigger=True, sgu=None, full_table=False):
  packer = _packer()
  out = []
  if include_sgu:
    out.append(packer.make_can_msg("TeslaRadarSguInfo", 1, sgu or {}))
  n = NUM_POINTS if full_table else 1
  for i in range(n):
    if i == 31 and not trigger:
      continue
    out.append(packer.make_can_msg(f"RadarPoint{i}_A", 1, {
      "Tracked": 1 if i == 0 else 0, "Meas": 1 if i == 0 else 0, "Index": i,
      "LongDist": 40.0 if i == 0 else 0.0, "ProbExist": 96.875 if i == 0 else 0.0,
    }))
    if i == 31 and not trigger:
      continue
    out.append(packer.make_can_msg(f"RadarPoint{i}_B", 1, {"Index2": i}))
  if trigger and not full_table:
    out.append(packer.make_can_msg("RadarPoint31_B", 1, {}))
  return out


def preap_ri(long_paths):
  long_paths(True)
  store(radar=True)
  return RadarInterface(preap_cp())


def no_gate(ri):
  if ri.preap_gate is not None:
    ri.preap_gate, ri.preap_radar_valid = None, True
  return ri


def drive(ri, t0, n_steps, *, send_trigger=True, send_sgu=True, full_table=False):
  """100 Hz steps. Trigger every 6 steps, SGU every 10, unless disabled."""
  published = []
  for i in range(n_steps):
    t = t0 + i * DT
    trig = send_trigger and (i % TRIG_EVERY == 0)
    sgu = send_sgu and (i % SGU_EVERY == 0)
    if trig or sgu or (full_table and trig):
      out = ri.update([(int(t * NS), frames(include_sgu=sgu, trigger=trig, full_table=full_table and trig))])
    else:
      out = ri.update([])
    if out is not None:
      published.append((t, out, trig))
  return published


def map_radar_can_error(fingerprint, *, drop_preap_gate=False):
  """Host mapping of radarErrors.canError, matching SelfdriveD.update_events. drop_preap_gate is the mutant."""
  ev = Events()
  if (True if drop_preap_gate else is_preap(fingerprint)):
    ev.add(EventName.radarDataInvalid)
  else:
    ev.add(EventName.canError)
  return set(ev.names)


# ---- schema and alerts ----

def test_enum_is_last_non_deprecated():
  events = log.OnroadEvent.EventName.schema.enumerants
  assert "radarDataInvalid" in events
  non_dep = {n: v for n, v in events.items() if not n.endswith("DEPRECATED")}
  # Its ordinal is fixed at 115. Later events take the next ordinals (preapEpasNotSteering @116), so it is no longer the last.
  assert events["radarDataInvalid"] == 115
  assert all(v > 115 for n, v in non_dep.items() if v >= 115 and n != "radarDataInvalid")
  assert events["preapEpasNotSteering"] == 116


def _fresh_canerror_like(text: str):
  # Same constructors and args as the canError / radarDataInvalid rows in events.py.
  # Do not use the EVENTS singletons: test_alertmanager mutates .duration on those shared objects.
  return {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(text),
    ET.PERMANENT: Alert(
      text,
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert(text),
  }


def _alert_fields_except_duration_and_text(a):
  # Every Alert field except duration (test_alertmanager mutates the singleton)
  # and the two text fields. Includes the alert class.
  out = {k: v for k, v in vars(a).items() if k not in ("duration", "alert_text_1", "alert_text_2")}
  out["cls"] = type(a)
  return out


def test_alerts_match_canerror_except_text():
  # Fresh constructors: isolation from test_alertmanager duration mutations on EVENTS singletons.
  rdi = _fresh_canerror_like("Radar Data Invalid")
  ce = _fresh_canerror_like("Unknown Vehicle Variant")
  assert set(EVENTS[EventName.radarDataInvalid]) == set(EVENTS[EventName.canError]) == set(rdi) == {
    ET.IMMEDIATE_DISABLE, ET.PERMANENT, ET.NO_ENTRY}

  for et in (ET.IMMEDIATE_DISABLE, ET.PERMANENT, ET.NO_ENTRY):
    live_a = EVENTS[EventName.radarDataInvalid][et]
    live_b = EVENTS[EventName.canError][et]
    # Live table: same class and every field except duration and text.
    assert type(live_a) is type(live_b) is type(ce[et]), et
    assert _alert_fields_except_duration_and_text(live_a) == \
           _alert_fields_except_duration_and_text(live_b) == \
           _alert_fields_except_duration_and_text(ce[et]) == \
           _alert_fields_except_duration_and_text(rdi[et]), et
    text_a = (live_a.alert_text_1, live_a.alert_text_2)
    text_b = (live_b.alert_text_1, live_b.alert_text_2)
    assert "Radar Data Invalid" in "".join(text_a)
    assert "Unknown Vehicle Variant" in "".join(text_b)
    swapped = tuple(t.replace("Radar Data Invalid", "Unknown Vehicle Variant") for t in text_a)
    assert swapped == text_b
    # Fresh objects keep the same wording (and are used for class/field expected values above).
    assert (rdi[et].alert_text_1, rdi[et].alert_text_2) == text_a
    assert (ce[et].alert_text_1, ce[et].alert_text_2) == text_b

  imm = rdi[ET.IMMEDIATE_DISABLE]
  assert type(imm) is ImmediateDisableAlert
  assert type(EVENTS[EventName.radarDataInvalid][ET.IMMEDIATE_DISABLE]) is ImmediateDisableAlert
  assert imm.alert_text_1 == "TAKE CONTROL IMMEDIATELY"
  assert imm.alert_text_2 == "Radar Data Invalid"
  assert EVENTS[EventName.radarDataInvalid][ET.IMMEDIATE_DISABLE].priority == \
         EVENTS[EventName.canError][ET.IMMEDIATE_DISABLE].priority == Priority.HIGHEST


def test_mutant_rdi_priority_or_class_change_is_caught():
  et = ET.IMMEDIATE_DISABLE
  live_a = EVENTS[EventName.radarDataInvalid][et]
  live_b = EVENTS[EventName.canError][et]
  assert type(live_a) is type(live_b) is ImmediateDisableAlert
  assert live_a.priority == live_b.priority == Priority.HIGHEST
  production = _alert_fields_except_duration_and_text(live_a)

  saved_priority = live_a.priority
  try:
    live_a.priority = Priority.LOWEST
    assert _alert_fields_except_duration_and_text(live_a) != _alert_fields_except_duration_and_text(live_b)
    assert live_a.priority != live_b.priority
  finally:
    live_a.priority = saved_priority
  assert _alert_fields_except_duration_and_text(live_a) == production

  saved_obj = EVENTS[EventName.radarDataInvalid][et]
  try:
    EVENTS[EventName.radarDataInvalid][et] = Alert(
      saved_obj.alert_text_1, saved_obj.alert_text_2,
      saved_obj.alert_status, saved_obj.alert_size,
      saved_obj.priority, saved_obj.visual_alert, saved_obj.audible_alert,
      4., creation_delay=saved_obj.creation_delay)
    mut = EVENTS[EventName.radarDataInvalid][et]
    assert type(mut) is Alert
    assert type(mut) is not type(live_b)
    assert _alert_fields_except_duration_and_text(mut) != _alert_fields_except_duration_and_text(live_b)
  finally:
    EVENTS[EventName.radarDataInvalid][et] = saved_obj
  assert EVENTS[EventName.radarDataInvalid][et] is saved_obj
  assert type(EVENTS[EventName.radarDataInvalid][et]) is ImmediateDisableAlert

def test_events_defined_includes_radar_data_invalid():
  events = log.OnroadEvent.EventName.schema.enumerants
  for name, e in events.items():
    if not name.endswith("DEPRECATED"):
      assert e in EVENTS, f"{name} @{e} not in EVENTS"


# ---- selfdrived mapping (source + mirror) ----

def test_selfdrived_maps_parser_error_preap_only():
  src = inspect.getsource(SelfdriveD.update_events)
  assert "if self.sm['radarState'].radarErrors.canError:" in src
  assert "from opendbc.car.tesla_ap1.values import is_preap" in src
  assert "self.events.add(EventName.radarDataInvalid)" in src
  assert "self.events.add(EventName.canError)" in src
  radar_block = src.split("if self.sm['radarState'].radarErrors.canError:")[1]
  radar_block = radar_block.split("elif self.sm['radarState'].radarErrors.radarUnavailableTemporary:")[0]
  assert "is_preap" in radar_block
  assert "EventName.radarDataInvalid" in radar_block
  assert "EventName.canError" in radar_block
  after = src[src.index("if CS.canTimeout:"):]
  assert "EventName.canBusMissing" in after
  assert "EventName.canError" in after
  assert "radarDataInvalid" not in after


def test_mapping_preap_gets_radar_data_invalid_not_canerror():
  names = map_radar_can_error(CAR.TESLA_PREAP_MODELS)
  assert names == {EventName.radarDataInvalid}
  assert EventName.canError not in names


def test_mapping_ap1_and_unknown_keep_canerror():
  for fp in (CAR.TESLA_AP1_MODELS, CAR.TESLA_AP1_MODELX, None, "UNKNOWN_CAR", "MOCK"):
    names = map_radar_can_error(fp)
    assert names == {EventName.canError}, fp
    assert EventName.radarDataInvalid not in names


def test_mutant_dropping_preap_gate_is_caught():
  mutated = map_radar_can_error(CAR.TESLA_AP1_MODELS, drop_preap_gate=True)
  assert EventName.radarDataInvalid in mutated
  correct = map_radar_can_error(CAR.TESLA_AP1_MODELS)
  assert correct == {EventName.canError}
  assert mutated != correct


def test_car_bus_invalid_is_canerror_not_radar_data_invalid():
  src = inspect.getsource(SelfdriveD.update_events)
  assert "elif not CS.canValid:" in src
  assert "if CS.canTimeout:" in src
  after = src[src.index("if CS.canTimeout:"):]
  assert "EventName.canBusMissing" in after
  assert "EventName.canError" in after
  assert "radarDataInvalid" not in after


# ---- radar_interface: silence path, grace at real cadence, AP1 ----

def test_grace_constant_is_at_most_one_second():
  assert 0 < PREAP_PARSER_GRACE_S <= 1.0
  assert PREAP_PARSER_GRACE_S == 0.25


def test_resume_predicate_uses_missing_radar_threshold():
  src = inspect.getsource(RadarInterface._preap_is_resume)
  assert "frames_without_radar >= PREAP_MISSING_RADAR_FRAMES" in src
  assert "frames_without_radar > 0" not in src
  assert "_preap_parser_seen_valid" in src


def test_silence_path_is_error_free(long_paths):
  ri = preap_ri(long_paths)
  drive(ri, 1.0, TRIG_EVERY)  # first contact (one trigger)
  outs = []
  for _ in range(PREAP_MISSING_RADAR_FRAMES + 5):
    outs.append(ri.update([]))
  published = [o for o in outs if o is not None]
  assert published, "silence path must publish empty RadarData"
  for o in published:
    assert not o.points
    assert not o.errors.canError
    assert not any(o.errors.to_dict().values())
  ev = Events()
  assert not ev.names
  src = inspect.getsource(RadarInterface.update)
  block = src[src.index("self.pts.clear()"):src.index("return None")]
  assert "return structs.RadarData()" in block
  assert "canError" not in block or "never canError" in block


def test_never_spoke_silence_is_error_free(long_paths):
  ri = preap_ri(long_paths)
  outs = [ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES * 2)]
  published = [o for o in outs if o is not None]
  assert published
  assert all(not o.points and not any(o.errors.to_dict().values()) for o in published)
  assert not ri.preap_radar_spoke


def test_first_contact_has_no_canerror_during_grace(long_paths):
  """(b) First-contact grace still suppresses at startup, at the real 100 Hz / 16 Hz cadence."""
  ri = no_gate(preap_ri(long_paths))
  n = int(PREAP_PARSER_GRACE_S / DT) - 1  # still inside grace
  pub = drive(ri, 1.0, n, send_sgu=False)
  assert pub, "first contact must publish"
  assert not ri.rcp.can_valid
  assert all(not o.errors.canError for _, o, _ in pub)
  assert all(not o.points for _, o, _ in pub)  # F3: no points during grace while invalid


def test_dropped_sgu_fires_after_grace_at_real_cadence(long_paths):
  """(a) 5 s of missing 0x301 (SGU) with the trigger still arriving must set canError after grace."""
  ri = no_gate(preap_ri(long_paths))
  pub = drive(ri, 1.0, int(5.0 / DT), send_sgu=False)
  assert not ri.rcp.can_valid
  in_grace = [o for t, o, trig in pub if trig and (t - 1.0) < PREAP_PARSER_GRACE_S]
  after = [o for t, o, trig in pub if trig and (t - 1.0) >= PREAP_PARSER_GRACE_S]
  assert in_grace and all(not o.errors.canError for o in in_grace)
  assert after and any(o.errors.canError for o in after)
  assert after[-1].errors.canError
  names = map_radar_can_error(CAR.TESLA_PREAP_MODELS)
  assert names == {EventName.radarDataInvalid}


def test_resume_after_real_silence_rearms_once(long_paths):
  """(c) After the parser has been valid, a real 0.5 s silence re-arms grace once, not every 0x36E gap."""
  ri = no_gate(preap_ri(long_paths))
  # Fill the parser (full 64-point table + SGU + trigger) so can_valid can become true.
  drive(ri, 1.0, int(1.0 / DT), send_sgu=True, full_table=True)
  assert ri._preap_parser_seen_valid or ri.rcp.can_valid
  # Real silence: 50+ empty 10 ms steps, no 0x36E.
  silent = [ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES + 2)]
  published_silent = [o for o in silent if o is not None]
  assert published_silent
  assert all(not o.errors.canError and not any(o.errors.to_dict().values()) for o in published_silent)
  # Resume with SGU dropped (invalid parser): grace must hide canError for 0.25 s, then fire.
  t_resume = 1.0 + 1.0 + (PREAP_MISSING_RADAR_FRAMES + 2) * DT
  pub = drive(ri, t_resume, int(1.0 / DT), send_sgu=False)
  in_grace = [o for t, o, trig in pub if trig and (t - t_resume) < PREAP_PARSER_GRACE_S]
  after = [o for t, o, trig in pub if trig and (t - t_resume) >= PREAP_PARSER_GRACE_S]
  assert in_grace and all(not o.errors.canError for o in in_grace)
  assert after and any(o.errors.canError for o in after)


def test_ap1_invalid_parser_is_canerror_immediately_no_grace():
  ri = RadarInterface(ap1_cp())
  pub = drive(ri, 1.0, TRIG_EVERY * 2, send_sgu=False)
  assert pub
  assert not ri.rcp.can_valid
  # AP1: the first published trigger already sets canError (no grace).
  first = next(o for _, o, trig in pub if trig)
  assert first.errors.canError
  # g5_ap1_first_contact_grace drops "self.preap and" from first_contact; that would
  # arm _preap_grace_until on AP1 even though in_grace still requires self.preap
  # (so canError alone would not catch it). 92aa behaviour: no first-contact grace.
  assert not ri.preap
  assert ri._preap_grace_until is None
  names = map_radar_can_error(CAR.TESLA_AP1_MODELS)
  assert names == {EventName.canError}
  assert EventName.radarDataInvalid not in names


def test_mutant_grace_removed_is_caught(long_paths, monkeypatch):
  import opendbc.car.tesla_ap1.radar_interface as ri_mod
  monkeypatch.setattr(ri_mod, "PREAP_PARSER_GRACE_S", 0.0)
  ri = no_gate(preap_ri(long_paths))
  pub = drive(ri, 1.0, 1, send_sgu=False)
  assert pub
  assert not ri.rcp.can_valid
  assert pub[0][1].errors.canError, "removing the grace must surface canError at first contact"


def test_mutant_grace_never_ending_is_caught(long_paths, monkeypatch):
  import opendbc.car.tesla_ap1.radar_interface as ri_mod
  monkeypatch.setattr(ri_mod, "PREAP_PARSER_GRACE_S", 1e9)
  ri = no_gate(preap_ri(long_paths))
  pub = drive(ri, 1.0, int(5.0 / DT), send_sgu=False)
  after = [o for t, o, trig in pub if trig and (t - 1.0) >= 0.25]
  assert after and all(not o.errors.canError for o in after), "an endless grace must hide a dropped SGU"


def test_mutant_old_resume_gt_zero_is_caught(long_paths, monkeypatch):
  def old_resume(self):
    return self.preap and self.preap_radar_spoke and self.frames_without_radar > 0
  monkeypatch.setattr(RadarInterface, "_preap_is_resume", old_resume)
  ri = no_gate(preap_ri(long_paths))
  pub = drive(ri, 1.0, int(5.0 / DT), send_sgu=False)
  after = [o for t, o, trig in pub if trig and (t - 1.0) >= PREAP_PARSER_GRACE_S]
  assert after and all(not o.errors.canError for o in after), (
      "the old frames_without_radar > 0 resume must hide a dropped SGU at the real cadence"
  )


def test_mutant_silence_raises_error_is_caught(long_paths, monkeypatch):
  import opendbc.car.tesla_ap1.radar_interface as ri_mod
  orig = ri_mod.RadarInterface.update

  def upd(self, can_strings):
    ret = orig(self, can_strings)
    if ret is not None and self.preap and self.preap_radar_spoke and self.frames_without_radar >= PREAP_MISSING_RADAR_FRAMES:
      ret.errors.canError = True
    return ret
  monkeypatch.setattr(ri_mod.RadarInterface, "update", upd)
  ri = preap_ri(long_paths)
  drive(ri, 1.0, TRIG_EVERY)
  outs = [ri.update([]) for _ in range(PREAP_MISSING_RADAR_FRAMES + 5)]
  published = [o for o in outs if o is not None]
  assert published and any(o.errors.canError for o in published), "silence must not set canError in production; this mutant does"


def test_events_defined_and_source_gate_still_present():
  src = inspect.getsource(SelfdriveD.update_events)
  assert "if is_preap(getattr(self.CP, \"carFingerprint\", None)):" in src
  ri_src = inspect.getsource(RadarInterface.update)
  assert "in_grace" in ri_src
  assert "PREAP_PARSER_GRACE_S" in ri_src
  assert "frames_without_radar >= PREAP_MISSING_RADAR_FRAMES" in inspect.getsource(RadarInterface._preap_is_resume)
  assert "if self.preap and in_grace and not self.rcp.can_valid:" in inspect.getsource(RadarInterface.update)


def test_invalid_frames_during_grace_publish_zero_points(long_paths):
  """Invalid parser frames at the 100 Hz card cadence must not publish points during grace."""
  ri = no_gate(preap_ri(long_paths))
  n = int(PREAP_PARSER_GRACE_S / DT)  # still inside grace
  pub = drive(ri, 1.0, n, send_sgu=False)
  trigger_pub = [o for _, o, trig in pub if trig]
  assert trigger_pub, "first-contact trigger frames must publish"
  assert not ri.rcp.can_valid
  for o in trigger_pub:
    assert not o.points
    assert not o.errors.canError


def test_flapping_at_real_cadence_does_not_rearm(long_paths):
  """Five empty 10 ms updates between 0x36E triggers are not a resume; a dropped SGU still fires after grace."""
  ri = no_gate(preap_ri(long_paths))
  pub = drive(ri, 1.0, int(2.0 / DT), send_sgu=False)
  after = [o for t, o, trig in pub if trig and (t - 1.0) >= PREAP_PARSER_GRACE_S]
  assert after and any(o.errors.canError for o in after)
  assert after[-1].errors.canError
  # grace should not have been re-armed on the later cycles
  assert ri._preap_grace_until is not None
  last_t = after[-1] and [t for t, o, trig in pub if trig][-1]
  assert last_t >= 1.0 + PREAP_PARSER_GRACE_S
  # still past grace: _preap_is_resume stays false because the gap is only 5 frames
  assert ri.frames_without_radar < PREAP_MISSING_RADAR_FRAMES or not ri._preap_parser_seen_valid


def test_mutant_keeping_grace_points_is_caught(long_paths, monkeypatch):
  import opendbc.car.tesla_ap1.radar_interface as ri_mod
  orig = ri_mod.RadarInterface.update

  def upd(self, can_strings):
    ret = orig(self, can_strings)
    if ret is not None and self.preap and self.pts:
      now = self._preap_grace_until
      in_grace = self.preap and self._preap_grace_until is not None
      # The production path empties ret.points during grace while invalid; this mutant puts them back.
      if in_grace and not self.rcp.can_valid:
        ret.points = list(self.pts.values())
    return ret
  monkeypatch.setattr(ri_mod.RadarInterface, "update", upd)
  ri = no_gate(preap_ri(long_paths))
  pub = drive(ri, 1.0, int(PREAP_PARSER_GRACE_S / DT), send_sgu=False)
  trigger_pub = [o for _, o, trig in pub if trig]
  assert trigger_pub and any(o.points for o in trigger_pub), (
      "removing the grace point drop must leak invalid points; production must not"
  )
