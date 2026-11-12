"""R1-R10 (beta stalk bookmark): replay over real logs. Skipped unless BOOKMARK_REPLAY_ROUTES is set.

BOOKMARK_REPLAY_ROUTES = "name|dir|count[|HH:MM:SS.ss,...]" entries joined by ";". dir holds segment folders (0, 1, ...) with
rlog(.zst/.bz2). Optional fire times are local wall clock (BOOKMARK_REPLAY_UTC_OFFSET_H, default -5), +-0.15 s.
BOOKMARK_REPLAY_OUT = file for a one-line JSON summary per route.

Per route, two full passes of the car interface over the logged CAN with logged carControl (card-equivalent:
CI.update -> carState, CI.apply -> sendcan, Experimental hold clocked by log time):
  pass OFF: flag file absent, no detector.  pass ON: flag file present, Detector fed replayed carState + logged
  selfdriveState + replayed sendcan 0x45, in logMonoTime order.
Checks: R1/R3/R4/R9 bookmark count (and fire times); R2 Experimental toggles identical ON vs OFF; R6 every carState
(incl. buttonEvents) and sendcan byte-identical ON vs OFF; R7 no 0x45 in sendcan inside a counted train; R10 the UI
hook stays inert off-list. R8 is tesla_ap1/tests/test_stalk_bus_isolation.py. Reads logs only; writes only the flag
file under /data/params_bogpilot (container-local) and BOOKMARK_REPLAY_OUT.
"""
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROUTES = os.environ.get("BOOKMARK_REPLAY_ROUTES", "")
needs_logs = pytest.mark.skipif(not ROUTES, reason="BOOKMARK_REPLAY_ROUTES not set")

HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location("beta_stalk_bookmark_rp", HERE.parents[1] / "beta_stalk_bookmark.py")
bsb = importlib.util.module_from_spec(spec)
sys.modules["beta_stalk_bookmark_rp"] = bsb
spec.loader.exec_module(bsb)


def _routes():
  out = []
  for item in filter(None, (x.strip() for x in ROUTES.split(";"))):
    parts = item.split("|")
    fires = [x for x in parts[3].split(",") if x] if len(parts) > 3 else []
    out.append((parts[0], Path(parts[1]), int(parts[2]), fires))
  return out


def _segments(d):
  segs = sorted((p for p in d.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name))
  for s in segs:
    for n in ("rlog.zst", "rlog.bz2", "rlog"):
      if (s / n).is_file():
        yield s / n
        break


def _events(d):
  from openpilot.tools.lib.logreader import _LogFileReader
  for fn in _segments(d):
    yield from _LogFileReader(str(fn), sort_by_time=True)


def _setup(d):
  from opendbc.car.car_helpers import interfaces
  fp, longi, fingerprint, init = None, False, {}, None
  for i, ev in enumerate(_events(d)):
    w = ev.which()
    if w == "carParams" and fp is None:
      fp, longi = str(ev.carParams.carFingerprint), bool(ev.carParams.openpilotLongitudinalControl)
    elif w == "initData" and init is None:
      init = (ev.logMonoTime, ev.initData.wallTimeNanos)
    elif w == "can":
      for c in ev.can:
        if c.src < 128:
          fingerprint.setdefault(c.src, {})[c.address] = len(c.dat)
    if fp is not None and init is not None and i > 20000:
      break
  CI_cls = interfaces[fp]
  return fp, longi, fingerprint, init, CI_cls


def _replay(d, flag_on, fp, longi, fingerprint, CI_cls):
  from opendbc.car import structs
  if flag_on:
    bsb.FLAG.parent.mkdir(parents=True, exist_ok=True)
    bsb.FLAG.write_text("1")
  elif bsb.FLAG.exists():
    bsb.FLAG.unlink()
  CP = CI_cls.get_params(fp, fingerprint, [], longi, False, False)
  CI = CI_cls(CP)
  now = [0.0]
  if hasattr(CI.CS, "stalk_controls"):
    CI.CS.stalk_controls.clock = lambda: now[0]
  det = bsb.Detector(bsb.ALLOW_LIST[0].cruise_state_gate) if flag_on else None
  digests, toggles, fires, trains, r7_bad = [], [], [], [], 0
  CC, sds, tx_log = None, True, []
  for ev in _events(d):
    w = ev.which()
    t = ev.logMonoTime
    if w == "carControl":
      CC = ev.carControl
    elif w == "selfdriveState":
      sds = bool(ev.selfdriveState.enabled)
    elif w == "can":
      now[0] = t * 1e-9
      if hasattr(CI.CS, "stalk_controls_allowed"):
        CI.CS.stalk_controls_allowed = True
      CS = CI.update([(t, [(c.address, bytes(c.dat), c.src) for c in ev.can])])
      h = hashlib.sha1(CS.to_bytes())
      tog = (bool(getattr(CI.CS, "stalk_pull_toggle", False)), bool(getattr(CI.CS, "stalk_fwd_toggle", False)))
      if any(tog):
        toggles.append((t, tog))
      sends = []
      if CC is not None:
        _, sends = CI.apply(CC, t)
        for a, dat, bus in sends:
          h.update(b"%d:%d:" % (a, bus) + bytes(dat))
      digests.append(h.digest())
      if det is not None:
        if any(a == bsb.STW_ACTN_RQ for a, _, _ in sends):
          det.note_own_tx(t * 1e-9)
          tx_log.append(t)
        start = det.taps[0][0] if det.taps else det.press_t
        if det.update(t * 1e-9, int(CS.bogpilot.spdCtrlLvr), bool(CS.cruiseState.enabled), sds, bool(CS.canValid)):
          fires.append(t)
          trains.append((start, t * 1e-9))
          r7_bad += sum(1 for x in tx_log if start is not None and start <= x * 1e-9 <= t * 1e-9)
  return NS(digests=digests, toggles=toggles, fires=fires, trains=trains, r7_bad=r7_bad, n=len(digests))


def _wall(t_ns, init, off_h):
  s = (init[1] + (t_ns - init[0])) / 1e9 + off_h * 3600
  s %= 86400
  return s


def _hms(s):
  return "%02d:%02d:%05.2f" % (s // 3600, (s % 3600) // 60, s % 60)


@needs_logs
@pytest.mark.parametrize("name,d,count,fire_times", _routes() if ROUTES else [])
def test_replay_route(name, d, count, fire_times):
  off_h = float(os.environ.get("BOOKMARK_REPLAY_UTC_OFFSET_H", "-5"))
  fp, longi, fingerprint, init, CI_cls = _setup(d)
  assert bsb.entry_for(NS(carFingerprint=fp, dashcamOnly=False, passive=False)) is not None, fp
  off = _replay(d, False, fp, longi, fingerprint, CI_cls)
  on = _replay(d, True, fp, longi, fingerprint, CI_cls)
  bsb.FLAG.unlink(missing_ok=True)
  walls = [_wall(t, init, off_h) for t in on.fires]
  diff = sum(1 for a, b in zip(on.digests, off.digests) if a != b) + abs(on.n - off.n)
  summary = {"route": name, "fingerprint": fp, "op_long": longi, "frames": on.n, "bookmarks": len(on.fires),
             "fires_local": [_hms(x) for x in walls], "experimental_toggles_on": len(on.toggles),
             "experimental_toggles_off": len(off.toggles), "toggles_identical": on.toggles == off.toggles,
             "carstate_sendcan_frames_differing": diff, "r7_0x45_inside_train": on.r7_bad}
  out = os.environ.get("BOOKMARK_REPLAY_OUT")
  if out:
    with open(out, "a") as f:
      f.write(json.dumps(summary) + "\n")
  assert diff == 0                                   # R6
  assert on.toggles == off.toggles                   # R2
  assert on.r7_bad == 0                              # R7
  assert len(on.fires) == count                      # R1 / R3 / R4 / R9
  for want, got in zip(fire_times, walls):
    h, m, s = want.split(":")
    assert abs((int(h) * 3600 + int(m) * 60 + float(s)) - got) <= 0.15, (want, _hms(got))


def test_r10_hook_inert_off_list(monkeypatch, tmp_path):
  flag = tmp_path / "BetaStalkBookmark"
  flag.write_text("1")
  monkeypatch.setattr(bsb, "FLAG", flag)
  monkeypatch.setattr(bsb, "_state", None)
  sent = []
  pm = NS(send=lambda s, m: sent.append(s))
  for fp in ("TESLA_PREAP_MODELS", "TESLA_AP1_MODELX"):
    monkeypatch.setattr(bsb, "_state", None)
    bsb.tick(pm, NS(started=True, sm={"carParams": NS(carFingerprint=fp, dashcamOnly=False, passive=False)}))
    assert bsb._state is False
  assert sent == []
