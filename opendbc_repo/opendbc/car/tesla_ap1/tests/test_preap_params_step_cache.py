"""Pre-AP params in card's 100 Hz step: no /data file IO in the step (preap/params.py StepCache, started by card.py)."""
import pathlib
import threading
import time

import pytest

from opendbc.car.tesla_ap1.preap import params
from opendbc.car.tesla_ap1.preap.params import PreApParamKeys as K
from opendbc.car.tesla_ap1.tests.test_preap_full_demote import Car, _double_pull
from opendbc.car.tesla_ap1.tests.test_preap_carstate_controller import _params_dir  # noqa: F401


@pytest.fixture
def cache():
  c = params.start_step_cache()
  yield c
  params.stop_step_cache()


@pytest.fixture
def io_log(monkeypatch):
  """Every file read / write made by a thread other than the cache's own."""
  log = []
  real_read, real_write = pathlib.Path.read_text, pathlib.Path.write_text

  def rd(self, *a, **kw):
    c = params._step_cache
    if c is None or threading.current_thread() is not c.thread:
      log.append(("read", self.name))
    return real_read(self, *a, **kw)

  def wr(self, *a, **kw):
    c = params._step_cache
    if c is None or threading.current_thread() is not c.thread:
      log.append(("write", self.name))
    return real_write(self, *a, **kw)
  monkeypatch.setattr(pathlib.Path, "read_text", rd)
  monkeypatch.setattr(pathlib.Path, "write_text", wr)
  return log


def test_full_drive_steps_make_no_file_io(cache, io_log):
  c = Car(pedal=True)
  io_log.clear()
  _double_pull(c)
  for _ in range(300):                       # 3 s more in FULL: pedal heartbeat writes every 1 s, calibration reads every step
    c.step()
  assert c.rig.cs.preap_fsm_mode is not None
  assert io_log == [] and cache.misses == 0


def test_without_the_cache_the_same_steps_do_file_io(io_log):
  c = Car(pedal=True)
  io_log.clear()
  for _ in range(150):
    c.step()
  assert any(op == "read" for op, _ in io_log)   # the check above is not vacuous


def test_writes_reach_the_file_from_the_background_thread(cache, _params_dir):
  params.set_float(K.PEDAL_SEEN_MONO, 12.5)
  assert params.get_float(K.PEDAL_SEEN_MONO) == 12.5          # read-your-write at once
  deadline = time.monotonic() + 2.0
  path = params._path(K.PEDAL_SEEN_MONO)
  while time.monotonic() < deadline and not path.is_file():
    time.sleep(0.02)
  assert path.read_text().strip() == "12.5"


def test_ui_writes_are_seen_within_a_refresh(cache):
  params.stop_step_cache()
  params.set_bool(K.PEDAL_CALIB_ARMED, False)
  c = params.start_step_cache()
  assert params.get_bool(K.PEDAL_CALIB_ARMED) is False
  params._write_text_file(K.PEDAL_CALIB_ARMED, "1")           # another process (the UI) arms calibration
  time.sleep(3 * c.REFRESH_S)
  assert params.get_bool(K.PEDAL_CALIB_ARMED) is True


def test_write_errors_never_raise_into_the_step(cache, monkeypatch):
  def boom(key, text):
    raise OSError("read-only /data")
  monkeypatch.setattr(params, "_write_text_file", boom)
  params.set_float(K.PEDAL_SEEN_TS, 1.0)                       # no raise
  cache.refresh_once()
  assert cache.write_errors >= 1


def test_card_starts_the_cache_for_pre_ap_and_moves_its_own_param_read():
  src = (pathlib.Path(params.__file__).resolve().parents[5] / "openpilot/selfdrive/car/card.py").read_text()
  pre = src.split("self.preap_refusals = TxRefusalWatch()", 1)[1].split("\n    if ", 1)[0]
  assert "start_step_cache()" in pre
  step_body = src.split("  def state_update(self)", 1)[1].split("  def params_thread", 1)[0]
  # the only Params call left in the step is stock's one-time ControlsReady write when controls first start
  assert "self.params.get" not in step_body
  assert [ln.strip() for ln in step_body.splitlines() if "self.params.put" in ln] == ['self.params.put_bool("ControlsReady", True)']
  assert 'self.onroad_distance_button = self.params.get_bool("OnroadDistanceButtonPressed")' in src
