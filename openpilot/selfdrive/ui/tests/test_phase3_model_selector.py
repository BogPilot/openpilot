"""Contract fixtures below are synthetic, not a shipping model catalog."""
from dataclasses import replace
import pytest
from openpilot.selfdrive.ui.bogpilot.phase3_model_selector import (
  Model, Snapshot, Result, ModelSelector, ITEMS, OPERATIONS, ALL_ACTIONS, create_model_selector_layout,
)


class Backend:
  def __init__(self):
    self.state = Snapshot("1", (
      Model("fixture-stock", "Fixture stock", True, True, True, protected=True),
      Model("fixture-alt", "Fixture alternate", True, True, True),
    ), ALL_ACTIONS, active_id="fixture-stock")
    self.calls = []
    self.failure = False

  def snapshot(self):
    if self.failure:
      raise RuntimeError("test offline")
    return self.state

  def request(self, action, model_id, revision):
    self.calls.append((action, model_id, revision))
    if action == "select":
      self.state = replace(self.state, pending_id=model_id, revision="2")
    return Result(True, "Request accepted, awaiting runtime validation")


def _no_device_probe(monkeypatch):
  """Hosts without /sys/firmware/devicetree (docker/VM): pretend tizi so gui_app imports; no rendering."""
  try:
    monkeypatch.setattr("openpilot.common.hardware.comma.hardware.get_device_type", lambda: "tizi")
  except (ImportError, AttributeError):
    pass


@pytest.fixture
def setup():
  b = Backend()
  offroad = [True]
  c = ModelSelector(b, lambda: offroad[0])
  return b, offroad, c


def test_inventory_exact():
  assert [key for key, _ in ITEMS] == ["automatic", "delete", "download", "randomizer", "blacklist", "ratings", "select"]
  assert OPERATIONS["delete"] == ("delete", "delete_all")
  assert OPERATIONS["download"] == ("download", "download_all", "cancel")
  assert OPERATIONS["blacklist"] == ("blacklist_add", "blacklist_remove", "blacklist_clear")


def test_only_rows_with_a_consumer_are_visible(setup):
  b, _, c = setup
  assert [k for k, _ in c.visible_items()] == [k for k, _ in ITEMS]  # all capabilities advertised
  b.state = replace(b.state, capabilities=frozenset(), revision="3")
  c.refresh()
  assert c.visible_items() == (("select", "Select Driving Model"),)  # stock-only: no inert rows, no ratings placeholder
  b.state = replace(b.state, capabilities=frozenset(("select", "delete")), revision="4")
  c.refresh()
  assert [k for k, _ in c.visible_items()] == ["delete", "select"]
  b.failure = True
  c.refresh()
  assert c.visible_items() == (("select", "Select Driving Model"),)  # backend down: still honest, nothing actionable
  assert not c.allowed("select", "fixture-alt")[0]


@pytest.mark.parametrize("action", sorted(ALL_ACTIONS))
def test_every_mutation_offroad_only(setup, action):
  b, offroad, c = setup
  offroad[0] = False
  assert not c.execute(action, "fixture-alt")
  assert not b.calls
  assert c.message == "Offroad only"


def test_selection_is_pending_not_active(setup):
  b, _, c = setup
  assert c.execute("select", "fixture-alt", "1")
  assert c.state.active_id == "fixture-stock"
  assert c.state.pending_id == "fixture-alt"
  assert "Pending: Fixture alternate" in c.status()
  assert "Active: Fixture stock" in c.status()
  assert b.calls == [("select", "fixture-alt", "1")]


@pytest.mark.parametrize("compatible", [False, None])
def test_incompatibility_fail_closed(setup, compatible):
  b, _, c = setup
  b.state = replace(b.state, models=(b.state.models[0], replace(b.state.models[1], compatible=compatible)))
  assert not c.execute("select", "fixture-alt")
  assert not c.execute("download", "fixture-alt")
  assert not b.calls


def test_incomplete_download_not_selectable(setup):
  b, _, c = setup
  b.state = replace(b.state, models=(b.state.models[0], replace(b.state.models[1], downloaded=False)))
  assert not c.execute("select", "fixture-alt")
  assert c.execute("download", "fixture-alt")


def test_stale_confirmation_never_dispatches(setup):
  b, _, c = setup
  b.state = replace(b.state, revision="changed")
  assert not c.execute("select", "fixture-alt", "1")
  assert not b.calls


@pytest.mark.parametrize("key", ["active_id", "pending_id"])
def test_no_deleting_active_or_pending(setup, key):
  b, _, c = setup
  b.state = replace(b.state, **{key: "fixture-alt"})
  assert not c.execute("delete", "fixture-alt")
  assert not b.calls


def test_protected_stock_no_delete(setup):
  b, _, c = setup
  assert not c.execute("delete", "fixture-stock")
  assert not b.calls


def test_unavailable_backend_clears_stale_actions(setup):
  b, _, c = setup
  b.failure = True
  assert not c.execute("select", "fixture-alt")
  assert c.state is None and "unavailable" in c.status()
  assert not b.calls


def test_missing_capability_does_not_write_dummy_params(setup):
  b, _, c = setup
  b.state = replace(b.state, capabilities=frozenset())
  assert not c.execute("select", "fixture-alt")
  assert not b.calls


def test_stock_only_randomizer_not_fake(setup):
  b, _, c = setup
  b.state = replace(b.state, models=(b.state.models[0],), limitation="Only stock validated")
  assert not c.execute("randomizer_on")
  assert "Only stock validated" in c.status()
  assert not b.calls


def test_busy_blocks_all_but_cancel(setup):
  b, _, c = setup
  b.state = replace(b.state, busy=True, progress="Downloading 30%")
  assert not c.execute("select", "fixture-alt")
  assert c.execute("cancel")
  assert "Downloading 30%" in c.status()


def test_idle_cannot_cancel(setup):
  _, _, c = setup
  assert not c.execute("cancel")


def test_runtime_unknown_is_not_stock_claim(setup):
  b, _, c = setup
  b.state = replace(b.state, active_id=None)
  c.refresh()
  assert "Active: Not confirmed" in c.status()


def test_runtime_unknown_model_fails_closed(setup):
  b, _, c = setup
  b.state = replace(b.state, active_id="not-in-catalog")
  assert c.refresh() is None


def test_duplicate_catalog_ids_fail_closed(setup):
  b, _, c = setup
  b.state = replace(b.state, models=(b.state.models[0], b.state.models[0]))
  assert c.refresh() is None


def test_backend_rejection_not_activation(setup):
  b, _, c = setup
  b.request = lambda *args: Result(False, "Inference rejected compatibility")
  assert not c.execute("select", "fixture-alt")
  assert "Inference rejected" in c.message
  assert c.state.pending_id is None


def test_backend_exception_reported(setup):
  b, _, c = setup
  def fail(*args):
    raise RuntimeError("artifact verification failed")
  b.request = fail
  assert not c.execute("select", "fixture-alt")
  assert "verification failed" in c.message


def test_real_layout_inventory_and_truthful_status(setup, monkeypatch):
  _, _, c = setup
  import pyray as rl
  _no_device_probe(monkeypatch)
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.widgets import list_view
  monkeypatch.setattr(gui_app, "font", lambda *args: rl.Font())
  monkeypatch.setattr(list_view, "measure_text_cached", lambda *args: rl.Vector2(0, 0))
  layout = create_model_selector_layout(c)
  assert layout.section is None
  # Real raylib widgets constructed on native machine; no rendering claimed.
  layout.open_section("select")
  assert layout.section == "select"
  layout.open_section("ratings")
  layout.open_section(None)
  assert layout.section is None


def test_stock_only_real_layout_has_single_select_row(setup, monkeypatch):
  b, _, c = setup
  import pyray as rl
  _no_device_probe(monkeypatch)
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.widgets import list_view
  monkeypatch.setattr(gui_app, "font", lambda *args: rl.Font())
  monkeypatch.setattr(list_view, "measure_text_cached", lambda *args: rl.Vector2(0, 0))
  b.state = replace(b.state, capabilities=frozenset(), models=(b.state.models[0],), revision="9", active_id=None,
                    limitation="Default (stock) is the only validated driving model.")
  layout = create_model_selector_layout(c)
  assert len(layout.scroller._items) == 1 + 1  # status row + the single Select Driving Model row
  assert "only validated" in c.status()


def test_offroad_state_failure_is_closed(setup):
  b, _, c = setup
  def unavailable():
    raise RuntimeError("state lost")
  c.is_offroad = unavailable
  assert not c.execute("select", "fixture-alt")
  assert not b.calls


def test_native_confirmation_rechecks_drive_state(setup, monkeypatch):
  b, offroad, c = setup
  import pyray as rl
  _no_device_probe(monkeypatch)
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.widgets import list_view, DialogResult
  monkeypatch.setattr(gui_app, "font", lambda *args: rl.Font())
  monkeypatch.setattr(list_view, "measure_text_cached", lambda *args: rl.Vector2(0, 0))
  dialogs = []
  monkeypatch.setattr(gui_app, "push_widget", dialogs.append)
  layout = create_model_selector_layout(c)
  layout.confirm("select", "fixture-alt")
  assert len(dialogs) == 1
  offroad[0] = False
  dialogs[0]._callback(DialogResult.CONFIRM)
  assert not b.calls
  assert c.message == "Offroad only"


def test_driving_controls_page_registers_and_builds_with_real_backend(monkeypatch):
  """phase2_navigation accepts the Driving Model page; the factory builds the real raylib layout over the real
  runtime backend (stock only on this host: no /data/bogpilot state) and shows Default (stock)."""
  import sys, types
  import pyray as rl
  _no_device_probe(monkeypatch)
  monkeypatch.setitem(sys.modules, "openpilot.selfdrive.ui.ui_state",
                      types.SimpleNamespace(ui_state=types.SimpleNamespace(is_offroad=lambda: True)))
  from openpilot.selfdrive.ui.layouts.settings.phase2_navigation import Page, active_groups
  from openpilot.selfdrive.ui.bogpilot.phase3_model_page import DRIVING_MODEL_KEYS, create_driving_model_layout
  groups = active_groups({"driving": (Page("driving_model", "Driving Model", create_driving_model_layout, DRIVING_MODEL_KEYS),)})
  assert [(k, t, [p.title for p in pages]) for k, t, pages in groups] == [("driving", "Driving Controls", ["Driving Model"])]
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.widgets import list_view
  monkeypatch.setattr(gui_app, "font", lambda *args: rl.Font())
  monkeypatch.setattr(list_view, "measure_text_cached", lambda *args: rl.Vector2(0, 0))
  layout = groups[0][2][0].factory()
  assert layout.section is None
  from openpilot.common.phase3_model_backend import RuntimeModelBackend
  from openpilot.common.phase3_model_runtime import STOCK_ID
  snap = RuntimeModelBackend(is_offroad=lambda: True).snapshot()
  assert [(m.id, m.name) for m in snap.models] == [(STOCK_ID, "Default (stock)")]
  assert snap.capabilities == frozenset() and snap.active_id is None
