"""Headless synthetic contract tests; no native renderer/device validation."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bp_lead_lockon", ROOT / "lead_lockon.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def rect(x, y, width, height):
  return NS(x=x, y=y, width=width, height=height)


def actual_box_helper():
  # Exercise the existing port's actual sizing helper without importing raylib.
  tree = ast.parse((ROOT / "redesign.py").read_text())
  func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "lead_lock_box")
  func.returns = None
  namespace = {"clamp": lambda x, lo, hi: max(lo, min(x, hi)), "rect": rect}
  exec(compile(ast.Module(body=[func], type_ignores=[]), "ported_helper", "exec"), namespace)
  return namespace["lead_lock_box"]


class SM(dict):
  pass


class TestLeadLockOn(unittest.TestCase):
  def setUp(self):
    self.now = 100.0
    self.style = NS(lead_lock_box=actual_box_helper(), rect=rect,
                    lead_distance_color=Mock(return_value="color"), paint_lead_lock=Mock())
    self.lock = module.LeadLockOn(clock=lambda: self.now, style=self.style)
    self.lead = NS(present=True, dRel=30., yRel=2., vRel=-3.)
    self.sm = SM(radarState=NS(leadOne=self.lead), carState=NS(vEgo=20.))
    names = ("carState", "modelV2", "radarState", "extrinsicsCalibration", "selfdriveState")
    self.sm.valid = dict.fromkeys(names, True)
    self.sm.alive = dict.fromkeys(names, True)
    self.sm.recv_frame = dict.fromkeys(names, 51)
    self.sm.recv_time = dict.fromkeys(names, self.now)
    self.renderer = NS(_path=NS(raw_points=[[0., 0., 0.], [30., 0., 0.5], [100., 0., 1.]]),
                       _path_offset_z=1.2, _rect=rect(0, 0, 2160, 1080),
                       _car_space_transform=[[0, 1, 0], [0, 0, 1], [1, 0, 0]],
                       _map_to_screen=Mock(return_value=(1080., 650.)))
    self.flags = dict(enabled=True, engaged=True, longitudinal=True)

  def update(self, **kw):
    return self.lock.update(self.renderer, self.sm, 50, **dict(self.flags, **kw))

  def test_real_lead_geometry_and_canonical_box(self):
    target = self.update()
    self.assertIsNotNone(target)
    self.renderer._map_to_screen.assert_called_once_with(30., -2., 1.7)
    self.assertEqual(target.box, self.style.lead_lock_box(1080., 650., 30., 2160., 1080., 0))
    self.assertEqual((target.d_rel, target.v_rel, target.v_ego), (30, -3, 20))

  def test_hide_lead_marker(self):
    self.assertIsNotNone(self.update())
    self.assertIsNone(self.update(hide_marker=True))

  def test_composer_slot_claim_is_validated(self):
    layer = module.make_layer()
    layer.lock = self.lock
    frame = NS(model_renderer=self.renderer, sm=self.sm, started_frame=50, redesign=True,
               engaged=True, longitudinal=True, hide_lead_marker=False, full_alert=False, mici=False, keepouts=[])
    self.assertTrue(layer.enabled(frame))
    frame.keepouts = [self.lock.target.box]
    self.assertFalse(layer.enabled(frame))
    frame.keepouts = []
    frame.full_alert = True
    self.assertFalse(layer.enabled(frame))
    frame.full_alert = False
    frame.hide_lead_marker = True
    self.assertFalse(layer.enabled(frame))
    frame.hide_lead_marker = False
    self.assertTrue(layer.enabled(frame))
    layer.reset()
    self.assertIsNone(self.lock.target)
    del frame.model_renderer
    self.assertFalse(layer.enabled(frame))
    self.assertIsNone(module.make_layer(mici=True))

  def test_gates_clear_previous_target(self):
    for flag in self.flags:
      with self.subTest(flag=flag):
        self.assertIsNotNone(self.update())
        self.assertIsNone(self.update(**{flag: False}))
        self.assertIsNone(self.lock.target)
    self.lead.present = False
    self.assertIsNone(self.update())

  def test_all_services_require_valid_alive_current_drive_and_fresh(self):
    for service in self.sm.valid:
      for field, bad in (("valid", False), ("alive", False), ("recv_frame", 50), ("recv_time", 0.),
                         ("recv_time", 101.), ("recv_time", float("nan"))):
        with self.subTest(service=service, field=field, bad=bad):
          values = getattr(self.sm, field)
          original = values[service]
          values[service] = bad
          self.assertIsNone(self.update())
          values[service] = original
    self.assertIsNone(self.lock.update(self.renderer, self.sm, 60, **self.flags))

  def test_lead_switch_replaces_without_latching(self):
    old = self.update()
    self.sm["radarState"].leadOne = NS(present=True, dRel=60., yRel=-3., vRel=0.)
    new = self.update()
    self.assertNotEqual(old.d_rel, new.d_rel)
    self.assertIsNone(self.lock.paint(self.renderer, old))
    self.sm["radarState"].leadOne.present = False
    self.assertIsNone(self.update())
    self.assertIsNone(self.lock.paint(self.renderer, new))

  def test_nonfinite_and_invalid_leads(self):
    for field in ("dRel", "yRel", "vRel"):
      original = getattr(self.lead, field)
      for value in (float("nan"), float("inf"), -float("inf")):
        setattr(self.lead, field, value)
        self.assertIsNone(self.update())
      setattr(self.lead, field, original)
    for d in (-1, 0, 101):
      self.lead.dRel = d
      self.assertIsNone(self.update())

  def test_invalid_path_and_depth(self):
    for points in ([], [[0, 0, 0]], [[0, 0, 0], [0, 0, 0]],
                   [[0, 0, 0], [100, 0, float("nan")]], [[100, 0, 0], [0, 0, 0]]):
      self.renderer._path.raw_points = points
      # Select NaN height at lead distance in the NaN case.
      if len(points) == 2 and points[-1][0] == 100:
        self.lead.dRel = 100
      self.assertIsNone(self.update())
    self.setUp()
    for depth in (-1., 0., float("nan")):
      self.renderer._car_space_transform[2] = [depth, 0, 0]
      self.assertIsNone(self.update())

  def test_projection_bounds_no_edge_invention(self):
    for point in (None, (float("nan"), 650), (-1, 650), (2161, 650), (1080, -1),
                  (1080, 1081), (1080, 20), (0, 650)):
      self.renderer._map_to_screen.return_value = point
      self.assertIsNone(self.update(), point)

  def test_c3x_and_c4_resize_coordinate_offsets(self):
    self.assertIsNotNone(self.update())
    old = self.lock.target
    self.renderer._rect.width = 1920
    self.assertIsNone(self.lock.paint(self.renderer, old))
    self.renderer._rect = rect(120, 50, 1920, 1080)
    self.renderer._map_to_screen.return_value = (960, 600)
    target = self.update(local=True)
    expected = self.style.lead_lock_box(1080, 650, 30, 2040, 1130, 120)
    self.assertEqual(target.box, expected)
    self.assertIsNotNone(self.update(local=False))
    self.assertNotEqual(self.lock.target.box, expected)

  def test_small_c4_camera_viewport(self):
    self.renderer._rect = rect(15, 10, 536, 240)
    self.renderer._map_to_screen.return_value = (268, 150)
    target = self.update(local=True)
    self.assertIsNotNone(target)
    self.assertTrue(module._inside(target.box, target.view, 24))
    self.assertEqual(target.box, self.style.lead_lock_box(283, 160, 30, 551, 250, 15))

  def test_draw_scissor_keepout_and_expiry(self):
    target = self.update()
    rl = NS(begin_scissor_mode=Mock(), end_scissor_mode=Mock())
    with patch.dict(sys.modules, pyray=rl):
      self.assertIsNone(self.lock.paint(self.renderer, target, keepouts=[target.box]))
      self.style.paint_lead_lock.assert_not_called()
      self.assertEqual(self.lock.paint(self.renderer, target), target.box)
      self.style.paint_lead_lock.assert_called_once_with(target.box, "", "color", target.view)
      rl.begin_scissor_mode.assert_called_once_with(0, 0, 2160, 1080)
      rl.end_scissor_mode.assert_called_once()
      self.now += .51
      self.assertIsNone(self.lock.paint(self.renderer, target))

  def test_scissor_restored_if_painter_fails(self):
    target = self.update()
    rl = NS(begin_scissor_mode=Mock(), end_scissor_mode=Mock())
    self.style.paint_lead_lock.side_effect = RuntimeError("synthetic")
    with patch.dict(sys.modules, pyray=rl), self.assertRaises(RuntimeError):
      self.lock.paint(self.renderer, target)
    rl.end_scissor_mode.assert_called_once()


if __name__ == "__main__":
  unittest.main()
