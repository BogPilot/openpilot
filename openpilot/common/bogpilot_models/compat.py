"""0.11.2 compatibility rules for a driving model and its warp programs (pure functions over abi.py output).

The rule is "fits the 0.11.2 driving code", not "identical to the stock model". It follows what this tree's
modeld.py actually does with a compiled driving program:

* Inputs. modeld fills exactly four inputs itself every frame: `new_img` (from the warp program), `desire`,
  `traffic_convention` and `action_t`. Every other input must be a history queue that modeld feeds back from the
  model's own `next_<name>` output. modeld would silently leave any other input at zero, so an unknown input name
  (for example sunnypilot's speed_limit, light_img, state_curve, state_calm, state_lc, state_aux, state_turn) is
  rejected, and so is a fed input with a different shape or dtype.
* History queues. Only the three 0.11.2 queues are accepted (state_img_q, state_desire_q, state_feat_q). Their
  length comes from the model metadata (modeld allocates them from input_specs), so only the history axis may
  differ from stock, up to 4x the stock length; dtype and the other axes must match.
* Outputs. One `outputs` vector [1, N] whose N comes from the metadata, plus `next_<queue>` for every queue,
  with nothing else.
* Output slices. They come from the model metadata too (modeld slices by name). Every slice the parser and
  fill_model_msg read must be present, inside [0, N], with the stock width (the parser reshapes them to fixed
  sizes). The `action` head is allowed (modeld.get_action_from_model reads action[0,0] and action[0,1] when it
  is present) with width 2 or 4; `pad` is allowed. No other names.
* The pickle may only reference classes the stock pickle uses, and its `run` program must be the same type.
"""
from __future__ import annotations

from openpilot.common.bogpilot_models.stock import STOCK_DRIVING_ABI, STOCK_WARP_ABI

# Inputs modeld feeds itself every frame; shape and dtype must match the stock spec exactly.
REQUIRED_INPUTS = ("new_img", "desire", "traffic_convention", "action_t")

# History queues modeld feeds back from next_<name>; value = the history axis that may change length.
STATE_QUEUES = {"state_img_q": 1, "state_desire_q": 0, "state_feat_q": 0}
MAX_HISTORY_FACTOR = 4

# Slices read by parse_model_outputs / fill_model_msg / modeld; widths must equal stock.
REQUIRED_SLICES = ("meta", "desire_pred", "pose", "wide_from_device_euler", "road_transform", "lane_lines",
                   "lane_lines_prob", "road_edges", "lead", "lead_prob", "hidden_state", "plan", "desire_state")
OPTIONAL_SLICES = ("action", "pad")
ACTION_WIDTHS = (2, 4)
MAX_OUTPUTS = 8192


def _resolved(slices: dict, n: int) -> dict[str, range]:
  return {k: range(*slice(a, b).indices(n)) for k, (a, b) in slices.items()}


def _shape_of(spec) -> list | None:
  return spec[0] if isinstance(spec, (list, tuple)) and len(spec) == 3 else None


def check_driving_abi(cand: dict, stock: dict | None = None, device: str | None = None) -> list[str]:
  """Problems that make `cand` unusable by the 0.11.2 modeld (empty list = it fits).

  `device` is the compile target every tensor must live on; default is the stock model's (QCOM). A CPU compile
  made for a sanity check passes device="CPU".
  """
  stock = STOCK_DRIVING_ABI if stock is None else stock
  sin, sout = stock["input_specs"], stock["output_specs"]
  device = sin["new_img"][2] if device is None else device
  bad: list[str] = []
  if cand.get("run") != stock["run"]:
    bad.append(f"run program is {cand.get('run')}, expected {stock['run']}")
  extra = sorted(set(cand.get("classes", ())) - set(stock["classes"]))
  if extra:
    bad.append("pickle references classes the stock model does not use: " + ", ".join(extra[:4]))
  ins, outs = cand.get("input_specs") or {}, cand.get("output_specs") or {}
  in_shapes, out_shapes = cand.get("input_shapes") or {}, cand.get("output_shapes") or {}

  # 1. inputs modeld fills
  for name in REQUIRED_INPUTS:
    want = [sin[name][0], sin[name][1], device]
    if ins.get(name) != want:
      bad.append(f"input {name} is {ins.get(name)}, expected {want}")

  # 2. history queues; anything else is an input modeld never feeds
  queues = []
  for name, spec in ins.items():
    if name in REQUIRED_INPUTS:
      continue
    if name not in STATE_QUEUES:
      bad.append(f"input {name} is not fed by the 0.11.2 modeld")
      continue
    queues.append(name)
    shape, s_shape = _shape_of(spec), sin[name][0]
    ax = STATE_QUEUES[name]
    if shape is None or len(shape) != len(s_shape) or spec[1] != sin[name][1] or spec[2] != device:
      bad.append(f"state input {name} is {spec}, expected rank {len(s_shape)} {sin[name][1]} on {device}")
    elif any(a != b for i, (a, b) in enumerate(zip(shape, s_shape, strict=True)) if i != ax):
      bad.append(f"state input {name} shape {shape} differs from {s_shape} outside its history axis")
    elif not 1 <= shape[ax] <= MAX_HISTORY_FACTOR * s_shape[ax]:
      bad.append(f"state input {name} history length {shape[ax]} is outside 1..{MAX_HISTORY_FACTOR * s_shape[ax]}")
    nxt = f"next_{name}"
    if outs.get(nxt) != spec:
      bad.append(f"state input {name} has no matching {nxt} output")
    if out_shapes.get(nxt) != _shape_of(spec):
      bad.append(f"metadata output_shapes lacks {nxt}")
  for name in STATE_QUEUES:
    if name not in ins:
      bad.append(f"state input {name} is missing")

  # 3. outputs
  o = outs.get("outputs")
  n = None
  o_shape = _shape_of(o)
  if (o_shape is None or len(o_shape) != 2 or o_shape[0] != 1 or o[1] != sout["outputs"][1] or o[2] != device
      or not 0 < o_shape[1] <= MAX_OUTPUTS):
    bad.append(f"outputs is {o}, expected [[1, N], {sout['outputs'][1]!r}, {device!r}] with 0 < N <= {MAX_OUTPUTS}")
  else:
    n = o_shape[1]
  unexpected = sorted(set(outs) - {"outputs"} - {f"next_{q}" for q in queues})
  if unexpected:
    bad.append("unexpected outputs: " + ", ".join(unexpected))
  for kind, specs, shapes in (("input", ins, in_shapes), ("output", outs, out_shapes)):
    for name, spec in specs.items():
      if shapes.get(name) != _shape_of(spec):
        bad.append(f"metadata {kind}_shapes disagrees with {kind}_specs for {name}")

  # 4. output slices (sizes from metadata, widths from what the parser reads)
  if n is None:
    return bad
  stock_n = sout["outputs"][0][1]
  want = {k: len(r) for k, r in _resolved(stock["output_slices"], stock_n).items()}
  try:
    got = _resolved(cand.get("output_slices") or {}, n)
  except (TypeError, ValueError):
    bad.append("output_slices are not valid slices")
    return bad
  missing = [k for k in REQUIRED_SLICES if k not in got]
  if missing:
    bad.append("output_slices lack " + ", ".join(missing))
  unknown = sorted(set(got) - set(REQUIRED_SLICES) - set(OPTIONAL_SLICES))
  if unknown:
    bad.append("output_slices the 0.11.2 parser does not read: " + ", ".join(unknown))
  for k in REQUIRED_SLICES:
    if k in got and len(got[k]) != want[k]:
      bad.append(f"output slice {k} has {len(got[k])} values, expected {want[k]}")
  for k, (a, b) in (cand.get("output_slices") or {}).items():
    for x in (a, b):
      if x is not None and not -n <= x <= n:
        bad.append(f"output slice {k} reaches past the {n}-wide outputs")
        break
  if "action" in got and len(got["action"]) not in ACTION_WIDTHS:
    bad.append(f"output slice action has {len(got['action'])} values, expected one of {ACTION_WIDTHS}")
  return bad


def check_warp_abi(cand: dict, role: str, stock: dict | None = None) -> list[str]:
  stock = STOCK_WARP_ABI if stock is None else stock
  if role not in stock:
    return [f"unknown warp role {role}"]
  s = stock[role]
  bad: list[str] = []
  if cand.get("run") != s["run"]:
    bad.append(f"warp program is {cand.get('run')}, expected {s['run']}")
  extra = sorted(set(cand.get("classes", ())) - set(s["classes"]))
  if extra:
    bad.append("warp pickle references classes the stock warp does not use: " + ", ".join(extra[:4]))
  if cand["input_specs"] != s["input_specs"]:
    bad.append(f"warp inputs are {cand['input_specs']}, expected {s['input_specs']}")
  return bad
