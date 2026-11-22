"""AP1 Model X openpilot long row: no reboot in any case. The setting is read once when the car starts (card CarParams and the
panda safety param), and every process holding it restarts with the ignition (manager only_onroad / started-gated: card,
controlsd, selfdrived, plannerd, radard; pandad re-reads CarParams after ControlsReady on each onroad transition, and
CarParams / ControlsReady are cleared on that transition). Car off: saved (turning on asks to confirm first). Car on, whether
driving, parked or engaged: queued, written when the car is turned off. AP1 S and Pre-AP rows unchanged."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.bogpilot import onroad_policy, phase2_vehicle as pv

KEY = pv.X_LONG
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
    self.m.moving_fn = lambda: self.state["moving"]
    self.m.engaged_fn = lambda: self.state["engaged"]
    onroad_policy.set_state(onroad_policy.DriveState(started=lambda: self.state["started"],
                                                     parked=lambda: self.state["parked"],
                                                     engaged=lambda: self.state["engaged"]))
    self.path = tmp_path / KEY

  def off(self):
    self.path.write_text("0")


@pytest.fixture(autouse=True)
def _restore():
  yield
  onroad_policy.set_state(None)


def test_enable_car_off_confirms_then_saves_without_reboot(tmp_path, pending):
  r = Rig(tmp_path)
  r.off()
  action, msg = r.m.x_long_change(True)
  assert action == "confirm" and "next time the car starts" in msg and "reboot" not in msg.lower()
  assert r.path.read_text() == "0" and r.puts == []                                  # nothing until confirm
  action, msg = r.m.confirm_x_long_on()
  assert action == "saved" and "No reboot needed" in msg
  assert r.path.read_text() == "1" and r.puts == [] and r.changes == [KEY] and pending == {}
  assert pv.X_LONG_ON_CONFIRM == "Turn On"


@pytest.mark.parametrize("state", [{"parked": True}, {"parked": False}, {"parked": True, "moving": True},
                                   {"parked": True, "engaged": True}, {"parked": False, "moving": True, "engaged": True}])
@pytest.mark.parametrize("value", [True, False])
def test_change_with_the_car_on_is_queued_never_rebooted(tmp_path, pending, state, value):
  r = Rig(tmp_path, started=True, **state)
  r.path.write_text("1" if not value else "0")
  action, msg = r.m.x_long_change(value)
  assert action == "queued" and "next time the car starts" in msg and "No reboot needed" in msg
  assert r.path.read_text() == ("1" if not value else "0") and r.puts == [] and pending == {KEY: value}
  assert r.m.read(KEY) is value                                                      # the row shows what the car will start with


def test_queued_change_applies_with_the_car_off(tmp_path, pending):
  r = Rig(tmp_path, started=True, parked=False)
  r.off()
  r.m.x_long_change(True)
  written = []
  onroad_policy.register_applier(KEY, lambda v: written.append(v) or True)
  try:
    assert onroad_policy.apply_pending() == {KEY: True}
  finally:
    onroad_policy.register_applier(KEY, None)
  assert written == [True] and pending == {} and r.puts == []


def test_real_applier_writes_the_file_for_an_x(tmp_path, monkeypatch):
  from opendbc.car.tesla_ap1 import toggles
  from openpilot.selfdrive.ui import ui_state as us
  monkeypatch.setattr(toggles, "_ap1x_op_long_path", tmp_path / KEY)
  monkeypatch.setattr(us.ui_state, "CP", cp())
  assert pv.apply_staged_x_long(True) is True and (tmp_path / KEY).read_text() == "1"
  monkeypatch.setattr(us.ui_state, "CP", cp("TESLA_AP1_MODELS"))
  assert pv.apply_staged_x_long(False) is False and (tmp_path / KEY).read_text() == "1"


def test_dialog_open_then_car_started_queues_instead(tmp_path, pending):
  r = Rig(tmp_path)
  r.off()
  assert r.m.x_long_change(True)[0] == "confirm"
  r.state.update(started=True)
  action, msg = r.m.confirm_x_long_on()
  assert action == "queued" and msg == pv.X_LONG_QUEUED_ON
  assert r.path.read_text() == "0" and pending == {KEY: True} and r.puts == []


def test_car_off_change_clears_an_older_queued_value(tmp_path, pending):
  r = Rig(tmp_path)
  pending[KEY] = True
  assert r.m.x_long_change(False)[0] == "saved"
  assert pending == {} and r.path.read_text() == "0"


def test_disable_car_off_saves_for_next_start_no_reboot(tmp_path, pending):
  r = Rig(tmp_path)
  action, msg = r.m.x_long_change(False)                                             # default on -> off
  assert action == "saved" and "next time the car starts" in msg
  assert r.path.read_text() == "0" and r.puts == [] and r.changes == [KEY]


def test_no_reboot_path_left():
  assert not hasattr(pv.VehicleSettings, "confirm_x_long_reboot")
  assert not hasattr(pv.VehicleSettings, "x_long_reboot_allowed")
  assert not any(n.startswith("X_LONG_REBOOT") for n in dir(pv))
  src = (OPENPILOT / "selfdrive/ui/bogpilot/phase2_vehicle.py").read_text()
  x_block = src[src.index("def x_long_change"):src.index("def _write_long")]
  assert "reboot_now" not in x_block and "DoReboot" not in x_block
  ui_block = src[src.index("def _set_x_long"):src.index("def refresh", src.index("def _set_x_long"))]
  assert "reboot" not in ui_block.replace("Never reboots", "")


def test_no_x_long_text_says_it_reboots():
  from openpilot.selfdrive.ui.bogpilot import menu_locks
  from openpilot.selfdrive.ui.bogpilot.toggle_help import resolve
  texts = [pv.DESCRIPTIONS[KEY], pv.X_LONG_ON_PROMPT, pv.X_LONG_ON_NEXT_START, pv.X_LONG_QUEUED_ON, pv.X_LONG_QUEUED_OFF,
           pv.X_LONG_OFF_NEXT_START, menu_locks.MODEL_X_VEHICLE.detail]
  entry = resolve(KEY)
  texts += [str(getattr(entry, f, "")) for f in ("what", "note", "when")]
  for t in texts:
    assert "reboots" not in t.lower() and "after a reboot" not in t.lower(), t


def test_staged_key_and_applier_registered():
  assert KEY in onroad_policy.STAGED_KEYS and "DisableOpenpilotLongitudinal" in onroad_policy.STAGED_KEYS
  assert onroad_policy._default_applier(KEY) is pv.apply_staged_x_long


@pytest.mark.parametrize("fp", ["TESLA_AP1_MODELS", "TESLA_PREAP_MODELS"])
def test_s_and_preap_refused(tmp_path, pending, fp):
  r = Rig(tmp_path, car=cp(fp))
  assert r.m.x_long_change(True) == ("refused", None) and not r.path.exists() and pending == {}
  assert r.m.confirm_x_long_on() == ("refused", None) and not r.path.exists() and r.puts == []


# ---- the lifecycle facts the no-reboot rule rests on (source checks; the ignition-cycle run is in the research note) ----
def test_every_process_holding_x_long_restarts_with_the_ignition():
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
