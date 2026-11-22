"""Driving Personalities defaults end to end on the real compiled Params (libparams_c.so): the real manager_init default loop
and BogPilot startup hooks (harness from test_bogpilot_startup.py), first boot vs upgrade. No process, hardware or device."""
from unittest.mock import Mock

import pytest

from openpilot.common.params import Params
from openpilot.common.bogpilot_store import ParamStore
from openpilot.system.manager.test.test_bogpilot_startup import imported_manager

RELAXED, STANDARD = 2, 1


class Device:
  """Real Params; only the harness's mocked hardware strings (serial, etc.) are not written."""
  def __init__(self, params):
    self._p = params

  def __getattr__(self, name):
    return getattr(self._p, name)

  def put(self, key, value, *a, **kw):
    if not isinstance(value, Mock):
      self._p.put(key, value, *a, **kw)

  def clear_all(self, flag=None):
    pass   # harness ParamKeyFlag values are plain ints; nothing to clear on these fresh stores


def boot(tmp_path, params):
  with imported_manager(tmp_path, Device(params)) as (manager, _process):
    manager.manager_init()
    manager.manager_cleanup()
  return params


@pytest.fixture
def params(tmp_path, monkeypatch):
  monkeypatch.setenv("BOGPILOT_PARAMS_DIR", str(tmp_path / "params_bogpilot"))
  return Params(str(tmp_path / "native"))


def test_compiled_defaults_are_on_and_2_0(params):
  assert params.get_default_value("CustomPersonalities") in (True, "1", b"1")
  assert float(params.get_default_value("RelaxedFollow")) == 2.0
  assert int(params.get_default_value("LongitudinalPersonality")) == STANDARD     # stock compiled default unchanged


@pytest.mark.parametrize("car_model", [None, "TESLA_PREAP_MODELS", "TESLA_AP1_MODELX", "TESLA_AP1_MODELS"])
def test_fresh_install_lands_on_1_2_0_relaxed(tmp_path, params, car_model):
  if car_model:
    params.put("CarModel", car_model)
  boot(tmp_path, params)
  assert params.get("CustomPersonalities") is True
  assert params.get("RelaxedFollow") == pytest.approx(2.0)
  assert params.get("LongitudinalPersonality") == RELAXED
  store = ParamStore(params=params)
  assert store.get_bool("CustomPersonalities") is True and store.get_float("RelaxedFollow") == pytest.approx(2.0)
  for level in (0, 1, 2, 3):                                   # on at every Tuning Level
    store.put("TuningLevelConfirmed", "1", block=True)
    store.put("TuningLevel", level, block=True)
    store.invalidate()
    assert store.toggle_bool("CustomPersonalities") is True, level


def test_upgrade_keeps_saved_values(tmp_path, params):
  params.put("HasAcceptedTerms", "2")
  params.put_bool("CustomPersonalities", False)
  params.put("RelaxedFollow", 1.75)
  params.put("LongitudinalPersonality", STANDARD)
  boot(tmp_path, params)
  assert params.get("CustomPersonalities") is False
  assert params.get("RelaxedFollow") == pytest.approx(1.75)
  assert params.get("LongitudinalPersonality") == STANDARD


def test_upgrade_never_picked_personality_stays_standard(tmp_path, params):
  params.put("HasAcceptedTerms", "2")
  boot(tmp_path, params)
  assert params.get("LongitudinalPersonality") == STANDARD     # compiled default, not the fresh-install Relaxed
