"""Atomic replace of /data/params_bogpilot files: a concurrent reader never sees a torn write.

07e8bd68f's StepCache writes these files from a background thread. Path.write_text truncates
first, so a reader can see empty text and fall back to the default. _write_text_file now
writes a tmp in the same directory, fsyncs, and os.replace.
"""
import os
import threading
import time

import pytest

from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401

KEY = K.PEDAL_CALIB_MESSAGE   # default ""
VALUES = ("alpha", "bravo")
STRESS_WRITES = 200
STRESS_ROUNDS = 80
MUTANT_ROUNDS = 80


def _inplace_write(key: str, text: str) -> None:
  """The 07e8bd68f in-place write: truncate, then write (mutant)."""
  params._params_dir.mkdir(parents=True, exist_ok=True)
  params._path(key).write_text(text, encoding="utf-8")


def _race(write_fn, n_writes=STRESS_WRITES) -> list[str]:
  """Writer alternates known values; the reader hammers _read_text_file. Returns bad reads."""
  bad = []
  stop = threading.Event()
  write_fn(KEY, VALUES[0])

  def reader():
    while not stop.is_set():
      text = params._read_text_file(KEY)
      if text not in VALUES:
        bad.append(text)
        return

  t = threading.Thread(target=reader, name="params_stress_reader")
  t.start()
  try:
    for i in range(n_writes):
      write_fn(KEY, VALUES[i % 2])
  finally:
    stop.set()
    t.join(timeout=2.0)
  text = params._read_text_file(KEY)
  if text not in VALUES:
    bad.append(text)
  leftovers = [n for n in os.listdir(params._params_dir) if n.endswith(".tmp") or (KEY + ".") in n and n != KEY]
  if leftovers:
    bad.append("leftover:" + ",".join(sorted(leftovers)))
  return bad


def test_atomic_write_reader_never_sees_empty_or_default(_params_dir):
  bads = []
  for i in range(STRESS_ROUNDS):
    bad = _race(params._write_text_file)
    if bad:
      bads.append((i, bad[:5]))
  assert bads == [], f"atomic write leaked empty/default or left tmp in {len(bads)}/{STRESS_ROUNDS} rounds: {bads[:3]}"


def test_mutant_inplace_write_is_caught_with_high_probability(_params_dir):
  kills = 0
  for _ in range(MUTANT_ROUNDS):
    if _race(_inplace_write):
      kills += 1
  rate = kills / MUTANT_ROUNDS
  # The in-place truncate-then-write must be visible to a hammering reader often
  # enough that this test is not a coin flip. Report the measured kill rate.
  assert rate >= 0.25, f"inplace mutant kill rate {rate:.2f} ({kills}/{MUTANT_ROUNDS}) is too low to trust"
  print(f"inplace_mutant_kill_rate={rate:.3f} kills={kills} rounds={MUTANT_ROUNDS}")


def test_failed_write_removes_only_the_tmp(_params_dir, monkeypatch):
  params._write_text_file(KEY, VALUES[0])
  dest = params._path(KEY)
  real_replace = os.replace

  def boom(src, dst):
    raise OSError("replace failed")

  monkeypatch.setattr(os, "replace", boom)
  with pytest.raises(OSError, match="replace failed"):
    params._write_text_file(KEY, VALUES[1])
  assert dest.read_text(encoding="utf-8") == VALUES[0]     # destination unchanged
  leftovers = list(params._params_dir.iterdir())
  assert leftovers == [dest], leftovers
