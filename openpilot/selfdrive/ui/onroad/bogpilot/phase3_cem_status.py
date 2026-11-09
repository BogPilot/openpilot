"""Native CEM status badge: existing CEStatus key + fresh existing frogpilotPlan.

Display only. Never changes ExperimentalMode, car controls, schemas or defaults.
CEStatus meanings are the own04d560f3e speed/turn/stop/curve/lead icon categories.
"""
from dataclasses import dataclass
from openpilot.selfdrive.controls.lib.phase3_long_accel import CEM_ACK

NAMES = {0: "Ready", 1: "Overridden", 2: "Experimental", 3: "Speed", 4: "Speed", 5: "Turn", 6: "Stop",
         7: "Turn", 8: "Curve", 9: "Lead", 10: "Lead", 11: "Stop", 12: "Stop", 13: "Experimental"}


@dataclass(frozen=True)
class StatusView:
  visible: bool = False
  text: str = ""
  active: bool = False
  reason: int = 0


HIDDEN = StatusView()


def read_status(store, sm, now, drive_start, enabled):
  try:
    if not (enabled and store.get_bool(CEM_ACK, False) and store.toggle_bool("ConditionalExperimental") and
            store.toggle_bool("ShowCEMStatus")):
      return HIDDEN
    t = sm.recv_time["frogpilotPlan"]
    if not (sm.alive["frogpilotPlan"] and sm.valid["frogpilotPlan"] and drive_start <= t <= now and now - t <= .5):
      return HIDDEN
    active = bool(sm["frogpilotPlan"].experimentalMode)
    reason = store.get_int("CEStatus", 0)
    if reason not in NAMES:
      return HIDDEN
    if not active:
      reason = 0  # do not pair a stale reason with a fresh inactive plan
    return StatusView(True, "CEM: " + NAMES[reason if reason or not active else 2], active, reason)
  except (AttributeError, KeyError, TypeError, ValueError):
    return HIDDEN


def paint_status(view, rect):
  """Actual pyray badge, design coordinates supplied by existing HUD matrix."""
  if not view.visible:
    return
  import pyray as rl
  from openpilot.system.ui.lib.application import gui_app, FontWeight
  background = rl.Color(130, 95, 20, 220) if view.active else rl.Color(30, 30, 30, 200)
  rl.draw_rectangle_rounded(rect, .3, 12, background)
  font = gui_app.font(FontWeight.MEDIUM)
  size = 28
  width = rl.measure_text_ex(font, view.text, size, 0).x
  rl.draw_text_ex(font, view.text, rl.Vector2(rect.x + (rect.width - width) / 2, rect.y + (rect.height - size) / 2),
                  size, 0, rl.WHITE)
