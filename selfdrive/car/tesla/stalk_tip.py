"""AP1 cruise-stalk tip (end) button via VSL_Enbl_Rq.

Pure mapping. No CAN sockets, no params, no actuation.

On AP1 Model S the stalk-end button toggles STW_ACTN_RQ.VSL_Enbl_Rq (bit 6
of 0x45). Each press flips 0↔1. SpdCtrlLvr_Stat stays IDLE (0). About 40 ms
later stock DI_cruiseState leaves ENABLED for STANDBY, which is why openpilot
used to disengage.

That is distinct from pushing the stalk forward (SpdCtrlLvr_Stat == 1 / FWD),
which BogPilot already maps to ButtonType.cancel.

Evidence: route 17 post-park engaged tip presses — four VSL edges each
immediately followed by DI STANDBY and an openpilot disengage; no SpdCtrlLvr
change and no cancel buttonEvent on those presses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StalkTipDecision:
  """One CarState update's view of the tip button."""

  # True on the update where VSL_Enbl_Rq changed (one press).
  pressed: bool
  # Current sticky VSL bit after this sample (0 or 1), or None if unseen.
  vsl: int | None


def tip_edge(vsl, previous_vsl) -> bool:
  """True when VSL_Enbl_Rq changed between samples.

  Missing samples are not an edge. The first observation after boot is not
  an edge either (no previous value to compare).
  """
  if vsl is None or previous_vsl is None:
    return False
  try:
    cur = int(vsl)
    prev = int(previous_vsl)
  except (TypeError, ValueError):
    return False
  if cur not in (0, 1) or prev not in (0, 1):
    return False
  return cur != prev


def parse_stalk_tip(vsl, previous: StalkTipDecision | None) -> StalkTipDecision:
  """Edge-detect one VSL_Enbl_Rq sample against the previous decision."""
  if vsl is None:
    return StalkTipDecision(pressed=False, vsl=None if previous is None else previous.vsl)
  try:
    cur = int(vsl)
  except (TypeError, ValueError):
    return StalkTipDecision(pressed=False, vsl=None if previous is None else previous.vsl)
  if cur not in (0, 1):
    return StalkTipDecision(pressed=False, vsl=None if previous is None else previous.vsl)
  prev_vsl = None if previous is None else previous.vsl
  return StalkTipDecision(pressed=tip_edge(cur, prev_vsl), vsl=cur)


def tip_hold_cruise(holding: bool, tip_pressed: bool, stock_acc_enabled: bool,
                    spd_ctrl_lvr: int | float | None, brake_pressed: bool,
                    was_enabled: bool) -> bool:
  """Whether CarState should keep reporting cruise enabled after a tip press.

  Starts a hold when the tip is pressed while openpilot was or is ACC-enabled.
  Clears on forward-push cancel (SpdCtrlLvr == 1) or brake. Stock going to
  STANDBY alone does not clear the hold — that is the tip's side effect.
  """
  try:
    spd = 0 if spd_ctrl_lvr is None else int(spd_ctrl_lvr)
  except (TypeError, ValueError):
    spd = 0
  if brake_pressed or spd == 1:
    return False
  if tip_pressed and (stock_acc_enabled or was_enabled or holding):
    return True
  return bool(holding)
