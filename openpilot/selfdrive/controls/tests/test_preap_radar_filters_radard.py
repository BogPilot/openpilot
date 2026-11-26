"""radard with the Pre-AP radar filters (docs/tesla/DIVERGENCES_preap_radar_filters.md): real RadarD, fake SubMaster."""
from opendbc.car.structs import car
from openpilot.cereal import log
from openpilot.selfdrive.controls.radard import RadarD

DT = 0.05


class Stream(dict):
  seen = {"modelV2": True}

  def __init__(self, **kw):
    super().__init__(**kw)
    self.recv_frame = {"carState": 0}
    self.logMonoTime = {"modelV2": 0}

  def all_checks(self, services=None):
    return True


def stream(v_ego, d_rel, lead_prob, y_rel=0.0, v_rel=0.0, n_points=1):
  model = log.ModelDataV2.new_message()
  model.velocity.x = [v_ego]
  for lead in model.init("leadsV3", 2):
    lead.prob = lead_prob
    for field, value in (("x", d_rel + 1.52), ("y", -y_rel), ("v", v_ego + v_rel), ("a", 0.),
                         ("xStd", 1.), ("yStd", 1.), ("vStd", 1.), ("aStd", 1.)):
      setattr(lead, field, [value])
  cs = car.CarState.new_message()
  cs.vEgo = v_ego
  radar = car.RadarData.new_message()
  pts = radar.init("points", n_points)
  if n_points:
    pts[0].trackId, pts[0].dRel, pts[0].yRel, pts[0].vRel = 7, d_rel, y_rel, v_rel
  return Stream(modelV2=model, carState=cs), radar


def drive(rd, v_of_t, d_rel, lead_prob, seconds, **kw):
  out = []
  for k in range(int(round(seconds / DT))):
    t = k * DT
    sm, rr = stream(v_of_t(t), d_rel, lead_prob, **kw)
    sm.recv_frame["carState"] = k + 1
    sm.logMonoTime["modelV2"] = int((1.0 + t) * 1e9)
    rd.update(sm, rr)
    out.append((t, rd.radar_state.leadOne.present, rd.radar_state.leadOne.radar))
  return out


def test_preap_fixed_track_while_accelerating_falls_back_to_the_camera_lead():
  base, preap = RadarD(), RadarD(preap=True)
  v = lambda t: 5.0 + 1.0 * t                                       # 5 -> 15 m/s, track fixed at 17.25 m, vRel 0 (measured)
  b = drive(base, v, 17.25, 0.9, 10.0)
  p = drive(preap, v, 17.25, 0.9, 10.0)
  assert all(present and radar for _, present, radar in b)          # stock: radar track keeps replacing the camera lead
  assert all(present and radar for t, present, radar in p if t < 4.5)
  assert all(present and not radar for t, present, radar in p if t > 5.5)   # Pre-AP: camera lead, never no lead


def test_non_preap_has_no_stuck_filter():
  assert RadarD().stuck_filter is None and RadarD(preap=False).stuck_filter is None
  assert RadarD(preap=True).stuck_filter is not None
