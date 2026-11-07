#!/usr/bin/env python3
"""C3X release-candidate UI acceptance gate (automated, no device).

Drives the REAL onroad composer (hud_compose.HudComposer) and the REAL alert source (alert_renderer.get_alert via
alert_banner.BogPilotAlertRenderer.current_plan) with real capnp messages, recording the actual call order instead
of drawing pixels. Geometry checks use the real component modules. Nothing is stubbed to make a case pass:
  PASS    the check ran and held
  FAIL    the check ran and was violated
  UNRUN   a required dependency (pyray, cereal, a module) is missing here -> the gate is NOT passed
  PENDING an optional feature contract (steering arc, pedals, speed limit, recorder) is not on this branch yet
All inputs are SYNTHETIC (built messages, fixed rects); real-log replay is a separate, pending native step.

Exit 0 only when no case FAILED or is UNRUN. Usage (native env, repo root on PYTHONPATH):
  python tools/bogpilot/rc_ui_gate.py [--json out.json] [--case NAME ...]
"""
from __future__ import annotations
import argparse
import importlib
import json
import sys
import traceback
from types import SimpleNamespace

BP = "openpilot.selfdrive.ui.onroad.bogpilot."
PASS, FAIL, UNRUN, PENDING = "PASS", "FAIL", "UNRUN", "PENDING"
SIZE_NONE, SIZE_SMALL, SIZE_MID, SIZE_FULL = 0, 1, 2, 3
C3X = (30.0, 30.0, 2100.0, 1020.0)          # 2160x1080 minus the 30 px border
NARROW = (30.0, 30.0, 1540.0, 940.0)        # resized window below the 1800 px wide breakpoint
CASES = {}


class Unrun(Exception):
  pass


class Pending(Exception):
  pass


def case(name, kind):
  def deco(fn):
    CASES[name] = (kind, fn)
    return fn
  return deco


def need(module):
  try:
    return importlib.import_module(module)
  except Exception as e:   # ImportError, missing native libs, capnp schema load
    raise Unrun(f"{module}: {type(e).__name__}: {e}") from None


def optional(module):
  try:
    return importlib.import_module(module)
  except ModuleNotFoundError as e:
    if e.name == module:
      raise Pending(f"{module} not on this branch (primary UI contract pending)") from None
    raise Unrun(f"{module}: {e}") from None
  except Exception as e:
    raise Unrun(f"{module}: {type(e).__name__}: {e}") from None


def check(cond, msg):
  if not cond:
    raise AssertionError(msg)


def tup(r):
  return (r.x, r.y, r.width, r.height) if hasattr(r, "width") else tuple(r)


def overlaps(a, b):
  ax, ay, aw, ah = tup(a)
  bx, by, bw, bh = tup(b)
  return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


# ---------------------------------------------------------------- pure (run anywhere the source tree is) ----
def _plan(size, status=0, rect=C3X, redesign=True, compact=False, started=True, typ=""):
  L = need(BP + "alert_banner_logic")
  return L.plan_alert(L.AlertIn("T1", "T2", size, status, typ), rect, started=started, redesign=redesign, compact=compact)


@case("full_alert_native", "pure")
def full_alert_native():
  for rd in (False, True):
    for cp in (False, True):
      p = _plan(SIZE_FULL, 2, redesign=rd, compact=cp)
      check(p.mode == "native" and tuple(p.rect) == C3X and p.hide_cluster, f"full alert not native/full-rect {rd=} {cp=}")


@case("alert_semantics_passthrough", "pure")
def alert_semantics_passthrough():
  L = need(BP + "alert_banner_logic")
  for size in (SIZE_SMALL, SIZE_MID, SIZE_FULL):
    for st in (0, 1, 2):
      a = L.AlertIn("Text One", "Text Two", size, st, "someEvent/warning")
      p = L.plan_alert(a, C3X, started=True, redesign=True)
      check(p.showing and p.alert is a, "alert text/size/status/type must pass through unchanged")


@case("stale_offroad_cleanup", "pure")
def stale_offroad_cleanup():
  for size in (SIZE_SMALL, SIZE_MID, SIZE_FULL):
    check(_plan(size, 2, started=False).mode == "none", "offroad must clear alert")
  check(_plan(SIZE_NONE).mode == "none", "size none must clear")


@case("resize_narrow_fallback", "pure")
def resize_narrow_fallback():
  for size in (SIZE_SMALL, SIZE_MID):
    p = _plan(size, rect=NARROW)
    x, y, w, h = p.rect
    check(NARROW[0] <= x and x + w <= NARROW[0] + NARROW[2] and y + h <= NARROW[1] + NARROW[3], "narrow banner off-screen")
    p = _plan(size, rect=(0, 0, 536, 240))
    check(p.mode == "native", "too-small rect must fall back to native, not clip")


@case("compact_rhd_dm", "pure")
def compact_rhd_dm():
  D = need(BP + "driver_monitor_layout")
  check(D.placement((0, 0, 536, 240)) is None, "compact must keep native DM (placement None)")
  check(D.placement(NARROW) is None, "narrow must keep native DM")
  lhd, rhd = D.placement(C3X), D.placement(C3X, rhd=True)
  check(lhd is not None and rhd is not None, "wide placement expected")
  cx = C3X[0] + C3X[2] / 2
  check(abs((lhd.x + lhd.width / 2 - cx) + (rhd.x + rhd.width / 2 - cx)) < 1e-6, "RHD must mirror LHD")
  for mid in (False, True):
    p = _plan(SIZE_MID if mid else SIZE_SMALL)
    check(not overlaps(p.rect, lhd) and not overlaps(p.rect, rhd), "banner overlaps relocated DM")
  check(_plan(SIZE_MID, compact=True).mode == "native", "compact (C4) alert must stay native")


@case("dm_freshness", "pure")
def dm_freshness():
  D = need(BP + "driver_monitor_layout")
  ks = ("driverStateV2", "driverMonitoringState")
  sm = SimpleNamespace(alive={k: True for k in ks}, valid={k: True for k in ks}, recv_frame={k: 11 for k in ks},
                       recv_time={k: 9.8 for k in ks})
  check(D.fresh(sm, 10.0, 10, 5.0), "fresh synthetic DM rejected")
  for mut, why in ((lambda s: s.recv_time.__setitem__("driverStateV2", 9.0), "stale >0.5s"),
                   (lambda s: s.valid.__setitem__("driverMonitoringState", False), "invalid"),
                   (lambda s: s.recv_frame.__setitem__("driverStateV2", 5), "previous drive"),
                   (lambda s: s.recv_time.__setitem__("driverStateV2", float("nan")), "non-finite")):
    s = SimpleNamespace(alive=dict(sm.alive), valid=dict(sm.valid), recv_frame=dict(sm.recv_frame), recv_time=dict(sm.recv_time))
    mut(s)
    check(not D.fresh(s, 10.0, 10, 5.0), f"DM freshness accepted {why}")


@case("banner_keepouts_cluster", "pure")
def banner_keepouts_cluster():
  L = need(BP + "alert_banner_logic")
  C = need(BP + "cluster_layout")
  check(L._STACK_BOTTOM == C.STACK_BOTTOM, "banner stack bottom drifted from cluster layout")
  for mid in (False, True):
    x, y, w, h = _plan(SIZE_MID if mid else SIZE_SMALL).rect
    check(y - C3X[1] >= C.STACK_BOTTOM, "banner overlaps speed row / graph stack")


# ---------------------------------------------------------------- composer (needs pyray + cereal) ----------
class SM(dict):
  """Holds REAL capnp messages; freshness bookkeeping is synthetic and explicit per case."""

  def __init__(self, messaging, frame=100, now=50.0):
    super().__init__()
    self.valid, self.alive, self.recv_frame, self.recv_time, self.updated = {}, {}, {}, {}, {}
    for name in ("selfdriveState", "driverMonitoringState", "driverStateV2", "carState", "radarState", "modelV2",
                 "controlsState", "carControl", "deviceState"):
      try:
        self[name] = getattr(messaging.new_message(name), name)
      except Exception as e:
        raise Unrun(f"capnp {name}: {e}") from None
      self.valid[name] = self.alive[name] = self.updated[name] = True
      self.recv_frame[name] = frame
      self.recv_time[name] = now
    self.frame = frame
    self.seen = dict.fromkeys(self, True)

  def set_alert(self, messaging, size, status=0, t1="", t2="", typ=""):
    m = messaging.new_message("selfdriveState")
    ss = m.selfdriveState
    ss.alertSize, ss.alertStatus, ss.alertText1, ss.alertText2, ss.alertType = size, status, t1, t2, typ
    ss.enabled = True
    self["selfdriveState"] = ss


class Spy:
  def __init__(self, name, log):
    self.name, self.log = name, log

  def render(self, rect):
    self.log.append(self.name)


class SpyLayer:
  """A peer layer stand-in that records calls; fail=True raises on draw to exercise the composer's fallback."""
  supports_compact = False

  def __init__(self, name, log, draw_result=True, fail=False, bounds=None):
    self.name, self.log, self.draw_result, self.fail, self.bounds = name, log, draw_result, fail, bounds

  def reset(self):
    pass

  def update(self, f):
    pass

  def enabled(self, f):
    return True

  def draw(self, f):
    if self.fail:
      raise RuntimeError("synthetic layer failure")
    self.log.append(self.name)
    return self.draw_result


def composer_env(redesign=True, longitudinal=True, rhd=False, alert=(SIZE_NONE, 0, "", "", ""), layers=("lead_lockon",
                 "lead_labels", "driver_monitor"), fail=(), stale=()):
  rl = need("pyray")
  messaging = need("openpilot.cereal.messaging")
  hc = need(BP + "hud_compose")
  ab = need(BP + "alert_banner")
  ar = need("openpilot.selfdrive.ui.onroad.alert_renderer")
  sm = SM(messaging)
  sm.set_alert(messaging, *alert)
  sm["driverMonitoringState"] = messaging.new_message("driverMonitoringState").driverMonitoringState
  sm["driverMonitoringState"].isRHD = rhd
  for n in stale:
    sm.alive[n] = False
  state = SimpleNamespace(sm=sm, started_frame=50, started_time=0.0, started=True, has_longitudinal_control=longitudinal,
                          is_metric=False)
  # The real alert source reads the module-level ui_state; point it at this synthetic state for the run.
  saved = (ar.ui_state, ab.ui_state)
  ar.ui_state = ab.ui_state = state
  log = []
  alert_r = object.__new__(ab.BogPilotAlertRenderer)          # real class; __init__ skipped (fonts need a window)
  alert_r._redesign_fn, alert_r._compact = (lambda: redesign), False
  alert_r.plan = None

  def render(rect, _a=alert_r):                               # real plan, no GL draw
    _a.plan = _a.current_plan(rect)
    log.append("alert")
  alert_r.render = render
  peers = {n: SpyLayer(n, log, fail=n in fail) for n in layers}
  model = Spy("model", log)
  model.bp_flush_primary_lead = lambda: log.append("stock_lead")
  comp = hc.HudComposer(model, Spy("hud", log), alert_r, Spy("stock_dm", log), layers=peers,
                        policy=SimpleNamespace(get=lambda: {"hide_lead_marker": True, "onroad_distance_button": True}),
                        traffic=SimpleNamespace(read=lambda now, ds: False), clock=lambda: 50.0, state=state,
                        toggle_get=lambda k: redesign if k == "RedesignUI" else False)

  def restore():
    ar.ui_state, ab.ui_state = saved
  return SimpleNamespace(rl=rl, comp=comp, log=log, alert=alert_r, restore=restore, state=state)


def run_frame(e, rect=C3X):
  try:
    r = e.rl.Rectangle(*rect)
    e.comp.render(r)
    return r
  finally:
    e.restore()


@case("alert_last", "composer")
def alert_last():
  for a in ((SIZE_MID, 2, "TAKE CONTROL", "Steering Unavailable", "x/warning"), (SIZE_FULL, 2, "TAKE CONTROL IMMEDIATELY", "x", "x/w"),
            (SIZE_SMALL, 1, "Small", "", "y/w"), (SIZE_NONE, 0, "", "", "")):
    e = composer_env(alert=a)
    run_frame(e)
    check(e.log and e.log[-1] == "alert", f"alert not last: {e.log}")
    check(e.comp.order[-1] == "alert", f"composer order not alert-last: {e.comp.order}")
    for later in ("driver_monitor", "lead_labels", "lead_lockon", "hud"):
      if later in e.log:
        check(e.log.index(later) < e.log.index("alert"), f"{later} after alert")


@case("alert_last_with_failing_layers", "composer")
def alert_last_with_failing_layers():
  e = composer_env(alert=(SIZE_MID, 2, "A", "B", "x/w"), fail=("lead_lockon", "lead_labels", "driver_monitor"))
  run_frame(e)
  check(e.log[-1] == "alert", f"alert not last after failures: {e.log}")
  check("stock_dm" in e.log, f"native DM not retained after DM layer failure: {e.log}")
  check({"lead_lockon", "lead_labels", "driver_monitor"} <= e.comp.disabled, "failed layers not disabled")


@case("native_dm_retained", "composer")
def native_dm_retained():
  e = composer_env(layers=("lead_lockon", "lead_labels"))
  run_frame(e)
  check("stock_dm" in e.log, f"stock DM missing without relocation layer: {e.log}")
  e = composer_env()
  run_frame(e, NARROW)                              # not wide -> no compact support -> stock DM
  check("stock_dm" in e.log and "driver_monitor" not in e.log, f"narrow must keep native DM: {e.log}")


@case("redesign_off_stock", "composer")
def redesign_off_stock():
  e = composer_env(redesign=False, alert=(SIZE_MID, 1, "A", "B", "x/w"))
  run_frame(e)
  check(e.comp.order == ["model", "hud", "alert", "stock_dm"], f"stock order changed: {e.comp.order}")
  check(not any(n in e.log for n in ("lead_lockon", "lead_labels", "driver_monitor")), f"peer layer ran with redesign off: {e.log}")
  check(e.alert.plan is not None and e.alert.plan.mode == "native", "redesign off must use the native painter")


@case("keepouts_and_no_occlusion", "composer")
def keepouts_and_no_occlusion():
  for size in (SIZE_SMALL, SIZE_MID):
    e = composer_env(alert=(size, 1, "A", "B", "x/w"))
    run_frame(e)
    f = e.comp.frame
    p = e.alert.plan
    check(p.mode == "banner", f"expected banner, got {p.mode}")
    check(any(tup(k) == tuple(p.rect) for k in f.base_keepouts), "alert rect missing from composer keepouts")
    for name, r in (("personality", f.personality_rect), ("stock_dm", f.stock_dm_rect)):
      if r is not None:
        check(not overlaps(p.rect, r), f"banner overlaps {name}")


@case("full_alert_hides_pill", "composer")
def full_alert_hides_pill():
  e = composer_env(alert=(SIZE_FULL, 2, "TAKE CONTROL IMMEDIATELY", "B", "x/w"))
  run_frame(e)
  check(e.comp.frame.full_alert and e.comp.frame.personality_rect is None, "personality pill shown under full alert")
  check(e.alert.plan.mode == "native" and e.alert.plan.full, "full alert not native full")


@case("runtime_freshness", "composer")
def runtime_freshness():
  e = composer_env(alert=(SIZE_MID, 2, "A", "B", "x/w"), stale=("selfdriveState", "driverMonitoringState"))
  run_frame(e)
  f = e.comp.frame
  check(not f.engaged and not f.rhd, "stale selfdriveState/DM used for engaged/RHD")
  check(f.personality_rect is None, "pill shown with stale selfdriveState")
  check(e.log[-1] == "alert", "alert not last with stale inputs")


@case("no_long", "composer")
def no_long():
  e = composer_env(longitudinal=False)
  run_frame(e)
  f = e.comp.frame
  check(not f.hide_lead_marker and not f.onroad_distance_button and f.personality_rect is None,
        "longitudinal-only features active without openpilot longitudinal")


@case("rhd_composer", "composer")
def rhd_composer():
  e = composer_env(rhd=True)
  r = run_frame(e)
  f = e.comp.frame
  check(f.rhd, "RHD not taken from fresh driverMonitoringState")
  check(f.stock_dm_rect.x > r.x + r.width / 2, "stock DM keepout not mirrored for RHD")


# ---------------------------------------------------------------- primary-UI extensions (contract-gated) ----
def _ext_rects():
  P = optional(BP + "pedals")
  A = optional(BP + "steering_arc")
  rl = need("pyray")
  out = []
  for rhd in (False, True):
    out.append((f"pedals rhd={rhd}", P.pedal_rect(C3X[2], rhd)))
  out.append(("steering_arc tap", A.tap_rect(rl.Rectangle(*C3X))))
  return out


@case("ext_pedals_arc_vs_alert", "extension")
def ext_pedals_arc_vs_alert():
  rects = _ext_rects()
  for size in (SIZE_SMALL, SIZE_MID):
    b = _plan(size).rect
    for name, r in rects:
      x, y, w, h = tup(r)
      if name.startswith("pedals"):            # pedal_rect is widget space
        x, y = x + C3X[0], y + C3X[1]
      check(not overlaps(b, (x, y, w, h)), f"alert banner overlaps {name}")


@case("ext_speed_limit_recorder_present", "extension")
def ext_speed_limit_recorder_present():
  S = optional(BP + "speed_limit_display")
  R = optional(BP + "screen_recorder")
  check(hasattr(S, "read_dashboard_limit") and hasattr(S, "speed_limit_view"), "speed limit API changed")
  check(hasattr(R, "RecorderEngine") and hasattr(R, "segment_name"), "recorder API changed")
  check(S.read_dashboard_limit(SimpleNamespace(), 1.0, 0.0) is None, "speed limit must be None on missing data")


def run(names=None):
  results = []
  for name, (kind, fn) in CASES.items():
    if names and name not in names:
      continue
    try:
      fn()
      results.append({"case": name, "kind": kind, "status": PASS})
    except Unrun as e:
      results.append({"case": name, "kind": kind, "status": UNRUN, "detail": str(e)})
    except Pending as e:
      results.append({"case": name, "kind": kind, "status": PENDING, "detail": str(e)})
    except AssertionError as e:
      results.append({"case": name, "kind": kind, "status": FAIL, "detail": str(e)})
    except Exception as e:
      results.append({"case": name, "kind": kind, "status": FAIL, "detail": f"{type(e).__name__}: {e}",
                      "trace": traceback.format_exc(limit=4)})
  return results


def exit_code(results) -> int:
  st = {r["status"] for r in results}
  if FAIL in st:
    return 1
  if UNRUN in st or not results:
    return 2
  return 0


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  ap.add_argument("--case", action="append")
  ap.add_argument("--json")
  a = ap.parse_args(argv)
  res = run(a.case)
  for r in res:
    print(f"{r['status']:8} {r['kind']:9} {r['case']}" + (f"  -- {r['detail']}" if r.get("detail") else ""))
  code = exit_code(res)
  print({0: "GATE PASS (synthetic inputs; real replay + pyray pixels are separate)", 1: "GATE FAIL",
         2: "GATE NOT PASSED: unrun cases (missing native deps)"}[code])
  if a.json:
    with open(a.json, "w") as fh:
      json.dump({"results": res, "exit": code, "inputs": "synthetic"}, fh, indent=1)
  return code


if __name__ == "__main__":
  sys.exit(main())
