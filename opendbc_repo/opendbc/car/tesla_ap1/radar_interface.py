"""AP1 Bosch radar (bus 1, tesla_radar_bosch_generated). 32 points, trigger 0x36e."""
from opendbc.can import CANParser
from opendbc.car import Bus, structs
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.tesla_ap1.preap_radar_filters import bosch_point_valid
from opendbc.car.tesla_ap1.values import CANBUS, DBC, is_preap

NUM_POINTS = 32
TRIGGER_MSG = 878  # RadarPoint31_B
# Pre-AP retrofit, fail closed: card calls update() at 100 Hz and the radar cycles at
# the measured 7.4-12.6 Hz, depending on track count. With no radar cycle for 0.5 s,
# publish a canError RadarData at 20 Hz (the RadarInterfaceBase rate) instead of nothing,
# so radard marks radarState invalid and selfdrived raises its radar CAN error / commIssue
# (no engage, soft disable).
PREAP_MISSING_RADAR_FRAMES = 50
PREAP_MISSING_RADAR_PUBLISH_DIV = 5


def get_radar_can_parser(CP):
  if CP.radarUnavailable or Bus.radar not in DBC[CP.carFingerprint]:
    return None
  messages = [('TeslaRadarSguInfo', 10)]
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

  def update(self, can_strings):
    if self.rcp is None:
      return super().update(None)

    vls = self.rcp.update(can_strings)
    self.updated_messages.update(vls)
    if self.trigger_msg not in self.updated_messages:
      if self.preap:
        self.frames_without_radar += 1
        if self.frames_without_radar >= PREAP_MISSING_RADAR_FRAMES and self.frames_without_radar % PREAP_MISSING_RADAR_PUBLISH_DIV == 0:
          self.pts.clear()               # no stale tracks survive a radar dropout
          ret = structs.RadarData()
          ret.errors.canError = True
          return ret
      return None
    self.frames_without_radar = 0

    ret = structs.RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True

    radar_status = self.rcp.vl['TeslaRadarSguInfo']
    if self.preap:
      # Retrofit: only a hardware failure faults (Tinkla: "ignore RADC_SGUFail on PREAP MODEL S due to retrofit").
      # NotAutopilot radar_interface.py:86-88@cc39c7fa. Tinkla still faults on SensorDirty unless behind the nosecone
      # (selfdrive/car/tesla/radar_interface.py:89-111@501c7de); NotAutopilot's HWFail-only rule is followed here.
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
    self.updated_messages.clear()
    return ret
