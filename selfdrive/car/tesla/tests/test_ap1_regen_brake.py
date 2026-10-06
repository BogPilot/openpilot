"""AP1 regen-sized comfort braking: toggle, distance math, MPC obstacle wiring.

The on-device acados / opendbc .so files are AArch64, so this host cannot load
LongitudinalMpc's real solver. Tests mock the cython solver and car.interfaces
to exercise the Python-side comfort_brake path, and use the closed-form
desired_follow_distance math for approach shape (earlier / gentler / same gap).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

# --- Import isolation (AArch64 .so not loadable on this host) ----------------
_ACCEL_MIN = -3.5
_ACCEL_MAX = 2.0
if "openpilot.selfdrive.car.interfaces" not in sys.modules:
  _iface = MagicMock()
  _iface.ACCEL_MIN = _ACCEL_MIN
  _iface.ACCEL_MAX = _ACCEL_MAX
  sys.modules["openpilot.selfdrive.car.interfaces"] = _iface

_solver_mod = "openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.c_generated_code.acados_ocp_solver_pyx"
if _solver_mod not in sys.modules:
  _solver_ns = MagicMock()
  _solver_ns.AcadosOcpSolverCython = MagicMock(name="AcadosOcpSolverCython")
  sys.modules[_solver_mod] = _solver_ns

if "casadi" not in sys.modules:
  sys.modules["casadi"] = MagicMock()

from cereal import log  # noqa: E402
from openpilot.selfdrive.car.tesla.regen_brake import (  # noqa: E402
  AP1_REGEN_COMFORT_BRAKE,
  STOCK_COMFORT_BRAKE,
  ap1_comfort_brake,
  regen_comfort_brake_enabled,
  set_regen_comfort_brake,
)
from openpilot.selfdrive.car.tesla.values import CAR  # noqa: E402
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import (  # noqa: E402
  COMFORT_BRAKE,
  N,
  PARAM_DIM,
  STOP_DISTANCE,
  T_IDXS,
  LongitudinalMpc,
  comfort_distance_delta,
  desired_follow_distance,
  get_T_FOLLOW,
  get_safe_obstacle_distance,
)


# --- Toggle -----------------------------------------------------------------

def test_stock_comfort_brake_matches_mpc_constant():
  assert STOCK_COMFORT_BRAKE == COMFORT_BRAKE
  assert AP1_REGEN_COMFORT_BRAKE < COMFORT_BRAKE
  assert 1.0 <= AP1_REGEN_COMFORT_BRAKE <= 1.5


def test_regen_toggle_default_on_for_ap1_only(tmp_path, monkeypatch):
  import openpilot.selfdrive.car.tesla.regen_brake as rb
  path = tmp_path / "RegenComfortBrake"
  monkeypatch.setattr(rb, "_regen_comfort_path", path)

  assert regen_comfort_brake_enabled(CAR.TESLA_AP1_MODELS) is True
  assert ap1_comfort_brake(CAR.TESLA_AP1_MODELS) == AP1_REGEN_COMFORT_BRAKE

  assert regen_comfort_brake_enabled(CAR.TESLA_AP2_MODELS) is False
  assert ap1_comfort_brake(CAR.TESLA_AP2_MODELS) == COMFORT_BRAKE
  assert regen_comfort_brake_enabled("HONDA_CIVIC") is False
  assert regen_comfort_brake_enabled(None) is False


def test_regen_toggle_explicit_off_on(tmp_path, monkeypatch):
  import openpilot.selfdrive.car.tesla.regen_brake as rb
  path = tmp_path / "RegenComfortBrake"
  monkeypatch.setattr(rb, "_regen_comfort_path", path)

  set_regen_comfort_brake(False, path=path)
  assert regen_comfort_brake_enabled(CAR.TESLA_AP1_MODELS) is False
  assert ap1_comfort_brake(CAR.TESLA_AP1_MODELS) == COMFORT_BRAKE

  set_regen_comfort_brake(True, path=path)
  assert regen_comfort_brake_enabled(CAR.TESLA_AP1_MODELS) is True

  assert regen_comfort_brake_enabled(CAR.TESLA_AP1_MODELS, stored="0") is False
  assert regen_comfort_brake_enabled(CAR.TESLA_AP1_MODELS, stored="1") is True


def test_comfort_distance_delta_zero_at_stop_and_scales_with_v():
  assert comfort_distance_delta(0.0, AP1_REGEN_COMFORT_BRAKE) == 0.0
  assert comfort_distance_delta(10.0, COMFORT_BRAKE) == 0.0
  d10 = float(comfort_distance_delta(10.0, AP1_REGEN_COMFORT_BRAKE))
  d20 = float(comfort_distance_delta(20.0, AP1_REGEN_COMFORT_BRAKE))
  assert d10 > 0
  assert d20 == pytest.approx(4.0 * d10, rel=1e-6)
  assert desired_follow_distance(0.0, 0.0, 1.45, comfort_brake=AP1_REGEN_COMFORT_BRAKE) == STOP_DISTANCE
  assert desired_follow_distance(0.0, 0.0, 1.45, comfort_brake=COMFORT_BRAKE) == STOP_DISTANCE


# --- Analytical approach shape (closed-form desired distance) ---------------

def brake_start_distance(v_mps, comfort_brake, t_follow=None):
  """Distance at which a comfort approach to a stopped lead should begin braking.

  Matches get_safe_obstacle_distance for v_lead=0 (desired gap at current speed).
  """
  if t_follow is None:
    t_follow = get_T_FOLLOW()
  return float(get_safe_obstacle_distance(v_mps, t_follow, comfort_brake))


@pytest.mark.parametrize("v0_mph", [24, 35, 45])
def test_stopped_lead_desired_distance_earlier_gentler_same_gap(v0_mph):
  v0 = v0_mph * 0.44704
  t_follow = get_T_FOLLOW()
  d_stock = brake_start_distance(v0, COMFORT_BRAKE, t_follow)
  d_regen = brake_start_distance(v0, AP1_REGEN_COMFORT_BRAKE, t_follow)

  # Regen comfort starts braking farther out
  assert d_regen > d_stock + 5.0, f"v={v0_mph}: regen {d_regen:.1f} vs stock {d_stock:.1f}"

  # Peak comfort decel is the comfort_brake itself (design target)
  assert AP1_REGEN_COMFORT_BRAKE <= 1.25
  assert AP1_REGEN_COMFORT_BRAKE < COMFORT_BRAKE

  # Final stop gap identical (v=0)
  assert desired_follow_distance(0.0, 0.0, t_follow, COMFORT_BRAKE) == \
         desired_follow_distance(0.0, 0.0, t_follow, AP1_REGEN_COMFORT_BRAKE) == STOP_DISTANCE

  # Stopping distance at constant comfort decel from v0 to the stop gap
  # regen needs more runway: v^2/(2*cb) is larger when cb is smaller
  stop_run_stock = (v0 ** 2) / (2 * COMFORT_BRAKE)
  stop_run_regen = (v0 ** 2) / (2 * AP1_REGEN_COMFORT_BRAKE)
  assert stop_run_regen > stop_run_stock
  assert d_regen - d_stock == pytest.approx(stop_run_regen - stop_run_stock, rel=1e-6)


def test_non_tesla_comfort_brake_unchanged():
  assert ap1_comfort_brake("HONDA_CIVIC") == COMFORT_BRAKE
  assert ap1_comfort_brake(CAR.TESLA_AP2_MODELS) == COMFORT_BRAKE
  assert ap1_comfort_brake(CAR.TESLA_AP1_MODELS, stored="0") == COMFORT_BRAKE


# --- Mocked MPC: obstacle adjustment + a_min authority ----------------------

class _FakeSolver:
  def __init__(self, *args, **kwargs):
    self.p = {}
    self.x = {}
    self.yref = {}
    self.W = {}
    self.Zl = {}
    self.lbx0 = None
    self.ubx0 = None
    self._stats = {"time_tot": [0.0], "time_qp": [0.0], "time_lin": [0.0], "time_sim": [0.0]}

  def reset(self):
    pass

  def cost_set(self, i, name, val):
    self.W[(i, name)] = val

  def set(self, i, name, val):
    if name == "p":
      self.p[i] = np.array(val, dtype=float).copy()
    elif name == "x":
      self.x[i] = np.array(val, dtype=float).copy()
    elif name == "yref":
      self.yref[i] = np.array(val, dtype=float).copy()

  def constraints_set(self, i, name, val):
    if name == "lbx":
      self.lbx0 = np.array(val, dtype=float).copy()
    elif name == "ubx":
      self.ubx0 = np.array(val, dtype=float).copy()

  def solve(self):
    # Trivial feasible coast: keep current state, zero jerk
    return 0

  def get_stats(self, name):
    return self._stats[name]

  def get(self, i, name):
    if name == "x":
      # return whatever was set as x0-ish; LongitudinalMpc overwrites from solve
      if self.lbx0 is not None:
        return self.lbx0.copy()
      return np.zeros(3)
    if name == "u":
      return np.zeros(1)
    raise KeyError(name)


def _install_fake_solver(monkeypatch):
  import openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc as lm
  monkeypatch.setattr(lm, "AcadosOcpSolverCython", _FakeSolver)


def _toggles():
  return SimpleNamespace(
    lead_detection_probability=0.5,
    human_following=False,
    model_version="v8",
  )


def _model_with_lead(prob=0.95):
  lead = log.ModelDataV2.LeadDataV3.new_message()
  lead.prob = float(prob)
  lead.x = [0.0] * 6
  lead.v = [0.0] * 6
  model = log.ModelDataV2.new_message()
  model.leadsV3 = [lead, lead]
  return model


def _radar_stopped(d_rel, v_lead=0.0, a_lead=0.0):
  rs = log.RadarState.new_message()
  for attr in ("leadOne", "leadTwo"):
    lead = getattr(rs, attr)
    lead.dRel = float(d_rel)
    lead.vLead = float(v_lead)
    lead.vLeadK = float(v_lead)
    lead.aLeadK = float(a_lead)
    lead.aLeadTau = 1.5
    lead.status = True
    lead.modelProb = 0.95
  return rs


def _mpc_params_for(monkeypatch, v_ego, d_rel, comfort_brake, a_lead=0.0, v_lead=0.0):
  _install_fake_solver(monkeypatch)
  mpc = LongitudinalMpc()
  mpc.mode = "acc"
  mpc.set_weights(prev_accel_constraint=False)
  mpc.set_cur_state(v_ego, 0.0)
  z = np.zeros(N + 1)
  mpc.update(
    v_ego + 5.0, _model_with_lead(), _radar_stopped(d_rel, v_lead, a_lead),
    z, z, z, z, get_T_FOLLOW(), _ACCEL_MIN, _ACCEL_MAX, _toggles(), False,
    comfort_brake=comfort_brake,
  )
  return mpc


def test_mpc_lead_obstacle_shrunk_for_regen_comfort(monkeypatch):
  """Runtime path: lower comfort_brake reduces lead x_obstacle by comfort_distance_delta."""
  v_ego = 15.0  # m/s
  # Must be inside cruise fake-obstacle so source is lead0/lead1
  d_rel = 40.0
  stock = _mpc_params_for(monkeypatch, v_ego, d_rel, COMFORT_BRAKE)
  regen = _mpc_params_for(monkeypatch, v_ego, d_rel, AP1_REGEN_COMFORT_BRAKE)

  # a_min hard limit identical (full braking authority)
  assert stock.params[0, 0] == pytest.approx(_ACCEL_MIN)
  assert regen.params[0, 0] == pytest.approx(_ACCEL_MIN)

  assert stock.source.startswith("lead"), stock.source
  assert regen.source.startswith("lead"), regen.source

  # Regen x_obstacle at h=0 is smaller by ~delta(v_ego)
  expected_delta = float(comfort_distance_delta(v_ego, AP1_REGEN_COMFORT_BRAKE))
  assert expected_delta > 5.0
  assert regen.params[0, 2] == pytest.approx(stock.params[0, 2] - expected_delta, abs=1.5)
  assert stock.params[0, 2] == pytest.approx(d_rel, abs=0.5)


def test_mpc_cut_in_keeps_full_accel_min(monkeypatch):
  """Close cut-in: a_min stays ACCEL_MIN for both stock and regen comfort."""
  for cb in (COMFORT_BRAKE, AP1_REGEN_COMFORT_BRAKE):
    mpc = _mpc_params_for(monkeypatch, v_ego=20.0, d_rel=12.0, comfort_brake=cb)
    assert mpc.params[0, 0] == pytest.approx(_ACCEL_MIN)
    assert np.all(mpc.params[:, 0] == pytest.approx(_ACCEL_MIN))


def test_mpc_hard_braking_lead_keeps_full_accel_min(monkeypatch):
  for cb in (COMFORT_BRAKE, AP1_REGEN_COMFORT_BRAKE):
    mpc = _mpc_params_for(
      monkeypatch, v_ego=25.0, d_rel=40.0, comfort_brake=cb, a_lead=-4.0, v_lead=25.0)
    assert mpc.params[0, 0] == pytest.approx(_ACCEL_MIN)


def test_mpc_stock_comfort_matches_no_delta(monkeypatch):
  """Passing stock COMFORT_BRAKE must not alter lead obstacles vs baseline math."""
  v_ego = 12.0
  d_rel = 35.0  # inside cruise obstacle so lead is active
  mpc = _mpc_params_for(monkeypatch, v_ego, d_rel, COMFORT_BRAKE)
  assert mpc.source.startswith("lead"), mpc.source
  # stopped lead: obstacle ~= d_rel. No delta applied at stock comfort.
  assert mpc.params[0, 2] == pytest.approx(d_rel, abs=0.5)


# --- Source / wiring / panda unchanged --------------------------------------

def test_planner_wires_ap1_comfort_brake_only():
  from pathlib import Path
  root = Path(__file__).resolve().parents[4]
  planner = (root / "selfdrive/controls/lib/longitudinal_planner.py").read_text()
  assert "ap1_comfort_brake" in planner
  assert "comfort_brake=comfort_brake" in planner
  long_mpc = (root / "selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py").read_text()
  assert "comfort_brake=COMFORT_BRAKE" in long_mpc
  assert "comfort_distance_delta" in long_mpc
  # Generated solver still embeds stock 2.5 (no regen constant in C)
  # Generated cost embeds v^2/(2*2.5) as v^2/5. and STOP_DISTANCE as 6.
  cost_c = (root / "selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/long_cost/long_cost_y_fun.c").read_text()
  assert "a4=5.;" in cost_c  # 2 * COMFORT_BRAKE
  assert "a4=6.;" in cost_c  # STOP_DISTANCE
  assert "1.2" not in cost_c  # AP1 regen comfort not baked into generated solver
  safety = (root / "panda/board/safety/safety_tesla.h").read_text()
  assert "RegenComfort" not in safety
  assert "COMFORT_BRAKE" not in safety
  # Braking floor constant in interfaces unchanged by this feature
  iface = (root / "selfdrive/car/interfaces.py").read_text()
  assert "ACCEL_MIN = -3.5" in iface


def test_following_uses_ap1_comfort_for_desired_distance():
  from pathlib import Path
  src = (Path(__file__).resolve().parents[4] / "frogpilot/controls/lib/frogpilot_following.py").read_text()
  assert "ap1_comfort_brake" in src
  assert "comfort_brake=comfort_brake" in src
