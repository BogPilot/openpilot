"""get_action_from_model: the stock (plan) path is untouched; the action-head path (Cheddar) uses upstream's 2.5 m/s
low-speed floor (openpilot 0c40995cd, #39182), which upstream shipped before Cheddar (b3ab22efe)."""
import unittest

import numpy as np

from openpilot.cereal import log
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.modeld.modeld import get_action_from_model


def plan_output():
  plan = np.zeros((1, ModelConstants.IDX_N, ModelConstants.PLAN_WIDTH), dtype=np.float32)
  return {"plan": plan}


class TestActionHead(unittest.TestCase):
  def test_action_head_low_speed_floor_is_2_5(self):
    out = {"action": np.array([[0.5, 0.2, 0.0, 0.0]], dtype=np.float32)}
    a = get_action_from_model(out, log.ModelDataV2.Action(), 0.2, 0.2, v_ego=1.0)
    self.assertAlmostEqual(a.desiredCurvature, 0.5 / 2.5 ** 2, places=6)
    a = get_action_from_model(out, log.ModelDataV2.Action(), 0.2, 0.2, v_ego=10.0)
    self.assertAlmostEqual(a.desiredCurvature, 0.5 / 100.0, places=6)

  def test_action_head_reads_first_two_values_only(self):
    for width in (2, 4):
      out = {"action": np.array([[1.0, -0.5] + [99.0] * (width - 2)], dtype=np.float32)}
      a = get_action_from_model(out, log.ModelDataV2.Action(), 0.2, 0.2, v_ego=20.0)
      self.assertAlmostEqual(a.desiredCurvature, 1.0 / 400.0, places=6)
      self.assertLess(a.desiredAcceleration, 0.0)

  def test_plan_path_has_no_floor_change(self):
    a = get_action_from_model(plan_output(), log.ModelDataV2.Action(), 0.2, 0.2, v_ego=1.0)
    self.assertEqual(a.desiredCurvature, 0.0)
    self.assertEqual(a.desiredAcceleration, 0.0)


if __name__ == "__main__":
  unittest.main()
