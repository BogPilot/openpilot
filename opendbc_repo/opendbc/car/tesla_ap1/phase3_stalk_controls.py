"""AP1 stalk preferences and experimental-only hold detection.

No engagement/disengagement timing, button events, safety flags or CAN TX here.
File-backed because the installed Params schema cannot accept new Tesla keys.
"""
from dataclasses import dataclass, asdict
import json
import math
import os
from pathlib import Path
import time

AP1 = 'TESLA_AP1_MODELS'
DEFAULT_HOLD_S = 1.23
MIN_HOLD_S = 1.10
MAX_HOLD_S = 5.00
# STW_ACTN_RQ is subscribed at 10 Hz. Never count more than 2.5 periods
# without a new sample; a single missing frame may recover, a stale latch may not.
MAX_SAMPLE_AGE_S = 0.25
RELEASE_S = 0.10
CONFIG_PATH = Path('/data/params_bogpilot/StalkControls.json')


def hold_seconds(value):
  if isinstance(value, bool):
    raise ValueError('hold duration is seconds, not a boolean')
  try:
    seconds = float(value)
  except (ValueError, TypeError, OverflowError) as e:
    raise ValueError('invalid hold duration') from e
  if not math.isfinite(seconds) or not MIN_HOLD_S <= seconds <= MAX_HOLD_S:
    raise ValueError('hold duration must be 1.10–5.00 seconds')
  # Store/display hundredths without losing the existing 1.23 default.
  if abs(seconds * 100 - round(seconds * 100)) > 1e-7:
    raise ValueError('hold duration must use 0.01-second increments')
  return round(seconds, 2)


@dataclass(frozen=True)
class Settings:
  twist_follow: bool = True
  experimental_pull: bool = True
  experimental_push: bool = True
  pull_hold_s: float = DEFAULT_HOLD_S
  push_hold_s: float = DEFAULT_HOLD_S


def supported(cp):
  return (cp is not None and str(cp.carFingerprint) == AP1
          and not getattr(cp, 'dashcamOnly', True) and not getattr(cp, 'passive', True))


def experimental_supported(cp):
  return supported(cp) and bool(cp.openpilotLongitudinalControl)


class Store:
  def __init__(self, path=CONFIG_PATH):
    self.path = Path(path)

  def read(self):
    try:
      data = json.loads(self.path.read_text())
      if not isinstance(data, dict):
        raise ValueError('not a config object')
    except FileNotFoundError:
      return Settings()
    except (OSError, ValueError):
      # Damaged config must not unexpectedly enable a gesture.
      return Settings(experimental_pull=False, experimental_push=False)
    result = asdict(Settings())
    for key in result:
      if key not in data:
        continue
      if key.endswith('_s'):
        try:
          result[key] = hold_seconds(data[key])
        except ValueError:
          # Invalid delay disables its gesture instead of using a shorter delay.
          result['experimental_pull' if key == 'pull_hold_s' else 'experimental_push'] = False
      elif type(data[key]) is bool:
        result[key] = data[key]
      else:
        result[key] = False
    return Settings(**result)

  def write(self, key, value):
    fields = asdict(self.read())
    if key not in fields:
      raise KeyError(key)
    if key.endswith('_s'):
      value = hold_seconds(value)
    elif type(value) is not bool:
      raise ValueError('boolean required')
    fields[key] = value
    self.path.parent.mkdir(parents=True, exist_ok=True)
    # A private uniquely named temporary file; readers see only complete JSON.
    import tempfile
    fd, temp = tempfile.mkstemp(prefix='.StalkControls-', dir=self.path.parent)
    try:
      with os.fdopen(fd, 'w') as f:
        json.dump(fields, f, allow_nan=False)
      os.replace(temp, self.path)
    finally:
      if os.path.exists(temp):
        os.unlink(temp)


class ExperimentalHold:
  """One pulse per gesture, only explicit fresh neutral can rearm.

  `now` is monotonic seconds; `sample_ns` is the parser's STW signal timestamp.
  Timestamp domains need not match: changes in sample_ns mark arrivals on now.
  A blocked/corrupt/offroad/stale sample or settings/state change aborts the
  entire gesture. An engage pull or an engaged cancel push never becomes a
  mode toggle if cruise state changes during that same hold.
  """
  def __init__(self, direction):
    if direction not in (1, 2):
      raise ValueError('direction must be FWD=1 or RWD=2')
    self.direction = direction
    self.last_now = None
    self.last_sample = 0
    self.fresh_at = None
    self.neutral_since = None
    self.ready = False
    self.started = None
    self.signature = None

  def abort(self):
    self.ready = False
    self.started = None
    self.neutral_since = None

  def update(self, spd, engaged, now, sample_ns, valid, allowed, enabled, hold_s):
    try:
      hold_s = hold_seconds(hold_s)
      now = float(now)
      sample_ns = int(sample_ns)
      spd_value = float(spd)
      if not math.isfinite(spd_value) or spd_value != int(spd_value):
        raise ValueError('invalid stalk')
      spd = int(spd_value)
    except (ValueError, TypeError, OverflowError):
      self.abort()
      return False
    if not math.isfinite(now) or (self.last_now is not None and now <= self.last_now):
      self.abort()
      return False
    gap = self.last_now is not None and now - self.last_now > MAX_SAMPLE_AGE_S
    self.last_now = now
    backwards = sample_ns < self.last_sample
    if sample_ns > self.last_sample:
      self.fresh_at = now
      self.last_sample = sample_ns
    stale = sample_ns <= 0 or self.fresh_at is None or now - self.fresh_at > MAX_SAMPLE_AGE_S
    signature = (bool(enabled), hold_s)
    changed = self.signature is not None and signature != self.signature
    self.signature = signature
    if gap or backwards or stale or not valid or not allowed or not enabled or changed:
      self.abort()
      return False
    if spd == 0:
      self.started = None
      if self.neutral_since is None:
        self.neutral_since = now
      if now - self.neutral_since >= RELEASE_S - 1e-9:
        self.ready = True
      return False
    self.neutral_since = None
    appropriate_state = bool(engaged) if self.direction == 2 else not bool(engaged)
    if spd != self.direction or not appropriate_state:
      self.abort()
      return False
    if not self.ready:
      return False
    if self.started is None:
      self.started = now
      return False
    if now - self.started >= hold_s - 1e-9:
      self.abort()
      return True
    return False


class StalkControls:
  def __init__(self, store=None, clock=time.monotonic):
    self.store = store if store is not None else Store()
    self.clock = clock
    self.pull = ExperimentalHold(2)
    self.push = ExperimentalHold(1)
    self.settings = self.store.read()
    self.read_at = None

  def update(self, spd, engaged, sample_ns, valid, allowed, cp, now=None):
    now = self.clock() if now is None else now
    # Refresh in one place, max 10 reads/s. UI only writes offroad. A mode toggle
    # is additionally gated in card on current experimental eligibility.
    if self.read_at is None or now < self.read_at or now - self.read_at >= 0.1:
      self.settings = self.store.read()
      self.read_at = now
    s = self.settings
    allowed = bool(allowed and experimental_supported(cp))
    pull = self.pull.update(spd, engaged, now, sample_ns, valid, allowed, s.experimental_pull, s.pull_hold_s)
    push = self.push.update(spd, engaged, now, sample_ns, valid, allowed, s.experimental_push, s.push_hold_s)
    return pull, push


def apply_experimental_toggle(params, cp, cs, started):
  """Actual card-side permission and persistence; never forces longitudinal."""
  if not (started and experimental_supported(cp) and cs.canValid
          and params.get_bool('ExperimentalModeConfirmed')):
    return None
  if not (cs.bogpilot.ap1StalkPullToggle or cs.bogpilot.ap1StalkFwdToggle):
    return None
  value = not params.get_bool('ExperimentalMode')
  params.put_bool('ExperimentalMode', value, block=True)
  return value
