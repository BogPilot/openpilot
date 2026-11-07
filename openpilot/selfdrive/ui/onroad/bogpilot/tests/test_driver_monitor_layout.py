import unittest
from types import SimpleNamespace as NS
from openpilot.selfdrive.ui.onroad.bogpilot.driver_monitor_layout import Box, placement, fresh
from openpilot.selfdrive.ui.onroad.bogpilot.driver_monitor import make_layer

class TestDriverMonitor(unittest.TestCase):
  def test_daily_centres(self):
    r=Box(30,30,2100,1020)
    self.assertEqual(placement(r),Box(60,855,150,150))
    self.assertEqual(placement(r,personality=True),Box(206,855,150,150))
    self.assertEqual(placement(r,True,True),Box(1804,855,150,150))
  def test_capsule_graph_alerts(self):
    r=Box(30,30,2100,1020)
    for speed_y, graph_y in [(24,228),(292,24)]:
      keeps=[(60,30+speed_y,710,176),(60,30+graph_y,560,240),(248,534,1732,245)]
      self.assertIsNotNone(placement(r,personality=True,keepouts=keeps))
    self.assertIsNone(placement(r,keepouts=[r]))
  def test_compact_and_resize_fallback(self):
    for r in [Box(0,0,536,240),Box(0,0,1100,600),Box(0,0,2100,900)]:
      self.assertIsNone(placement(r))
    self.assertIsNone(make_layer(True))
  def sm(self):
    keys=['driverStateV2','driverMonitoringState']
    return NS(alive=dict.fromkeys(keys,True),valid=dict.fromkeys(keys,True),
              recv_frame=dict.fromkeys(keys,21),recv_time=dict.fromkeys(keys,10.0))
  def test_fresh(self):
    self.assertTrue(fresh(self.sm(),10.5,20,9.0))
    for field,value in [('alive',False),('valid',False),('recv_frame',20),('recv_time',8.0),('recv_time',11.0),('recv_time',float('nan'))]:
      sm=self.sm();getattr(sm,field)['driverMonitoringState']=value
      self.assertFalse(fresh(sm,10.1,20,9.0))
    self.assertFalse(fresh(self.sm(),10.51,20,9))
    self.assertFalse(fresh(None,10.0,20,9))
  def frame(self):
    return NS(redesign=True,mici=False,full_alert=False,alert=None,sm=self.sm(),now=10.1,
              started_frame=20,drive_start=9,rect=Box(30,30,2100,1020),rhd=False,keepouts=[])
  def test_gates_and_reset(self):
    l=make_layer();f=self.frame();self.assertTrue(l.enabled(f))
    for key,value in [('redesign',False),('mici',True),('full_alert',True),('alert',NS(size=1))]:
      f=self.frame();setattr(f,key,value);self.assertFalse(l.enabled(f))
    l.reset();self.assertIsNone(l.bounds);self.assertIsNone(l._renderer)
    self.assertEqual(l.replaces,frozenset({'driver_state'}))

if __name__=='__main__':unittest.main()
