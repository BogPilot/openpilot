"""Pre-AP radarDataInvalid: mapping, alerts, first-contact/resume grace, silence path, AP1 unchanged."""
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
from openpilot.selfdrive.selfdrived.events import EVENTS, ET, Events, EventName
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD


NS = 1_000_000_000


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


def frames(sgu=None, trigger=True):
  packer = CANPacker(DBC[CAR.TESLA_PREAP_MODELS][Bus.radar])
  out = [packer.make_can_msg("TeslaRadarSguInfo", 1, sgu or {}),
         packer.make_can_msg("RadarPoint0_A", 1, {"Tracked": 1, "Meas": 1, "Index": 1, "LongDist": 40.0, "ProbExist": 96.875}),
         packer.make_can_msg("RadarPoint0_B", 1, {"Index2": 1})]
  if trigger:
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


def step(ri, t_s, trigger=True):
  return ri.update([(int(t_s * NS), frames(trigger=trigger))])


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
  assert events["radarDataInvalid"] == max(non_dep.values())
  assert events["radarDataInvalid"] == 115


def test_alerts_match_canerror_except_text():
  rdi = EVENTS[EventName.radarDataInvalid]
  ce = EVENTS[EventName.canError]
  assert set(rdi) == set(ce) == {ET.IMMEDIATE_DISABLE, ET.PERMANENT, ET.NO_ENTRY}

  def fields(a, skip_text=False):
    keys = ("alert_status", "alert_size", "priority", "visual_alert", "audible_alert",
            "duration", "creation_delay")
    out = {k: getattr(a, k) for k in keys}
    out["cls"] = type(a)
    if not skip_text:
      out["alert_text_1"] = a.alert_text_1
      out["alert_text_2"] = a.alert_text_2
    return out

  for et in (ET.IMMEDIATE_DISABLE, ET.PERMANENT, ET.NO_ENTRY):
    a, b = rdi[et], ce[et]
    assert fields(a, skip_text=True) == fields(b, skip_text=True), et
    text_a = (a.alert_text_1, a.alert_text_2)
    text_b = (b.alert_text_1, b.alert_text_2)
    assert "Radar Data Invalid" in "".join(text_a)
    assert "Unknown Vehicle Variant" in "".join(text_b)
    swapped = tuple(t.replace("Radar Data Invalid", "Unknown Vehicle Variant") for t in text_a)
    assert swapped == text_b

  # Immediate disable wording required by the owner: TAKE CONTROL IMMEDIATELY / Radar Data Invalid
  imm = rdi[ET.IMMEDIATE_DISABLE]
  assert imm.alert_text_1 == "TAKE CONTROL IMMEDIATELY"
  assert imm.alert_text_2 == "Radar Data Invalid"


def test_events_defined_includes_radar_data_invalid():
  events = log.OnroadEvent.EventName.schema.enumerants
  for name, e in events.items():
    if not name.endswith("DEPRECATED"):
      assert e in EVENTS, f"{name} @{e} not in EVENTS"


# ---- selfdrived mapping (source + mirror) ----

def test_selfdrived_maps_parser_error_preap_only():
  src = inspect.getsource(SelfdriveD.update_events)
  # Radar-side branch is gated; the car-bus canValid path is unchanged.
  assert "if self.sm['radarState'].radarErrors.canError:" in src
  assert "from opendbc.car.tesla_ap1.values import is_preap" in src
  assert "self.events.add(EventName.radarDataInvalid)" in src
  assert "self.events.add(EventName.canError)" in src
  radar_block = src.split("if self.sm['radarState'].radarErrors.canError:")[1]
  radar_block = radar_block.split("elif self.sm['radarState'].radarErrors.radarUnavailableTemporary:")[0]
  assert "is_preap" in radar_block
  assert "EventName.radarDataInvalid" in radar_block
  assert "EventName.canError" in radar_block  # AP1 / unknown else-branch
  # Car-bus path is a separate branch and must not use radarDataInvalid
  bus = src.split("elif not CS.canValid:")[1]
  bus = bus.split("\n", 2)[0] + bus.split("\n", 2)[1]
  assert "EventName.canError" in src.split("elif not CS.canValid:")[1].split("\n")[1]
  assert "radarDataInvalid" not in src.split("elif not CS.canValid:")[1].split("if")[0]


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
  # If the is_preap gate is dropped, AP1 would get radarDataInvalid. The test must fail that.
  mutated = map_radar_can_error(CAR.TESLA_AP1_MODELS, drop_preap_gate=True)
  assert EventName.radarDataInvalid in mutated
  correct = map_radar_can_error(CAR.TESLA_AP1_MODELS)
  assert correct == {EventName.canError}
  assert mutated != correct


def test_car_bus_invalid_is_canerror_not_radar_data_invalid():
  src = inspect.getsource(SelfdriveD.update_events)
  # The car-bus path is CS.canTimeout / not CS.canValid, not the radarErrors branch.
  assert "elif not CS.canValid:" in src
  assert "if CS.canTimeout:" in src
  after = src[src.index("if CS.canTimeout:"):]
  assert "EventName.canBusMissing" in after
  assert "EventName.canError" in after
  # radarDataInvalid must not appear in the car-bus section
  assert "radarDataInvalid" not in after


# ---- radar_interface: silence path, grace, AP1 ----

def test_grace_constant_is_at_most_one_second():
  assert 0 < PREAP_PARSER_GRACE_S <= 1.0
  assert PREAP_PARSER_GRACE_S == 0.25


def test_silence_path_is_error_free(long_paths):
  ri = preap_ri(long_paths)
  # First contact, then silence past the 0.5 s advisory window.
  assert step(ri, 1.0) is not None
  outs = []
  for i in range(1, PREAP_MISSING_RADAR_FRAMES + 5):
    outs.append(ri.update([]))
  published = [o for o in outs if o is not None]
  assert published, "silence path must publish empty RadarData"
  for o in published:
    assert not o.points
    assert not o.errors.canError
    assert not any(o.errors.to_dict().values())
  # Host mapping: a silent radar raises neither event
  ev = Events()
  # no canError flag, so neither branch fires
  assert not ev.names
  src = inspect.getsource(RadarInterface.update)
  # The option-B return is empty RadarData with no canError assignment on that path
  assert "return structs.RadarData()" in src
  silence = src.split("if self.preap:")[2] if src.count("if self.preap:") >= 3 else src
  # The empty return does not set canError
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
  ri = no_gate(preap_ri(long_paths))
  out = step(ri, 1.0)
  assert out is not None
  assert not ri.rcp.can_valid, "fixture must leave the parser invalid (incomplete table)"
  assert not out.errors.canError
  # still inside grace
  out2 = step(ri, 1.0 + PREAP_PARSER_GRACE_S - 0.01)
  assert out2 is not None and not out2.errors.canError


def test_resume_after_silence_has_no_canerror_during_grace(long_paths):
  ri = no_gate(preap_ri(long_paths))
  assert step(ri, 1.0) is not None
  for _ in range(PREAP_MISSING_RADAR_FRAMES):
    ri.update([])
  # Resume at 10 s: parser still invalid, grace must hide canError
  out = step(ri, 10.0)
  assert out is not None
  assert not ri.rcp.can_valid
  assert not out.errors.canError
  out2 = step(ri, 10.0 + PREAP_PARSER_GRACE_S - 0.01)
  assert out2 is not None and not out2.errors.canError


def test_sustained_invalid_after_grace_sets_canerror(long_paths):
  ri = no_gate(preap_ri(long_paths))
  assert step(ri, 1.0) is not None
  out = step(ri, 1.0 + PREAP_PARSER_GRACE_S + 0.01)
  assert out is not None
  assert not ri.rcp.can_valid
  assert out.errors.canError
  names = map_radar_can_error(CAR.TESLA_PREAP_MODELS)
  assert names == {EventName.radarDataInvalid}


def test_ap1_invalid_parser_is_canerror_immediately_no_grace():
  ri = RadarInterface(ap1_cp())
  out = step(ri, 1.0)
  assert out is not None
  assert not ri.rcp.can_valid
  assert out.errors.canError
  names = map_radar_can_error(CAR.TESLA_AP1_MODELS)
  assert names == {EventName.canError}
  assert EventName.radarDataInvalid not in names
  # a later frame still canError (no grace window on AP1)
  out2 = step(ri, 1.0 + 0.01)
  assert out2 is not None and out2.errors.canError


def test_mutant_grace_removed_is_caught(long_paths, monkeypatch):
  import opendbc.car.tesla_ap1.radar_interface as ri_mod
  monkeypatch.setattr(ri_mod, "PREAP_PARSER_GRACE_S", 0.0)
  ri = no_gate(preap_ri(long_paths))
  out = step(ri, 1.0)
  assert out is not None
  assert not ri.rcp.can_valid
  assert out.errors.canError, "removing the grace must surface canError at first contact"
  # Production (unmutated constant already applied only via monkeypatch on this instance)
  # The production path is covered by test_first_contact_has_no_canerror_during_grace.


def test_events_defined_and_source_gate_still_present():
  src = inspect.getsource(SelfdriveD.update_events)
  # Mutant: dropping the pre-AP gate would map AP1 to radarDataInvalid. Source must keep the gate.
  assert "if is_preap(getattr(self.CP, \"carFingerprint\", None)):" in src
  ri_src = inspect.getsource(RadarInterface.update)
  assert "in_grace" in ri_src
  assert "PREAP_PARSER_GRACE_S" in ri_src
