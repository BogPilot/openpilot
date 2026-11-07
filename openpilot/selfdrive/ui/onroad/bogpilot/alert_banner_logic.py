"""C3X alert-banner layout contract (pure Python, no pyray / cereal at import time).

The alert itself always comes from the native raylib source (onroad/alert_renderer.AlertRenderer.get_alert), which reads
selfdriveState produced by selfdrived's AlertManager. This module only decides WHERE and in WHICH painter an alert is
drawn. It never drops, rewrites, reorders or re-prioritises an alert: text1/text2/size/status/alertType pass through.

Modes
  NONE    no alert (alertSize none, stale pre-onroad message, offroad)
  BANNER  RedesignUI on, wide C3X content, small/mid alert -> redesign.paint_alert_banner in the banner slot
  NATIVE  everything else, incl. every FULL alert and all UI-synthesised timeout alerts -> stock painter, full rect
"""
from __future__ import annotations
from dataclasses import dataclass

# log.SelfdriveState.AlertSize / AlertStatus raw values (cereal/log.capnp)
SIZE_NONE, SIZE_SMALL, SIZE_MID, SIZE_FULL = 0, 1, 2, 3
STATUS_NORMAL, STATUS_USER_PROMPT, STATUS_CRITICAL = 0, 1, 2

MODE_NONE, MODE_BANNER, MODE_NATIVE = "none", "banner", "native"

# Same constants as redesign.alert_banner_rect / bogpilot_redesign.cc alertBannerRect (style.py values)
WIDE_MIN_W = 1800
_REC_CX, _REC_HIT, _ALERT_GAP, _ALERT_RIGHT_MARGIN = 20 + 75, 174, 36, 150
_STACK_BOTTOM, _CLUSTER_CY, _CLUSTER_D, _PILL_LABEL_SPACE = 228 + 240, 900, 150, 40
SMALL_H = 170
NARROW_MID_H, NARROW_BOTTOM_GAP, NARROW_SIDE = 300, 230, 40

# Normal status uses the dark redesign panel (PANEL_DARK rgb, alpha 215); prompt / critical keep the native status colour.
NORMAL_BANNER_FILL = (14, 17, 22, 215)

# UI-synthesised alerts from the native source; identified by text/size because they carry no alertType.
SYNTHETIC_TEXT1 = ("openpilot Unavailable", "TAKE CONTROL IMMEDIATELY", "System Unresponsive")


@dataclass(frozen=True)
class AlertIn:
  text1: str = ""
  text2: str = ""
  size: int = SIZE_NONE
  status: int = STATUS_NORMAL
  alert_type: str = ""


@dataclass(frozen=True)
class AlertPlan:
  mode: str
  alert: AlertIn | None
  rect: tuple[float, float, float, float] | None   # x, y, w, h in the caller's rect space; None for NONE
  mid: bool = False
  use_native_fill: bool = True                      # False -> NORMAL_BANNER_FILL
  # HUD hints for w9 (Qt annotated_camera hideCluster / alertHeight semantics)
  showing: bool = False
  full: bool = False
  hide_cluster: bool = False
  lkas_fault: bool = False
  reserved_top: float | None = None                 # top edge of the area the alert occupies (None = nothing reserved)


def is_lkas_fault(alert: AlertIn) -> bool:
  t = alert.alert_type or ""
  return t.startswith("steerUnavailable/") or "lkas fault" in alert.text1.lower() or "lkas fault" in alert.text2.lower()


def banner_rect(x: float, y: float, w: float, h: float, mid: bool) -> tuple[float, float, float, float]:
  """alert_banner_rect in caller space (rect origin x, y; widget size w, h)."""
  if w >= WIDE_MIN_W:
    left = _REC_CX + _REC_HIT // 2 + _ALERT_GAP
    right = int(w) - _ALERT_RIGHT_MARGIN
    top = _STACK_BOTTOM + _ALERT_GAP
    bottom = _CLUSTER_CY - _CLUSTER_D // 2 - _PILL_LABEL_SPACE - _ALERT_GAP
    bh = bottom - top if mid else min(bottom - top, SMALL_H)
    by = top + (bottom - top - bh) // 2
    return (x + left, y + by, right - left, bh)
  bh = NARROW_MID_H if mid else SMALL_H
  return (x + NARROW_SIDE, y + h - NARROW_BOTTOM_GAP - bh, w - 2 * NARROW_SIDE, bh)


def banner_fits(w: float, h: float) -> bool:
  """Wide layout needs the full 1080-class height for the fixed rows; the narrow fallback needs room above the
  bottom gap. Anything smaller is drawn natively so the alert is never clipped."""
  if w >= WIDE_MIN_W:
    return h >= _CLUSTER_CY - _CLUSTER_D // 2
  return w >= 2 * NARROW_SIDE + 200 and h >= NARROW_BOTTOM_GAP + NARROW_MID_H + 40


def plan_alert(alert: AlertIn | None, rect: tuple[float, float, float, float], *, started: bool, redesign: bool,
               compact: bool = False) -> AlertPlan:
  """compact=True is the C4/mici device: its own native AlertRenderer (top gradient + turn icons) is always used."""
  if not started or alert is None or alert.size == SIZE_NONE:
    return AlertPlan(MODE_NONE, None, None)
  x, y, w, h = rect
  full = alert.size == SIZE_FULL
  lkas = is_lkas_fault(alert)
  banner_ok = (redesign and not compact and alert.size in (SIZE_SMALL, SIZE_MID) and banner_fits(w, h))
  if banner_ok:
    mid = alert.size == SIZE_MID
    r = banner_rect(x, y, w, h, mid)
    return AlertPlan(MODE_BANNER, alert, r, mid=mid, use_native_fill=alert.status != STATUS_NORMAL, showing=True,
                     full=False, hide_cluster=False, lkas_fault=lkas, reserved_top=r[1])
  # Native: full alerts cover everything; the redesign hides the cluster only for FULL (Qt hideCluster).
  hide = full if redesign else True
  return AlertPlan(MODE_NATIVE, alert, (x, y, w, h), mid=alert.size == SIZE_MID, showing=True, full=full,
                   hide_cluster=hide, lkas_fault=lkas, reserved_top=y if full else None)
