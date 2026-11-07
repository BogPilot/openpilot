"""C3X alert layer adapter: native raylib alert source + ported redesign banner painter.

w9 (HUD composition) owns where this is called. Contract: render it LAST among onroad content layers (after model,
HUD/graph/lead/personality and driver-monitor), so a safety alert is never painted over. See alert_banner_logic.
"""
from __future__ import annotations
import pyray as rl

from openpilot.selfdrive.ui.onroad.alert_renderer import (
  AlertRenderer, ALERT_COLORS, AlertStatus, ALERT_STARTUP_PENDING, ALERT_CRITICAL_TIMEOUT, ALERT_CRITICAL_REBOOT)
from openpilot.selfdrive.ui.onroad.bogpilot import alert_banner_logic as L
from openpilot.selfdrive.ui.onroad.bogpilot.redesign import paint_alert_banner
from openpilot.selfdrive.ui.ui_state import ui_state


def to_alert_in(alert) -> L.AlertIn | None:
  if alert is None:
    return None
  return L.AlertIn(alert.text1, alert.text2, int(alert.size), int(alert.status), getattr(alert, "alert_type", "") or "")


def read_alert_type(sm) -> str:
  try:
    return str(sm['selfdriveState'].alertType)
  except Exception:
    return ""


class BogPilotAlertRenderer(AlertRenderer):
  """Drop-in for AlertRenderer. redesign_fn returns the RedesignUI file toggle; compact for the C4 layout."""

  def __init__(self, redesign_fn=lambda: False, compact: bool = False):
    super().__init__()
    self._redesign_fn = redesign_fn
    self._compact = compact
    self.plan = L.AlertPlan(L.MODE_NONE, None, None)

  def current_plan(self, rect: rl.Rectangle) -> L.AlertPlan:
    sm = ui_state.sm
    started = bool(getattr(ui_state, "started", True))
    native = self.get_alert(sm) if started else None
    a = to_alert_in(native)
    if a is not None and not any(native is c for c in (ALERT_STARTUP_PENDING, ALERT_CRITICAL_TIMEOUT, ALERT_CRITICAL_REBOOT)):
      a = L.AlertIn(a.text1, a.text2, a.size, a.status, read_alert_type(sm))   # real selfdriveState alert
    return L.plan_alert(a, (rect.x, rect.y, rect.width, rect.height), started=started,
                        redesign=bool(self._redesign_fn()), compact=self._compact)

  def hud_state(self) -> L.AlertPlan:
    """Last frame's plan for w9 (hide_cluster, lkas_fault border, reserved_top)."""
    return self.plan

  def _render(self, rect: rl.Rectangle):
    self.plan = plan = self.current_plan(rect)
    if plan.mode == L.MODE_NONE:
      return
    if plan.mode == L.MODE_NATIVE:
      super()._render(rect)
      return
    a = plan.alert
    fill = ALERT_COLORS.get(a.status, ALERT_COLORS[AlertStatus.normal]) if plan.use_native_fill else rl.Color(*L.NORMAL_BANNER_FILL)
    paint_alert_banner(rl.Rectangle(*plan.rect), plan.mid, a.text1, a.text2, fill)
