# UI divergence D2: gated list actions for locked BogPilot settings rows

Not a product. No warranty. Driver remains responsible. This note records a UI divergence; it changes no signal, CAN
frame, panda check or control path, and invents no signal.

Recorded only where the cited files were read. Written in the style of `docs/tesla/DIVERGENCES.md` (bogpilot-tesla);
fold it into that file when the trees meet.

## Stock v0.11.2 list actions vs BogPilot settings rows

Stock openpilot v0.11.2 (`f7db927c7`, `openpilot/system/ui/widgets/list_view.py`; the rc8 copy keeps the
`DualButtonAction` and `MultipleButtonAction` code byte-identical, BogPilot only adds `ListItem` help/level/indent):

- `DualButtonAction` builds its two `Button`s enabled and never passes its own `enabled` to them. A `Button` gates
  touches on its own `enabled` (`system/ui/widgets/__init__.py`, `Widget.render`), so a dual row "locked" with
  `enabled=` still looks live and still fires its callbacks.
- `MultipleButtonAction` is always built `enabled=True`. `_handle_mouse_release` sets `selected_button` before it calls
  the callback and has no enabled check, so a caller that locks only the `ListItem` gets a live row whose highlight can
  move to a choice that was never stored.

Stock panels are not affected in practice (`layouts/settings/device.py` re-checks `engaged` in its prompts;
`toggles.py` and `developer.py` lock `action_item`).

BogPilot rc8 (`openpilot/selfdrive/ui/bogpilot/gated_actions.py`):

- `GatedDualButtonAction(DualButtonAction)`: each button's `enabled` follows the action's `enabled` every frame
  (dimmed and touch-gated), and both callbacks are wrapped so they do nothing while the action is locked.
- `GatedMultipleButtonAction(MultipleButtonAction)`: takes an `enabled` lock, ignores releases while locked (no
  callback, no highlight move), and with `selected_source` shows the stored choice every frame and after each tap.
  Unlocked taps without `selected_source` behave exactly like stock.
- `gated_dual_button_item` / `gated_multiple_button_item`: same signatures as the stock factories plus `enabled` /
  `selected_source`; they return a stock `ListItem`.
- Used by every BogPilot settings panel with a dual or multiple row: SLC (`phase3_speed_control_settings.py`), long
  accel, following, stalk controls, stopping, steering tuning, lane change, alert volumes. Stock `device.py` and
  `toggles.py` keep the stock actions. `selfdrive/ui/tests/test_bogpilot_gated_actions.py` fails if a BogPilot panel
  goes back to a stock dual/multiple action or builds a gated row without a lock.

**Why diverge.** rc7 locked-row audit: 10 BogPilot rows looked and acted enabled
while onroad (rows 1-4, 6, 8, 9, 15, 17, 19), and rows 1, 17 and 19 could leave a wrong value highlighted. No row wrote
a Param, because every BogPilot editor re-checks offroad/visibility at write time. That is unchanged: the gate here
only adds refusals in front of the editors' own checks, so writes stay refused onroad by the same code as before.

**Why a subclass, not a stock edit.** Owner decision D2 option 2: `system/ui/widgets/list_view.py` stays as upstream
ships it (rebases carry no BogPilot hunk in the action classes). Cost: the subclasses rely on stock attribute names
(`left_button`, `right_button`, `button_width`, `selected_button`, `_click_callback`); the tests catch a rename.

**Not in this change: lane `ui-polish-t1361`.** That lane edits stock `list_view.py` for its stepper, `button_spacing`
and shrink-to-fit labels. If the lane is ever revisited, those belong in `GatedMultipleButtonAction` (or a subclass of
it) rather than in `list_view.py`. Revisiting it needs the owner's ask first.

**Sources.** Stock openpilot v0.11.2 `f7db927c7` (`list_view.py`, `widgets/__init__.py`, `widgets/button.py`); BogPilot
rc7 `27e82a496` panels (cited in the audit). Tinkla/BogGyver and NAP use the Qt UI and were not read for this; no
claim is made about them.
