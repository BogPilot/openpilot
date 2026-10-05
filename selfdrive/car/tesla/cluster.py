"""AP1 instrument-cluster frames. Pure logic, no CANPacker, no messaging.

Behavior reference: Tinkla earlytesla-openpilot (tesla_unity_dev,
501c7de91b59c70510e9dc1585acfde9b7102c93) selfdrive/car/tesla/HUD_module.py
and teslacan.py create_das_status / create_das_status2 / create_lane_message,
plus earlytesla-panda (f7751e4) board/safety/safety_tesla.h TESLA_AP_FWD_MODDED
and tesla_fwd_hook. This file is BogPilot's own code. Nothing is copied from
Tesla firmware.

What Tinkla does on an AP1 car: openpilot sends its cluster values to the
panda. The panda takes each stock Mobileye frame from bus 2, keeps the stock
bits named by a per-address mask (counter, speed limits, blind spot, ...),
writes openpilot's bits over the rest, fixes the checksum, and forwards it to
bus 0. So the cluster sees stock timing and stock data, except for the fields
that make it look like Autosteer is steering.

BogPilot's panda forward hook only gets (bus, addr). It cannot edit a frame.
So the same result is built here instead: each new stock frame read from bus 2
is rebuilt from its decoded DBC signals, openpilot's fields are written over
it, and openpilot sends it on bus 0. The panda drops the stock copy only while
openpilot has recently sent that address (tesla_fwd_hook). openpilot sends
nothing for an address until it has seen a stock frame for it, so no frame is
ever made up without a stock source.

Counter: openpilot sends stock counter + 1. While substituting, the stock frame
that would have carried that counter is the one the panda drops, so the
counter seen on bus 0 stays continuous at the start and end of substitution.

Frames (opendbc/tesla_can.dbc, the DBC this tree loads):

  0x399 AutopilotStatus  (Tinkla's DBC calls it DAS_status), 2 Hz, checksum
  0x389 DAS_status2      2 Hz, checksum
  0x239 DAS_lanes        10 Hz, no checksum

Checksum, checked against Tinkla tesla_compute_checksum and AP1 rlogs:
(addr & 0xFF) + (addr >> 8) + sum(bytes 0..6), & 0xFF, in byte 7.

Not done here: 0x3e9 DAS_bodyControls (turn, hazard, headlight and wiper
requests; real stock frames carry bits no DBC signal covers), DAS_object,
DAS_telemetry, the warning matrices, pre-AP 0x659. See docs/tesla/DIVERGENCES.md.

Not a product, no warranty, driver remains responsible, comply with local law.
This does not make the car safe to drive.
"""

import os
import re
from dataclasses import dataclass

AUTOPILOT_STATUS = 0x399
DAS_STATUS2 = 0x389
DAS_LANES = 0x239
CLUSTER_ADDRS = (AUTOPILOT_STATUS, DAS_STATUS2, DAS_LANES)
CLUSTER_BUS = 0

MSG_NAMES = {
  AUTOPILOT_STATUS: "AutopilotStatus",
  DAS_STATUS2: "DAS_status2",
  DAS_LANES: "DAS_lanes",
}
COUNTER_SIGNALS = {
  AUTOPILOT_STATUS: "DAS_statusCounter",
  DAS_STATUS2: "DAS_status2Counter",
  DAS_LANES: "DAS_lanesCounter",
}
CHECKSUM_SIGNALS = {
  AUTOPILOT_STATUS: "DAS_statusChecksum",
  DAS_STATUS2: "DAS_status2Checksum",
}

# Tinkla earlytesla-panda TIME_TO_HIDE_ERRORS = 4000000 us. Its comment says
# "less than 3 seconds"; the constant is 4 s and that is what ran.
POST_DISENGAGE_NS = 4_000_000_000

# tesla_can.dbc VAL_ 921 autopilotStatus / DAS_autopilotState.
AP_STATE_UNAVAILABLE = 1
AP_STATE_AVAILABLE = 2
AP_STATE_ACTIVE_MIN = 3
# Tinkla HUD_module: DAS_op_status = 5 if enabled.
AP_STATE_OPENPILOT = 5

# VAL_ 921 DAS_autopilotHandsOnState. Tinkla: 2 by default while enabled,
# 3 for a quiet steer-required or for human steering, 5 with a chime.
HANDS_ON_NOT_DETECTED = 2
HANDS_ON_VISUAL = 3
HANDS_ON_CHIME_2 = 5

# VAL_ 921 DAS_autoLaneChangeState.
ALC_NO_LANES = 1
ALC_ONLY_L = 6
ALC_ONLY_R = 7
ALC_BOTH = 8
ALC_IN_PROGRESS_L = 9
ALC_IN_PROGRESS_R = 10

# VAL_ 921 DAS_laneDepartureWarning.
LDW_LEFT = 1
LDW_RIGHT = 2

# DAS_status2 DAS_csaState. Not in this tree's tesla_can.dbc: BO_ 905 there has
# DAS_lssState 31|3. Tinkla's tesla_can.dbc (BogGyver/opendbc 9c0b6fe) has
# DAS_relaxCruiseLimits 31|1 and DAS_csaState 32|2 (VAL 2 ENABLE, 1 AVAILABLE).
# AP1 rlogs only ever set bits 32-33 of this frame (to 0 or 1), never bit 31,
# which fits Tinkla's layout. Tinkla sends 2 while enabled.
CSA_SIGNAL = ("DAS_csaState", 32, 2)
CSA_ENABLE = 2
# VAL_ 905 DAS_longCollisionWarning 1 FCM_LONG_COLLISION_WARNING_VEHICLE_UNKNOWN.
LONG_FCW_VEHICLE = 1

# Tinkla HUD_module: IC_LANE_SCALE = 0.5, so path coefficients are scaled by
# f = 2 (C2 * f^2). DAS_virtualLaneViewRange 50 m. LineUsage 2 is FUSED.
IC_LANE_SCALE = 0.5
LANE_VIEW_RANGE_M = 50
LINE_USAGE_FUSED = 2
LINE_USAGE_REJECTED = 0


@dataclass(frozen=True)
class Signal:
  name: str
  start: int
  size: int
  factor: float
  offset: float


def _dbc_path():
  from opendbc import DBC_PATH
  return os.path.join(DBC_PATH, "tesla_can.dbc")


_SG = re.compile(r"^\s*SG_\s+(\w+)\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*\(([^,]+),([^)]+)\)")


def load_signals(path=None, addrs=CLUSTER_ADDRS):
  """{addr: {name: Signal}} from the DBC this tree ships.

  Only little-endian unsigned signals are expected in these frames. Anything
  else raises, so a changed DBC cannot be packed wrong silently.
  """
  path = path or _dbc_path()
  out = {a: {} for a in addrs}
  cur = None
  with open(path, encoding="utf-8", errors="replace") as f:
    for line in f:
      if line.startswith("BO_ "):
        addr = int(line.split()[1])
        cur = addr if addr in out else None
      elif cur is not None:
        m = _SG.match(line)
        if m is None:
          if line.strip() == "":
            cur = None
          continue
        name, start, size, le, sign, factor, offset = m.groups()
        if le != "1" or sign != "+":
          raise ValueError(f"0x{cur:x} {name}: only little-endian unsigned is supported")
        out[cur][name] = Signal(name, int(start), int(size), float(factor), float(offset))
  for a in addrs:
    if not out[a]:
      raise ValueError(f"0x{a:x} not found in {path}")
  return out


def _raw(sig, value):
  raw = int(round((float(value) - sig.offset) / sig.factor))
  return max(0, min(raw, (1 << sig.size) - 1))


def set_raw(word, start, size, raw):
  mask = ((1 << size) - 1) << start
  return (word & ~mask) | ((int(raw) << start) & mask)


def get_raw(word, start, size):
  return (word >> start) & ((1 << size) - 1)


def tesla_checksum(addr, dat):
  return ((addr & 0xFF) + ((addr >> 8) & 0xFF) + sum(dat[:7])) & 0xFF


def pack(addr, sigs, values):
  """Rebuild 8 bytes from decoded values. Unknown names are an error.

  Signals missing from values are 0. On AP1 rlogs, every bit the stock
  0x399 / 0x389 / 0x239 frames set lies inside a DBC signal of this tree, so
  rebuilding a stock frame from its decoded values gives the same bytes.
  """
  word = 0
  for name, value in values.items():
    word = set_raw(word, sigs[name].start, sigs[name].size, _raw(sigs[name], value))
  return word


def finish(addr, word, counter):
  """Set counter and, where the frame has one, the checksum. Returns bytes."""
  sigs = SIGNALS[addr]
  c = sigs[COUNTER_SIGNALS[addr]]
  word = set_raw(word, c.start, c.size, counter & ((1 << c.size) - 1))
  dat = bytearray(word.to_bytes(8, "little"))
  if addr in CHECKSUM_SIGNALS:
    k = sigs[CHECKSUM_SIGNALS[addr]]
    assert k.start == 56 and k.size == 8
    dat[7] = tesla_checksum(addr, dat)
  return bytes(dat)


def unpack(addr, dat):
  word = int.from_bytes(bytes(dat), "little")
  return {n: get_raw(word, s.start, s.size) * s.factor + s.offset for n, s in SIGNALS[addr].items()}


SIGNALS = load_signals()


@dataclass(frozen=True)
class HudInputs:
  """Everything the cluster frames read. Built in CarController from CC/CS."""
  enabled: bool
  fcw: bool
  steer_required: bool
  audible: bool
  human_steering: bool
  left_lane_depart: bool
  right_lane_depart: bool
  left_blinker: bool
  right_blinker: bool
  curvature: float


def hands_on_state(h):
  """Tinkla HUD_module DAS_hands_on_state while enabled."""
  state = HANDS_ON_NOT_DETECTED
  if h.steer_required:
    state = HANDS_ON_CHIME_2 if h.audible else HANDS_ON_VISUAL
  if h.human_steering:
    state = HANDS_ON_VISUAL
  return state


def alc_state(h, left_lane, right_lane):
  """Tinkla DAS_alca_state. Lane presence is the stock Mobileye DAS_lanes bit.

  Tinkla used openpilot lane-line probabilities. CarController does not get
  modelV2, so the stock camera's own left/right lane bits stand in.
  A lane change in progress is openpilot's (CC blinkers), 9 left, 10 right.
  """
  if h.left_blinker:
    return ALC_IN_PROGRESS_L
  if h.right_blinker:
    return ALC_IN_PROGRESS_R
  if left_lane and right_lane:
    return ALC_BOTH
  if left_lane:
    return ALC_ONLY_L
  if right_lane:
    return ALC_ONLY_R
  return ALC_NO_LANES


def lane_c2(curvature):
  """Tinkla scales the path x^2 coefficient by (1/IC_LANE_SCALE)^2.

  For a path of curvature k, y = k/2 * x^2. Left positive, as in modelV2.
  Clipped to DBC DAS_virtualLaneC2 range.
  """
  f = 1.0 / IC_LANE_SCALE
  return max(-0.0025, min(0.0025, (curvature / 2.0) * f * f))


def build_autopilot_status(stock, h, stock_lanes, mode):
  """stock: decoded AutopilotStatus values. mode 'engaged' or 'post'."""
  v = dict(stock)
  stock_state = int(round(stock.get("autopilotStatus", 0)))
  if mode == "engaged":
    # Tinkla: 5 while enabled. Stock already active (3..5) is left alone.
    if stock_state < AP_STATE_ACTIVE_MIN:
      v["autopilotStatus"] = AP_STATE_OPENPILOT
    v["DAS_autopilotHandsOnState"] = hands_on_state(h)
    left = bool(stock_lanes and stock_lanes.get("DAS_leftLaneExists", 0))
    right = bool(stock_lanes and stock_lanes.get("DAS_rightLaneExists", 0))
    v["DAS_autoLaneChangeState"] = alc_state(h, left, right)
    # Warnings: openpilot's only add to stock. A stock warning is never cleared.
    if h.fcw:
      v["DAS_forwardCollisionWarning"] = 1
    if h.left_lane_depart:
      v["DAS_laneDepartureWarning"] = LDW_LEFT
    elif h.right_lane_depart:
      v["DAS_laneDepartureWarning"] = LDW_RIGHT
  elif mode == "post":
    # Tinkla tesla_fwd_hook: for 4 s after disengage, autopilot state 2.
    # Here only when stock says UNAVAILABLE (the state openpilot caused).
    if stock_state == AP_STATE_UNAVAILABLE:
      v["autopilotStatus"] = AP_STATE_AVAILABLE
  else:
    raise ValueError(mode)
  return pack(AUTOPILOT_STATUS, SIGNALS[AUTOPILOT_STATUS], v)


def build_das_status2(stock, h, mode):
  v = dict(stock)
  # Tinkla: activationFailureStatus is openpilot's (0) while enabled, and is
  # zeroed in the 4 s window after disengage.
  v["DAS_activationFailureStatus"] = 0
  if mode == "engaged":
    v["DAS_driverInteractionLevel"] = 0
    if h.fcw:
      v["DAS_longCollisionWarning"] = LONG_FCW_VEHICLE
  elif mode != "post":
    raise ValueError(mode)
  word = pack(DAS_STATUS2, SIGNALS[DAS_STATUS2], v)
  if mode == "engaged":
    name, start, size = CSA_SIGNAL
    word = set_raw(word, start, size, CSA_ENABLE)
  return word


def build_das_lanes(stock, h):
  v = dict(stock)
  left = bool(stock.get("DAS_leftLaneExists", 0))
  right = bool(stock.get("DAS_rightLaneExists", 0))
  # Tinkla draws openpilot's path. C0 and C1 are 0 (Tinkla suppresses C1 and
  # its C0 is the model offset at x=0). C3 is 0: only curvature is known here.
  v["DAS_virtualLaneC0"] = 0.0
  v["DAS_virtualLaneC1"] = 0.0
  v["DAS_virtualLaneC2"] = lane_c2(h.curvature)
  v["DAS_virtualLaneC3"] = 0.0
  v["DAS_virtualLaneViewRange"] = LANE_VIEW_RANGE_M
  v["DAS_leftLineUsage"] = LINE_USAGE_FUSED if left else LINE_USAGE_REJECTED
  v["DAS_rightLineUsage"] = LINE_USAGE_FUSED if right else LINE_USAGE_REJECTED
  return pack(DAS_LANES, SIGNALS[DAS_LANES], v)


class ClusterController:
  """Decides, per control step, which cluster frames openpilot sends.

  update() takes the newest decoded stock frame per address that arrived this
  step (or none). Nothing is sent for an address without a new stock frame.
  While enabled: all three. For POST_DISENGAGE_NS after enabled drops:
  AutopilotStatus and DAS_status2 with Tinkla's post-disengage rewrite only.
  Otherwise nothing, and stock flows through the panda.
  """

  def __init__(self):
    self.prev_enabled = False
    self.disengaged_ns = None
    self.last_lanes = None

  def mode(self, enabled, now_nanos):
    if enabled:
      self.disengaged_ns = None
      mode = "engaged"
    else:
      if self.prev_enabled:
        self.disengaged_ns = now_nanos
      if self.disengaged_ns is not None and (now_nanos - self.disengaged_ns) < POST_DISENGAGE_NS:
        mode = "post"
      else:
        self.disengaged_ns = None
        mode = None
    self.prev_enabled = enabled
    return mode

  def update(self, h, new_stock, now_nanos):
    """new_stock: {addr: decoded values} for stock frames received this step.

    Returns [(addr, bytes)] to send on CLUSTER_BUS.
    """
    if DAS_LANES in new_stock:
      self.last_lanes = new_stock[DAS_LANES]
    mode = self.mode(h.enabled, now_nanos)
    if mode is None:
      return []

    out = []
    for addr in CLUSTER_ADDRS:
      stock = new_stock.get(addr)
      if stock is None:
        continue
      if addr == AUTOPILOT_STATUS:
        word = build_autopilot_status(stock, h, self.last_lanes, mode)
      elif addr == DAS_STATUS2:
        word = build_das_status2(stock, h, mode)
      else:
        if mode != "engaged":
          continue
        word = build_das_lanes(stock, h)
      counter = int(round(stock.get(COUNTER_SIGNALS[addr], 0))) + 1
      out.append((addr, finish(addr, word, counter)))
    return out
