"""Pure-python message doubles for the CSC / curve-brake planner pieces (no capnp, no solver)."""
import types

import numpy as np

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants

T = np.array(ModelConstants.T_IDXS)


class Store:
  """ParamStore double: CurveSpeedController on, no learned curvature data."""
  def __init__(self, on=True):
    self.on = on

  def toggle_bool(self, key):
    return self.on

  def get(self, key, default=None):
    return default if default is not None else ""

  def put(self, key, value):
    pass


class SM(dict):
  def __init__(self, msgs, mono_ns=None):
    super().__init__(msgs)
    self.valid = dict.fromkeys(msgs, True)
    self.alive = dict.fromkeys(msgs, True)
    self.logMonoTime = {"modelV2": mono_ns} if mono_ns is not None else {}


def ns(**kw):
  return types.SimpleNamespace(**kw)


def csc_sm(v_ego, k=0.0, t_start=0.0, yaw=None, blinker=False, enabled=True, lead=None, lane_change=False, mono_ns=None,
           standstill=False, x_scale=1.0):
  """modelV2 path at constant model speed v_ego whose curvature is k (1/m) from t_start on; yaw overrides the rate."""
  n = len(T)
  v = np.full(n, float(v_ego))
  x = np.cumsum(np.concatenate([[0.0], np.diff(T) * (v[:-1] + v[1:]) / 2])) * x_scale
  rate = np.where(T >= t_start, k * v, 0.0) if yaw is None else np.asarray(yaw, dtype=float)
  model = ns(position=ns(x=[float(a) for a in x]), velocity=ns(x=[float(a) for a in v]),
             orientationRate=ns(z=[float(a) for a in rate], t=[float(a) for a in T]),
             meta=ns(laneChangeState=1 if lane_change else 0))
  lead_msg = ns(present=False, dRel=0.0, vRel=0.0) if lead is None else ns(present=True, dRel=lead[0], vRel=lead[1] - v_ego)
  return SM({
    "modelV2": model,
    "carState": ns(leftBlinker=blinker, rightBlinker=False, standstill=standstill),
    "radarState": ns(leadOne=lead_msg),
    "selfdriveState": ns(enabled=enabled),
    "controlsState": ns(curvature=0.0),
    "carControl": ns(longActive=enabled),
  }, mono_ns=mono_ns)
