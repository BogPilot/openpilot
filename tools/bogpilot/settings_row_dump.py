#!/usr/bin/env python3
"""Row-visibility dump of every BogPilot settings page and MANAGE / OPEN submenu (test tooling, no product code).

For each scenario (car x Tuning Level x param profile) it builds every page of the BogPilot menu from a clean
temporary Params / file store, renders a few headless frames, and writes one line per row:

  path | n | label | widget | vis | shown | row_en | act_en | value | key | extra

  vis     ListItem.is_visible (set_visible / nesting / level gate)
  shown   the row was rendered in the last frame (its page or submenu is the one on screen)
  row_en  the row's own enabled state (greyed when 0)
  act_en  the action's enabled state (locked when 0; taps ignored)
  value   resolved value text (toggle state, button labels, text value, selected index)
  key     the help / param key attached to the row, if any
  extra   only for rows that expose them: hint text, non-default highlight

Submenus are reached by calling the row's own MANAGE / OPEN callback on a freshly built page, never a write path.
Each scenario runs in its own process with its own temporary HOME, PARAMS_ROOT and BOGPILOT_PARAMS_DIR, so nothing persists.
Needs a raylib window: run with RAYLIB_BACKEND=headless (or a virtual display).

  python tools/bogpilot/settings_row_dump.py --out DIR --tag base          # all scenarios
  python tools/bogpilot/settings_row_dump.py --one CAR LEVEL PROFILE FILE   # one scenario (used internally)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

# nocar: no CarParams yet. ap1 / preap: known car as the interface reports it (longitudinal off).
# ap1long / preaplong: the same car with openpilot longitudinal on. nonap1: a known car that is not a legacy Tesla.
CARS = ("nocar", "ap1", "ap1long", "preap", "preaplong", "nonap1")
LEVELS = (0, 1, 2, 3)
# defaults: untouched install. alertvol: Alert Volume Controller on, one row away from its default.
# nudgeless: Automatic Lane Changes on and its panel adopted, so Delay/Width and their Reset can be dumped.
# personalities: Driving Personalities on, so Follow / jerk rows and their section resets can be dumped.
# One Follow value is away from its default so the highlight can be dumped.
PROFILES = {
  "defaults": {},
  "alertvol": {"AlertVolumeControl": "1", "EngageVolume": "60"},
  # steer: Advanced Lateral Tuning and Quality of Life on, some values away from their defaults.
  "steer": {"AdvancedLateralTune": "1", "QOLLateral": "1", "SteerRatio": "16", "PauseLateralSpeed": "20",
            "OverrideSensitivity": "4"},
  "personalities": {"CustomPersonalities": "1", "RelaxedFollow": "2.00"},
  "nudgeless": {"NudgelessLaneChange": "1", "Phase3LaneChangeEnabled": "1"},
  # gasbrake: the Gas / Brake sections on (adopted), one value per section away from its default.
  "gasbrake": {"AdvancedLongitudinalTune": "1", "Phase3AdvancedLongEnabled": "1", "MaxDesiredAcceleration": "3.0",
               "ConditionalExperimental": "1", "Phase3CEMEnabled": "1", "CESpeed": "20",
               "QOLLongitudinal": "1", "IncreasedStoppedDistance": "2", "Phase3StoppedDistanceEnabled": "1",
               "SpeedLimitController": "1", "Phase3SpeedLimitEnabled": "1", "Offset1": "7", "SLCLookaheadLower": "8",
               "AP1TapFromZeroMph": "20"},
}
# Profiles seeded through ParamStore (compiled Params keys go to Params, the rest to the file store). Each of their
# scenarios gets its own temp PARAMS_ROOT, so a seeded Params key never carries over into a later scenario.
STORE_PROFILES = ("steer", "personalities", "nudgeless", "gasbrake")
NAV_WORDS = ("MANAGE", "OPEN")
MAX_DEPTH = 3
FRAMES = 3


def _make_cp(car):
  if car == "nocar":
    return None
  if car.startswith(("ap1", "preap")):
    from opendbc.car.tesla_ap1.interface import CarInterface
    from opendbc.car.tesla_ap1.values import CAR
    cp = CarInterface.get_non_essential_params(CAR.TESLA_AP1_MODELS if car.startswith("ap1") else CAR.TESLA_PREAP_MODELS)
    if car.endswith("long"):   # same car with openpilot longitudinal on, as the menu tests set it
      cp.openpilotLongitudinalControl = True
    return cp
  from opendbc.car.toyota.interface import CarInterface
  from opendbc.car.toyota.values import CAR
  return CarInterface.get_non_essential_params(CAR.TOYOTA_COROLLA_TSS2)


def _res(v):
  try:
    v = v() if callable(v) else v
  except Exception as e:  # never raise from a dump
    return f"<err {type(e).__name__}>"
  return "" if v is None else str(v)


def _clean(s):
  return " ".join(str(s).replace("|", "/").split())[:120]


class Walker:
  def __init__(self, rl, gui_app):
    from openpilot.system.ui.widgets import Widget
    from openpilot.system.ui.widgets.list_view import ListItem
    self.rl, self.gui_app, self.Widget, self.ListItem = rl, gui_app, Widget, ListItem
    self.rendered: dict[int, object] = {}
    original = ListItem.render
    walker = self

    def render(item, *a, **k):
      if item.is_visible:
        walker.rendered[id(item)] = item
      return original(item, *a, **k)
    ListItem.render = render

  def draw(self, widget):
    rect = self.rl.Rectangle(0, 0, self.gui_app.width, self.gui_app.height)
    for _ in range(FRAMES):
      self.rendered = {}
      self.rl.begin_drawing()
      try:
        widget.render(rect)
      finally:
        self.rl.end_drawing()

  def rows(self, root):
    """Scroller items in order (any widget type), then any other reachable ListItem."""
    from openpilot.system.ui.widgets.scroller_tici import Scroller
    seen, order, scrollers = set(), [], []
    stack = [(root, 0)]
    visited = set()
    while stack:
      obj, depth = stack.pop()
      if id(obj) in visited or depth > 8:
        continue
      visited.add(id(obj))
      if isinstance(obj, Scroller):
        scrollers.append(obj)
      if isinstance(obj, self.ListItem):
        order.append(obj)
        continue          # a row's internals are not more rows
      if isinstance(obj, self.Widget) or depth == 0 or (hasattr(obj, "__dict__") and not callable(obj)
                                                        and type(obj).__module__.startswith("openpilot.selfdrive.ui")):
        children = list(vars(obj).values()) if hasattr(obj, "__dict__") else []
        for c in list(children):
          cells = getattr(c, "__closure__", None) if callable(c) else None
          children.extend(x.cell_contents for x in (cells or ()) if _has_contents(x))
      elif isinstance(obj, (list, tuple, set)):
        children = list(obj)
      elif isinstance(obj, dict):
        children = list(obj.values())
      else:
        continue
      for c in reversed(children):
        if isinstance(c, (self.Widget, list, tuple, set, dict)) or (
            hasattr(c, "__dict__") and not callable(c) and type(c).__module__.startswith("openpilot.selfdrive.ui")):
          stack.append((c, depth + 1))
    out = []
    for s in scrollers:
      for it in getattr(s, "_items", []):
        if id(it) not in seen:
          seen.add(id(it))
          out.append(it)
    for it in order + list(self.rendered.values()):
      if id(it) not in seen:
        seen.add(id(it))
        out.append(it)
    return out

  def describe(self, it):
    a = getattr(it, "action_item", None)
    kind = type(a).__name__ if a is not None else type(it).__name__
    vis = int(bool(_safe(lambda: it.is_visible)))
    shown = int(id(it) in self.rendered)
    row_en = int(bool(_safe(lambda: it.enabled)))
    act_en = int(bool(_safe(lambda: a.enabled))) if a is not None else -1
    value, extra = "", []
    if a is not None:
      if hasattr(a, "buttons") and hasattr(a, "selected_button"):
        value = "[" + ",".join(_res(b) for b in a.buttons) + f"] sel={_safe(lambda: a.selected_button)}"
      elif hasattr(a, "get_state") and not hasattr(a, "manage"):
        value = f"state={int(bool(_safe(a.get_state)))}"
      elif hasattr(a, "manage") and hasattr(a, "toggle"):
        value = f"state={int(bool(_safe(a.toggle.get_state)))} manage_en={int(bool(_safe(lambda: a.manage.enabled)))}"
      elif hasattr(a, "left_button") and hasattr(a, "right_button"):
        value = f"[{_btn_text(a.left_button)},{_btn_text(a.right_button)}]"
      elif hasattr(a, "_value_source") and hasattr(a, "_text_source"):
        value = f"btn={_res(a._text_source)} val={_res(a._value_source)}"
      elif hasattr(a, "_text_source"):
        value = _res(a._text_source)
      for name in ("hint_text", "highlighted"):
        if hasattr(a, name):
          extra.append(f"{name}={_res(getattr(a, name))}")
    title = _res(getattr(it, "_title", getattr(it, "title", "")))
    key = getattr(it, "help_key", None) or ""
    return [title, kind, vis, shown, row_en, act_en, value, key, " ".join(extra)]

  def entries(self, items):
    """(label, opener) for rows that open a submenu with their own MANAGE / OPEN control."""
    out = []
    for it in items:
      a = getattr(it, "action_item", None)
      title = _res(getattr(it, "_title", ""))
      if a is not None and hasattr(a, "manage") and hasattr(a, "toggle"):
        cb = getattr(a.manage, "_click_callback", None)
        if cb:
          out.append((title, cb))
      elif a is not None and hasattr(a, "_text_source") and hasattr(a, "_button"):
        if _res(a._text_source).strip().upper() in NAV_WORDS and getattr(it, "callback", None):
          out.append((title, it.callback))
    return out


def _has_contents(cell):
  try:
    _ = cell.cell_contents
    return True
  except ValueError:
    return False


def _btn_text(button):
  label = getattr(button, "_label", None)
  return _res(getattr(label, "_text", "")) if label is not None else ""


def _safe(fn):
  try:
    return fn()
  except Exception:
    return None


def run_one(car, level, profile, out_path):
  os.environ.setdefault("RAYLIB_BACKEND", "headless")
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.common.bogpilot_store import write_text
  from openpilot.selfdrive.ui.bogpilot import tuning_level as tl
  from openpilot.selfdrive.ui.ui_state import ui_state
  from openpilot.selfdrive.ui.layouts.settings.bogpilot import menu_sections

  if not gui_app.big_ui() and not rl.is_window_ready():
    gui_app._width, gui_app._height = 2160, 1080
    gui_app._scaled_width, gui_app._scaled_height = int(2160 * gui_app._scale), int(1080 * gui_app._scale)
  gui_app.init_window("settings row dump")
  if profile in STORE_PROFILES:
    if not params_dir_is_temp(os.environ.get("PARAMS_ROOT")):
      raise SystemExit("a store profile seeds Params; PARAMS_ROOT must be under a temp dir")
    from openpilot.common.bogpilot_store import ParamStore
    seed = ParamStore()
    for k, v in PROFILES[profile].items():
      seed.put(k, v)
  else:
    for k, v in PROFILES[profile].items():
      if not write_text(k, v):
        raise SystemExit(f"could not seed {k}")
  tl.invalidate()
  if not tl.set_level(level):
    raise SystemExit("could not set Tuning Level")
  tl.invalidate()
  cp = _make_cp(car)
  ui_state.CP = cp
  w = Walker(rl, gui_app)
  lines = [" ".join([f"# car={car} level={level} profile={profile}",
                     f"fingerprint={getattr(cp, 'carFingerprint', None)}",
                     f"op_long={getattr(cp, 'openpilotLongitudinalControl', None)}",
                     f"offroad={int(bool(ui_state.is_offroad()))} effective_level={tl.effective_level()}"])]
  errors = 0

  def build(page, clicks):
    """Fresh page, then each MANAGE / OPEN in turn. Returns (widget, ids of the rows before the last click)."""
    widget = page.factory()
    widget.show_event()
    w.draw(widget)
    before: list = []
    for label in clicks:
      items = w.rows(widget)
      found = [cb for t, cb in w.entries(items) if t == label]
      if not found:
        return None, None
      before = items                      # strong refs: ids stay unique while compared
      found[0]()
      w.draw(widget)
    return widget, before

  def explore(path, page, clicks):
    nonlocal errors
    where = " > ".join(path)
    try:
      widget, before = build(page, clicks)
    except Exception as e:
      errors += 1
      lines.append(f"{where} | ! | <error {type(e).__name__}: {_clean(e)}>")
      return
    if widget is None:
      errors += 1
      lines.append(f"{where} | ! | <entry not found>")
      return
    before_ids = {id(x) for x in before}
    new = [x for x in w.rows(widget) if id(x) not in before_ids]
    if os.getenv("ROWDUMP_DEBUG"):
      print(f"[explore] {where} before={len(before)} new={len(new)} entries={[t for t, _ in w.entries(new)]}", file=sys.stderr)
    for n, it in enumerate(new):
      lines.append(" | ".join([where, str(n)] + [_clean(x) for x in w.describe(it)]))
    if len(clicks) < MAX_DEPTH:
      for label, _cb in w.entries(new):
        explore(path + [label], page, clicks + [label])

  for s in menu_sections():
    for p in s.pills:
      for page in p.pages:
        explore([s.title, p.label, page.title], page, [])
  lines.append(f"# rows={sum(1 for x in lines if not x.startswith('#') and ' | ! | ' not in x)} errors={errors}")
  tmp = out_path + ".tmp"
  with open(tmp, "w") as f:
    f.write("\n".join(lines) + "\n")
  os.replace(tmp, out_path)


def params_dir_is_temp(params_dir: str | None) -> bool:
  """True only when the params store is under the temp dir, so --one can never seed a live device store."""
  if not params_dir:
    return False
  tmp = os.path.realpath(tempfile.gettempdir())
  return os.path.commonpath([os.path.realpath(params_dir), tmp]) == tmp and os.path.realpath(params_dir) != tmp


def _on_device() -> bool:
  """The tree's own device check: openpilot/common/hardware/__init__.py sets AGNOS = os.path.isfile('/AGNOS') and
  PC = not AGNOS. Read at call time so a test can patch it."""
  from openpilot.common import hardware
  return not hardware.PC


def real_params_dirs(env=None) -> list[str]:
  """Live stores this tool must never seed: the Params root (openpilot/common/hardware/hw.h: PARAMS_ROOT, else
  /data/params on a device, ~/.comma/params on a PC) and the BogPilot file store default
  (openpilot/common/bogpilot_store.py: /data/params_bogpilot)."""
  env = os.environ if env is None else env
  dirs = ["/data/params", "/data/params_bogpilot", os.path.join(os.path.expanduser("~"), ".comma", "params")]
  if env.get("PARAMS_ROOT"):
    dirs.append(env["PARAMS_ROOT"])
  return [os.path.realpath(d) for d in dirs]


def refuse_reason(one: bool, env=None) -> str | None:
  """Why this run must not go ahead, or None. Checked in main() before any store or Params write."""
  env = os.environ if env is None else env
  if _on_device():
    return "this is a device (/AGNOS present); the row dump runs only on a PC or the build VM"
  if one:
    params_dir = env.get("BOGPILOT_PARAMS_DIR")
    if params_dir:
      real = os.path.realpath(params_dir)
      for d in real_params_dirs(env):
        if real == d or os.path.commonpath([real, d]) == d:
          return f"BOGPILOT_PARAMS_DIR is a real params store ({d})"
    if not params_dir_is_temp(params_dir):
      return "--one seeds the params store; BOGPILOT_PARAMS_DIR must be under a temp dir"
  return None


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--out")
  ap.add_argument("--tag", default="dump")
  ap.add_argument("--one", nargs=4, metavar=("CAR", "LEVEL", "PROFILE", "FILE"))
  args = ap.parse_args()
  reason = refuse_reason(one=bool(args.one))
  if reason:
    print(f"settings_row_dump: refusing to run: {reason}", file=sys.stderr)
    return 2
  if args.one:
    car, level, profile, path = args.one
    run_one(car, int(level), profile, path)
    return 0
  os.makedirs(args.out, exist_ok=True)
  failed = 0
  for car in CARS:
    for level in LEVELS:
      for profile in PROFILES:
        path = os.path.join(args.out, f"{args.tag}_{car}_L{level}_{profile}.txt")
        with tempfile.TemporaryDirectory(prefix="rowdump-") as tmp:
          env = dict(os.environ, HOME=tmp,
                     BOGPILOT_PARAMS_DIR=os.path.join(tmp, "bp"),
                     PARAMS_ROOT=os.path.join(tmp, "params"))
          os.makedirs(env["BOGPILOT_PARAMS_DIR"])
          os.makedirs(env["PARAMS_ROOT"])
          log = path + ".log"
          with open(log, "w") as lf:
            rc = subprocess.call([sys.executable, os.path.abspath(__file__), "--one", car, str(level), profile, path],
                                 env=env, stdout=lf, stderr=subprocess.STDOUT)
          seeded = set(PROFILES[profile]) | {"TuningLevel", "TuningLevelConfirmed"}
          extra_files = sorted({f for _d, _s, fs in os.walk(tmp) for f in fs} - seeded - {os.path.basename(log)})
        status = "ok" if rc == 0 else f"rc={rc}"
        failed += rc != 0
        print(f"{os.path.basename(path)} {status} files_written_beyond_seed={len(extra_files)} {' '.join(extra_files)[:200]}")
  return 1 if failed else 0


if __name__ == "__main__":
  sys.exit(main())
