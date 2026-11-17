"""AP1 Bosch radar (bus 1, tesla_radar_bosch_generated). 32 points, trigger 0x36e."""
from opendbc.can import CANParser
from opendbc.car import Bus, structs
from opendbc.car.carlog import carlog
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.tesla_ap1.preap.panda_link import GTW_ECHO_ADDRS, GTW_ECHO_SRC
from opendbc.car.tesla_ap1.preap.radar_valid import RadarValidGate
from opendbc.car.tesla_ap1.preap_radar_filters import bosch_point_valid
from opendbc.car.tesla_ap1.safety_flags import FLAG_TESLA_PREAP_RADAR_EMULATION
from opendbc.car.tesla_ap1.values import CANBUS, DBC, is_preap

PREAP_STATUS_S = 5.0

NUM_POINTS = 32
TRIGGER_MSG = 878  # RadarPoint31_B
# Pre-AP retrofit: card calls update() at 100 Hz and the radar cycles at the measured
# 7.4-12.6 Hz, depending on track count.
# - Silent radar (its trigger message has never arrived since card started): harmless, as NAP
#   (opendbc/car/tesla/radar_interface.py:176-177 @ opendbc 508d26fcb returns before any error).
#   It publishes an empty RadarData with no errors at 20 Hz (the RadarInterfaceBase rate), so radard
#   keeps radarState valid on camera leads: no canError, commIssue, radarFault or radarTempUnavailable.
# - After the trigger has arrived, no radar cycle for 0.5 s: a canError RadarData at 20 Hz (NAP raises
#   canError from can_valid there, radar_interface.py:190-191), so radard marks radarState invalid.
PREAP_MISSING_RADAR_FRAMES = 50
PREAP_MISSING_RADAR_PUBLISH_DIV = 5


def get_radar_can_parser(CP):
  if CP.radarUnavailable or Bus.radar not in DBC[CP.carFingerprint]:
    return None
  messages = [('TeslaRadarSguInfo', 10)]
  if is_preap(CP.carFingerprint):
    # 0x501 alert matrix for the Pre-AP radar-valid gate (preap/radar_valid.py), ~1 Hz; never part of can_valid (nan = no alive check)
    messages.append(('TeslaRadarAlertMatrix', float('nan')))
  for i in range(NUM_POINTS):
    messages.extend([(f'RadarPoint{i}_A', 16), (f'RadarPoint{i}_B', 16)])
  # CANBUS.radar is bus 1. 0x32e / 0x33e on this bus are RadarPoint10_A /
  # RadarPoint15_B (8 bytes, measured 7.4-12.6 Hz depending on track count;
  # the parser still lists 16 Hz so the 0.625 s point timeout is unchanged).
  # The same IDs on the chassis bus (bus 0)
  # are 5-byte park-assist frames (front / rear corner ultrasonics at 4 Hz,
  # 255 = no reading). CANParser skips src != self.bus, and the Pre-AP panda
  # has disable_forwarding, so those chassis frames never reach this parser.
  # Never filter by CAN ID alone: that would drop a real radar track.
  return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, CANBUS.radar)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.CP = CP
    self.num_points = NUM_POINTS
    self.trigger_msg = TRIGGER_MSG
    self.rcp = get_radar_can_parser(CP)
    self.updated_messages = set()
    self.preap = is_preap(CP.carFingerprint)
    self.frames_without_radar = 0
    # Pre-AP radar-valid filter (preap/radar_valid.py), advisory only (NAP / Tinkla: radar health is not an engage gate): no radar
    # points reach radard until the radar is VALID (accepted its config and tracks moving objects), and none while a fault (starved /
    # rejected ITC, 0x501 alerts, a frozen table, HWFail, no gateway echo) is active. Speed control then runs on camera leads and
    # card raises the one warning (carState.bogpilot.preapRadarNotReady). Never a no-entry, soft disable or disengage.
    self.preap_gate = None
    self.preap_radar_valid = True
    self.preap_radar_spoke = False     # the trigger message has arrived at least once since card started
    self.preap_v_ego = 0.0             # card.py sets it each step (for the gate's late label only)
    self._preap_steps = 0
    if self.preap and self.rcp is not None:
      configs = list(getattr(CP, "safetyConfigs", None) or [])
      param = int(configs[-1].safetyParam) if configs else 0
      self.preap_gate = RadarValidGate(bool(param & FLAG_TESLA_PREAP_RADAR_EMULATION))
      self.preap_radar_valid = False

  def _preap_status_line(self, now: float, n_points: int) -> None:
    """Log-only radar status line (no UI, no control): every STATUS_S and on every change of echoed / pending / valid / fault."""
    st = self.preap_gate.status()
    key = (st["echoed"], st["pending"], st["valid"], st["fault"], st["late"])
    last_t, last_key = getattr(self, "_preap_status", (None, None))
    if last_t is None or key != last_key or now - last_t >= PREAP_STATUS_S:
      carlog.info(f"preap radar: echoed={int(st['echoed'])} pending={int(st['pending'])} valid={int(st['valid'])} "
                  f"fault={st['fault']} late={int(st['late'])} itc={st['itc']} camera_lead={int(not st['valid'])} points={n_points} "
                  f"faults={st['faults']}")
      self._preap_status = (now, key)

  def _preap_gate_step(self, can_strings, vls) -> float:
    """Feed the gate this step's echoes and 0x501; returns its time (CAN log time, else 10 ms steps)."""
    self._preap_steps += 1
    now = None
    for pkt in can_strings or ():
      if isinstance(pkt, tuple) and len(pkt) == 2:
        nanos, msgs = pkt
        if nanos:
          now = float(nanos) * 1e-9
        if any(src == GTW_ECHO_SRC and addr in GTW_ECHO_ADDRS for addr, _, src in msgs):
          self.preap_gate.on_echo(now if now is not None else self._preap_steps * 0.01)
    now = now if now is not None else self._preap_steps * 0.01
    self.preap_gate.on_ego(now, self.preap_v_ego)
    if 1281 in vls:
      self.preap_gate.on_alert_matrix(now, self.rcp.vl['TeslaRadarAlertMatrix'])
    return now

  def update(self, can_strings):
    if self.rcp is None:
      return super().update(None)

    vls = self.rcp.update(can_strings)
    self.updated_messages.update(vls)
    gate_now = None
    if self.preap_gate is not None:
      gate_now = self._preap_gate_step(can_strings, vls)
    if self.trigger_msg not in self.updated_messages:
      if self.preap_gate is not None:
        self.preap_radar_valid = self.preap_gate.update(gate_now)
      if self.preap and not self.preap_radar_spoke:
        return super().update(None)      # silent radar: empty, error-free RadarData at 20 Hz (camera leads), as NAP :176-177
      if self.preap:
        self.frames_without_radar += 1
        if self.frames_without_radar >= PREAP_MISSING_RADAR_FRAMES and self.frames_without_radar % PREAP_MISSING_RADAR_PUBLISH_DIV == 0:
          self.pts.clear()               # no stale tracks survive a radar dropout
          ret = structs.RadarData()
          ret.errors.canError = True
          return ret
      return None
    self.frames_without_radar = 0
    self.preap_radar_spoke = True

    ret = structs.RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True

    radar_status = self.rcp.vl['TeslaRadarSguInfo']
    if self.preap:
      # Retrofit: only a hardware failure faults (Tinkla: "ignore RADC_SGUFail on PREAP MODEL S due to retrofit"; NAP ignores SGUFail
      # too, opendbc/car/tesla/radar_interface.py:203-210 @ opendbc 508d26fcb). SensorDirty is ignored here, a divergence
      # (docs/tesla/DIVERGENCES.md, radar status faults): NAP sets radarUnavailableTemporary on it (radar_interface.py:215-216 @
      # 508d26fcb) and Tinkla faults on it unless behind the nosecone (selfdrive/car/tesla/radar_interface.py:89-111@501c7de).
      fault = radar_status['RADC_HWFail']
    else:
      fault = radar_status['RADC_HWFail'] or radar_status['RADC_SGUFail'] or radar_status['RADC_SensorDirty']
    if fault:
      ret.errors.radarFault = True

    for i in range(self.num_points):
      msg_a = self.rcp.vl[f'RadarPoint{i}_A']
      msg_b = self.rcp.vl[f'RadarPoint{i}_B']
      if msg_a['Index'] != msg_b['Index2']:
        continue
      if not msg_a['Tracked']:
        if i in self.pts:
          del self.pts[i]
        continue
      if self.preap and not bosch_point_valid(msg_a['LongDist'], msg_a['ProbExist']):
        # Pre-AP: LongDist <= 0 or > 250 m or ProbExist < 50 %. Tinkla selfdrive/car/tesla/radar_interface.py:129-135 @ 501c7de,
        # NAP opendbc/car/tesla/radar_interface.py:105-109 @ cc39c7fa (both on every Bosch car; AP1 keeps every point here).
        if i in self.pts:
          del self.pts[i]
        continue
      if i not in self.pts:
        self.pts[i] = structs.RadarData.RadarPoint()
        self.pts[i].trackId = self.track_id
        self.track_id += 1
      self.pts[i].dRel = msg_a['LongDist']
      self.pts[i].yRel = msg_a['LatDist']
      self.pts[i].vRel = msg_a['LongSpeed']

    ret.points = list(self.pts.values())
    if self.preap_gate is not None:
      self.preap_gate.on_sgu(gate_now, int(radar_status['RADC_SGU_ITC']), bool(radar_status['RADC_SGUFail']),
                             bool(radar_status['RADC_HWFail']), bool(radar_status['RADC_SensorDirty']))
      self.preap_gate.on_points(gate_now, {i: (p.dRel, p.yRel, p.vRel) for i, p in self.pts.items()})
      self.preap_radar_valid = self.preap_gate.update(gate_now)
      self._preap_status_line(gate_now, len(ret.points))
      if not self.preap_radar_valid:
        ret.points = []          # filter only: tracks keep their ids in self.pts; radard runs on camera leads meanwhile
    self.updated_messages.clear()
    return ret
