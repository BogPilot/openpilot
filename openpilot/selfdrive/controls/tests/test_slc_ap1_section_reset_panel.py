"""The real SLC panel on AP1 Model S: hints and section resets follow the AP1 profile (the editor-level cases are in
selfdrive/ui/tests/test_slc_ap1_section_reset.py). Other cars keep the general table (test_gas_brake_mounts.py)."""
from openpilot.common.bogpilot_ap1_profile import AP1_CAR_MODEL
from openpilot.selfdrive.controls.tests.test_gas_brake_mounts import (  # noqa: F401  (fixtures used by name)
  confirm_yes, press, reset_rows, rows, slc_page, store, titled, window,
)


def test_ap1_s_panel_resets_to_the_ap1_profile(store, monkeypatch):
  asked = confirm_yes(monkeypatch)
  store.put("CarModel", AP1_CAR_MODEL, block=True)
  page, _ = slc_page(store)
  panel = page.panel
  hints = {t: titled(panel, t).action_item.hint_text for t in ("Priority 1", "Priority 2", "Priority 3", "Look-ahead")}
  assert hints == {"Priority 1": "default: Dashboard", "Priority 2": "default: Map Data", "Priority 3": "default: Navigation",
                   "Look-ahead": "default: 5 seconds"}
  # main section: value rows plus the Override choice reset together
  press(titled(panel, "Look-ahead"), +1)
  titled(panel, "Override Speed").action_item.callback(1)          # 0 None, 1 gas pedal, 2 max set speed
  assert store.get_int("SLCOverride") == 1 and store.get_int("SLCLookaheadLower") == 6
  (reset,) = reset_rows(panel)
  reset.callback()
  store.invalidate()
  assert (store.get_int("SLCOverride"), store.get("SLCPriority1"), store.get("SLCPriority2"), store.get("SLCPriority3"),
          store.get_int("SLCLookaheadLower")) == (2, "Dashboard", "Map Data", "Navigation", 5)
  # offsets page: 4/5/5/5/7/8/10 mph
  [i for i in rows(panel) if i.title == "Speed Limit Offsets"][0].callback()
  offsets = [i for i in rows(panel) if i.title.startswith("Speed Offset (")]
  assert [i.action_item.hint_text for i in offsets] == [f"default: +{v} mph" for v in (4, 5, 5, 5, 7, 8, 10)]
  press(offsets[0], +1)
  (offset_reset,) = reset_rows(panel)
  offset_reset.callback()
  store.invalidate()
  assert [store.get_int(f"Offset{i}") for i in range(1, 8)] == [4, 5, 5, 5, 7, 8, 10]
  # Visual Settings: one reset row on AP1 S, for Show Speed Limit Offset (profile: on)
  assert page.navigation_back() is True
  [i for i in rows(panel) if i.title == "Visual Settings"][0].callback()
  assert store.get_bool("ShowSLCOffset") is True                    # registry default on
  store.put("ShowSLCOffset", "0", block=True)                      # a saved off is only changed by the reset
  (visual_reset,) = reset_rows(panel)
  visual_reset.callback()
  store.invalidate()
  assert store.get_bool("ShowSLCOffset") is True
  assert len(asked) == 3
  # Quality of Life has no row the profile writes: still no reset
  assert page.navigation_back() is True
  [i for i in rows(panel) if i.title == "Quality of Life"][0].callback()
  assert reset_rows(panel) == []
