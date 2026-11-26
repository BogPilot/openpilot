"""AP1 Model X single longitudinal row (Disable openpilot Longitudinal Control): no reboot in any case. The setting is read once
when the car starts (card CarParams and the panda safety param), and every process holding it restarts with the ignition (manager
only_onroad / started-gated: card, controlsd, selfdrived, plannerd, radard; pandad re-reads CarParams after ControlsReady on each
onroad transition, and CarParams / ControlsReady are cleared on that transition). Car off: saved. Car on, whether driving, parked
or engaged: queued, written when the car is turned off. An older queued Model X row change is applied as this row."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.bogpilot import onroad_policy, phase2_vehicle as pv

LONG, X_LONG = pv.LONG, pv.X_LONG
OPENPILOT = Path(__file__).resolve().parents[3]


def cp(fp="TESLA_AP1_MODELX"):
  return SimpleNamespace(carFingerprint=fp, dashcamOnly=False, openpilotLongitudinalControl=False, alphaLongitudinalAvailable=False)


@pytest.fixture
def pending(monkeypatch):
  store = {}
  monkeypatch.setattr(onroad_policy, "_read_all", lambda: dict(store))

  def write_all(values):
    store.clear()
    store.update(values)
    return True
  monkeypatch.setattr(onroad_policy, "_write_all", write_all)
  return store


class Rig:
  def __init__(self, tmp_path, started=False, parked=True, moving=False, engaged=False, car=None):
    self.puts, self.changes = [], []
    self.state = {"started": started, "parked": parked, "moving": moving, "engaged": engaged}
    params = SimpleNamespace(put_bool=lambda k, v, **kw: self.puts.append((k, v)))
    self.m = pv.VehicleSettings(params, lambda: car or cp(), lambda: True, file_dir=str(tmp_path),
                                params_file=str(tmp_path / "unused"), started=lambda: self.state["started"],
                                on_change=self.changes.append)
    onroad_policy.set_state(onroad_policy.DriveState(started=lambda: self.state["started"],
                                                     parked=lambda: self.state["parked"],
                                                     engaged=lambda: self.state["engaged"]))
    self.x_path = tmp_path / X_LONG


@pytest.fixture(autouse=True)
def _restore():
  yield
  onroad_policy.set_state(None)


@pytest.mark.parametrize("value", [True, False])
def test_car_off_saves_and_removes_the_retired_model_x_file(tmp_path, pending, value):
  r = Rig(tmp_path)
  r.x_path.write_text("0")                                                         # old row Off
  assert r.m.write(LONG, value) is True
  assert r.puts == [(LONG, value)] and not r.x_path.exists() and pending == {} and r.changes == [LONG]


@pytest.mark.parametrize("state", [{"parked": True}, {"parked": False}, {"parked": True, "moving": True},
                                   {"parked": True, "engaged": True}, {"parked": False, "moving": True, "engaged": True}])
@pytest.mark.parametrize("value", [True, False])
def test_change_with_the_car_on_is_queued_never_rebooted(tmp_path, pending, state, value):
  r = Rig(tmp_path, started=True, **state)
  pending[X_LONG] = False                                                          # an older queued Model X row change
  assert r.m.write(LONG, value) is True
  assert r.puts == [] and not r.x_path.exists() and pending == {LONG: value}       # replaces it, nothing written yet
  assert r.m.read(LONG) is value                                                   # the row shows what the car will start with


def test_queued_change_applies_with_the_car_off(tmp_path, pending):
  r = Rig(tmp_path, started=True, parked=False)
  r.m.write(LONG, False)
  written = []
  onroad_policy.register_applier(LONG, lambda v: written.append(v) or True)
  try:
    assert onroad_policy.apply_pending() == {LONG: True}
  finally:
    onroad_policy.register_applier(LONG, None)
  assert written == [False] and pending == {}


@pytest.mark.parametrize("queued", [True, False])
def test_older_queued_model_x_row_change_shows_and_applies_as_the_single_row(tmp_path, pending, monkeypatch, queued):
  from openpilot.selfdrive.ui import ui_state as us
  r = Rig(tmp_path)
  pending[X_LONG] = queued
  assert r.m.read(LONG) is (not queued)
  calls = []
  monkeypatch.setattr(pv.VehicleSettings, "write", lambda self, key, state: calls.append((key, state)) or True)
  monkeypatch.setattr(us.ui_state, "CP", cp())
  assert pv.apply_staged_x_long(queued) is True and calls == [(LONG, not queued)]
  monkeypatch.setattr(us.ui_state, "CP", cp("TESLA_AP1_MODELS"))
  assert pv.apply_staged_x_long(queued) is False and len(calls) == 1


def test_no_model_x_row_flow_or_reboot_path_left():
  for name in ("x_long_change", "confirm_x_long_on", "confirm_x_long_reboot", "x_long_reboot_allowed"):
    assert not hasattr(pv.VehicleSettings, name), name
  assert not any(n.startswith(("X_LONG_REBOOT", "X_LONG_ON_", "X_LONG_QUEUED", "X_LONG_OFF")) for n in dir(pv))
  src = (OPENPILOT / "selfdrive/ui/bogpilot/phase2_vehicle.py").read_text()
  assert "_set_x_long" not in src
  block = src[src.index("def _write_long"):src.index("def apply_staged_x_long")]
  assert "reboot_now" not in block and "DoReboot" not in block


def test_no_model_x_text_says_it_reboots():
  from openpilot.selfdrive.ui.bogpilot import menu_locks
  from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve
  texts = [pv.DESCRIPTIONS[X_LONG], pv.X_DISABLE_LONG_DESCRIPTION, menu_locks.MODEL_X_VEHICLE.detail, menu_locks.MODEL_X_WHEEL.detail]
  for key in (X_LONG, LONG):
    entry = resolve(key)
    texts += [str(getattr(entry, f, "")) for f in ("what", "note", "when")]
  for t in texts:
    assert "reboots" not in t.lower() and "after a reboot" not in t.lower(), t


def test_staged_keys_and_appliers_registered():
  assert X_LONG in onroad_policy.STAGED_KEYS and LONG in onroad_policy.STAGED_KEYS     # X_LONG kept for older queued changes
  assert onroad_policy._default_applier(X_LONG) is pv.apply_staged_x_long
  assert onroad_policy._default_applier(LONG) is pv.apply_staged_long


@pytest.mark.parametrize("fp", ["TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"])
def test_s_and_preap_never_touch_the_model_x_file(tmp_path, pending, fp):
  r = Rig(tmp_path, car=cp(fp))
  pending[X_LONG] = True
  assert r.m.write(LONG, False) is True and not r.x_path.exists() and pending == {X_LONG: True}
  assert r.m.read(LONG) is False


# ---- the lifecycle facts the no-reboot rule rests on (source checks; the ignition-cycle run is in the research note) ----
def test_every_process_holding_the_setting_restarts_with_the_ignition():
  from openpilot.system.manager.process_config import managed_processes as procs
  params = SimpleNamespace(get_bool=lambda k: False, put_bool=lambda *a, **k: None)
  CP = SimpleNamespace(notCar=False)
  for name in ("card", "controlsd", "selfdrived", "plannerd", "radard"):
    p = procs[name]
    assert p.should_run(True, params, CP) is True and p.should_run(False, params, CP) is False, name


def test_carparams_and_pandad_handshake_cleared_on_each_onroad_transition():
  keys = (OPENPILOT / "common/params_keys.h").read_text()
  for k in ("CarParams", "ControlsReady", "FirmwareQueryDone"):
    line = next(l for l in keys.splitlines() if f'{{"{k}",' in l)
    assert "CLEAR_ON_ONROAD_TRANSITION" in line, k
  safety = (OPENPILOT / "selfdrive/pandad/panda_safety.cc").read_text()
  # pandad drops its configured safety when the car goes offroad and fetches CarParams again after ControlsReady
  assert "} else if (!is_onroad) {" in safety and "safety_configured_ = false;" in safety
  assert 'params_.getBool("ControlsReady")' in safety and 'params_.get("CarParams")' in safety


def test_ui_rereads_carparams():
  src = (OPENPILOT / "selfdrive/ui/ui_state.py").read_text()
  body = src[src.index("def update_params"):]
  assert 'self.params.get("CarParamsPersistent")' in body[:400]
