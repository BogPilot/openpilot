#!/usr/bin/env python3
"""BogPilot C3X release-candidate settings gate (static, no native imports, no device state).

Audits the settings inventory of a source tree WITHOUT importing openpilot (no params_pyx, no
/data, no /cache): module-level literals are read with `ast`, the generated params header and the
upstream key table are parsed as text. Every check is fail-closed: a missing file, an unparsable
literal or an unknown key type is a FAIL, never a skip.

Usage:  python3 tools/bogpilot/rc_settings_gate.py [--root REPO] [--json]
Exit 0 only when every check passes.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_TYPES = frozenset({"BOOL", "INT", "FLOAT", "STRING", "JSON", "BYTES", "TIME"})
KNOWN_FLAGS = frozenset({"PERSISTENT", "CLEAR_ON_MANAGER_START", "CLEAR_ON_ONROAD_TRANSITION",
                         "CLEAR_ON_OFFROAD_TRANSITION", "DONT_LOG", "DEVELOPMENT_ONLY", "CLEAR_ON_IGNITION_ON",
                         "BACKUP"})
VOLUME_KEYS = ("EngageVolume", "DisengageVolume", "RefuseVolume", "PromptVolume", "PromptDistractedVolume",
               "WarningSoftVolume", "WarningImmediateVolume")
# Approved owner policy (bogpilot-wave2-brief / stream 5/7): typed Params defaults.
APPROVED_PARAM_DEFAULTS = {
  "AlwaysOnLateral": "0",
  "NudgelessLaneChange": "0",
  "AdjacentLeadsUI": "1",  # t956u; never override saved OFF
  "ScreenRecorder": "1",
  "GreenLightAlert": "1",  # t968u; integrate ONLY with live alert consumer
  "LeadDepartingAlert": "1",
  "AlertVolumeControl": "0",
  "TuningLevel": "0",
  "TuningLevelConfirmed": "0",
  **dict.fromkeys(VOLUME_KEYS, "101"),
}
REQUIRED_FILE_ONLY = frozenset({"RedesignUI", "BSMFlameTracks", "SwapSpeedGraph", "DeveloperHUD", "HideAccelGraph"})
# Keys the CSC / longitudinal toggles depend on (must be typed Params).
CSC_KEYS = ("CurveSpeedController", "ShowCSCStatus", "CalibratedLateralAcceleration", "CalibrationProgress",
            "DisableOpenpilotLongitudinal", "ExperimentalMode")

# Metadata params that store nothing today ONLY because no C3X UI renders toggle_metadata.py. Each stays a
# FAIL the moment any non-test module imports toggle_metadata (see ui.metadata_unrendered).
KNOWN_UNRENDERED_UNREGISTERED = {
  "TeslaEarly": "MANAGE panel parent of early-Tesla rows; not in params_keys_bogpilot.h. Register it (owner "
                "review) or make it a non-stored BUTTON/MANAGE panel before any settings UI renders the metadata.",
}

FILES = {
  "params_py": "openpilot/common/bogpilot_params.py",
  "header": "openpilot/common/params_keys_bogpilot.h",
  "upstream_keys": "openpilot/common/params_keys.h",
  "shipping": "openpilot/common/bogpilot_shipping_defaults.py",
  "toggles": "openpilot/common/bogpilot_toggles.py",
  "ap1_profile": "openpilot/common/bogpilot_ap1_profile.py",
  "metadata": "openpilot/selfdrive/ui/bogpilot/toggle_metadata.py",
  "reset": "openpilot/system/bogpilot/toggle_reset.py",
  "manager": "openpilot/system/manager/manager.py",
  "controls_dir": "openpilot/selfdrive/controls",
}

_ROW = re.compile(r'^\s*\{"(?P<key>[^"]+)",\s*\{(?P<flags>[A-Z_ |]+),\s*(?P<type>[A-Z_]+)(?:,\s*"(?P<default>(?:[^"\\]|\\.)*)")?\}\},\s*$')


class GateError(Exception):
  pass


@dataclass
class Report:
  results: list[dict] = field(default_factory=list)

  def check(self, name: str, ok: bool, detail: str = "") -> None:
    self.results.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

  @property
  def ok(self) -> bool:
    return bool(self.results) and all(r["status"] == "PASS" for r in self.results)


def _lits(root: Path, key: str, names: tuple[str, ...]) -> dict[str, object]:
  try:
    return module_literals(_read(root, key), names)
  except GateError as e:
    raise GateError(f"{FILES[key]}: {e}") from e


def _read(root: Path, key: str) -> str:
  path = root / FILES[key]
  if not path.is_file():
    raise GateError(f"missing {FILES[key]}")
  return path.read_text(encoding="utf-8")


def module_literals(source: str, names: tuple[str, ...]) -> dict[str, object]:
  """Evaluate selected module-level literal assignments (dict/tuple/set/frozenset({...}) literals only)."""
  tree = ast.parse(source)
  found: dict[str, object] = {}
  consts: dict[str, object] = {}
  for node in tree.body:  # simple module-level constants (e.g. THEME = "BogPilot") may be referenced
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
        and isinstance(node.value, ast.Constant):
      consts[node.targets[0].id] = node.value.value
  for node in tree.body:
    targets = []
    if isinstance(node, ast.Assign):
      targets, value = node.targets, node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
      targets, value = [node.target], node.value
    for t in targets:
      if isinstance(t, ast.Name) and t.id in names:
        found[t.id] = _literal(value, consts)
  missing = [n for n in names if n not in found]
  if missing:
    raise GateError(f"literal(s) not found: {', '.join(missing)}")
  return found


def _literal(node, consts=None):
  consts = consts or {}
  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset":
    if not node.args:
      return frozenset()
    inner = node.args[0]
    # frozenset("""a b""".split())
    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "split":
      return frozenset(ast.literal_eval(inner.func.value).split())
    return frozenset(_literal(inner, consts))
  if isinstance(node, ast.Dict):
    out = {}
    for k, v in zip(node.keys, node.values):
      if k is None:  # **spread — not a plain literal
        raise GateError("dict spread in audited literal")
      out[ast.literal_eval(k)] = _literal(v, consts)
    return out
  if isinstance(node, ast.Name) and node.id in consts:
    return consts[node.id]
  if isinstance(node, ast.Tuple):
    return tuple(_literal(e, consts) for e in node.elts)
  try:
    return ast.literal_eval(node)
  except ValueError as e:
    raise GateError(f"non-literal value at line {getattr(node, 'lineno', '?')}") from e


def parse_header(text: str) -> dict[str, dict]:
  rows: dict[str, dict] = {}
  for n, line in enumerate(text.splitlines(), 1):
    s = line.strip()
    if not s or s.startswith("//"):
      continue
    m = _ROW.match(line)
    if not m:
      raise GateError(f"unparsable header row {n}")
    key = m["key"]
    if key in rows:
      raise GateError(f"duplicate header key {key}")
    rows[key] = {"flags": frozenset(f.strip() for f in m["flags"].split("|")), "type": m["type"],
                 "default": m["default"]}
  return rows


def upstream_keys(text: str) -> set[str]:
  return set(re.findall(r'^\s*\{"([^"]+)",\s*\{', text, re.M))


_FIELD = re.compile(r'^\s{4}(param|parent_param|toggle_type|button_labels|car_params)=(.+?),?\s*$', re.M)


def toggle_blocks(source: str) -> list[dict]:
  """Top-level fields of each ToggleDefinition(...) row (4-space indented keyword lines)."""
  out = []
  for chunk in source.split("ToggleDefinition(")[1:]:
    fields = {}
    for name, value in _FIELD.findall(chunk.split("\n  ),", 1)[0]):
      value = value.strip()
      if name == "toggle_type":
        value = value.removeprefix("ToggleType.")
      elif value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
      fields[name] = value
    out.append(fields)
  return out


def code_mentions(source: str, key: str) -> bool:
  """True if `key` appears as a string literal in code (docstrings and comments ignored)."""
  tree = ast.parse(source)
  docs = set()
  for node in ast.walk(tree):
    if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body \
        and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
      docs.add(id(node.body[0].value))
  return any(isinstance(n, ast.Constant) and isinstance(n.value, str) and key in n.value and id(n) not in docs
             for n in ast.walk(tree))


def run(root: Path) -> Report:
  rep = Report()
  try:
    _run(root, rep)
  except GateError as e:
    rep.check("inputs", False, str(e))
  except SyntaxError as e:
    rep.check("inputs", False, f"syntax error: {e.msg} line {e.lineno}")
  return rep


def _run(root: Path, rep: Report) -> None:
  bp = _lits(root, "params_py", ("BOGPILOT_PARAMS",))["BOGPILOT_PARAMS"]
  header = parse_header(_read(root, "header"))
  upstream = upstream_keys(_read(root, "upstream_keys"))
  ship = _lits(root, "shipping", ("PARAM_OVERRIDES", "FILE_TOGGLE_DEFAULTS"))
  tog = _lits(root, "toggles", ("FILE_ONLY_UI_KEYS", "FILE_TOGGLES"))
  ap1 = _lits(root, "ap1_profile", ("AP1_PARAM_PROFILE", "AP1_FILE_TOGGLE_PROFILE"))
  reset = _lits(root, "reset", ("UNSET_KEYS",))
  meta_src = _read(root, "metadata")
  manager_src = _read(root, "manager")

  # 1. schema: every header row uses known types/flags; registry == header (no hand edits / drift)
  bad = sorted(k for k, r in header.items() if r["type"] not in KNOWN_TYPES or not r["flags"] <= KNOWN_FLAGS)
  rep.check("header.known_schema", not bad, f"unknown type/flag: {bad}" if bad else f"{len(header)} rows")
  drift = []
  for k, (flags, typ, default, _lvl, _stock) in bp.items():
    h = header.get(k)
    want = frozenset(f.strip() for f in flags.split("|"))
    if h is None or h["type"] != typ or h["flags"] != want or (h["default"] or None) != (default or None):
      drift.append(k)
  extra = sorted(set(header) - set(bp))
  rep.check("header.matches_registry", not drift and not extra, f"drift={sorted(drift)} extra={extra}")
  dup = sorted(set(header) & upstream)
  rep.check("header.no_upstream_duplicates", not dup, str(dup))
  typed = set(header) | upstream

  # 2. approved defaults: registry, header and shipping overlay all agree
  wrong = {}
  for k, want in APPROVED_PARAM_DEFAULTS.items():
    reg = bp.get(k, (None, None, None))[2]
    hdr = header.get(k, {}).get("default")
    shp = ship["PARAM_OVERRIDES"].get(k, (want,))[0]
    if not (reg == hdr == want == str(shp)):
      wrong[k] = {"registry": reg, "header": hdr, "shipping": shp}
  rep.check("defaults.approved_policy", not wrong, json.dumps(wrong, sort_keys=True))
  rep.check("defaults.tuning_unset_on_reset", {"TuningLevel", "TuningLevelConfirmed"} <= set(reset["UNSET_KEYS"]),
            "toggle_reset UNSET_KEYS")
  profile_bad = sorted(k for k in ap1["AP1_PARAM_PROFILE"]
                       if k in APPROVED_PARAM_DEFAULTS and ap1["AP1_PARAM_PROFILE"][k] != APPROVED_PARAM_DEFAULTS[k])
  profile_bad += sorted(k for k in ("TuningLevel", "TuningLevelConfirmed", *VOLUME_KEYS, "AlertVolumeControl")
                        if k in ap1["AP1_PARAM_PROFILE"])
  rep.check("defaults.ap1_profile_respects_policy", not profile_bad, str(sorted(set(profile_bad))))

  # 3. file-only ownership: never typed Params, all declared as file toggles
  fo = set(tog["FILE_ONLY_UI_KEYS"])
  rep.check("fileonly.required_set", REQUIRED_FILE_ONLY <= fo, f"missing={sorted(REQUIRED_FILE_ONLY - fo)}")
  leaked = sorted(fo & typed)
  rep.check("fileonly.not_typed_params", not leaked, str(leaked))
  undeclared = sorted(fo - set(tog["FILE_TOGGLES"]))
  rep.check("fileonly.declared_file_toggles", not undeclared, str(undeclared))
  ship_file_mismatch = sorted(k for k, v in ship["FILE_TOGGLE_DEFAULTS"].items()
                              if k not in tog["FILE_TOGGLES"] or tog["FILE_TOGGLES"][k][0] is not v)
  rep.check("fileonly.shipping_matches_registry", not ship_file_mismatch, str(ship_file_mismatch))
  file_in_typed = sorted((set(tog["FILE_TOGGLES"]) | set(ap1["AP1_FILE_TOGGLE_PROFILE"])) & typed)
  rep.check("fileonly.file_toggles_not_typed", not file_in_typed, str(file_in_typed))

  # 4. screensaver: reserved file key, default OFF, not a typed Param, no fake C3X settings row
  ss = tog["FILE_TOGGLES"].get("OffroadScreensaver")
  rep.check("screensaver.default_off", ss is not None and ss[0] is False
            and ship["FILE_TOGGLE_DEFAULTS"].get("OffroadScreensaver", False) is False, repr(ss))
  rep.check("screensaver.not_typed", "OffroadScreensaver" not in typed, "")
  rep.check("screensaver.no_settings_row", "OffroadScreensaver" not in meta_src, "toggle_metadata.py")

  # 5. settings UI params: every stored param in toggle metadata is registered (typed or file toggle).
  # Pure grouping panels (BUTTON rows labelled MANAGE that only parent other rows) store nothing.
  blocks = toggle_blocks(meta_src)
  parents = {b["parent_param"] for b in blocks if b.get("parent_param")}
  panels = {b["param"] for b in blocks if b.get("param") in parents and b.get("toggle_type") == "BUTTON"
            and b.get("button_labels") == '["MANAGE"]'}
  meta_params = {b["param"] for b in blocks if b.get("param")} | parents
  unregistered = set(meta_params - panels - typed - set(tog["FILE_TOGGLES"]))
  known = unregistered & set(KNOWN_UNRENDERED_UNREGISTERED)
  unknown = sorted(unregistered - known)
  rep.check("ui.metadata_params_registered", bool(blocks) and not unknown,
            f"{len(meta_params)} params, {len(panels)} grouping panels; unregistered={unknown}; "
            f"known-unrendered={sorted(known)}")
  consumers = sorted(str(p.relative_to(root)) for p in (root / "openpilot").rglob("*.py")
                     if "/tests/" not in str(p) and p.name != "toggle_metadata.py"
                     and re.search(r"\btoggle_metadata\b", p.read_text(encoding="utf-8", errors="replace")))
  rep.check("ui.metadata_unrendered", not (known and consumers),
            f"consumers={consumers}" + (f"; BLOCKER if rendered: {sorted(known)}" if known else ""))

  # 6. CSC gates
  missing_csc = sorted(k for k in CSC_KEYS if k not in typed)
  rep.check("csc.keys_registered", not missing_csc, str(missing_csc))
  by_param = {b["param"]: b for b in blocks if b.get("param")}
  rep.check("csc.status_widget_child", by_param.get("ShowCSCStatus", {}).get("parent_param") == "CurveSpeedController",
            "ShowCSCStatus under CurveSpeedController")
  rep.check("csc.requires_op_long", by_param.get("CurveSpeedController", {}).get("car_params") == '["openpilot_longitudinal"]',
            "")
  controls = root / FILES["controls_dir"]
  if not controls.is_dir():
    raise GateError(f"missing {FILES['controls_dir']}")
  readers = sorted(str(p.relative_to(root)) for p in controls.rglob("*.py")
                   if "/tests/" not in str(p) and code_mentions(p.read_text(encoding="utf-8", errors="replace"), "ShowCSCStatus"))
  rep.check("csc.status_display_only", not readers, f"controls readers={readers}")

  # 7. manager defaults only fill unset keys (user edits preserved)
  fill = re.search(r'default_value = params\.get_default_value\(k\)\s*\n\s*if default_value is not None and '
                   r'params\.get\(k\) is None:\s*\n\s*params\.put\(k, default_value', manager_src)
  rep.check("manager.defaults_fill_unset_only", fill is not None, "manager_init default loop")


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
  ap.add_argument("--json", action="store_true")
  a = ap.parse_args(argv)
  rep = run(Path(a.root))
  if a.json:
    print(json.dumps({"ok": rep.ok, "results": rep.results}, indent=2))
  else:
    for r in rep.results:
      print(f"{r['status']}  {r['check']}  {r['detail']}")
    print("GATE " + ("PASS" if rep.ok else "FAIL"))
  return 0 if rep.ok else 1


if __name__ == "__main__":
  sys.exit(main())
