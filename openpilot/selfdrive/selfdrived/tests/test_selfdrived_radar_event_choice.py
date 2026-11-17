"""Drive SelfdriveD.update_events radar-event choice at runtime.

Covers selfdrived.py:449-453 (radar canError -> radarDataInvalid vs canError),
SelfdriveD.__init__ line 101 (PreapRegenWatch), and the preapRegenLimit path at
401-402. Pre-AP emits radarDataInvalid and not canError; AP1 and unknown keep
canError. Construction uses mocked Params/messaging only; the method under test
is the real SelfdriveD.update_events.
"""
from collections import defaultdict
from types import SimpleNamespace

import pytest
from opendbc.car import gen_empty_fingerprint
from opendbc.car.structs import car
from opendbc.car.tesla_ap1.interface import CarInterface
from opendbc.car.tesla_ap1.values import AP1_CHASSIS_SIGNATURE, CAR
from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import EventName
from openpilot.selfdrive.selfdrived.preap_regen import HOLD_FRAMES, PreapRegenWatch
from openpilot.selfdrive.selfdrived import selfdrived as sdmod
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD


class FakeParams:
  def get_bool(self, *args, **kwargs):
    return False

  def get(self, *args, **kwargs):
    if kwargs.get("return_default"):
      return 0
    return None

  def remove(self, *args, **kwargs):
    pass

  def put_bool(self, *args, **kwargs):
    pass

  def put(self, *args, **kwargs):
    pass


class FakePM:
  def __init__(self, *args, **kwargs):
    pass

  def send(self, *args, **kwargs):
    pass


class _RadarErrors:
  def __init__(self, can_error=True, radar_unavailable_temporary=False):
    self.canError = can_error
    self.radarUnavailableTemporary = radar_unavailable_temporary

  def to_dict(self):
    return {
      "canError": self.canError,
      "radarUnavailableTemporary": self.radarUnavailableTemporary,
    }


class FakeSM:
  def __init__(self, *args, **kwargs):
    self.frame = 0
    self.recv_frame = defaultdict(int)
    self.seen = defaultdict(lambda: False)
    self.alive = defaultdict(lambda: True)
    self.valid = defaultdict(lambda: True)
    self.updated = defaultdict(lambda: False)
    ThermalStatus = log.DeviceState.ThermalStatus
    self._data = {
      "controlsState": SimpleNamespace(
        curvature=0.0,
        lateralControlState=SimpleNamespace(
          which=lambda: "angleState",
          angleState=SimpleNamespace(active=False, saturated=False))),
      "deviceState": SimpleNamespace(
        chestnutPresent=False, thermalStatus=ThermalStatus.ok,
        freeSpacePercent=50, memoryUsagePercent=10, fanSpeedPercentDesired=0,
        started=False),
      "modelV2": SimpleNamespace(
        meta=SimpleNamespace(
          laneChangeState=log.LaneChangeState.off,
          laneChangeDirection=log.LaneChangeDirection.none,
          hardBrakePredicted=False),
        action=SimpleNamespace(desiredCurvature=0.0),
        frameDropPerc=0),
      "driverMonitoringState": SimpleNamespace(
        lockout=False, alwaysOnLockout=False,
        activePolicy=log.DriverMonitoringState.MonitoringPolicy.vision,
        alertLevel=log.DriverMonitoringState.AlertLevel.none,
        visionPolicyState=SimpleNamespace(uncertainOffroadAlertPercent=0)),
      "carControl": SimpleNamespace(longActive=False),
      "peripheralState": SimpleNamespace(
        pandaType=log.PandaState.PandaType.unknown, fanSpeedRpm=0),
      "extrinsicsCalibration": SimpleNamespace(
        calStatus=log.ExtrinsicsCalibration.Status.calibrated),
      "driverAssistance": SimpleNamespace(
        leftLaneDeparture=False, rightLaneDeparture=False),
      "longitudinalPlan": SimpleNamespace(aTarget=0.0, fcw=False),
      "radarState": SimpleNamespace(radarErrors=_RadarErrors(True)),
      "pandaStates": [],
      "managerState": SimpleNamespace(processes=[]),
      "deviceMotion": SimpleNamespace(posenetOK=True, inputsOK=False),
    }

  def __getitem__(self, key):
    if key not in self._data:
      self._data[key] = SimpleNamespace()
    return self._data[key]

  def all_checks(self, *args, **kwargs):
    return True

  def all_alive(self, *args, **kwargs):
    return True

  def all_freq_ok(self, *args, **kwargs):
    return True


class _QuietCarEvents:
  def update(self, *args, **kwargs):
    return SimpleNamespace(to_msg=lambda: [])


def _preap_cp():
  return CarInterface.get_params(CAR.TESLA_PREAP_MODELS, {}, [], False, False, False)


def _ap1_cp(candidate=CAR.TESLA_AP1_MODELS, long_control=None):
  fp = gen_empty_fingerprint()
  fp[0] = dict(AP1_CHASSIS_SIGNATURE)
  fp[2] = {0x399: 8, 0x2B9: 8, 0x488: 4}
  CP = CarInterface.get_params(candidate, fp, [], False, False, False)
  if long_control is not None:
    CP.openpilotLongitudinalControl = long_control
  return CP


def _unknown_cp(fingerprint=""):
  CP = car.CarParams.new_message()
  CP.carFingerprint = fingerprint
  CP.brand = "tesla_ap1"
  CP.openpilotLongitudinalControl = True
  CP.passive = False
  CP.notCar = False
  CP.pcmCruise = True
  CP.alphaLongitudinalAvailable = False
  CP.secOcRequired = False
  return CP


def _cs():
  CS = car.CarState.new_message()
  CS.canValid = True
  CS.canTimeout = False
  CS.gasPressed = False
  CS.regenBraking = False
  CS.standstill = True
  CS.leftBlindspot = False
  CS.rightBlindspot = False
  CS.vCruise = 0
  CS.vEgo = 0
  CS.aEgo = 0
  CS.steeringPressed = False
  CS.brakePressed = False
  CS.cruiseState.enabled = False
  return CS


def _make_sd(monkeypatch, CP, *, can_error=True):
  sm = FakeSM()
  sm._data["radarState"] = SimpleNamespace(radarErrors=_RadarErrors(can_error))
  monkeypatch.setattr(sdmod, "Params", FakeParams)
  monkeypatch.setattr(sdmod.messaging, "PubMaster", FakePM)
  monkeypatch.setattr(sdmod.messaging, "SubMaster", lambda *a, **k: sm)
  monkeypatch.setattr(sdmod.messaging, "sub_sock", lambda *a, **k: object())
  monkeypatch.setattr(sdmod, "get_build_metadata", lambda: SimpleNamespace(
    openpilot=SimpleNamespace(comma_remote=False), tested_channel=False))
  monkeypatch.setattr(sdmod, "get_gps_location_service", lambda params: "gpsLocation")
  monkeypatch.setattr(sdmod.HARDWARE, "get_device_type", lambda: "pc")

  sd = SelfdriveD(CP=CP)
  sd.sm = sm
  sd.initialized = True
  sd.startup_event = None
  sd.enabled = False
  sd.car_events = _QuietCarEvents()
  sd.CS_prev = _cs()
  sd.rk = SimpleNamespace(lagging=False)
  return sd, sm


def _event_names(sd, CS=None, frames=1):
  CS = _cs() if CS is None else CS
  last = None
  for _ in range(frames):
    sd.update_events(CS)
    last = set(sd.events.names)
  return last


def test_selfdrived_init_constructs_preap_regen_watch(monkeypatch):
  sd, _ = _make_sd(monkeypatch, _preap_cp())
  assert isinstance(sd.preap_regen, PreapRegenWatch)


def test_update_events_preap_emits_radar_data_invalid_not_canerror(monkeypatch):
  sd, _ = _make_sd(monkeypatch, _preap_cp(), can_error=True)
  names = _event_names(sd)
  assert EventName.radarDataInvalid in names
  assert EventName.canError not in names


@pytest.mark.parametrize("cp", [
  _ap1_cp(CAR.TESLA_AP1_MODELS),
  _ap1_cp(CAR.TESLA_AP1_MODELX, long_control=True),
  _unknown_cp(""),
  _unknown_cp("UNKNOWN_CAR"),
])
def test_update_events_ap1_and_unknown_keep_canerror(monkeypatch, cp):
  sd, _ = _make_sd(monkeypatch, cp, can_error=True)
  names = _event_names(sd)
  assert EventName.canError in names, cp.carFingerprint
  assert EventName.radarDataInvalid not in names, cp.carFingerprint


def test_update_events_modelx_without_op_long_does_not_map_radar(monkeypatch):
  # Model X is lateral-only by default; the radar-event branch is behind OP long.
  cp = _ap1_cp(CAR.TESLA_AP1_MODELX)
  assert not cp.openpilotLongitudinalControl
  sd, _ = _make_sd(monkeypatch, cp, can_error=True)
  names = _event_names(sd)
  assert EventName.radarDataInvalid not in names
  assert EventName.canError not in names


def test_update_events_unknown_none_fingerprint_keeps_canerror(monkeypatch):
  # carFingerprint is capnp text and cannot be None; use a wrapper so getattr is None.
  class _CP:
    def __init__(self, inner):
      self._inner = inner
      self.carFingerprint = None
    def __getattr__(self, name):
      return getattr(self._inner, name)
  sd, _ = _make_sd(monkeypatch, _CP(_unknown_cp("")), can_error=True)
  names = _event_names(sd)
  assert EventName.canError in names
  assert EventName.radarDataInvalid not in names


def test_update_events_preap_regen_limit_added(monkeypatch):
  sd, sm = _make_sd(monkeypatch, _preap_cp(), can_error=False)
  sm._data["carControl"] = SimpleNamespace(longActive=True)
  sm._data["longitudinalPlan"] = SimpleNamespace(aTarget=-3.0, fcw=False)
  names = _event_names(sd, frames=HOLD_FRAMES + 5)
  assert EventName.preapRegenLimit in names
  assert EventName.canError not in names


def test_mutant_dropping_is_preap_in_update_events_is_caught(monkeypatch):
  sd, _ = _make_sd(monkeypatch, _preap_cp(), can_error=True)
  production = _event_names(sd)
  assert EventName.radarDataInvalid in production
  assert EventName.canError not in production

  monkeypatch.setattr("opendbc.car.tesla_ap1.values.is_preap", lambda candidate: False)
  mutated = _event_names(sd)
  assert EventName.canError in mutated
  assert EventName.radarDataInvalid not in mutated
  assert mutated != production


def test_mutant_swapping_is_preap_in_update_events_is_caught(monkeypatch):
  import opendbc.car.tesla_ap1.values as values
  orig = values.is_preap
  monkeypatch.setattr(values, "is_preap", lambda candidate: not orig(candidate))

  preap = _event_names(_make_sd(monkeypatch, _preap_cp(), can_error=True)[0])
  ap1 = _event_names(_make_sd(monkeypatch, _ap1_cp(), can_error=True)[0])
  assert EventName.canError in preap
  assert EventName.radarDataInvalid not in preap
  assert EventName.radarDataInvalid in ap1
  assert EventName.canError not in ap1
