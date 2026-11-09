"""Read only already-downloaded M4 CAN recording; never accesses a vehicle."""
import json
import sys
from pathlib import Path
from collections import Counter
from openpilot.cereal import log
from opendbc.can import CANParser
from opendbc.car.tesla_ap1.phase3_stalk_controls import ExperimentalHold

if len(sys.argv) < 2:
  raise SystemExit('usage: replay_phase3_stalk_controls.py <path to a downloaded CAN recording (rlog)>')
path = Path(sys.argv[1])
parser = CANParser('tesla_can', [('STW_ACTN_RQ', 10)], 0)
pull, push = ExperimentalHold(2), ExperimentalHold(1)
levels = Counter()
segments = []
prev_level = None
prev_start = None
last_time = None
can_messages = 0
pulses = [0, 0]
engaged = False
count = 0
for event in log.Event.read_multiple_bytes(path.read_bytes()):
  kind = event.which()
  if kind == 'carState':
    engaged = bool(event.carState.cruiseState.enabled)
  if kind != 'can':
    continue
  t = event.logMonoTime / 1e9
  frames = [(c.address, c.dat, c.src) for c in event.can if c.address == 0x45 and c.src == 0]
  if not frames:
    continue
  parser.update([(event.logMonoTime, frames)])
  spd = int(parser.vl['STW_ACTN_RQ']['SpdCtrlLvr_Stat'])
  sample = parser.ts_nanos['STW_ACTN_RQ']['SpdCtrlLvr_Stat']
  levels[spd] += 1
  if spd != prev_level:
    if prev_level in (1, 2): segments.append({'direction':prev_level, 'duration_s':round(t-prev_start, 6)})
    prev_level, prev_start = spd, t
  pulses[0] += pull.update(spd, engaged, t, sample, True, True, True, 1.23)
  pulses[1] += push.update(spd, engaged, t, sample, True, True, True, 1.23)
  last_time = t
  can_messages += len(frames)
  count += 1
if prev_level in (1,2):
  segments.append({'direction':prev_level,'duration_s':round(last_time-prev_start,6),'truncated':True})
print(json.dumps({'fixture':str(path),'fixture_bytes':path.stat().st_size,'can_0x45_bus0_frames':can_messages,
                  'levels':dict(levels),'pull_push_intervals':segments,'experimental_pulses_at_default':pulses,
                  'note':'Actual local recorded CAN replay, not live vehicle. No claim of long-hold coverage unless present in intervals.'}, indent=2))
