import datetime
import os
import threading
import time
import uuid

from openpilot.common.test import OpenpilotTestCase
from openpilot.common.params import Params, ParamKeyFlag, UnknownKeyName

class TestParams(OpenpilotTestCase):
  def setup_method(self):
    self.params = Params()

  def test_params_put_and_get(self):
    self.params.put("DongleId", "cb38263377b873ee", block=True)
    assert self.params.get("DongleId") == "cb38263377b873ee"

  def test_params_non_ascii(self):
    st = b"\xe1\x90\xff"
    self.params.put("CarParams", st, block=True)
    assert self.params.get("CarParams") == st

  def test_params_get_cleared_manager_start(self):
    self.params.put("CarParams", b"test", block=True)
    self.params.put("DongleId", "cb38263377b873ee", block=True)
    assert self.params.get("CarParams") == b"test"

    undefined_param = self.params.get_param_path(uuid.uuid4().hex)
    with open(undefined_param, "w") as f:
      f.write("test")
    assert os.path.isfile(undefined_param)

    self.params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
    assert self.params.get("CarParams") is None
    assert self.params.get("DongleId") is not None
    assert not os.path.isfile(undefined_param)

  def test_params_two_things(self):
    self.params.put("DongleId", "bob", block=True)
    self.params.put("AthenadPid", 123, block=True)
    assert self.params.get("DongleId") == "bob"
    assert self.params.get("AthenadPid") == 123

  def test_params_get_block(self):
    def _delayed_writer():
      time.sleep(0.1)
      self.params.put("CarParams", b"test", block=True)
    threading.Thread(target=_delayed_writer).start()
    assert self.params.get("CarParams") is None
    assert self.params.get("CarParams", block=True) == b"test"

  def test_params_unknown_key_fails(self):
    with self.assertRaises(UnknownKeyName):
      self.params.get("swag")

    with self.assertRaises(UnknownKeyName):
      self.params.get_bool("swag")

    with self.assertRaises(UnknownKeyName):
      self.params.put("swag", "abc", block=True)

    with self.assertRaises(UnknownKeyName):
      self.params.put_bool("swag", True, block=True)

    with self.assertRaises(UnknownKeyName):
      self.params.put(b"DongleId\0suffix", "abc", block=True)

    assert self.params.get_param_path(b"key\0suffix").endswith("/key\0suffix")

  def test_remove_not_there(self):
    assert self.params.get("CarParams") is None
    self.params.remove("CarParams")
    assert self.params.get("CarParams") is None

  def test_get_bool(self):
    self.params.remove("IsMetric")
    assert not self.params.get_bool("IsMetric")

    self.params.put_bool("IsMetric", True, block=True)
    assert self.params.get_bool("IsMetric")

    self.params.put_bool("IsMetric", False, block=True)
    assert not self.params.get_bool("IsMetric")

    self.params.put("IsMetric", True, block=True)
    assert self.params.get_bool("IsMetric")

    self.params.put("IsMetric", False, block=True)
    assert not self.params.get_bool("IsMetric")

  def test_put_non_blocking_with_get_block(self):
    q = Params()
    def _delayed_writer():
      time.sleep(0.1)
      Params().put("CarParams", b"test")
    threading.Thread(target=_delayed_writer).start()
    assert q.get("CarParams") is None
    assert q.get("CarParams", True) == b"test"

  def test_put_bool_non_blocking_with_get_block(self):
    q = Params()
    def _delayed_writer():
      time.sleep(0.1)
      Params().put_bool("CarParams", True)
    threading.Thread(target=_delayed_writer).start()
    assert q.get("CarParams") is None
    assert q.get("CarParams", True) == b"1"

  @staticmethod
  def _reads_back(key, want, timeout=1.0):
    reader = Params()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
      if reader.get(key) == want:
        return True
      time.sleep(0.0002)
    return reader.get(key) == want

  def test_put_non_blocking_never_strands_a_write(self):
    # a new value right after the previous one lands probes the moment the
    # writer thread finds the queue empty and is about to return
    q = Params()
    for i in range(1000):
      val = f"single{i}".encode()
      q.put("CarParams", val)
      assert self._reads_back("CarParams", val), f"write {i} was not persisted"

  def test_put_non_blocking_two_threads_one_object(self):
    q = Params()
    errors = []
    def _writer(key, prefix, as_bytes):
      for i in range(500):
        val = f"{prefix}{i}"
        val = val.encode() if as_bytes else val
        q.put(key, val)
        if not self._reads_back(key, val):
          errors.append((key, i))
          return
    threads = [threading.Thread(target=_writer, args=("CarParams", "a", True)),
               threading.Thread(target=_writer, args=("DongleId", "b", False))]
    for t in threads:
      t.start()
    for t in threads:
      t.join()
    assert not errors, f"writes not persisted: {errors}"

  def test_put_non_blocking_then_release_object(self):
    for i in range(200):
      q = Params()
      val = f"released{i}".encode()
      q.put("CarParams", val)
      del q  # the destructor waits for the writer
      assert Params().get("CarParams") == val

  def test_params_all_keys(self):
    keys = Params().all_keys()

    # sanity checks
    assert len(keys) > 20
    assert len(keys) == len(set(keys))
    assert b"CarParams" in keys

  def test_params_default_value(self):
    self.params.remove("LanguageSetting")
    self.params.remove("LongitudinalPersonality")
    self.params.remove("LiveParametersV2")

    assert self.params.get("LanguageSetting") is None
    assert self.params.get("LanguageSetting", return_default=False) is None
    assert isinstance(self.params.get("LanguageSetting", return_default=True), str)
    assert isinstance(self.params.get("LongitudinalPersonality", return_default=True), int)
    assert self.params.get("LiveParametersV2") is None
    assert self.params.get("LiveParametersV2", return_default=True) is None

  def test_params_get_type(self):
    # json
    self.params.put("ApiCache_FirehoseStats", {"a": 0}, block=True)
    assert self.params.get("ApiCache_FirehoseStats") == {"a": 0}

    # int
    self.params.put("BootCount", 1441, block=True)
    assert self.params.get("BootCount") == 1441

    # bool
    self.params.put("AdbEnabled", True, block=True)
    assert self.params.get("AdbEnabled")
    assert isinstance(self.params.get("AdbEnabled"), bool)

    # time
    now = datetime.datetime.now(datetime.UTC)
    self.params.put("InstallDate", now, block=True)
    assert self.params.get("InstallDate") == now
