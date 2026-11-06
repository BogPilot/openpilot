"""AP1 Bosch radar (bus 1, tesla_radar_bosch_generated). 32 points, trigger 0x36e."""
from opendbc.can import CANParser
from opendbc.car import Bus, structs
from opendbc.car.interfaces import RadarInterfaceBase
from opendbc.car.tesla_ap1.values import CANBUS, DBC

NUM_POINTS = 32
TRIGGER_MSG = 878  # RadarPoint31_B


def get_radar_can_parser(CP):
  if CP.radarUnavailable or Bus.radar not in DBC[CP.carFingerprint]:
    return None
  messages = [('TeslaRadarSguInfo', 10)]
  for i in range(NUM_POINTS):
    messages.extend([(f'RadarPoint{i}_A', 16), (f'RadarPoint{i}_B', 16)])
  return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, CANBUS.radar)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.CP = CP
    self.num_points = NUM_POINTS
    self.trigger_msg = TRIGGER_MSG
    self.rcp = get_radar_can_parser(CP)
    self.updated_messages = set()

  def update(self, can_strings):
    if self.rcp is None:
      return super().update(None)

    vls = self.rcp.update(can_strings)
    self.updated_messages.update(vls)
    if self.trigger_msg not in self.updated_messages:
      return None

    ret = structs.RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True

    radar_status = self.rcp.vl['TeslaRadarSguInfo']
    if radar_status['RADC_HWFail'] or radar_status['RADC_SGUFail'] or radar_status['RADC_SensorDirty']:
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
