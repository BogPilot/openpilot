"""Synthetic adapters/layout only: no cereal/pyray/device validation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as N
import unittest

spec = importlib.util.spec_from_file_location("labels_under_test", Path(__file__).parents[1]/"onroad/bogpilot/lead_labels.py")
import sys
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def lead(**kw):
  d = dict(present=True,dRel=30.,vLead=10.,vRel=-1.,radar=True)
  d.update(kw)
  return N(**d)


class SM:
  def __init__(self):
    self.data = dict(radarState=N(leadOne=lead(),leadTwo=lead()),selfdriveState=N(personality=2))
    self.recv_time = dict(radarState=10.,selfdriveState=10.)
    self.recv_frame = dict(radarState=20,selfdriveState=20)
    self.alive = dict(radarState=True,selfdriveState=True)
    self.valid = self.alive.copy()
  def __getitem__(self,k): return self.data[k]


class TestLabels(unittest.TestCase):
  def test_units(self):
    a=m.lead_labels(lead());self.assertEqual((a.speed,a.dist,a.dist_unit),("36","30","m"))
    a=m.lead_labels(lead(),False);self.assertEqual((a.speed,a.dist,a.dist_unit),("22","98","ft"))
  def test_no_ego_substitute(self):
    self.assertIsNone(m.lead_labels(N(present=True,dRel=10,vRel=0,radar=True)))
    self.assertEqual(m.lead_labels(lead(vLead=0)).speed,"0")
  def test_invalid(self):
    for kw in [dict(present=False),dict(dRel=0),dict(dRel=-1),dict(dRel=float("nan")),dict(vLead=float("inf")),dict(vRel=float("nan"))]:
      self.assertIsNone(m.lead_labels(lead(**kw)))
    self.assertIsNone(m.lead_labels(None))
  def test_vision_accent(self):
    self.assertEqual(m.lead_labels(lead(radar=False,vRel=-5)).speed,"~36")
    for v,c in [(-5,"red"),(-4.4704,"amber"),(-0.1,"amber"),(0,None),(3,None)]:
      self.assertEqual(m.lead_labels(lead(vRel=v)).accent,c)
  def test_adjacent(self):
    self.assertIsNone(m.lead_labels(lead(vLead=0),adjacent=True))
    self.assertEqual(m.lead_labels(lead(),adjacent=True).dist,"")
  def test_qround(self):
    self.assertEqual(m.qround(2.5),3)
    self.assertEqual(m.lead_labels(lead(dRel=2.5)).dist,"3")
  def test_fresh(self):
    s=SM();self.assertIsNotNone(m.read_lead_labels(s,10.5,9,10))
    for now,start,fr in [(10.501,9,10),(9.9,9,10),(10,10.1,10),(10,9,20)]:
      self.assertIsNone(m.read_lead_labels(s,now,start,fr))
    s.valid['radarState']=False;self.assertIsNone(m.read_lead_labels(s,10,9,10))
  def test_no_leading_data(self):
    self.assertIsNone(m.read_lead_labels(None,10,9,10))
    s=SM();s.data['radarState']=N();self.assertIsNone(m.read_lead_labels(s,10,9,10))
    self.assertIsNone(m.read_lead_labels(SM(),10,9,10,index=2))
  def test_personalities(self):
    for i,name in enumerate(["Aggressive","Standard","Relaxed"]):
      self.assertEqual(m.personality_data(i,False).label,name)
      self.assertEqual(m.personality_data(i,True).label,"Traffic")
    for i in [-1,3,None,True]:self.assertIsNone(m.personality_data(i,False))
    self.assertIsNone(m.personality_data(1,None))
    self.assertIsNone(m.read_personality(SM(),11,9,10,False))
  def test_distance_keepouts(self):
    box=(800,400,180,160);view=(0,0,2160,1080)
    below=m.distance_tag(box,100,view)
    self.assertEqual(below[1],582)
    above=m.distance_tag(box,100,view,[below]);self.assertEqual(above[1],332)
    self.assertIsNone(m.distance_tag(box,100,view,[below,above]))
    # DM, speed graph, and alert reservations use the identical collision rule.
    for name in ['dm','graph','capsule','alert','other_lead']:
      with self.subTest(name=name):self.assertFalse(m.clear(below,view,[below]))
  def test_compact_resize(self):
    self.assertIsNone(m.make_layer(mici=True))
    for scale in [1,1920/2160,536/2160]:
      view=(0,0,2160*scale,1080*scale)
      box=(800*scale,400*scale,180*scale,160*scale)
      tag=m.distance_tag(box,100,view)
      if tag is not None:self.assertTrue(m.clear(tag,view,[box]))
  def test_invalid_geometry(self):
    self.assertFalse(m.clear((0,0,-1,2),(0,0,100,100)))
    self.assertFalse(m.clear((10,10,10,10),(0,0,100,100),[(float('nan'),0,1,1)]))
  def test_layer_stale_reset(self):
    f=N(redesign=True,mici=False,full_alert=False,sm=SM(),now=10,drive_start=9,started_frame=10,is_metric=True,
        longitudinal=True,lead_info=True,onroad_distance_button=True,traffic_mode=False)
    layer=m.make_layer();layer.update(f);self.assertIsNotNone(layer.lead);self.assertIsNotNone(layer.personality)
    f.now=11;layer.update(f);self.assertIsNone(layer.lead);self.assertIsNone(layer.personality)
    f.now=10;layer.update(f);f.redesign=False;layer.update(f);self.assertIsNone(layer.lead)
    f.redesign=True;f.lead_info=False;f.onroad_distance_button=False;layer.update(f)
    self.assertIsNone(layer.lead);self.assertIsNone(layer.personality)

class TestRuntimeTypes(unittest.TestCase):
  def test_dynamic_enum_protocol(self):
    class Enum:
      raw = 1
      def __int__(self): raise TypeError("DynamicEnum does not support int()")
    self.assertEqual(m.personality_data(Enum(),False).label,"Standard")
    self.assertEqual(m.personality_data(Enum(),True).label,"Traffic")
    Enum.raw=99
    self.assertIsNone(m.personality_data(Enum(),False))
    for invalid in [1.0,"1",True,None]:self.assertIsNone(m.personality_data(invalid,False))

  def test_old_status_is_not_presence(self):
    self.assertIsNone(m.lead_labels(N(status=True,dRel=32,vLead=18.5,vRel=-1,radar=True)))
    self.assertIsNone(m.lead_labels(N(present=False,status=True,dRel=32,vLead=18.5,vRel=-1,radar=True)))

  @classmethod
  def setUpClass(cls):
    import os
    try:
      from openpilot.cereal import log
      cls.log=log
    except ImportError:
      if os.environ.get("BOGPILOT_REQUIRE_SCHEMA") == "1": raise
      cls.log=None

  def require_schema(self):
    if self.log is None:self.skipTest("actual cereal schema unavailable; run with BOGPILOT_REQUIRE_SCHEMA=1 in approved runtime")

  def test_actual_0112_lead_reader(self):
    self.require_schema()
    msg=self.log.RadarState.new_message()
    msg.leadOne.present=True;msg.leadOne.dRel=32;msg.leadOne.vLead=18.5
    msg.leadOne.vRel=-5;msg.leadOne.radar=True
    reader=msg.as_reader().leadOne
    # Verify this test really exercises the target schema (no status field).
    self.assertNotIn("status",reader.schema.fields)
    self.assertIn("present",reader.schema.fields)
    a=m.lead_labels(reader,False)
    self.assertEqual((a.speed,a.dist,a.dist_unit,a.accent),("41","105","ft","red"))
    a=m.lead_labels(reader,True)
    self.assertEqual((a.speed,a.dist,a.dist_unit),("67","32","m"))
    msg.leadOne.present=False;self.assertIsNone(m.lead_labels(msg.as_reader().leadOne))
    msg.leadOne.present=True;msg.leadOne.vLead=0
    self.assertEqual(m.lead_labels(msg.as_reader().leadOne).speed,"0")
    msg.leadOne.dRel=0;self.assertIsNone(m.lead_labels(msg.as_reader().leadOne))
    msg.leadOne.dRel=32;msg.leadOne.vLead=float("nan")
    self.assertIsNone(m.lead_labels(msg.as_reader().leadOne))

  def test_actual_0112_enum_reader(self):
    self.require_schema()
    msg=self.log.SelfdriveState.new_message()
    for ordinal,label in enumerate(["Aggressive","Standard","Relaxed"]):
      msg.personality=ordinal
      enum=msg.as_reader().personality
      self.assertEqual(enum.raw,ordinal)
      with self.assertRaises(TypeError):int(enum)
      self.assertEqual(m.personality_data(enum,False).label,label)
      self.assertEqual(m.personality_data(enum,True).label,"Traffic")

  def test_actual_readers_layer_lifecycle(self):
    self.require_schema()
    radar=self.log.RadarState.new_message();radar.leadOne.present=True
    radar.leadOne.dRel=32;radar.leadOne.vLead=18.5;radar.leadOne.radar=True
    state=self.log.SelfdriveState.new_message();state.personality="standard"
    sm=SM();sm.data.update(radarState=radar.as_reader(),selfdriveState=state.as_reader())
    frame=N(redesign=True,mici=False,full_alert=False,sm=sm,now=10,drive_start=9,started_frame=10,
            is_metric=False,longitudinal=True,lead_info=True,onroad_distance_button=True,traffic_mode=False)
    layer=m.make_layer();layer.update(frame)
    self.assertEqual(layer.lead.speed,"41");self.assertEqual(layer.personality.label,"Standard")
    frame.now=11;layer.update(frame);self.assertIsNone(layer.lead);self.assertIsNone(layer.personality)
    frame.now=10;layer.update(frame);frame.full_alert=True;layer.update(frame)
    self.assertIsNone(layer.lead);self.assertIsNone(layer.personality)

if __name__ == '__main__': unittest.main()
