"""0.11.2 compatibility rules for a driving model and its warp programs (pure functions over abi.py output)."""
from __future__ import annotations

from openpilot.common.bogpilot_models.stock import STOCK_DRIVING_ABI, STOCK_WARP_ABI

# Inputs modeld feeds itself every frame; they must match the stock spec exactly.
REQUIRED_INPUTS = ("new_img", "desire", "traffic_convention", "action_t")


def _resolved(slices: dict, n: int) -> dict[str, int]:
  return {k: len(range(*slice(a, b).indices(n))) for k, (a, b) in slices.items()}


def check_driving_abi(cand: dict, stock: dict | None = None) -> list[str]:
  """Problems that make `cand` unusable by the 0.11.2 modeld (empty list = compatible)."""
  stock = STOCK_DRIVING_ABI if stock is None else stock
  bad: list[str] = []
  if cand.get("run") != stock["run"]:
    bad.append(f"run program is {cand.get('run')}, expected {stock['run']}")
  extra = sorted(set(cand.get("classes", ())) - set(stock["classes"]))
  if extra:
    bad.append("pickle references classes the stock model does not use: " + ", ".join(extra[:4]))
  ins, outs = cand["input_specs"], cand["output_specs"]
  for name in REQUIRED_INPUTS:
    if ins.get(name) != stock["input_specs"][name]:
      bad.append(f"input {name} is {ins.get(name)}, expected {stock['input_specs'][name]}")
  states = [n for n in ins if n not in REQUIRED_INPUTS]
  for name in states:
    nxt = f"next_{name}"
    if outs.get(nxt) != ins[name]:
      bad.append(f"state input {name} has no matching {nxt} output")
    if cand["output_shapes"].get(nxt) != ins[name][0]:
      bad.append(f"metadata output_shapes lacks {nxt}")
  if outs.get("outputs") != stock["output_specs"]["outputs"]:
    bad.append(f"outputs is {outs.get('outputs')}, expected {stock['output_specs']['outputs']}")
  unexpected = sorted(set(outs) - {"outputs"} - {f"next_{n}" for n in states})
  if unexpected:
    bad.append("unexpected outputs: " + ", ".join(unexpected))
  for kind, specs, shapes in (("input", ins, cand["input_shapes"]), ("output", outs, cand["output_shapes"])):
    for name, spec in specs.items():
      if shapes.get(name) != spec[0]:
        bad.append(f"metadata {kind}_shapes disagrees with {kind}_specs for {name}")
  n = stock["output_specs"]["outputs"][0][1]
  want, got = _resolved(stock["output_slices"], n), None
  try:
    got = _resolved(cand["output_slices"], n)
  except (TypeError, ValueError):
    bad.append("output_slices are not valid slices")
  if got is not None:
    if set(got) != set(want):
      bad.append("output_slices names differ from stock: " + ", ".join(sorted(set(got) ^ set(want))))
    else:
      for k in want:
        if got[k] != want[k]:
          bad.append(f"output slice {k} has {got[k]} values, expected {want[k]}")
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
