"""Injected-latency deviceState rate gate for hardwared (slow; opt-in).

Gate: with the real hardware_thread and real msgq messaging, deviceState must hold 2 Hz (rate >= 1.9 Hz) with no gap of
0.6 s or more while slow hardware reads stall for about 12 s: one thermal zone read blocks LAT_S every PERIOD_S and the SoM
power-draw read blocks SOM_LAT_S every SOM_PERIOD_S (12.6 s / 12.7 s are the stalls NAP recorded).

It needs a long runtime (default 120 s once onroad, plus startup), and it writes Params, so it is skipped unless
BOGPILOT_LATENCY_RATE_GATE=1 is set. Run it only in a disposable test environment, never on a device:
  BOGPILOT_LATENCY_RATE_GATE=1 BOGPILOT_LATENCY_RATE_S=600 pytest openpilot/system/hardware/tests/test_hardwared_latency_rate.py
or directly:
  python3 openpilot/system/hardware/tests/test_hardwared_latency_rate.py DURATION_S [LAT_S PERIOD_S SOM_LAT_S SOM_PERIOD_S]
The repo registers no 'slow' pytest marker, so the opt-in skip is the slow guard.
"""
import os
import subprocess
import sys

import pytest

GATE_ENV = "BOGPILOT_LATENCY_RATE_GATE"
DURATION_ENV = "BOGPILOT_LATENCY_RATE_S"
MIN_RATE_HZ = 1.9
MAX_GAP_S = 0.6


def run_gate(argv):
  import queue
  import threading
  import time
  os.environ.setdefault("MPLBACKEND", "Agg")
  import openpilot.cereal.messaging as messaging
  from openpilot.cereal import log
  from openpilot.common.hardware.base import ThermalConfig
  from openpilot.common.params import Params
  from openpilot.common.version import terms_version, training_version
  import openpilot.system.hardware.hardwared as hwd

  dur = float(argv[0])
  lat, per, slat, sper = (float(x) for x in (argv[1:5] or (12.0, 30.0, 12.6, 45.0)))
  t0 = time.monotonic()
  stalls = {"thermal": 0, "som": 0}

  class Zone:
    def __init__(self, name, temp, slow=False):
      self.name, self.temp, self.slow, self.next = name, temp, slow, t0 + 15.0

    def read(self):
      if self.slow and time.monotonic() >= self.next:
        self.next = time.monotonic() + per
        stalls["thermal"] += 1
        time.sleep(lat)
      return self.temp

  som_next = [t0 + 25.0]

  def som():
    if time.monotonic() >= som_next[0]:
      som_next[0] = time.monotonic() + sper
      stalls["som"] += 1
      time.sleep(slat)
    return 3.3

  p = Params()
  p.put("HasAcceptedTerms", terms_version)
  p.put("CompletedTrainingVersion", training_version)
  for k in ("IsDriverViewEnabled", "DoUninstall", "OnroadCycleRequested"):
    p.remove(k)
  cfg = ThermalConfig(cpu=[Zone("cpu0", 45.0, slow=True), Zone("cpu1", 45.0)], gpu=[Zone("gpu0", 45.0)],
                      memory=Zone("ddr", 45.0), pmic=[Zone("pm", 45.0)])
  hw = hwd.HARDWARE
  hw.initialize_hardware = lambda: None
  hw.get_thermal_config = lambda: cfg
  hw.get_som_power_draw = som
  hw.booted = lambda: True
  hw.set_power_save = lambda on: None
  hwd.get_usb_state = list

  end = threading.Event()

  def pub_panda():
    pm = messaging.PubMaster(["pandaStates"])
    nxt = time.monotonic()
    while not end.is_set():
      m = messaging.new_message("pandaStates", 1)
      ps = m.pandaStates[0]
      ps.ignitionLine = True
      ps.pandaType = log.PandaState.PandaType.redPanda
      ps.harnessStatus = log.PandaState.HarnessStatus.normal
      pm.send("pandaStates", m)
      nxt += 0.1
      time.sleep(max(0.0, nxt - time.monotonic()))

  sock = messaging.sub_sock("deviceState", conflate=False, timeout=100)
  threading.Thread(target=pub_panda, daemon=True).start()
  threading.Thread(target=hwd.hardware_thread, args=(end, queue.Queue(maxsize=1)), daemon=True).start()
  t_on, ts = None, []
  deadline = t0 + 60.0
  while True:
    now = time.monotonic()
    if t_on is None and now > deadline:
      print("LATENCY_RATE_VERDICT FAIL never_onroad")
      end.set()
      return 1
    if t_on is not None and now - t_on > dur:
      break
    for msg in messaging.drain_sock(sock, wait_for_one=True):
      if msg.deviceState.started and t_on is None:
        t_on = time.monotonic()
      if t_on is not None:
        ts.append(time.monotonic())
  end.set()
  gaps = [b - a for a, b in zip(ts, ts[1:], strict=False)]
  rate = (len(ts) - 1) / (ts[-1] - ts[0])
  gmax = max(gaps)
  ok = rate >= MIN_RATE_HZ and gmax < MAX_GAP_S
  print(f"DEVSTATE_RATE n={len(ts)} window_s={ts[-1] - ts[0]:.1f} rate_hz={rate:.3f} max_gap_s={gmax:.3f} "
        f"gaps_over_0p6={sum(g >= MAX_GAP_S for g in gaps)} thermal_stalls={stalls['thermal']}x{lat}s som_stalls={stalls['som']}x{slat}s")
  print(f"LATENCY_RATE_VERDICT {'PASS' if ok else 'FAIL'}")
  return 0 if ok else 1


@pytest.mark.skipif(os.getenv(GATE_ENV) != "1", reason=f"slow injected-latency gate; set {GATE_ENV}=1 to run")
def test_devicestate_holds_2hz_through_injected_12s_read_stalls():
  dur = os.getenv(DURATION_ENV, "120")
  # own process: the gate patches HARDWARE and uses real msgq sockets
  r = subprocess.run([sys.executable, os.path.abspath(__file__), dur], capture_output=True, text=True, timeout=float(dur) + 180)
  print(r.stdout[-4000:])
  print(r.stderr[-4000:])
  assert "LATENCY_RATE_VERDICT PASS" in r.stdout, r.stdout[-2000:]
  assert r.returncode == 0


if __name__ == "__main__":
  sys.exit(run_gate(sys.argv[1:]))
